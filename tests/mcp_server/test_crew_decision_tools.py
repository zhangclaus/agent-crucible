import json
from unittest.mock import MagicMock

from codex_claude_orchestrator.mcp_server.tools.crew_decision import register_decision_tools


class FakeServer:
    def __init__(self):
        self.tools = {}

    def tool(self, name):
        def decorator(func):
            self.tools[name] = func
            return func
        return decorator


def test_decision_tools_registered():
    server = FakeServer()
    controller = MagicMock()
    register_decision_tools(server, controller)
    assert "crew_accept" in server.tools
    assert "crew_challenge" in server.tools


def test_crew_accept():
    server = FakeServer()
    controller = MagicMock()
    controller.accept.return_value = {"status": "accepted"}
    register_decision_tools(server, controller)
    import asyncio
    result = asyncio.run(server.tools["crew_accept"](crew_id="c1"))
    data = json.loads(result[0].text)
    assert data["status"] == "accepted"
    controller.accept.assert_called_once_with(crew_id="c1", summary="Accepted by user")


def test_crew_accept_passes_summary():
    server = FakeServer()
    controller = MagicMock()
    controller.accept.return_value = {"status": "accepted"}
    register_decision_tools(server, controller)
    import asyncio
    result = asyncio.run(server.tools["crew_accept"](crew_id="c1", summary="looks good"))
    data = json.loads(result[0].text)
    assert data["status"] == "accepted"
    controller.accept.assert_called_once_with(crew_id="c1", summary="looks good")


def test_crew_accept_default_summary():
    server = FakeServer()
    controller = MagicMock()
    controller.accept.return_value = {"status": "accepted"}
    register_decision_tools(server, controller)
    import asyncio
    result = asyncio.run(server.tools["crew_accept"](crew_id="c1"))
    controller.accept.assert_called_once_with(crew_id="c1", summary="Accepted by user")


def test_crew_accept_returns_error_on_exception():
    server = FakeServer()
    controller = MagicMock()
    controller.accept.side_effect = FileNotFoundError("crew not found: c1")
    register_decision_tools(server, controller)
    import asyncio
    result = asyncio.run(server.tools["crew_accept"](crew_id="c1"))
    data = json.loads(result[0].text)
    assert "error" in data
    assert "crew not found" in data["error"]


class TestCrewChallenge:
    def test_crew_challenge(self):
        """crew_challenge should record a challenge for a worker."""
        server = FakeServer()
        controller = MagicMock()
        controller.challenge.return_value = {"crew_id": "crew-1", "summary": "fix this"}
        register_decision_tools(server, controller)

        import asyncio
        result = asyncio.run(server.tools["crew_challenge"](
            crew_id="crew-1",
            summary="fix this",
            task_id="w1",
        ))

        response = json.loads(result[0].text)
        assert response["crew_id"] == "crew-1"
        controller.challenge.assert_called_once_with(
            crew_id="crew-1",
            summary="fix this",
            task_id="w1",
        )

    def test_crew_challenge_without_task_id(self):
        """crew_challenge should work without task_id."""
        server = FakeServer()
        controller = MagicMock()
        controller.challenge.return_value = {"crew_id": "crew-1", "summary": "fix this"}
        register_decision_tools(server, controller)

        import asyncio
        result = asyncio.run(server.tools["crew_challenge"](
            crew_id="crew-1",
            summary="fix this",
        ))

        response = json.loads(result[0].text)
        assert response["crew_id"] == "crew-1"
        controller.challenge.assert_called_once_with(
            crew_id="crew-1",
            summary="fix this",
            task_id=None,
        )

    def test_crew_challenge_not_found(self):
        """crew_challenge should return error when crew not found."""
        server = FakeServer()
        controller = MagicMock()
        controller.challenge.side_effect = FileNotFoundError("crew not found: crew-1")
        register_decision_tools(server, controller)

        import asyncio
        result = asyncio.run(server.tools["crew_challenge"](
            crew_id="crew-1",
            summary="fix this",
        ))

        response = json.loads(result[0].text)
        assert "error" in response
        assert "crew not found" in response["error"]
