from __future__ import annotations

from codex_claude_orchestrator.v4.runtime import (
    CancellationResult,
    DeliveryResult,
    RuntimeEvent,
    StopResult,
    TurnEnvelope,
    WorkerHandle,
    WorkerSpec,
)


class ClaudeCodeTmuxAdapter:
    def __init__(self, *, native_session):
        self._native_session = native_session
        self._workers: dict[str, WorkerSpec] = {}

    def register_worker(self, spec: WorkerSpec) -> WorkerHandle:
        self._workers[spec.worker_id] = spec
        return WorkerHandle(
            crew_id=spec.crew_id,
            worker_id=spec.worker_id,
            runtime_type=spec.runtime_type,
        )

    def spawn_worker(self, spec: WorkerSpec) -> WorkerHandle:
        return self.register_worker(spec)

    def deliver_turn(self, turn: TurnEnvelope) -> DeliveryResult:
        worker = self._workers.get(turn.worker_id)
        terminal_pane = worker.terminal_pane if worker else turn.worker_id
        result = self._native_session.send(
            terminal_pane=terminal_pane,
            message=turn.message,
            turn_marker=turn.expected_marker,
        )
        return DeliveryResult(
            delivered=True,
            marker=result.get("marker", turn.expected_marker),
            reason="sent to tmux pane",
        )

    def watch_turn(self, turn: TurnEnvelope):
        worker = self._workers.get(turn.worker_id)
        terminal_pane = worker.terminal_pane if worker else turn.worker_id
        observation = self._native_session.observe(
            terminal_pane=terminal_pane,
            lines=200,
            turn_marker=turn.expected_marker,
        )
        text = observation.get("snapshot", "")
        artifact_refs = (
            [observation.get("transcript_artifact", "")]
            if observation.get("transcript_artifact")
            else []
        )
        if text:
            yield RuntimeEvent(
                type="output.chunk",
                turn_id=turn.turn_id,
                worker_id=turn.worker_id,
                payload={"text": text},
                artifact_refs=artifact_refs,
            )
        if observation.get("marker_seen", False):
            yield RuntimeEvent(
                type="marker.detected",
                turn_id=turn.turn_id,
                worker_id=turn.worker_id,
                payload={
                    "marker": observation.get("marker", turn.expected_marker),
                    "source": "tmux",
                },
                artifact_refs=artifact_refs,
            )

    def collect_artifacts(self, turn: TurnEnvelope) -> list[str]:
        worker = self._workers.get(turn.worker_id)
        return [worker.transcript_artifact] if worker and worker.transcript_artifact else []

    def cancel_turn(self, turn: TurnEnvelope) -> CancellationResult:
        return CancellationResult(
            cancelled=False,
            reason="tmux Claude turn cancellation is not supported by this adapter",
        )

    def stop_worker(self, worker_id: str) -> StopResult:
        return StopResult(
            stopped=False,
            reason="worker stop is delegated to existing worker pool",
        )
