"""Completion detection for V4 runtime turns."""

from __future__ import annotations

from dataclasses import dataclass, field

from codex_claude_orchestrator.v4.runtime import RuntimeEvent, TurnEnvelope


@dataclass(frozen=True, slots=True)
class CompletionDecision:
    event_type: str
    reason: str
    evidence_refs: list[str] = field(default_factory=list)


class CompletionDetector:
    @staticmethod
    def evaluate(
        turn: TurnEnvelope,
        events: list[RuntimeEvent],
        contract_marker: str = "",
        timed_out: bool = False,
    ) -> CompletionDecision:
        output_text = "".join(
            str(event.payload.get("text", ""))
            for event in events
            if event.type == "output.chunk"
        )
        evidence_refs = list(
            dict.fromkeys(
                artifact_ref
                for event in events
                for artifact_ref in event.artifact_refs
            )
        )

        if turn.expected_marker and turn.expected_marker in output_text:
            return CompletionDecision(
                event_type="turn.completed",
                reason="expected marker detected",
                evidence_refs=evidence_refs,
            )

        if contract_marker and contract_marker in output_text:
            return CompletionDecision(
                event_type="turn.inconclusive",
                reason="contract marker found but expected turn marker was missing",
                evidence_refs=evidence_refs,
            )

        for event in events:
            if event.type == "process.exited":
                return CompletionDecision(
                    event_type="turn.failed",
                    reason=event.payload.get("reason")
                    or "process exited before completion",
                    evidence_refs=evidence_refs,
                )

        if timed_out:
            return CompletionDecision(
                event_type="turn.timeout",
                reason="deadline reached before completion evidence",
                evidence_refs=evidence_refs,
            )

        return CompletionDecision(
            event_type="turn.inconclusive",
            reason="completion evidence not found",
            evidence_refs=evidence_refs,
        )
