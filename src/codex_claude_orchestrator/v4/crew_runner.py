"""V4 main-path runner for crew run and supervise commands."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from codex_claude_orchestrator.crew.decision_policy import CrewDecisionPolicy
from codex_claude_orchestrator.crew.gates import WriteScopeGate
from codex_claude_orchestrator.crew.models import DecisionActionType, WorkerRole
from codex_claude_orchestrator.v4.event_store_protocol import EventStore
from codex_claude_orchestrator.v4.runtime import WorkerSpec
from codex_claude_orchestrator.v4.workflow import V4WorkflowEngine
from codex_claude_orchestrator.workers.selection import WorkerSelectionPolicy


class V4CrewRunner:
    def __init__(
        self,
        *,
        controller,
        supervisor,
        event_store: EventStore,
        decision_policy: CrewDecisionPolicy | None = None,
        scope_gate: WriteScopeGate | None = None,
    ) -> None:
        self._controller = controller
        self._supervisor = supervisor
        self._events = event_store
        self._workflow = V4WorkflowEngine(event_store=event_store)
        self._decision_policy = decision_policy or CrewDecisionPolicy()
        self._scope_gate = scope_gate or WriteScopeGate()

    def run(
        self,
        *,
        repo_root: Path,
        goal: str,
        verification_commands: list[str],
        max_rounds: int = 3,
        worker_roles: list[WorkerRole] | None = None,
        poll_interval_seconds: float | None = None,
        allow_dirty_base: bool = False,
        spawn_policy: str = "dynamic",
        seed_contract: str | None = None,
    ) -> dict[str, Any]:
        if spawn_policy == "dynamic":
            crew = self._controller.start_dynamic(repo_root=repo_root, goal=goal)
            return self.supervise(
                repo_root=repo_root,
                crew_id=crew.crew_id,
                verification_commands=verification_commands,
                max_rounds=max_rounds,
                poll_interval_seconds=poll_interval_seconds,
                dynamic=True,
                allow_dirty_base=allow_dirty_base,
                seed_contract=seed_contract,
            )

        selected_roles = worker_roles or WorkerSelectionPolicy().select(goal=goal).roles
        crew = self._controller.start(
            repo_root=repo_root,
            goal=goal,
            worker_roles=selected_roles,
            allow_dirty_base=allow_dirty_base,
        )
        return self.supervise(
            repo_root=repo_root,
            crew_id=crew.crew_id,
            verification_commands=verification_commands,
            max_rounds=max_rounds,
            poll_interval_seconds=poll_interval_seconds,
            dynamic=False,
        )

    def supervise(
        self,
        *,
        repo_root: Path,
        crew_id: str,
        verification_commands: list[str],
        max_rounds: int = 3,
        poll_interval_seconds: float | None = None,
        dynamic: bool = False,
        allow_dirty_base: bool = False,
        seed_contract: str | None = None,
    ) -> dict[str, Any]:
        if not verification_commands:
            raise ValueError("at least one verification command is required")

        events: list[dict[str, Any]] = []
        verification_failures: list[dict[str, Any]] = []

        for round_index in range(1, max_rounds + 1):
            details = self._controller.status(repo_root=repo_root, crew_id=crew_id)
            goal = details.get("crew", {}).get("root_goal", "")
            source_worker = self._source_worker(details)
            if source_worker is None and dynamic:
                source_worker = self._spawn_source_worker(
                    repo_root=repo_root,
                    crew_id=crew_id,
                    goal=goal,
                    details=details,
                    verification_failures=verification_failures,
                    allow_dirty_base=allow_dirty_base,
                    seed_contract=seed_contract,
                )
                events.append(
                    {
                        "action": "spawn_worker",
                        "worker_id": source_worker["worker_id"],
                        "contract_id": source_worker.get("contract_id", ""),
                    }
                )
            if source_worker is None:
                raise ValueError(f"crew {crew_id} has no source worker")

            self._register_worker(crew_id=crew_id, worker=source_worker)
            round_id = f"round-{round_index}"
            marker = self._turn_marker(crew_id, source_worker["worker_id"], "source", round_index)
            turn_result = self._supervisor.run_source_turn(
                crew_id=crew_id,
                goal=goal,
                worker_id=source_worker["worker_id"],
                round_id=round_id,
                message=self._source_message(round_index=round_index, failures=verification_failures),
                expected_marker=marker,
            )
            events.append(
                {
                    "action": "v4_source_turn",
                    "round": round_index,
                    "worker_id": source_worker["worker_id"],
                    **turn_result,
                }
            )

            if turn_result.get("status") != "turn_completed":
                return self._turn_not_completed_result(
                    crew_id=crew_id,
                    worker_id=source_worker["worker_id"],
                    turn_result=turn_result,
                    events=events,
                )

            changes = self._controller.changes(crew_id=crew_id, worker_id=source_worker["worker_id"])
            events.append({"action": "record_changes", "round": round_index, "changes": changes})

            scope_result = self._scope_gate.evaluate(
                changed_files=changes.get("changed_files", []),
                write_scope=self._write_scope_for_worker(details, source_worker),
                evidence_refs=[
                    ref
                    for ref in (changes.get("artifact"), changes.get("diff_artifact"))
                    if ref
                ],
            )
            events.append(
                {
                    "action": "scope_gate",
                    "round": round_index,
                    "status": scope_result.status,
                }
            )
            if scope_result.status == "block":
                self._workflow.require_human(
                    crew_id=crew_id,
                    reason="write_scope_blocked",
                    evidence_refs=scope_result.evidence_refs,
                )
                return {
                    "crew_id": crew_id,
                    "status": "needs_human",
                    "runtime": "v4",
                    "reason": "write_scope_blocked",
                    "rounds": round_index,
                    "events": events,
                }
            if scope_result.status == "challenge":
                summary = self._scope_challenge_message(scope_result)
                self._controller.challenge(crew_id=crew_id, summary=summary)
                events.append({"action": "challenge", "round": round_index, "summary": summary})
                continue

            verification_results = [
                self._controller.verify(
                    crew_id=crew_id,
                    command=command,
                    worker_id=source_worker["worker_id"],
                )
                for command in verification_commands
            ]
            verification_events = self._append_verification_events(
                crew_id=crew_id,
                worker=source_worker,
                round_id=round_id,
                verification_commands=verification_commands,
                verification_results=verification_results,
            )
            events.append({"action": "verify", "round": round_index, "results": verification_results})
            failed = [result for result in verification_results if not result.get("passed", False)]
            if not failed:
                evidence_refs = [
                    ref
                    for ref in (changes.get("artifact"), changes.get("diff_artifact"))
                    if ref
                ]
                self._workflow.mark_ready(
                    crew_id=crew_id,
                    round_id=round_id,
                    evidence_refs=[
                        *evidence_refs,
                        *(event.event_id for event in verification_events),
                    ],
                )
                return {
                    "crew_id": crew_id,
                    "status": "ready_for_codex_accept",
                    "runtime": "v4",
                    "rounds": round_index,
                    "events": events,
                }

            verification_failures.extend(failed)
            summary = "; ".join(result.get("summary", "verification failed") for result in failed)
            self._controller.challenge(crew_id=crew_id, summary=summary)
            events.append({"action": "challenge", "round": round_index, "summary": summary})

        return {
            "crew_id": crew_id,
            "status": "max_rounds_exhausted",
            "runtime": "v4",
            "rounds": max_rounds,
            "events": events,
        }

    def _spawn_source_worker(
        self,
        *,
        repo_root: Path,
        crew_id: str,
        goal: str,
        details: dict[str, Any],
        verification_failures: list[dict[str, Any]],
        allow_dirty_base: bool,
        seed_contract: str | None,
    ) -> dict[str, Any]:
        action = self._decision_policy.decide(
            {
                "crew_id": crew_id,
                "goal": goal,
                "workers": details.get("workers", []),
                "verification_failures": verification_failures,
                "changed_files": [],
                "seed_contract": seed_contract,
                "context_insufficient": False,
                "repo_write_scope": self._repo_write_scope(repo_root),
            }
        )
        if action.action_type is not DecisionActionType.SPAWN_WORKER or action.contract is None:
            self._workflow.require_human(crew_id=crew_id, reason=action.reason)
            raise ValueError(f"V4 planner did not create a source worker: {action.reason}")
        self._record_decision_if_supported(crew_id, action.to_dict())
        return self._controller.ensure_worker(
            repo_root=repo_root,
            crew_id=crew_id,
            contract=action.contract,
            allow_dirty_base=allow_dirty_base,
        )

    def _source_worker(self, details: dict[str, Any]) -> dict[str, Any] | None:
        workers = [
            worker
            for worker in details.get("workers", [])
            if worker.get("status", "running") not in {"failed", "stopped"}
        ]
        return next(
            (worker for worker in workers if worker.get("authority_level") == "source_write"),
            next((worker for worker in workers if worker.get("role") == WorkerRole.IMPLEMENTER.value), None),
        )

    def _register_worker(self, *, crew_id: str, worker: dict[str, Any]) -> None:
        register = getattr(self._supervisor, "register_worker", None)
        if register is None:
            return
        register(
            WorkerSpec(
                crew_id=worker.get("crew_id") or crew_id,
                worker_id=worker["worker_id"],
                runtime_type="tmux_claude",
                contract_id=worker.get("contract_id") or worker.get("role", ""),
                workspace_path=str(worker.get("workspace_path", "")),
                terminal_pane=worker.get("terminal_pane", ""),
                transcript_artifact=worker.get("transcript_artifact", ""),
                capabilities=list(worker.get("capabilities", [])),
            )
        )

    def _turn_not_completed_result(
        self,
        *,
        crew_id: str,
        worker_id: str,
        turn_result: dict[str, Any],
        events: list[dict[str, Any]],
    ) -> dict[str, Any]:
        status = turn_result.get("status", "")
        if status == "waiting":
            return {
                "crew_id": crew_id,
                "status": "waiting_for_worker",
                "runtime": "v4",
                "worker_id": worker_id,
                "reason": turn_result.get("reason", "completion evidence not found"),
                "events": events,
            }
        return {
            "crew_id": crew_id,
            "status": status or "turn_not_completed",
            "runtime": "v4",
            "worker_id": worker_id,
            "reason": turn_result.get("reason", ""),
            "events": events,
        }

    def _write_scope_for_worker(self, details: dict[str, Any], worker: dict[str, Any]) -> list[str]:
        worker_scope = worker.get("write_scope") or []
        if worker_scope:
            return list(worker_scope)

        contract_id = worker.get("contract_id")
        for contract in details.get("worker_contracts", []):
            if contract.get("contract_id") == contract_id and contract.get("write_scope"):
                return list(contract["write_scope"])

        return ["src/", "tests/"]

    def _repo_write_scope(self, repo_root: Path) -> list[str]:
        roots = [
            f"{name}/"
            for name in ("src", "tests", "test", "tools", "packages", "apps", "app", "lib", "scripts")
            if (repo_root / name).is_dir()
        ]
        return roots or ["src/", "tests/"]

    def _record_decision_if_supported(self, crew_id: str, action: dict[str, Any]) -> None:
        recorder = getattr(self._controller, "record_decision", None)
        if recorder is not None:
            recorder(crew_id=crew_id, action=action)

    def _append_verification_events(
        self,
        *,
        crew_id: str,
        worker: dict[str, Any],
        round_id: str,
        verification_commands: list[str],
        verification_results: list[dict[str, Any]],
    ) -> list:
        events = []
        for index, (command, result) in enumerate(
            zip(verification_commands, verification_results, strict=False),
            start=1,
        ):
            event_type = "verification.passed" if result.get("passed", False) else "verification.failed"
            artifact_refs = _artifact_refs_from_result(result)
            events.append(
                self._events.append(
                    stream_id=crew_id,
                    type=event_type,
                    crew_id=crew_id,
                    worker_id=worker["worker_id"],
                    round_id=round_id,
                    contract_id=worker.get("contract_id", ""),
                    idempotency_key=f"{crew_id}/{round_id}/{worker['worker_id']}/verification/{index}",
                    payload={
                        "command": command,
                        "result": result,
                    },
                    artifact_refs=artifact_refs,
                )
            )
        return events

    def _source_message(self, *, round_index: int, failures: list[dict[str, Any]]) -> str:
        if not failures:
            return "Begin or continue the dynamic worker contract. Report evidence, risks, and changed files."
        summary = "; ".join(result.get("summary", "verification failed") for result in failures[-3:])
        return f"Fix verification failure before the next Codex review:\n{summary}"

    def _scope_challenge_message(self, scope_result) -> str:
        out_of_scope = scope_result.details.get("out_of_scope", [])
        changed = ", ".join(out_of_scope) or "unknown files"
        return f"Changed files outside write_scope: {changed}. Update the patch to stay within scope or explain why scope must change."

    def _turn_marker(self, crew_id: str, worker_id: str, phase: str, round_index: int) -> str:
        return f"<<<CODEX_TURN_DONE crew={crew_id} worker={worker_id} phase={phase} round={round_index}>>>"


def _artifact_refs_from_result(result: dict[str, Any]) -> list[str]:
    refs = []
    artifact_refs = result.get("artifact_refs", [])
    if isinstance(artifact_refs, list):
        refs.extend(ref for ref in artifact_refs if isinstance(ref, str) and ref)
    for key in ("artifact", "stdout_artifact", "stderr_artifact"):
        value = result.get(key)
        if isinstance(value, str) and value:
            refs.append(value)
    return list(dict.fromkeys(refs))


__all__ = ["V4CrewRunner"]
