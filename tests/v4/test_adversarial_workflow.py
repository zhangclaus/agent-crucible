from codex_claude_orchestrator.v4.adversarial import (
    AdversarialEvaluator,
    ChallengeManager,
)
from codex_claude_orchestrator.v4.event_store import SQLiteEventStore
from codex_claude_orchestrator.v4.learning import LearningRecorder, SkillCandidateGate
from codex_claude_orchestrator.v4.learning_projection import LearningProjection
from codex_claude_orchestrator.v4.paths import V4Paths
from codex_claude_orchestrator.v4.watchers import OutboxWatcher


def test_challenge_repair_learning_flow_replays_without_terminal_output(tmp_path):
    store = SQLiteEventStore(tmp_path / "events.sqlite3")
    paths = V4Paths(repo_root=tmp_path, crew_id="crew-1")

    completed = store.append(
        stream_id="crew-1",
        type="turn.completed",
        crew_id="crew-1",
        worker_id="worker-1",
        turn_id="turn-1",
        round_id="round-1",
        contract_id="contract-1",
        artifact_refs=["workers/worker-1/outbox/turn-1.json"],
    )
    store.append(
        stream_id="crew-1",
        type="worker.outbox.detected",
        crew_id="crew-1",
        worker_id="worker-1",
        turn_id="turn-1",
        round_id="round-1",
        contract_id="contract-1",
        payload={"valid": True, "status": "completed", "verification": []},
    )

    challenge = AdversarialEvaluator(event_store=store).evaluate_completed_turn(completed)
    before_repair = LearningProjection.from_events(store.list_stream("crew-1"))
    assert before_repair.open_challenge_ids == [challenge.payload["challenge_id"]]
    assert before_repair.has_blocking_challenge is True

    repair = ChallengeManager(event_store=store).complete_repair(
        crew_id="crew-1",
        worker_id="worker-2",
        round_id="round-1",
        contract_id="contract-repair-1",
        challenge_id=challenge.payload["challenge_id"],
        repair_turn_id="turn-repair-1",
        outcome="fixed",
        verification_event_ids=["evt-verification"],
        changed_files=["tests/test_feature.py"],
    )
    note = LearningRecorder(event_store=store, paths=paths).create_note(
        note_id="note-1",
        source_challenge_ids=[challenge.payload["challenge_id"]],
        source_event_ids=[challenge.event_id, repair.event_id],
        failure_class="missing_verification",
        lesson="Do not accept repair turns without passed verification evidence.",
        trigger_conditions=["repair turn", "missing verification"],
        scope="v4 readiness",
    )
    gate = SkillCandidateGate(event_store=store, paths=paths)
    gate.create_candidate(
        candidate_id="skill-1",
        source_note_ids=[note.payload["note_id"]],
        source_event_ids=[note.event_id],
        summary="Require passed verification evidence for repair turns.",
        trigger_conditions=["repair turn"],
        body="Check `verification.passed` or passed outbox verification before readiness.",
    )

    projection = LearningProjection.from_events(store.list_stream("crew-1"))

    assert projection.open_challenge_ids == []
    assert projection.has_blocking_challenge is False
    assert projection.candidate_states["skill-1"] == "pending"
    assert projection.active_skill_refs == []
    assert paths.learning_note_path("note-1").exists()
    assert paths.skill_candidate_path("skill-1").exists()


def test_outbox_watcher_verification_prevents_false_challenge(tmp_path):
    store = SQLiteEventStore(tmp_path / "events.sqlite3")
    outbox_path = tmp_path / "turn-1.json"
    outbox_path.write_text(
        """
        {
          "crew_id": "crew-1",
          "worker_id": "worker-1",
          "turn_id": "turn-1",
          "status": "completed",
          "verification": [
            {
              "command": "pytest tests/v4 -q",
              "status": "passed",
              "summary": "V4 tests passed."
            }
          ]
        }
        """,
        encoding="utf-8",
    )
    completed = store.append(
        stream_id="crew-1",
        type="turn.completed",
        crew_id="crew-1",
        worker_id="worker-1",
        turn_id="turn-1",
        round_id="round-1",
        contract_id="contract-1",
        artifact_refs=["workers/worker-1/outbox/turn-1.json"],
    )

    for event in OutboxWatcher().watch(
        crew_id="crew-1",
        turn_id="turn-1",
        worker_id="worker-1",
        outbox_path=outbox_path,
        artifact_ref="workers/worker-1/outbox/turn-1.json",
    ):
        store.append(
            stream_id="crew-1",
            type=event.type,
            crew_id="crew-1",
            worker_id=event.worker_id,
            turn_id=event.turn_id,
            round_id="round-1",
            contract_id="contract-1",
            payload=event.payload,
            artifact_refs=event.artifact_refs,
        )

    review = AdversarialEvaluator(event_store=store).evaluate_completed_turn(completed)

    assert review.type == "review.completed"
    assert review.payload["verdict"] == "pass"
