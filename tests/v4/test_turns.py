from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import time
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
    def __init__(
        self,
        *,
        delivered: bool = True,
        marker: str | None = None,
        reason: str = "delivered",
        delay_seconds: float = 0,
    ) -> None:
        self.delivered: list[str] = []
        self._result_delivered = delivered
        self._marker = marker
        self._reason = reason
        self._delay_seconds = delay_seconds

    def spawn_worker(self, spec: WorkerSpec) -> WorkerHandle:
        return WorkerHandle(
            crew_id=spec.crew_id,
            worker_id=spec.worker_id,
            runtime_type=spec.runtime_type,
        )

    def deliver_turn(self, turn: TurnEnvelope) -> DeliveryResult:
        if self._delay_seconds:
            time.sleep(self._delay_seconds)
        self.delivered.append(turn.turn_id)
        return DeliveryResult(
            delivered=self._result_delivered,
            marker=self._marker or turn.expected_marker,
            reason=self._reason,
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


def make_attempt(attempt: int) -> TurnEnvelope:
    turn = make_turn()
    return TurnEnvelope(
        crew_id=turn.crew_id,
        worker_id=turn.worker_id,
        turn_id=turn.turn_id,
        round_id=turn.round_id,
        phase=turn.phase,
        message=turn.message,
        expected_marker=turn.expected_marker,
        attempt=attempt,
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


def test_turn_service_concurrent_same_successful_turn_delivers_once(tmp_path: Path) -> None:
    store = SQLiteEventStore(tmp_path / "events.sqlite3")
    adapter = FakeAdapter(delay_seconds=0.01)
    service = TurnService(event_store=store, adapter=adapter)

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: service.request_and_deliver(make_turn()), range(8)))

    assert all(result.delivered is True for result in results)
    assert adapter.delivered == ["turn-1"]
    assert [event.type for event in store.list_stream("crew-1")].count("turn.delivered") == 1


def test_turn_service_same_attempt_failure_replay_returns_stored_failure(
    tmp_path: Path,
) -> None:
    store = SQLiteEventStore(tmp_path / "events.sqlite3")
    adapter = FakeAdapter(delivered=False, reason="marker missing")
    service = TurnService(event_store=store, adapter=adapter)

    first = service.request_and_deliver(make_turn())
    second = service.request_and_deliver(make_turn())

    assert first.delivered is False
    assert second == DeliveryResult(
        delivered=False,
        marker="marker-1",
        reason="marker missing",
        artifact_refs=["artifact-1"],
    )
    assert adapter.delivered == ["turn-1"]


def test_turn_service_same_attempt_failure_replay_preserves_failed_marker(
    tmp_path: Path,
) -> None:
    store = SQLiteEventStore(tmp_path / "events.sqlite3")
    adapter = FakeAdapter(delivered=False, marker="partial-marker", reason="marker missing")
    service = TurnService(event_store=store, adapter=adapter)

    first = service.request_and_deliver(make_turn())
    second = service.request_and_deliver(make_turn())

    assert first.marker == "partial-marker"
    assert second == DeliveryResult(
        delivered=False,
        marker="partial-marker",
        reason="marker missing",
        artifact_refs=["artifact-1"],
    )
    assert adapter.delivered == ["turn-1"]


def test_turn_service_preexisting_delivery_started_returns_in_progress(
    tmp_path: Path,
) -> None:
    store = SQLiteEventStore(tmp_path / "events.sqlite3")
    turn = make_turn()
    store.append(
        stream_id=turn.crew_id,
        type="turn.delivery_started",
        crew_id=turn.crew_id,
        worker_id=turn.worker_id,
        turn_id=turn.turn_id,
        idempotency_key=f"{turn.idempotency_key}/attempt-{turn.attempt}/delivery-started",
        artifact_refs=["claim-log"],
    )
    adapter = FakeAdapter()
    service = TurnService(event_store=store, adapter=adapter)

    result = service.request_and_deliver(turn)

    assert result == DeliveryResult(
        delivered=False,
        marker="marker-1",
        reason="delivery already in progress",
        artifact_refs=["claim-log"],
    )
    assert adapter.delivered == []


def test_delivery_locks_cleaned_up_after_use(tmp_path: Path) -> None:
    """Lock entries should be removed after request_and_deliver completes."""
    from codex_claude_orchestrator.v4.turns import _delivery_locks, _delivery_locks_guard

    store = SQLiteEventStore(tmp_path / "events.sqlite3")
    adapter = FakeAdapter()
    service = TurnService(event_store=store, adapter=adapter)

    with _delivery_locks_guard:
        initial_count = len(_delivery_locks)

    service.request_and_deliver(make_turn())

    with _delivery_locks_guard:
        final_count = len(_delivery_locks)

    assert final_count <= initial_count


def test_turn_service_new_attempt_after_failure_delivers_again(tmp_path: Path) -> None:
    store = SQLiteEventStore(tmp_path / "events.sqlite3")
    adapter = FakeAdapter(delivered=False, reason="marker missing")
    service = TurnService(event_store=store, adapter=adapter)

    service.request_and_deliver(make_attempt(1))
    service.request_and_deliver(make_attempt(2))

    event_types = [event.type for event in store.list_stream("crew-1")]
    assert event_types.count("turn.requested") == 2
    assert event_types.count("turn.delivery_started") == 2
    assert event_types.count("turn.delivery_failed") == 2
    assert adapter.delivered == ["turn-1", "turn-1"]
