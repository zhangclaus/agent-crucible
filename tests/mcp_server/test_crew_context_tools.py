import json
from unittest.mock import MagicMock

from codex_claude_orchestrator.mcp_server.tools.crew_context import register_context_tools


class FakeServer:
    def __init__(self):
        self.tools = {}

    def tool(self, name):
        def decorator(func):
            self.tools[name] = func
            return func
        return decorator


def test_context_tools_registered():
    server = FakeServer()
    controller = MagicMock()
    register_context_tools(server, controller)
    assert "crew_blackboard" in server.tools
    assert "crew_events" in server.tools
    assert "crew_observe" in server.tools
    assert "crew_changes" in server.tools
    assert "crew_diff" in server.tools


def test_crew_blackboard_calls_controller():
    server = FakeServer()
    controller = MagicMock()
    controller.blackboard_entries.return_value = [
        {"entry_id": "e1", "type": "fact", "content": "test"},
    ]
    register_context_tools(server, controller)
    import asyncio
    result = asyncio.run(server.tools["crew_blackboard"](crew_id="c1"))
    data = json.loads(result[0].text)
    assert len(data) == 1
    controller.blackboard_entries.assert_called_once_with(crew_id="c1")


def test_crew_blackboard_filters_by_worker_id():
    server = FakeServer()
    controller = MagicMock()
    controller.blackboard_entries.return_value = [
        {"entry_id": "e1", "actor_id": "w1", "type": "fact", "content": "a"},
        {"entry_id": "e2", "actor_id": "w2", "type": "fact", "content": "b"},
    ]
    register_context_tools(server, controller)
    import asyncio
    result = asyncio.run(server.tools["crew_blackboard"](crew_id="c1", worker_id="w1"))
    data = json.loads(result[0].text)
    assert len(data) == 1
    assert data[0]["actor_id"] == "w1"


def test_crew_blackboard_filters_by_entry_type():
    server = FakeServer()
    controller = MagicMock()
    controller.blackboard_entries.return_value = [
        {"entry_id": "e1", "type": "fact", "content": "a"},
        {"entry_id": "e2", "type": "patch", "content": "b"},
    ]
    register_context_tools(server, controller)
    import asyncio
    result = asyncio.run(server.tools["crew_blackboard"](crew_id="c1", entry_type="patch"))
    data = json.loads(result[0].text)
    assert len(data) == 1
    assert data[0]["type"] == "patch"


def test_crew_events_calls_controller():
    from pathlib import Path
    server = FakeServer()
    controller = MagicMock()
    controller.status.return_value = {
        "decisions": [{"type": "crew.started", "data": {}}],
        "messages": [{"type": "turn.completed", "data": {}}],
    }
    register_context_tools(server, controller)
    import asyncio
    result = asyncio.run(server.tools["crew_events"](repo="/repo", crew_id="c1"))
    data = json.loads(result[0].text)
    assert len(data) == 2
    controller.status.assert_called_once_with(repo_root=Path("/repo"), crew_id="c1")


def test_crew_events_filters_non_key_events():
    server = FakeServer()
    controller = MagicMock()
    controller.status.return_value = {
        "decisions": [
            {"type": "crew.started", "data": {}},
            {"type": "noise.event", "data": {}},
        ],
        "messages": [
            {"type": "turn.completed", "data": {}},
            {"type": "random.event", "data": {}},
        ],
    }
    register_context_tools(server, controller)
    import asyncio
    result = asyncio.run(server.tools["crew_events"](repo="/repo", crew_id="c1"))
    data = json.loads(result[0].text)
    assert len(data) == 2


