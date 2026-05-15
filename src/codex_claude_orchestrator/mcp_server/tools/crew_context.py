"""Context tools: crew_observe, crew_changes, crew_diff."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path

from mcp.server import Server
from mcp.types import TextContent

from codex_claude_orchestrator.mcp_server.context.compressor import (
    compress_observe_result,
    read_latest_outbox,
)
from codex_claude_orchestrator.mcp_server.context.token_budget import truncate_json


def _poll_worker_for_marker(
    *,
    native_session,
    terminal_pane: str,
    worker_id: str,
    turn_marker: str,
    cancel_event: threading.Event,
    result_holder: dict,
    done_event: threading.Event,
    baseline_markers: int = 0,
    poll_initial_delay: float = 2.0,
    poll_max_delay: float = 10.0,
    poll_timeout: float = 1800.0,
) -> None:
    """Poll a single worker's tmux pane for completion marker. Sets done_event when found.

    Only detects a NEW marker (one that appeared after baseline_markers count).
    This prevents stale markers from previous turns causing false positives.
    """
    delay = poll_initial_delay
    deadline = time.monotonic() + poll_timeout
    prev_count = baseline_markers
    try:
        while not cancel_event.is_set():
            try:
                observation = native_session.observe(
                    terminal_pane=terminal_pane,
                    lines=200,
                    turn_marker=turn_marker,
                )
            except Exception:
                if time.monotonic() >= deadline:
                    result_holder["error"] = f"timeout observing {worker_id}"
                    return
                if cancel_event.wait(delay):
                    return
                delay = min(delay * 2, poll_max_delay)
                continue

            # Only detect NEW markers (count increased since last check or baseline)
            snapshot = observation.get("snapshot", "")
            current_count = snapshot.count(turn_marker)
            if current_count > prev_count:
                result_holder["worker_id"] = worker_id
                result_holder["observation"] = observation
                return
            prev_count = current_count

            if time.monotonic() >= deadline:
                result_holder["error"] = f"timeout waiting for {worker_id}"
                return

            if cancel_event.wait(delay):
                return
            delay = min(delay * 2, poll_max_delay)
    finally:
        done_event.set()


def _wait_for_any_worker(
    *,
    controller,
    repo_root: Path,
    crew_id: str,
    worker_id: str | None = None,
    turn_marker: str = "<<<CODEX_TURN_DONE status=ready_for_codex>>>",
) -> dict:
    """Block until a worker completes. If worker_id is given, wait for that specific worker.
    Otherwise wait for ANY active worker in the crew to complete.
    Returns {"worker_id": ..., "observation": ...} or {"error": ...}.
    """
    native_session = controller._worker_pool._native_session
    recorder = controller._worker_pool._recorder

    if worker_id:
        worker_ids = [worker_id]
    else:
        worker_ids = recorder.active_worker_ids(crew_id)
        if not worker_ids:
            return {"error": f"no active workers in crew {crew_id}"}

    # Get terminal pane for each worker
    worker_panes = {}
    for wid in worker_ids:
        try:
            worker = controller._worker_pool._find_worker(crew_id, wid)
            pane = worker.get("terminal_pane")
            if pane:
                worker_panes[wid] = pane
        except Exception:
            continue

    if not worker_panes:
        return {"error": "no workers with terminal panes found"}

    # Snapshot baseline marker counts for each pane BEFORE polling starts.
    # This prevents stale markers from previous turns causing false positives.
    baseline_counts: dict[str, int] = {}
    for wid, pane in worker_panes.items():
        try:
            snap = native_session.observe(terminal_pane=pane, lines=200, turn_marker=turn_marker)
            baseline_counts[wid] = snap.get("snapshot", "").count(turn_marker)
        except Exception:
            baseline_counts[wid] = 0

    if len(worker_panes) == 1:
        # Single worker — poll directly
        wid, pane = next(iter(worker_panes.items()))
        result_holder: dict = {}
        cancel_event = threading.Event()
        done_event = threading.Event()
        _poll_worker_for_marker(
            native_session=native_session,
            terminal_pane=pane,
            worker_id=wid,
            turn_marker=turn_marker,
            cancel_event=cancel_event,
            result_holder=result_holder,
            done_event=done_event,
            baseline_markers=baseline_counts.get(wid, 0),
        )
        return result_holder

    # Multiple workers — poll all in parallel threads, return when any completes
    cancel_event = threading.Event()
    result_holder = {}
    done_events = []
    threads = []

    for wid, pane in worker_panes.items():
        per_worker_done = threading.Event()
        t = threading.Thread(
            target=_poll_worker_for_marker,
            kwargs=dict(
                native_session=native_session,
                terminal_pane=pane,
                worker_id=wid,
                turn_marker=turn_marker,
                cancel_event=cancel_event,
                result_holder=result_holder,
                done_event=per_worker_done,
                baseline_markers=baseline_counts.get(wid, 0),
            ),
            daemon=True,
        )
        done_events.append(per_worker_done)
        threads.append(t)
        t.start()

    # Wait for any thread to signal done
    while True:
        for evt in done_events:
            if evt.is_set():
                cancel_event.set()  # cancel all other threads
                for t in threads:
                    t.join(timeout=2)
                if result_holder:
                    return result_holder
        time.sleep(0.2)


def register_context_tools(server: Server, controller) -> None:

    @server.tool("crew_observe")
    async def crew_observe(
        repo: str,
        crew_id: str,
        worker_id: str | None = None,
    ) -> list[TextContent]:
        """等待 Worker 完成并返回结果。

        - 指定 worker_id: 等该 worker 完成
        - 不指定: 等任意 active worker 完成

        内部用 Python 线程轮询 tmux，不消耗 LLM token。
        """
        try:
            result = await asyncio.to_thread(
                _wait_for_any_worker,
                controller=controller,
                repo_root=Path(repo),
                crew_id=crew_id,
                worker_id=worker_id,
            )
            if "error" in result and "observation" not in result:
                return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]

            completed_worker_id = result.get("worker_id", worker_id or "")
            observation = result.get("observation", {})
            outbox = read_latest_outbox(Path(repo), crew_id, completed_worker_id)
            report = compress_observe_result(observation, outbox, worker_id=completed_worker_id)
            return [TextContent(type="text", text=truncate_json(report))]
        except Exception as exc:
            return [TextContent(type="text", text=json.dumps({"error": f"internal: {exc}"}, ensure_ascii=False))]

    @server.tool("crew_changes")
    async def crew_changes(crew_id: str) -> list[TextContent]:
        """查看 Crew 的文件变更列表（所有 Worker 聚合）。"""
        try:
            result = controller.changes(crew_id=crew_id)
            if isinstance(result, list):
                all_files = []
                for entry in result:
                    for f in entry.get("changed_files", []):
                        if f not in all_files:
                            all_files.append(f)
                return [TextContent(type="text", text=json.dumps(all_files, ensure_ascii=False))]
            return [TextContent(type="text", text=json.dumps(result.get("changed_files", []), ensure_ascii=False))]
        except FileNotFoundError as exc:
            return [TextContent(type="text", text=json.dumps({"error": str(exc)}, ensure_ascii=False))]
        except ValueError as exc:
            return [TextContent(type="text", text=json.dumps({"error": str(exc)}, ensure_ascii=False))]
        except Exception as exc:
            return [TextContent(type="text", text=json.dumps({"error": f"internal: {exc}"}, ensure_ascii=False))]

    @server.tool("crew_diff")
    async def crew_diff(crew_id: str, file: str | None = None) -> list[TextContent]:
        """查看具体文件的 diff（或所有变更摘要）。"""
        try:
            result = controller.changes(crew_id=crew_id)
            entries = result if isinstance(result, list) else [result]
            if file:
                entries = [e for e in entries if file in e.get("changed_files", [])]
            summaries = [
                {
                    "worker_id": e.get("worker_id", ""),
                    "changed_files": e.get("changed_files", []),
                    "branch": e.get("branch", ""),
                }
                for e in entries
            ]
            return [TextContent(type="text", text=truncate_json(summaries))]
        except FileNotFoundError as exc:
            return [TextContent(type="text", text=json.dumps({"error": str(exc)}, ensure_ascii=False))]
        except ValueError as exc:
            return [TextContent(type="text", text=json.dumps({"error": str(exc)}, ensure_ascii=False))]
        except Exception as exc:
            return [TextContent(type="text", text=json.dumps({"error": f"internal: {exc}"}, ensure_ascii=False))]
