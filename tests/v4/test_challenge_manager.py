import pytest

from codex_claude_orchestrator.v4.adversarial import ChallengeManager
from codex_claude_orchestrator.v4.event_store import SQLiteEventStore


def test_challenge_manager_requests_repair_from_challenge_event(tmp_path):
    store = SQLiteEventStore(tmp_path / "events.sqlite3")
    challenge = store.append(
        stream_id="crew-1",
        type="challenge.issued",
        crew_id="crew-1",
        worker_id="worker-1",
        turn_id="turn-1",
        round_id="round-1",
        contract_id="contract-1",
        payload={
            "challenge_id": "challenge-1",
            "source_turn_id": "turn-1",
            "source_event_ids": ["evt-source"],
            "severity": "block",
            "category": "missing_verification",
            "finding": "No verification.",
            "required_response": "Repair with verification.",
            "repair_allowed": True,
            "artifact_refs": ["workers/worker-1/outbox/turn-1.json"],
        },
    )

    manager = ChallengeManager(event_store=store)
    event = manager.request_repair(
        challenge,
        repair_contract_id="contract-repair-1",
        repair_turn_id="turn-repair-1",
        worker_policy="fresh_worker",
        allowed_write_scope=["src/**/*.py", "tests/**/*.py"],
        acceptance_criteria=["Repair includes passed verification."],
        required_outbox_path="workers/worker-2/outbox/turn-repair-1.json",
    )

    assert event.type == "repair.requested"
    assert event.payload["challenge_id"] == "challenge-1"
    assert event.payload["worker_policy"] == "fresh_worker"
    assert event.turn_id == "turn-repair-1"


def test_challenge_manager_records_repair_completion(tmp_path):
    store = SQLiteEventStore(tmp_path / "events.sqlite3")
    manager = ChallengeManager(event_store=store)

    event = manager.complete_repair(
        crew_id="crew-1",
        worker_id="worker-2",
        round_id="round-1",
        contract_id="contract-repair-1",
        challenge_id="challenge-1",
        repair_turn_id="turn-repair-1",
        outcome="fixed",
        verification_event_ids=["evt-verification"],
        changed_files=["tests/test_feature.py"],
    )

    assert event.type == "repair.completed"
    assert event.payload["outcome"] == "fixed"
    assert event.payload["verification_event_ids"] == ["evt-verification"]


def test_challenge_manager_rejects_repair_when_challenge_disallows_it(tmp_path):
    store = SQLiteEventStore(tmp_path / "events.sqlite3")
    challenge = store.append(
        stream_id="crew-1",
        type="challenge.issued",
        crew_id="crew-1",
        worker_id="worker-1",
        turn_id="turn-1",
        round_id="round-1",
        contract_id="contract-1",
        payload={"challenge_id": "challenge-1", "repair_allowed": False},
    )
    manager = ChallengeManager(event_store=store)

    with pytest.raises(ValueError, match="challenge does not allow repair"):
        manager.request_repair(
            challenge,
            repair_contract_id="contract-repair-1",
            repair_turn_id="turn-repair-1",
            worker_policy="fresh_worker",
            allowed_write_scope=["src/**/*.py"],
            acceptance_criteria=["Repair includes passed verification."],
            required_outbox_path="workers/worker-2/outbox/turn-repair-1.json",
        )

    assert [event.type for event in store.list_all()] == ["challenge.issued"]


def test_challenge_manager_dedupes_identical_repair_request(tmp_path):
    store = SQLiteEventStore(tmp_path / "events.sqlite3")
    challenge = store.append(
        stream_id="crew-1",
        type="challenge.issued",
        crew_id="crew-1",
        worker_id="worker-1",
        turn_id="turn-1",
        round_id="round-1",
        contract_id="contract-1",
        payload={"challenge_id": "challenge-1", "repair_allowed": True},
    )
    manager = ChallengeManager(event_store=store)

    first = manager.request_repair(
        challenge,
        repair_contract_id="contract-repair-1",
        repair_turn_id="turn-repair-1",
        worker_policy="fresh_worker",
        allowed_write_scope=["src/**/*.py"],
        acceptance_criteria=["Repair includes passed verification."],
        required_outbox_path="workers/worker-2/outbox/turn-repair-1.json",
    )
    second = manager.request_repair(
        challenge,
        repair_contract_id="contract-repair-1",
        repair_turn_id="turn-repair-1",
        worker_policy="fresh_worker",
        allowed_write_scope=["src/**/*.py"],
        acceptance_criteria=["Repair includes passed verification."],
        required_outbox_path="workers/worker-2/outbox/turn-repair-1.json",
    )

    assert second.event_id == first.event_id