def test_crew_observe_calls_controller():
    from pathlib import Path
    server = FakeServer()
    controller = MagicMock()
    controller.observe_worker.return_value = {"snapshot": "worker output here", "marker_seen": True, "message_blocks": []}
    register_context_tools(server, controller)
    import asyncio
    result = asyncio.run(server.tools["crew_observe"](repo="/repo", crew_id="c1", worker_id="w1"))
    data = json.loads(result[0].text)
    assert "status" in data
    assert "summary" in data
    assert "changed_files" in data
    assert "marker_seen" in data
    assert "snapshot" not in data
    controller.observe_worker.assert_called_once_with(
        repo_root=Path("/repo"), crew_id="c1", worker_id="w1",
    )


def test_crew_changes_calls_controller():
    server = FakeServer()
    controller = MagicMock()
    controller.changes.return_value = [
        {"worker_id": "w1", "changed_files": ["src/foo.py", "src/bar.py"]},
    ]
    register_context_tools(server, controller)
    import asyncio
    result = asyncio.run(server.tools["crew_changes"](crew_id="c1"))
    data = json.loads(result[0].text)
    assert data == ["src/foo.py", "src/bar.py"]
    controller.changes.assert_called_once_with(crew_id="c1")


def test_crew_changes_aggregates_multiple_workers():
    server = FakeServer()
    controller = MagicMock()
    controller.changes.return_value = [
        {"worker_id": "w1", "changed_files": ["src/foo.py"]},
        {"worker_id": "w2", "changed_files": ["src/bar.py", "src/foo.py"]},
    ]
    register_context_tools(server, controller)
    import asyncio
    result = asyncio.run(server.tools["crew_changes"](crew_id="c1"))
    data = json.loads(result[0].text)
    assert data == ["src/foo.py", "src/bar.py"]  # deduplicated


def test_crew_diff_calls_controller():
    server = FakeServer()
    controller = MagicMock()
    controller.changes.return_value = [
        {"worker_id": "w1", "changed_files": ["src/foo.py", "src/bar.py"], "branch": "codex/c1-w1"},
    ]
    register_context_tools(server, controller)
    import asyncio
    result = asyncio.run(server.tools["crew_diff"](crew_id="c1", file="src/foo.py"))
    data = json.loads(result[0].text)
    assert len(data) == 1
    assert data[0]["worker_id"] == "w1"
    assert "src/foo.py" in data[0]["changed_files"]


def test_crew_diff_returns_all_when_no_file():
    server = FakeServer()
    controller = MagicMock()
    controller.changes.return_value = [
        {"worker_id": "w1", "changed_files": ["src/foo.py"], "branch": "b1"},
        {"worker_id": "w2", "changed_files": ["src/bar.py"], "branch": "b2"},
    ]
    register_context_tools(server, controller)
    import asyncio
    result = asyncio.run(server.tools["crew_diff"](crew_id="c1"))
    data = json.loads(result[0].text)
    assert len(data) == 2


def test_crew_blackboard_triggers_summarizer_when_over_threshold():
    """When blackboard has >20 entries and no fresh summary, spawn summarizer async."""
    from pathlib import Path
    server = FakeServer()
    controller = MagicMock()
    entries = [
        {"entry_id": f"e{i}", "type": "fact", "content": f"entry {i}",
         "timestamp": f"2026-05-06T{i:02d}:00:00"}
        for i in range(25)
    ]
    controller.blackboard_entries.return_value = entries
    controller.ensure_worker.return_value = {"worker_id": "ws1", "status": "running"}
    register_context_tools(server, controller)
    import asyncio
    result = asyncio.run(server.tools["crew_blackboard"](crew_id="c1", repo="/repo"))
    data = json.loads(result[0].text)
    assert len(data) > 0
    controller.ensure_worker.assert_called_once()
    call_kwargs = controller.ensure_worker.call_args[1]
    assert call_kwargs["contract"].label == "summarizer"
    assert call_kwargs["repo_root"] == Path("/repo")


