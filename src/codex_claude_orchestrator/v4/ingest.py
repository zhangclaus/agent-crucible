from __future__ import annotations

from codex_claude_orchestrator.v4.runtime import RuntimeEvent


TURN_DONE_PREFIX = "<<<CODEX_TURN_DONE"


class OutputIngestor:
    def current_turn_text(self, text: str, *, expected_marker: str) -> str:
        before_marker = text.split(expected_marker, 1)[0] if expected_marker else text
        prior_start = before_marker.rfind(TURN_DONE_PREFIX)
        prior_end = -1
        while prior_start != -1:
            prior_end = before_marker.find(">>>", prior_start)
            if prior_end != -1:
                break
            prior_start = before_marker.rfind(TURN_DONE_PREFIX, 0, prior_start)
        if prior_start == -1 or prior_end == -1:
            return before_marker
        current_text = before_marker[prior_end + len(">>>") :]
        if current_text.startswith("\r\n"):
            return current_text[2:]
        if current_text.startswith("\n"):
            return current_text[1:]
        return current_text

    def to_output_events(
        self,
        *,
        turn_id: str,
        worker_id: str,
        text: str,
        artifact_ref: str = "",
    ) -> list[RuntimeEvent]:
        artifact_refs = [artifact_ref] if artifact_ref else []
        return [
            RuntimeEvent(
                type="output.chunk",
                turn_id=turn_id,
                worker_id=worker_id,
                payload={"text": line},
                artifact_refs=artifact_refs,
            )
            for line in text.splitlines()
        ]
