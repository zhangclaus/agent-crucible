from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import pytest

from codex_claude_orchestrator.v4.events import AgentEvent


class EventType(StrEnum):
    WORKER_STARTED = "worker.started"


@dataclass
class NestedPayload:
    path: Path
    kind: EventType


def test_agent_event_to_dict_normalizes_nested_values() -> None:
    event = AgentEvent(
        event_id="evt-1",
        stream_id="stream-1",
        sequence=1,
        type=EventType.WORKER_STARTED,
        crew_id="crew-1",
        worker_id="worker-1",
        turn_id="turn-1",
        idempotency_key="worker-1:start",
        payload={
            "nested": NestedPayload(Path("logs/worker-1.jsonl"), EventType.WORKER_STARTED),
            7: [Path("artifacts/result.txt"), EventType.WORKER_STARTED],
        },
        artifact_refs=["artifact-1"],
        created_at="2026-05-01T00:00:00Z",
    )

    assert event.to_dict() == {
        "event_id": "evt-1",
        "stream_id": "stream-1",
        "sequence": 1,
        "type": "worker.started",
        "crew_id": "crew-1",
        "worker_id": "worker-1",
        "turn_id": "turn-1",
        "idempotency_key": "worker-1:start",
        "payload": {
            "nested": {"path": "logs/worker-1.jsonl", "kind": "worker.started"},
            "7": ["artifacts/result.txt", "worker.started"],
        },
        "artifact_refs": ["artifact-1"],
        "created_at": "2026-05-01T00:00:00Z",
    }


def test_agent_event_rejects_missing_type() -> None:
    with pytest.raises(ValueError, match="type is required"):
        AgentEvent(event_id="evt-1", stream_id="stream-1", sequence=1, type="")
