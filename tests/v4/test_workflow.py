from codex_claude_orchestrator.crew.gates import GateResult
from codex_claude_orchestrator.crew.review_verdict import ReviewVerdict
from codex_claude_orchestrator.v4.gates import GateEventBuilder


def test_gate_event_builder_builds_scope_event_payload():
    event = GateEventBuilder().scope_evaluated(
        crew_id="crew-1",
        round_id="round-1",
        worker_id="worker-1",
        result=GateResult(status="pass", reason="inside scope", evidence_refs=["changes.json"]),
    )

    assert event.type == "scope.evaluated"
    assert event.payload["status"] == "pass"
    assert event.artifact_refs == ["changes.json"]


def test_gate_event_builder_builds_review_event_payload():
    event = GateEventBuilder().review_verdict(
        crew_id="crew-1",
        round_id="round-1",
        worker_id="worker-review",
        verdict=ReviewVerdict(status="warn", summary="minor", findings=["risk"], evidence_refs=["review.json"]),
    )

    assert event.type == "review.verdict"
    assert event.payload["status"] == "warn"
    assert event.payload["findings"] == ["risk"]
