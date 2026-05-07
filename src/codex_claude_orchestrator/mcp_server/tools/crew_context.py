from __future__ import annotations

import json
from pathlib import Path

from mcp.server import Server
from mcp.types import TextContent

from codex_claude_orchestrator.mcp_server.context.compressor import (
    compress_blackboard,
    compress_observe_result,
    filter_events,
    read_latest_outbox,
)
from codex_claude_orchestrator.mcp_server.context.summarizer_trigger import (
    should_trigger_summarizer,
)
from codex_claude_orchestrator.mcp_server.context.token_budget import truncate_json


def register_context_tools(server: Server, controller) -> None:

    def _spawn_summarizer_if_needed(crew_id: str, entries: list[dict], repo: str) -> None:
        """Spawn summarizer worker synchronously if needed."""
        from codex_claude_orchestrator.mcp_server.tools.crew_lifecycle import WORKER_TEMPLATES
        if not repo or not should_trigger_summarizer(entries):
            return
        contract = WORKER_TEMPLATES["summarizer"]
        controller.ensure_worker(
            repo_root=Path(repo),
            crew_id=crew_id,
            contract=contract,
        )

    @server.tool("crew_blackboard")
    async def crew_blackboard(
        crew_id: str,
        worker_id: str | None = None,
        entry_type: str | None = None,
        limit: int = 10,
        repo: str = "",
    ) -> list[TextContent]:
        """读取黑板条目（过滤后，默认最近 10 条）。"""
        try:
            entries = controller.blackboard_entries(crew_id=crew_id)
            _spawn_summarizer_if_needed(crew_id, entries, repo)
            filtered = compress_blackboard(entries, limit=limit, worker_id=worker_id, entry_type=entry_type)
            return [TextContent(type="text", text=truncate_json(filtered))]
        except FileNotFoundError as exc:
            return [TextContent(type="text", text=json.dumps({"error": str(exc)}, ensure_ascii=False))]
        except ValueError as exc:
            return [TextContent(type="text", text=json.dumps({"error": str(exc)}, ensure_ascii=False))]
        except Exception as exc:
            return [TextContent(type="text", text=json.dumps({"error": f"internal: {exc}"}, ensure_ascii=False))]

    @server.tool("crew_events")
    async def crew_events(repo: str, crew_id: str, limit: int = 20) -> list[TextContent]:
        """读取关键事件（过滤中间事件，默认最近 20 条）。"""
        try:
            raw = controller.status(repo_root=Path(repo), crew_id=crew_id)
            events = raw.get("decisions", []) + raw.get("messages", [])
            filtered = filter_events(events, limit=limit)
            return [TextContent(type="text", text=truncate_json(filtered))]
        except FileNotFoundError as exc:
            return [TextContent(type="text", text=json.dumps({"error": str(exc)}, ensure_ascii=False))]
        except ValueError as exc:
            return [TextContent(type="text", text=json.dumps({"error": str(exc)}, ensure_ascii=False))]
        except Exception as exc:
            return [TextContent(type="text", text=json.dumps({"error": f"internal: {exc}"}, ensure_ascii=False))]

    @server.tool("crew_observe")
    async def crew_observe(repo: str, crew_id: str, worker_id: str) -> list[TextContent]:
        """观察某个 Worker 的当前轮次输出（结构化报告）。"""
        try:
            observation = controller.observe_worker(repo_root=Path(repo), crew_id=crew_id, worker_id=worker_id)
            outbox = read_latest_outbox(Path(repo), crew_id, worker_id)
            report = compress_observe_result(observation, outbox, worker_id=worker_id)
            return [TextContent(type="text", text=truncate_json(report))]
        except FileNotFoundError as exc:
            return [TextContent(type="text", text=json.dumps({"error": str(exc)}, ensure_ascii=False))]
        except ValueError as exc:
            return [TextContent(type="text", text=json.dumps({"error": str(exc)}, ensure_ascii=False))]
        except Exception as exc:
            return [TextContent(type="text", text=json.dumps({"error": f"internal: {exc}"}, ensure_ascii=False))]

    @server.tool("crew_changes")
    async def crew_changes(crew_id: str) -> list[TextContent]:
        """查看 Crew 的文件变更列表（所有 Worker 聚合）。"""
        try:
            result = controller.changes(crew_id=crew_id)
            # result is a list of per-worker change dicts
            if isinstance(result, list):
                all_files = []
                for entry in result:
                    for f in entry.get("changed_files", []):
                        if f not in all_files:
                            all_files.append(f)
                return [TextContent(type="text", text=json.dumps(all_files, ensure_ascii=False))]
            # single worker result
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
            # Return summary without raw diff (diff is in artifacts)
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
