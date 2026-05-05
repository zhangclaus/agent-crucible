import json
from unittest.mock import MagicMock, patch

from codex_claude_orchestrator.mcp_server.tools.crew_execution import register_execution_tools


class FakeServer:
    def __init__(self):
        self.tools = {}

    def tool(self, name):
        def decorator(func):
            self.tools[name] = func
            return func
        return decorator


def test_execution_tools_registered():
    server = FakeServer()
    controller = MagicMock()
    register_execution_tools(server, controller, supervision_loop=None)
    assert "crew_run" in server.tools
    assert "crew_verify" in server.tools
    assert "crew_merge_plan" in server.tools


def test_crew_run_returns_result():
    from codex_claude_orchestrator.crew.loop_step_result import LoopStepResult

    server = FakeServer()
    controller = MagicMock()
    loop = MagicMock()
    loop.run_step.return_value = LoopStepResult(action="waiting", reason="still running")
    register_execution_tools(server, controller, supervision_loop=loop)
    import asyncio
    result = asyncio.run(server.tools["crew_run"](crew_id="c1", max_steps=1))
    data = json.loads(result[0].text)
    assert data["action"] == "max_steps_reached"
    loop.run_step.assert_called_once()


def test_crew_verify():
    server = FakeServer()
    controller = MagicMock()
    controller.verify.return_value = {"passed": True}
    register_execution_tools(server, controller, supervision_loop=None)
    import asyncio
    result = asyncio.run(server.tools["crew_verify"](crew_id="c1", worker_id="w1"))
    data = json.loads(result[0].text)
    assert data["passed"] is True


def test_crew_merge_plan():
    server = FakeServer()
    controller = MagicMock()
    controller.merge_plan.return_value = {"plan": "merge main into feature"}
    register_execution_tools(server, controller, supervision_loop=None)
    import asyncio
    result = asyncio.run(server.tools["crew_merge_plan"](crew_id="c1"))
    data = json.loads(result[0].text)
    assert data["plan"] == "merge main into feature"


def test_crew_run_no_loop():
    server = FakeServer()
    controller = MagicMock()
    register_execution_tools(server, controller, supervision_loop=None)
    import asyncio
    result = asyncio.run(server.tools["crew_run"](crew_id="c1", max_steps=1))
    data = json.loads(result[0].text)
    assert "error" in data
    assert "supervision_loop not initialized" in data["error"]


def test_crew_run_needs_decision_stops():
    from codex_claude_orchestrator.crew.loop_step_result import LoopStepResult

    server = FakeServer()
    controller = MagicMock()
    loop = MagicMock()
    loop.run_step.return_value = LoopStepResult(
        action="needs_decision",
        reason="spawn new worker",
        snapshot={"crew_id": "c1"},
    )
    register_execution_tools(server, controller, supervision_loop=loop)
    import asyncio
    result = asyncio.run(server.tools["crew_run"](crew_id="c1", max_steps=5))
    data = json.loads(result[0].text)
    assert data["action"] == "needs_decision"
    loop.run_step.assert_called_once()


def test_crew_run_ready_for_accept_stops():
    from codex_claude_orchestrator.crew.loop_step_result import LoopStepResult

    server = FakeServer()
    controller = MagicMock()
    loop = MagicMock()
    loop.run_step.return_value = LoopStepResult(
        action="ready_for_accept",
        reason="all checks passed",
    )
    register_execution_tools(server, controller, supervision_loop=loop)
    import asyncio
    result = asyncio.run(server.tools["crew_run"](crew_id="c1", max_steps=5))
    data = json.loads(result[0].text)
    assert data["action"] == "ready_for_accept"
    loop.run_step.assert_called_once()


def test_crew_run_challenged_continues():
    from codex_claude_orchestrator.crew.loop_step_result import LoopStepResult

    server = FakeServer()
    controller = MagicMock()
    loop = MagicMock()
    # First call: challenged, second call: ready_for_accept
    loop.run_step.side_effect = [
        LoopStepResult(action="challenged", reason="challenge sent"),
        LoopStepResult(action="ready_for_accept", reason="all good"),
    ]
    register_execution_tools(server, controller, supervision_loop=loop)
    import asyncio
    result = asyncio.run(server.tools["crew_run"](crew_id="c1", max_steps=5))
    data = json.loads(result[0].text)
    assert data["action"] == "ready_for_accept"
    assert loop.run_step.call_count == 2
