"""ParallelSupervisor: drives multiple subtask workers concurrently with two-layer adversarial review."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from codex_claude_orchestrator.crew.models import (
    AuthorityLevel,
    WorkerContract,
    WorkspacePolicy,
)
from codex_claude_orchestrator.v4.subtask import SubTask


class ParallelSupervisor:
    """Orchestrates multiple subtasks in parallel with unit and integration review layers."""

    def __init__(
        self,
        *,
        controller: Any,
        supervisor: Any,
        event_store: Any,
    ) -> None:
        self._controller = controller
        self._supervisor = supervisor
        self._event_store = event_store

    async def supervise(
        self,
        *,
        repo_root: Path,
        crew_id: str,
        goal: str,
        subtasks: list[SubTask],
        verification_commands: list[str],
        max_rounds: int = 3,
        max_workers: int = 3,
        progress_callback: Callable[[str, int, int], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        """Main supervision loop: run parallel watch+review per round, then integration review."""
        events: list[dict[str, Any]] = []

        for round_index in range(1, max_rounds + 1):
            if cancel_event and cancel_event.is_set():
                return {
                    "crew_id": crew_id,
                    "status": "cancelled",
                    "runtime": "v4-parallel",
                    "rounds": round_index - 1,
                    "events": events,
                }

            if progress_callback is not None:
                try:
                    progress_callback("watching", round_index, max_rounds)
                except Exception:
                    pass

            round_id = f"parallel-round-{round_index}"

            # Phase 1: parallel watch + unit review
            unit_results = await self._run_parallel_watch_and_review(
                subtasks=subtasks,
                crew_id=crew_id,
                goal=goal,
                round_id=round_id,
                repo_root=repo_root,
                cancel_event=cancel_event,
            )
            events.append({"action": "parallel_watch", "round": round_index, "results": unit_results})

            # Challenge failed subtasks
            failed_subtasks = [
                r for r in unit_results if r.get("unit_review") == "fail"
            ]
            for failed in failed_subtasks:
                subtask = next(
                    (st for st in subtasks if st.task_id == failed["task_id"]),
                    None,
                )
                if subtask is not None:
                    self._controller.challenge(
                        crew_id=crew_id,
                        summary=failed.get("reason", "unit review failed"),
                        task_id=subtask.task_id,
                        worker_id=subtask.worker_id,
                        category="unit_review_fail",
                        round_id=round_id,
                    )
                    subtask.review_attempts += 1
                    events.append({
                        "action": "challenge",
                        "round": round_index,
                        "task_id": subtask.task_id,
                        "summary": failed.get("reason", ""),
                    })

            # If any unit reviews failed, retry next round
            if failed_subtasks:
                if round_index >= max_rounds:
                    return {
                        "crew_id": crew_id,
                        "status": "max_rounds_exhausted",
                        "runtime": "v4-parallel",
                        "rounds": max_rounds,
                        "events": events,
                    }
                continue

            # Phase 2: integration review
            if progress_callback is not None:
                try:
                    progress_callback("integration", round_index, max_rounds)
                except Exception:
                    pass

            integration = self._run_integration_review(
                subtasks=subtasks,
                crew_id=crew_id,
                verification_commands=verification_commands,
            )
            events.append({"action": "integration_review", "round": round_index, **integration})

            if integration["status"] == "pass":
                return {
                    "crew_id": crew_id,
                    "status": "ready_for_codex_accept",
                    "runtime": "v4-parallel",
                    "rounds": round_index,
                    "events": events,
                }

            # Integration failed — challenge and retry
            summary = integration.get("reason", "integration review failed")
            self._controller.challenge(
                crew_id=crew_id,
                summary=summary,
                category=f"integration_{integration['status']}",
                round_id=round_id,
            )
            events.append({
                "action": "challenge",
                "round": round_index,
                "summary": summary,
            })

            if round_index >= max_rounds:
                return {
                    "crew_id": crew_id,
                    "status": "max_rounds_exhausted",
                    "runtime": "v4-parallel",
                    "rounds": max_rounds,
                    "events": events,
                }

        return {
            "crew_id": crew_id,
            "status": "max_rounds_exhausted",
            "runtime": "v4-parallel",
            "rounds": max_rounds,
            "events": events,
        }

    async def _run_parallel_watch_and_review(
        self,
        *,
        subtasks: list[SubTask],
        crew_id: str,
        goal: str,
        round_id: str,
        repo_root: Path,
        cancel_event: threading.Event | None = None,
    ) -> list[dict[str, Any]]:
        """Run watch+review for all pending subtasks in parallel using asyncio.gather."""
        pending = [st for st in subtasks if st.status in ("pending", "failed")]
        if not pending:
            return []

        results = await asyncio.gather(
            *[
                self._watch_and_review_one(
                    subtask=st,
                    crew_id=crew_id,
                    goal=goal,
                    round_id=round_id,
                    repo_root=repo_root,
                    cancel_event=cancel_event,
                )
                for st in pending
            ],
            return_exceptions=True,
        )

        # Convert exceptions to failure dicts
        final: list[dict[str, Any]] = []
        for st, result in zip(pending, results):
            if isinstance(result, BaseException):
                st.status = "failed"
                st.result = {"error": str(result)}
                final.append({
                    "task_id": st.task_id,
                    "unit_review": "fail",
                    "reason": f"exception: {result}",
                })
            else:
                final.append(result)
        return final

    async def _watch_and_review_one(
        self,
        *,
        subtask: SubTask,
        crew_id: str,
        goal: str,
        round_id: str,
        repo_root: Path,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        """Watch a single worker turn and run unit review if turn completes."""
        subtask.status = "running"
        worker_info = self._spawn_worker(subtask, crew_id=crew_id, repo_root=repo_root)
        subtask.worker_id = worker_info["worker_id"]

        turn_id = f"{round_id}-{subtask.worker_id}-source"
        marker = f"<<<CODEX_TURN_DONE crew={crew_id} worker={subtask.worker_id} phase=source>>>"

        turn_result = await self._supervisor.async_run_worker_turn(
            crew_id=crew_id,
            goal=goal,
            worker_id=subtask.worker_id,
            round_id=round_id,
            phase="source",
            contract_id=worker_info.get("contract_id", ""),
            message=f"Complete subtask: {subtask.description}",
            expected_marker=marker,
            cancel_event=cancel_event,
        )

        if turn_result.get("status") != "turn_completed":
            subtask.status = "failed"
            subtask.result = turn_result
            return {
                "task_id": subtask.task_id,
                "unit_review": "fail",
                "reason": f"turn not completed: {turn_result.get('status', 'unknown')}",
            }

        # Unit review
        subtask.status = "unit_review"
        review_result = await self._run_unit_review(
            subtask,
            crew_id=crew_id,
            goal=goal,
            round_id=round_id,
            repo_root=repo_root,
            cancel_event=cancel_event,
        )

        if review_result["verdict"] == "pass":
            subtask.status = "passed"
            subtask.result = {"turn": turn_result, "review": review_result}
            return {
                "task_id": subtask.task_id,
                "unit_review": "pass",
                "reason": review_result.get("reason", ""),
            }
        else:
            subtask.status = "failed"
            subtask.result = {"turn": turn_result, "review": review_result}
            return {
                "task_id": subtask.task_id,
                "unit_review": "fail",
                "reason": review_result.get("reason", "unit review blocked"),
            }

    async def _run_unit_review(
        self,
        subtask: SubTask,
        *,
        crew_id: str,
        goal: str,
        round_id: str,
        repo_root: Path,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        """Run adversarial unit review for a single subtask's changes."""
        changes = self._controller.changes(
            crew_id=crew_id,
            worker_id=subtask.worker_id,
        )
        if not changes.get("changed_files"):
            return {"verdict": "pass", "reason": "no changes to review"}

        # Spawn a reviewer worker for the unit review
        reviewer_info = self._spawn_worker(
            subtask,
            crew_id=crew_id,
            role="reviewer",
            repo_root=repo_root,
        )
        reviewer_id = reviewer_info["worker_id"]
        review_turn_id = f"{round_id}-{subtask.task_id}-unit-review"
        review_marker = f"<<<CODEX_TURN_DONE crew={crew_id} worker={reviewer_id} phase=unit_review>>>"

        changed_files = ", ".join(changes.get("changed_files", []))
        review_message = (
            f"Review the changes for subtask '{subtask.description}' (task_id={subtask.task_id}).\n"
            f"Changed files: {changed_files}\n"
            f"Goal: {goal}\n\n"
            "If the changes have issues, write BLOCK in your summary. "
            "If the changes look correct, write OK in your summary."
        )

        review_result = await self._supervisor.async_run_worker_turn(
            crew_id=crew_id,
            goal=goal,
            worker_id=reviewer_id,
            round_id=round_id,
            phase="unit_review",
            contract_id=reviewer_info.get("contract_id", ""),
            message=review_message,
            expected_marker=review_marker,
            cancel_event=cancel_event,
        )

        # Parse verdict from events
        turn_id = review_result.get("turn_id", review_turn_id)
        events = self._event_store.list_by_turn(turn_id)

        verdict = "pass"
        reason = ""
        for event in reversed(events):
            summary = event.payload.get("summary", "")
            if isinstance(summary, str) and "BLOCK" in summary:
                verdict = "block"
                reason = summary
                break

        return {"verdict": verdict, "reason": reason}

    def _run_integration_review(
        self,
        *,
        subtasks: list[SubTask],
        crew_id: str,
        verification_commands: list[str],
    ) -> dict[str, Any]:
        """Run integration review: conflict detection + verification commands."""
        # Collect changes from all passed subtasks
        all_changes: list[dict[str, Any]] = []
        for st in subtasks:
            if st.status == "passed":
                try:
                    changes = self._controller.changes(
                        crew_id=crew_id,
                        worker_id=st.worker_id,
                    )
                    if changes:
                        all_changes.append(changes)
                except Exception:
                    continue

        # Detect conflicts
        conflicts = self._detect_conflicts(all_changes)
        if conflicts:
            conflict_desc = "; ".join(
                f"{f} changed by {', '.join(workers)}"
                for f, workers in conflicts.items()
            )
            return {
                "status": "conflict",
                "reason": f"file conflicts detected: {conflict_desc}",
                "conflicts": conflicts,
            }

        # Run verification commands
        for command in verification_commands:
            try:
                result = self._controller.verify(crew_id=crew_id, command=command)
                if not result.get("passed", False):
                    return {
                        "status": "test_failed",
                        "reason": f"verification failed: {result.get('summary', command)}",
                        "command": command,
                        "result": result,
                    }
            except Exception as exc:
                return {
                    "status": "test_failed",
                    "reason": f"verification error: {exc}",
                    "command": command,
                }

        return {"status": "pass", "reason": "all verifications passed"}

    def _detect_conflicts(
        self, all_changes: list[dict[str, Any]]
    ) -> dict[str, list[str]]:
        """Find files changed by multiple workers."""
        file_to_workers: dict[str, list[str]] = {}
        for changes in all_changes:
            worker_id = changes.get("worker_id", "unknown")
            for f in changes.get("changed_files", []):
                file_to_workers.setdefault(f, []).append(worker_id)
        return {
            f: workers
            for f, workers in file_to_workers.items()
            if len(workers) > 1
        }

    def _spawn_worker(
        self,
        subtask: SubTask,
        *,
        crew_id: str,
        repo_root: Path,
        role: str = "implementer",
    ) -> dict[str, Any]:
        """Spawn a worker via controller.ensure_worker with a contract for the subtask."""
        if role == "reviewer":
            contract = WorkerContract(
                contract_id=f"review-{subtask.task_id}",
                label="subtask-reviewer",
                mission=f"Review changes for subtask: {subtask.description}",
                required_capabilities=["review_patch"],
                authority_level=AuthorityLevel.READONLY,
                workspace_policy=WorkspacePolicy.READONLY,
            )
        else:
            contract = WorkerContract(
                contract_id=f"source-{subtask.task_id}",
                label="subtask-implementer",
                mission=f"Implement subtask: {subtask.description}",
                required_capabilities=["edit_source"],
                authority_level=AuthorityLevel.SOURCE_WRITE,
                workspace_policy=WorkspacePolicy.WORKTREE,
                write_scope=list(subtask.scope),
            )

        return self._controller.ensure_worker(
            repo_root=repo_root,
            crew_id=crew_id,
            contract=contract,
        )
