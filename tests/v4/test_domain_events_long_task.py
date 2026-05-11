"""Tests for stage.planned and stage.completed domain events."""

from __future__ import annotations

from pathlib import Path

from codex_claude_orchestrator.v4.domain_events import DomainEventEmitter
from codex_claude_orchestrator.v4.event_store import SQLiteEventStore


def test_emit_stage_planned(tmp_path: Path):
    store = SQLiteEventStore(tmp_path / "events.sqlite3")
    emitter = DomainEventEmitter(store)

    event = emitter.emit_stage_planned(
        crew_id="crew-1",
        stage_id=1,
        goal="实现认证功能",
        acceptance_criteria=["支持 RS256", "token 过期 30 分钟"],
        sub_tasks=[{"task_id": "1a", "role": "backend-developer", "goal": "实现 JWT API"}],
        dependencies=[],
        contract={"api_endpoints": [{"method": "POST", "path": "/api/auth/login"}]},
    )

    assert event.type == "stage.planned"
    assert event.crew_id == "crew-1"
    assert event.payload["stage_id"] == 1
    assert event.payload["goal"] == "实现认证功能"
    assert event.payload["acceptance_criteria"] == ["支持 RS256", "token 过期 30 分钟"]
    assert event.payload["sub_tasks"][0]["task_id"] == "1a"
    assert event.payload["contract"]["api_endpoints"][0]["method"] == "POST"


def test_emit_stage_completed(tmp_path: Path):
    store = SQLiteEventStore(tmp_path / "events.sqlite3")
    emitter = DomainEventEmitter(store)

    event = emitter.emit_stage_completed(
        crew_id="crew-1",
        stage_id=1,
        summary="实现了 JWT 认证，测试通过",
        verdict="OK",
        action="pass",
        changed_files=["src/api/auth.py", "tests/test_auth.py"],
    )

    assert event.type == "stage.completed"
    assert event.crew_id == "crew-1"
    assert event.payload["stage_id"] == 1
    assert event.payload["summary"] == "实现了 JWT 认证，测试通过"
    assert event.payload["verdict"] == "OK"
    assert event.payload["action"] == "pass"
    assert event.payload["changed_files"] == ["src/api/auth.py", "tests/test_auth.py"]


def test_emit_stage_planned_idempotent(tmp_path: Path):
    """Same stage_id should be idempotent."""
    store = SQLiteEventStore(tmp_path / "events.sqlite3")
    emitter = DomainEventEmitter(store)

    event1 = emitter.emit_stage_planned(
        crew_id="crew-1", stage_id=1, goal="test",
        acceptance_criteria=[], sub_tasks=[], dependencies=[],
    )
    event2 = emitter.emit_stage_planned(
        crew_id="crew-1", stage_id=1, goal="test",
        acceptance_criteria=[], sub_tasks=[], dependencies=[],
    )
    assert event1.event_id == event2.event_id  # idempotent


def test_emit_stage_completed_idempotent(tmp_path: Path):
    """Same stage_id should be idempotent."""
    store = SQLiteEventStore(tmp_path / "events.sqlite3")
    emitter = DomainEventEmitter(store)

    event1 = emitter.emit_stage_completed(
        crew_id="crew-1", stage_id=1, summary="done", verdict="OK", action="pass",
    )
    event2 = emitter.emit_stage_completed(
        crew_id="crew-1", stage_id=1, summary="done", verdict="OK", action="pass",
    )
    assert event1.event_id == event2.event_id
