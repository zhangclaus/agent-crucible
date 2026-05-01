from __future__ import annotations

from codex_claude_orchestrator.crew.gates import GateResult
from codex_claude_orchestrator.crew.readiness import ReadinessReport
from codex_claude_orchestrator.crew.review_verdict import ReviewVerdict
from codex_claude_orchestrator.v4.events import AgentEvent


class GateEventBuilder:
    def scope_evaluated(self, *, crew_id: str, round_id: str, worker_id: str, result: GateResult) -> AgentEvent:
        return AgentEvent(
            event_id=f"event-{crew_id}-{round_id}-scope",
            stream_id=crew_id,
            sequence=1,
            type="scope.evaluated",
            crew_id=crew_id,
            worker_id=worker_id,
            payload={"round_id": round_id, **result.to_dict()},
            artifact_refs=list(result.evidence_refs),
        )

    def review_verdict(self, *, crew_id: str, round_id: str, worker_id: str, verdict: ReviewVerdict) -> AgentEvent:
        return AgentEvent(
            event_id=f"event-{crew_id}-{round_id}-review",
            stream_id=crew_id,
            sequence=1,
            type="review.verdict",
            crew_id=crew_id,
            worker_id=worker_id,
            payload={"round_id": round_id, **verdict.to_dict()},
            artifact_refs=list(verdict.evidence_refs),
        )

    def readiness_evaluated(self, *, crew_id: str, round_id: str, worker_id: str, report: ReadinessReport) -> AgentEvent:
        return AgentEvent(
            event_id=f"event-{crew_id}-{round_id}-readiness",
            stream_id=crew_id,
            sequence=1,
            type="readiness.evaluated",
            crew_id=crew_id,
            worker_id=worker_id,
            payload=report.to_dict(),
            artifact_refs=list(report.evidence_refs),
        )
