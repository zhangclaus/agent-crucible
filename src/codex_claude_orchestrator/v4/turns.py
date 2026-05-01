"""Turn delivery service for the durable V4 runtime."""

from __future__ import annotations

from codex_claude_orchestrator.v4.event_store import SQLiteEventStore
from codex_claude_orchestrator.v4.runtime import DeliveryResult, RuntimeAdapter, TurnEnvelope


class TurnService:
    def __init__(self, *, event_store: SQLiteEventStore, adapter: RuntimeAdapter) -> None:
        self._events = event_store
        self._adapter = adapter

    def request_and_deliver(self, turn: TurnEnvelope) -> DeliveryResult:
        self._events.append(
            stream_id=turn.crew_id,
            type="turn.requested",
            crew_id=turn.crew_id,
            worker_id=turn.worker_id,
            turn_id=turn.turn_id,
            idempotency_key=f"{turn.idempotency_key}/requested",
            payload={
                "round_id": turn.round_id,
                "phase": turn.phase,
                "message": turn.message,
                "expected_marker": turn.expected_marker,
                "deadline_at": turn.deadline_at,
                "attempt": turn.attempt,
            },
        )

        delivered_event = self._events.get_by_idempotency_key(
            f"{turn.idempotency_key}/delivered"
        )
        if delivered_event is not None:
            return DeliveryResult(
                delivered=True,
                marker=delivered_event.payload.get("marker", turn.expected_marker),
                reason="already delivered",
                artifact_refs=list(delivered_event.artifact_refs),
            )

        self._events.append(
            stream_id=turn.crew_id,
            type="turn.delivery_started",
            crew_id=turn.crew_id,
            worker_id=turn.worker_id,
            turn_id=turn.turn_id,
            idempotency_key=f"{turn.idempotency_key}/delivery-started",
        )

        result = self._adapter.deliver_turn(turn)
        if result.delivered:
            self._events.append(
                stream_id=turn.crew_id,
                type="turn.delivered",
                crew_id=turn.crew_id,
                worker_id=turn.worker_id,
                turn_id=turn.turn_id,
                idempotency_key=f"{turn.idempotency_key}/delivered",
                payload={"marker": result.marker, "reason": result.reason},
                artifact_refs=result.artifact_refs,
            )
        else:
            self._events.append(
                stream_id=turn.crew_id,
                type="turn.delivery_failed",
                crew_id=turn.crew_id,
                worker_id=turn.worker_id,
                turn_id=turn.turn_id,
                idempotency_key=f"{turn.idempotency_key}/delivery-failed/{turn.attempt}",
                payload={"reason": result.reason},
                artifact_refs=result.artifact_refs,
            )

        return result
