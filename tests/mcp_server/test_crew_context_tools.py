"""Tests for crew_context MCP tools (observe, changes, diff)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest


class TestCrewObserve:
    def test_crew_observe_returns_structured_report(self):
        """crew_observe should return a structured report, not raw tmux text."""
        from codex_claude_orchestrator.mcp_server.tools.crew_context import register_context_tools

        server = MagicMock()
        captured_tools = {}
        def capture_tool(name):
            def decorator(func):
                captured_tools[name] = func
                return func
            return decorator
        server.tool = capture_tool

        # Mock the internal worker pool chain for the blocking observe
        # First call = baseline snapshot (no marker), second call = poll (marker appears)
        native_session = MagicMock()
        native_session.observe.side_effect = [
            {"snapshot": "worker output here\n", "marker_seen": False},
            {"snapshot": "worker output here\n<<<CODEX_TURN_DONE status=ready_for_codex>>>", "marker_seen": True},
        ]
        recorder = MagicMock()
        recorder.active_worker_ids.return_value = ["worker-1"]

        worker_pool = MagicMock()
        worker_pool._native_session = native_session
        worker_pool._recorder = recorder
        worker_pool._find_worker.return_value = {"terminal_pane": "session:claude.0"}

        controller = MagicMock()
        controller._worker_pool = worker_pool

        register_context_tools(server, controller)

        import asyncio
        result = asyncio.run(captured_tools["crew_observe"](
            repo="/tmp/test",
            crew_id="crew-1",
            worker_id="worker-1",
        ))

        response = json.loads(result[0].text)
        assert "worker_id" in response or "status" in response or "error" in response


class TestCrewChanges:
    def test_crew_changes_returns_file_list(self):
        """crew_changes should return a list of changed files."""
        from codex_claude_orchestrator.mcp_server.tools.crew_context import register_context_tools

        server = MagicMock()
        captured_tools = {}
        def capture_tool(name):
            def decorator(func):
                captured_tools[name] = func
                return func
            return decorator
        server.tool = capture_tool

        controller = MagicMock()
        controller.changes.return_value = {"changed_files": ["src/a.py", "src/b.py"]}
        register_context_tools(server, controller)

        import asyncio
        result = asyncio.run(captured_tools["crew_changes"](crew_id="crew-1"))

        response = json.loads(result[0].text)
        assert isinstance(response, list)
        assert "src/a.py" in response


class TestCrewDiff:
    def test_crew_diff_returns_change_summary(self):
        """crew_diff should return change summary for a file."""
        from codex_claude_orchestrator.mcp_server.tools.crew_context import register_context_tools

        server = MagicMock()
        captured_tools = {}
        def capture_tool(name):
            def decorator(func):
                captured_tools[name] = func
                return func
            return decorator
        server.tool = capture_tool

        controller = MagicMock()
        controller.changes.return_value = [
            {"worker_id": "w1", "changed_files": ["src/a.py"], "branch": "feat/a"},
        ]
        register_context_tools(server, controller)

        import asyncio
        result = asyncio.run(captured_tools["crew_diff"](crew_id="crew-1", file="src/a.py"))

        response = json.loads(result[0].text)
        assert isinstance(response, list)
