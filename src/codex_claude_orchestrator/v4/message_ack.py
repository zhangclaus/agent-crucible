"""Message acknowledgement processing for V4 outbox results."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from codex_claude_orchestrator.v4.event_store_protocol import EventStore
from codex_claude_orchestrator.v4.events import AgentEvent


class MessageCursorWriter(Protocol):
    def advance_cursor_for_read_message_ids(
        self,
        *,
        crew_id: str,
        recipient: str,
        message_ids: list[str],
    ) -> list[str]:
        ...


@dataclass(frozen=True, slots=True)
class MessageAckResult:
    read_message_ids: list[str] = field(default_factory=list)
    invalid_message_ids: list[str] = field(default_factory=list)
    cursor_advanced_message_ids: list[str] = field(default_factory=list)


class MessageAckProcessor:
    def __init__(self, *, event_store: EventStore, message_bus: MessageCursorWriter):
        self._events = event_store
        self._message_bus = message_bus

    def process(self, outbox_event: AgentEvent) -> MessageAckResult:
        if (
            outbox_event.type != "worker.outbox.detected"
            or outbox_event.payload.get("valid") is not True
        ):
            return MessageAckResult()

        acknowledged_ids = _unique_strings(
            outbox_event.payload.get("acknowledged_message_ids", [])
        )
        if not acknowledged_ids:
            return MessageAckResult()

        delivered_ids = self._delivered_message_ids(outbox_event)
        delivered_id_set = set(delivered_ids)
        read_ids = [
            message_id
            for message_id in acknowledged_ids
            if message_id in delivered_id_set
        ]
        invalid_ids = [
            message_id
            for message_id in acknowledged_ids
            if message_id not in delivered_id_set
        ]

        for message_id in read_ids:
            self._append_message_read(outbox_event, message_id=message_id)
        for message_id in invalid_ids:
            self._append_invalid_ack(outbox_event, message_id=message_id)

        all_read_ids = self._read_message_ids(
            crew_id=outbox_event.crew_id,
            worker_id=outbox_event.worker_id,
        )
        advanced_ids = self._message_bus.advance_cursor_for_read_message_ids(
            crew_id=outbox_event.crew_id,
            recipient=outbox_event.worker_id,
            message_ids=all_read_ids,
        )
        return MessageAckResult(
            read_message_ids=read_ids,
            invalid_message_ids=invalid_ids,
            cursor_advanced_message_ids=advanced_ids,
        )

    def _delivered_message_ids(self, outbox_event: AgentEvent) -> list[str]:
        delivered: list[str] = []
        for event in self._events.list_by_turn(outbox_event.turn_id):
            if (
                event.crew_id != outbox_event.crew_id
                or event.worker_id != outbox_event.worker_id
                or event.type != "turn.requested"
            ):
                continue
            delivered.extend(_unique_strings(event.payload.get("unread_message_ids", [])))
        return list(dict.fromkeys(delivered))

    def _append_message_read(self, outbox_event: AgentEvent, *, message_id: str) -> AgentEvent:
        return self._events.append(
            stream_id=outbox_event.crew_id,
            type="message.read",
            crew_id=outbox_event.crew_id,
            worker_id=outbox_event.worker_id,
            turn_id=outbox_event.turn_id,
            round_id=outbox_event.round_id,
            contract_id=outbox_event.contract_id,
            idempotency_key=(
                f"{outbox_event.crew_id}/{outbox_event.worker_id}/"
                f"messages/{message_id}/read"
            ),
            payload={
                "message_id": message_id,
                "source_event_id": outbox_event.event_id,
            },
        )

    def _append_invalid_ack(self, outbox_event: AgentEvent, *, message_id: str) -> AgentEvent:
        return self._events.append(
            stream_id=outbox_event.crew_id,
            type="message.ack_invalid",
            crew_id=outbox_event.crew_id,
            worker_id=outbox_event.worker_id,
            turn_id=outbox_event.turn_id,
            round_id=outbox_event.round_id,
            contract_id=outbox_event.contract_id,
            idempotency_key=(
                f"{outbox_event.crew_id}/{outbox_event.worker_id}/"
                f"{outbox_event.turn_id}/messages/{message_id}/ack-invalid"
            ),
            payload={
                "message_id": message_id,
                "reason": "message id was not delivered in this turn",
                "source_event_id": outbox_event.event_id,
            },
        )

    def _read_message_ids(self, *, crew_id: str, worker_id: str) -> list[str]:
        message_ids: list[str] = []
        for event in self._events.list_stream(crew_id):
            if event.type != "message.read" or event.worker_id != worker_id:
                continue
            message_id = event.payload.get("message_id")
            if isinstance(message_id, str) and message_id:
                message_ids.append(message_id)
        return list(dict.fromkeys(message_ids))


def _unique_strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(item for item in value if isinstance(item, str) and item))
