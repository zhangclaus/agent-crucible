from __future__ import annotations

from pathlib import Path
from typing import Iterable

from codex_claude_orchestrator.v4.event_store import SQLiteEventStore
from codex_claude_orchestrator.v4.runtime import (
    CancellationResult,
    DeliveryResult,
    RuntimeEvent,
    StopResult,
    TurnEnvelope,
    WorkerHandle,
    WorkerSpec,
)
from codex_claude_orchestrator.v4.turns import TurnService


class FakeAdapter:
    def __init__(self) -> None:
        self.delivered: list[str] = []

    def spawn_worker(self, spec: WorkerSpec) -> WorkerHandle:
        return WorkerHandle(
            crew_id=spec.crew_id,
            worker_id=spec.worker_id,
            runtime_type=spec.runtime_type,
        )

    def deliver_turn(self, turn: TurnEnvelope) -> DeliveryResult:
        self.delivered.append(turn.turn_id)
        return DeliveryResult(
            delivered=True,
            marker=turn.expected_marker,
            reason="delivered",
            artifact_refs=["artifact-1"],
        )

    def watch_turn(self, turn: TurnEnvelope) -> Iterable[RuntimeEvent]:
        return []

    def collect_artifacts(self, turn: TurnEnvelope) -> list[str]:
        return []

    def cancel_turn(self, turn: TurnEnvelope) -> CancellationResult:
        return CancellationResult(cancelled=True)

    def stop_worker(self, worker_id: str) -> StopResult:
        return StopResult(stopped=True)


def make_turn() -> TurnEnvelope:
    return TurnEnvelope(
        crew_id="crew-1",
        worker_id="worker-1",
        turn_id="turn-1",
        round_id="round-1",
        phase="source",
        message="Implement",
        expected_marker="marker-1",
    )


def test_turn_service_records_request_and_delivery(tmp_path: Path) -> None:
    store = SQLiteEventStore(tmp_path / "events.sqlite3")
    adapter = FakeAdapter()
    service = TurnService(event_store=store, adapter=adapter)

    result = service.request_and_deliver(make_turn())

    assert result.delivered is True
    assert [event.type for event in store.list_stream("crew-1")] == [
        "turn.requested",
        "turn.delivery_started",
        "turn.delivered",
    ]


def test_turn_service_does_not_deliver_same_turn_twice(tmp_path: Path) -> None:
    store = SQLiteEventStore(tmp_path / "events.sqlite3")
    adapter = FakeAdapter()
    service = TurnService(event_store=store, adapter=adapter)

    service.request_and_deliver(make_turn())
    service.request_and_deliver(make_turn())

    assert adapter.delivered == ["turn-1"]
    assert [event.type for event in store.list_stream("crew-1")].count("turn.delivered") == 1
