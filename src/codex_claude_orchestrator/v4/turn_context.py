"""Turn context assembly for V4 worker turns."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class InboxReader(Protocol):
    def read_inbox(self, *, crew_id: str, recipient: str, mark_read: bool = False) -> list[dict]:
        ...


@dataclass(frozen=True, slots=True)
class TurnContext:
    crew_id: str
    worker_id: str
    unread_count: int
    unread_message_ids: list[str] = field(default_factory=list)
    unread_inbox_digest: str = ""


class TurnContextBuilder:
    def __init__(self, message_bus: InboxReader):
        self._message_bus = message_bus

    def build(self, *, crew_id: str, worker_id: str) -> TurnContext:
        unread = self._message_bus.read_inbox(
            crew_id=crew_id,
            recipient=worker_id,
            mark_read=False,
        )
        unread_message_ids = [
            message["message_id"]
            for message in unread
            if isinstance(message.get("message_id"), str)
        ]
        return TurnContext(
            crew_id=crew_id,
            worker_id=worker_id,
            unread_count=len(unread),
            unread_message_ids=unread_message_ids,
            unread_inbox_digest=_digest_messages(unread),
        )


def _digest_messages(messages: list[dict]) -> str:
    lines = []
    for message in messages:
        message_id = _text(message.get("message_id"), "unknown-message")
        sender = _text(message.get("from"), "unknown-sender")
        message_type = _text(message.get("type"), "message")
        body = " ".join(_text(message.get("body"), "").split())
        if body:
            lines.append(f"- [{message_id}] {message_type} from {sender}: {body}")
        else:
            lines.append(f"- [{message_id}] {message_type} from {sender}")
    return "\n".join(lines)


def _text(value: object, default: str) -> str:
    return value if isinstance(value, str) and value else default