def test_crew_blackboard_no_trigger_when_under_threshold():
    """When blackboard has <=20 entries, no summarizer spawned."""
    server = FakeServer()
    controller = MagicMock()
    entries = [
        {"entry_id": f"e{i}", "type": "fact", "content": f"entry {i}",
         "timestamp": f"2026-05-06T{i:02d}:00:00"}
        for i in range(10)
    ]
    controller.blackboard_entries.return_value = entries
    register_context_tools(server, controller)
    import asyncio
    result = asyncio.run(server.tools["crew_blackboard"](crew_id="c1", repo="/repo"))
    data = json.loads(result[0].text)
    assert len(data) > 0
    controller.ensure_worker.assert_not_called()


def test_crew_blackboard_no_trigger_when_fresh_summary():
    """When a fresh summary exists, no summarizer spawned even if over threshold."""
    server = FakeServer()
    controller = MagicMock()
    entries = [
        {"entry_id": f"e{i}", "type": "fact", "content": f"entry {i}",
         "timestamp": f"2026-05-06T{i:02d}:00:00"}
        for i in range(22)
    ]
    entries.append({
        "entry_id": "s1", "type": "summary", "content": "the summary",
        "timestamp": "2026-05-06T50:00:00",
    })
    controller.blackboard_entries.return_value = entries
    register_context_tools(server, controller)
    import asyncio
    result = asyncio.run(server.tools["crew_blackboard"](crew_id="c1", repo="/repo"))
    data = json.loads(result[0].text)
    assert len(data) > 0
    controller.ensure_worker.assert_not_called()


def test_crew_blackboard_no_trigger_without_repo():
    """When repo is not provided, trigger is skipped even if over threshold."""
    server = FakeServer()
    controller = MagicMock()
    entries = [
        {"entry_id": f"e{i}", "type": "fact", "content": f"entry {i}",
         "timestamp": f"2026-05-06T{i:02d}:00:00"}
        for i in range(25)
    ]
    controller.blackboard_entries.return_value = entries
    register_context_tools(server, controller)
    import asyncio
    result = asyncio.run(server.tools["crew_blackboard"](crew_id="c1"))
    data = json.loads(result[0].text)
    assert len(data) > 0
    controller.ensure_worker.assert_not_called()


def test_crew_blackboard_returns_error_on_exception():
    server = FakeServer()
    controller = MagicMock()
    controller.blackboard_entries.side_effect = FileNotFoundError("crew not found: c1")
    register_context_tools(server, controller)
    import asyncio
    result = asyncio.run(server.tools["crew_blackboard"](crew_id="c1"))
    data = json.loads(result[0].text)
    assert "error" in data


def test_crew_events_returns_error_on_exception():
    server = FakeServer()
    controller = MagicMock()
    controller.status.side_effect = FileNotFoundError("crew not found: c1")
    register_context_tools(server, controller)
    import asyncio
    result = asyncio.run(server.tools["crew_events"](repo="/repo", crew_id="c1"))
    data = json.loads(result[0].text)
    assert "error" in data


def test_crew_observe_returns_error_on_exception():
    server = FakeServer()
    controller = MagicMock()
    controller.observe_worker.side_effect = FileNotFoundError("worker not found: w1")
    register_context_tools(server, controller)
    import asyncio
    result = asyncio.run(server.tools["crew_observe"](repo="/repo", crew_id="c1", worker_id="w1"))
    data = json.loads(result[0].text)
    assert "error" in data


def test_crew_changes_returns_error_on_value_error():
    server = FakeServer()
    controller = MagicMock()
    controller.changes.side_effect = ValueError("change recorder not configured")
    register_context_tools(server, controller)
    import asyncio
    result = asyncio.run(server.tools["crew_changes"](crew_id="c1"))
    data = json.loads(result[0].text)
    assert "error" in data


def test_crew_diff_returns_error_on_exception():
    server = FakeServer()
    controller = MagicMock()
    controller.changes.side_effect = FileNotFoundError("crew not found: c1")
    register_context_tools(server, controller)
    import asyncio
    result = asyncio.run(server.tools["crew_diff"](crew_id="c1"))
    data = json.loads(result[0].text)
    assert "error" in data
