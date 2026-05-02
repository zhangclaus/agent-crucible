from __future__ import annotations

from pathlib import Path

from codex_claude_orchestrator.crew.models import AgentMessageType, CrewRecord
from codex_claude_orchestrator.messaging.message_bus import AgentMessageBus
from codex_claude_orchestrator.state.crew_recorder import CrewRecorder
from codex_claude_orchestrator.v4.event_store import SQLiteEventStore
from codex_claude_orchestrator.v4.message_ack import MessageAckProcessor


def make_bus(tmp_path: Path) -> AgentMessageBus:
    recorder = CrewRecorder(tmp_path / ".orchestrator")
    recorder.start_crew(CrewRecord(crew_id="crew-1", repo=str(tmp_path), root_goal="goal"))
    return AgentMessageBus(
        recorder,
        message_id_factory=iter(["msg-1", "msg-2"]).__next__,
        thread_id_factory=iter(["thread-1", "thread-2"]).__next__,
    )


def append_turn_requested(store: SQLiteEventStore, unread_message_ids: list[str]) -> None:
    store.append(
        stream_id="crew-1",
        type="turn.requested",
        crew_id="crew-1",
        worker_id="worker-1",
        turn_id="turn-1",
        idempotency_key="crew-1/turn-1/requested",
        payload={"unread_message_ids": unread_message_ids},
    )


def append_outbox_detected(
    store: SQLiteEventStore,
    *,
    valid: bool = True,
    acknowledged_message_ids: list[str] | None = None,
):
    return store.append(
        stream_id="crew-1",
        type="worker.outbox.detected",
        crew_id="crew-1",
        worker_id="worker-1",
        turn_id="turn-1",
        idempotency_key="crew-1/turn-1/outbox",
        payload={
            "valid": valid,
            "status": "completed",
            "acknowledged_message_ids": acknowledged_message_ids or [],
        },
    )


def send_two_messages(bus: AgentMessageBus) -> None:
    bus.send(
        crew_id="crew-1",
        sender="codex",
        recipient="worker-1",
        message_type=AgentMessageType.QUESTION,
        body="first",
    )
    bus.send(
        crew_id="crew-1",
        sender="codex",
        recipient="worker-1",
        message_type=AgentMessageType.QUESTION,
        body="second",
    )


def test_valid_outbox_ack_emits_message_read_and_advances_cursor(tmp_path: Path) -> None:
    store = SQLiteEventStore(tmp_path / "events.sqlite3")
    bus = make_bus(tmp_path)
    send_two_messages(bus)
    append_turn_requested(store, ["msg-1", "msg-2"])
    outbox_event = append_outbox_detected(store, acknowledged_message_ids=["msg-1"])

    result = MessageAckProcessor(event_store=store, message_bus=bus).process(outbox_event)

    assert result.read_message_ids == ["msg-1"]
    assert bus.cursor_summary("crew-1") == {"worker-1": 1}
    assert [message["message_id"] for message in bus.read_inbox(crew_id="crew-1", recipient="worker-1")] == [
        "msg-2"
    ]
    assert [event.type for event in store.list_stream("crew-1")].count("message.read") == 1


def test_turn_delivered_does_not_advance_message_cursor(tmp_path: Path) -> None:
    store = SQLiteEventStore(tmp_path / "events.sqlite3")
    bus = make_bus(tmp_path)
    send_two_messages(bus)
    delivered_event = store.append(
        stream_id="crew-1",
        type="turn.delivered",
        crew_id="crew-1",
        worker_id="worker-1",
        turn_id="turn-1",
        idempotency_key="crew-1/turn-1/delivered",
    )

    result = MessageAckProcessor(event_store=store, message_bus=bus).process(delivered_event)

    assert result.read_message_ids == []
    assert bus.cursor_summary("crew-1") == {}


def test_invalid_outbox_ack_is_ignored(tmp_path: Path) -> None:
    store = SQLiteEventStore(tmp_path / "events.sqlite3")
    bus = make_bus(tmp_path)
    send_two_messages(bus)
    append_turn_requested(store, ["msg-1"])
    outbox_event = append_outbox_detected(
        store,
        valid=False,
        acknowledged_message_ids=["msg-1"],
    )

    result = MessageAckProcessor(event_store=store, message_bus=bus).process(outbox_event)

    assert result.read_message_ids == []
    assert bus.cursor_summary("crew-1") == {}
    assert "message.read" not in [event.type for event in store.list_stream("crew-1")]


def test_unknown_outbox_ack_records_invalid_event_without_advancing_cursor(
    tmp_path: Path,
) -> None:
    store = SQLiteEventStore(tmp_path / "events.sqlite3")
    bus = make_bus(tmp_path)
    send_two_messages(bus)
    append_turn_requested(store, ["msg-1"])
    outbox_event = append_outbox_detected(store, acknowledged_message_ids=["msg-404"])

    result = MessageAckProcessor(event_store=store, message_bus=bus).process(outbox_event)

    events = store.list_stream("crew-1")
    assert result.invalid_message_ids == ["msg-404"]
    assert bus.cursor_summary("crew-1") == {}
    assert [event.type for event in events].count("message.ack_invalid") == 1
    assert "message.read" not in [event.type for event in events]


def test_cursor_advances_only_through_contiguous_read_messages(tmp_path: Path) -> None:
    store = SQLiteEventStore(tmp_path / "events.sqlite3")
    bus = make_bus(tmp_path)
    send_two_messages(bus)
    append_turn_requested(store, ["msg-1", "msg-2"])
    processor = MessageAckProcessor(event_store=store, message_bus=bus)

    processor.process(append_outbox_detected(store, acknowledged_message_ids=["msg-2"]))
    assert bus.cursor_summary("crew-1") == {}

    outbox_event = store.append(
        stream_id="crew-1",
        type="worker.outbox.detected",
        crew_id="crew-1",
        worker_id="worker-1",
        turn_id="turn-1",
        idempotency_key="crew-1/turn-1/outbox-2",
        payload={
            "valid": True,
            "status": "completed",
            "acknowledged_message_ids": ["msg-1"],
        },
    )
    processor.process(outbox_event)

    assert bus.cursor_summary("crew-1") == {"worker-1": 2}
    assert bus.read_inbox(crew_id="crew-1", recipient="worker-1") == []
