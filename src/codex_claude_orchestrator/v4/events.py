"""Event primitives for the durable V4 runtime."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any


def normalize(value: Any) -> Any:
    """Convert supported Python objects into JSON-friendly primitives."""
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value):
        return normalize(asdict(value))
    if isinstance(value, dict):
        return {str(key): normalize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalize(item) for item in value]
    return value


@dataclass(slots=True)
class AgentEvent:
    event_id: str
    stream_id: str
    sequence: int
    type: str
    crew_id: str = ""
    worker_id: str = ""
    turn_id: str = ""
    round_id: str = ""
    contract_id: str = ""
    idempotency_key: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    artifact_refs: list[str] = field(default_factory=list)
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.event_id:
            raise ValueError("event_id is required")
        if not self.stream_id:
            raise ValueError("stream_id is required")
        if not self.type:
            raise ValueError("type is required")
        if self.sequence < 1:
            raise ValueError("sequence must be positive")

    def to_dict(self) -> dict[str, Any]:
        return normalize(self)
