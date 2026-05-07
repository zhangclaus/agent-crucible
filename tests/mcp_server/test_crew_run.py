"""Tests for crew_run, crew_job_status, and crew_cancel MCP tools."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest

from codex_claude_orchestrator.mcp_server.job_manager import JobManager
from codex_claude_orchestrator.mcp_server.tools.crew_run import register_run_tools


class FakeServer:
    """Minimal fake FastMCP server that captures registered tool functions."""

    def __init__(self):
        self.tools = {}

    def tool(self, name: str):
        def decorator(func):
            self.tools[name] = func
            return func
        return decorator


class FakeRunner:
    def __init__(self, result=None, delay=0.0):
        self._result = result or {"status": "ready_for_codex_accept", "crew_id": "crew-1"}
        self._delay = delay

    def run(self, **kwargs):
        if self._delay:
            time.sleep(self._delay)
        return self._result

    def supervise(self, **kwargs):
        return self.run(**kwargs)

    async def async_supervise(self, **kwargs):
        if self._delay:
            time.sleep(self._delay)
        return self._result

    @property
    def adapter(self):
        return None


@pytest.fixture
def setup(tmp_path):
    server = FakeServer()
    controller = None  # Not needed for these tests
    job_manager = JobManager()
    runner = FakeRunner(delay=2.0)
    register_run_tools(server, controller, job_manager, runner=runner)
    return server, job_manager


def test_crew_run_returns_job_id(setup):
    server, job_manager = setup
    crew_run = server.tools["crew_run"]

    result = asyncio.run(crew_run(repo="/tmp", goal="test goal"))
    data = json.loads(result[0].text)

    assert "job_id" in data
    assert data["status"] == "running"
    assert data["poll_after_seconds"] == 5
    assert "crew_job_status" in data["poll_hint"]
    # Background agent prompt for async sub-agent pattern
    assert "background_agent_prompt" in data
    assert "crew_job_status" in data["background_agent_prompt"]
    assert "crew_accept" in data["background_agent_prompt"]
    assert "crew_id" in data["background_agent_prompt"]


def test_crew_job_status_unchanged_when_no_change(setup):
    server, job_manager = setup
    crew_run = server.tools["crew_run"]
    crew_job_status = server.tools["crew_job_status"]

    result = asyncio.run(crew_run(repo="/tmp", goal="test"))
    job_id = json.loads(result[0].text)["job_id"]

    # First poll reports the initial phase (idle != last_reported "")
    time.sleep(0.05)
    status1 = asyncio.run(crew_job_status(job_id=job_id))
    data1 = json.loads(status1[0].text)
    assert data1["status"] == "running"

    # Second poll - state hasn't changed, should be "unchanged"
    time.sleep(0.05)
    status2 = asyncio.run(crew_job_status(job_id=job_id))
    data2 = json.loads(status2[0].text)

    assert data2["job_id"] == job_id
    assert data2["status"] == "unchanged"
    assert "elapsed" in data2


def test_crew_job_status_terminal_returns_full_result(tmp_path):
    server = FakeServer()
    jm = JobManager()
    fast_runner = FakeRunner(delay=0.0)
    register_run_tools(server, None, jm, runner=fast_runner)

    result = asyncio.run(server.tools["crew_run"](repo="/tmp", goal="test"))
    job_id = json.loads(result[0].text)["job_id"]

    # Wait for job to complete
    time.sleep(0.3)
    status = asyncio.run(server.tools["crew_job_status"](job_id=job_id))
    data = json.loads(status[0].text)

    assert data["status"] == "done"
    assert data["result"]["status"] == "ready_for_codex_accept"
    assert "elapsed" in data
    assert "rounds" in data


def test_crew_job_status_error_returns_error(setup, tmp_path):
    server, _ = setup
    crew_run = server.tools["crew_run"]
    crew_job_status = server.tools["crew_job_status"]

    # Override runner to fail
    failing_runner = FakeRunner()
    failing_runner.run = lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom"))

    # Re-register with failing runner
    server2 = FakeServer()
    jm = JobManager()
    register_run_tools(server2, None, jm, runner=failing_runner)

    result = asyncio.run(server2.tools["crew_run"](repo="/tmp", goal="test"))
    job_id = json.loads(result[0].text)["job_id"]

    time.sleep(0.2)
    status = asyncio.run(server2.tools["crew_job_status"](job_id=job_id))
    data = json.loads(status[0].text)

    assert data["status"] == "failed"
    assert "boom" in data["error"]


def test_crew_cancel(setup):
    server, job_manager = setup
    crew_run = server.tools["crew_run"]
    crew_cancel = server.tools["crew_cancel"]
    crew_job_status = server.tools["crew_job_status"]

    # Use a slow runner
    slow_runner = FakeRunner(delay=5)
    server2 = FakeServer()
    jm = JobManager()
    register_run_tools(server2, None, jm, runner=slow_runner)

    result = asyncio.run(server2.tools["crew_run"](repo="/tmp", goal="test"))
    job_id = json.loads(result[0].text)["job_id"]

    cancel_result = asyncio.run(server2.tools["crew_cancel"](job_id=job_id))
    data = json.loads(cancel_result[0].text)

    assert data["job_id"] == job_id
    assert data["status"] == "cancelling"

    # Verify job is cancelled
    time.sleep(0.1)
    status = asyncio.run(server2.tools["crew_job_status"](job_id=job_id))
    status_data = json.loads(status[0].text)
    assert status_data["status"] == "cancelled"


def test_crew_job_status_nonexistent(setup):
    server, _ = setup
    crew_job_status = server.tools["crew_job_status"]

    result = asyncio.run(crew_job_status(job_id="nonexistent"))
    data = json.loads(result[0].text)
    assert "error" in data


def test_crew_cancel_nonexistent(setup):
    server, _ = setup
    crew_cancel = server.tools["crew_cancel"]

    result = asyncio.run(crew_cancel(job_id="nonexistent"))
    data = json.loads(result[0].text)
    assert "error" in data


def test_crew_cancel_terminal_job_returns_warning(tmp_path):
    """Cancelling an already-done job returns a warning, not 'cancelling'."""
    server = FakeServer()
    jm = JobManager()
    fast_runner = FakeRunner(delay=0.0)
    register_run_tools(server, None, jm, runner=fast_runner)

    result = asyncio.run(server.tools["crew_run"](repo="/tmp", goal="test"))
    job_id = json.loads(result[0].text)["job_id"]

    # Wait for job to complete
    time.sleep(0.3)

    cancel_result = asyncio.run(server.tools["crew_cancel"](job_id=job_id))
    data = json.loads(cancel_result[0].text)

    assert data["job_id"] == job_id
    assert data["status"] == "done"
    assert "warning" in data


def test_crew_run_parallel_returns_job_id():
    """crew_run with parallel=True should create a job with parallel mode."""
    server = FakeServer()
    jm = JobManager()
    runner = FakeRunner(delay=0.0)
    register_run_tools(server, None, jm, runner=runner)

    result = asyncio.run(server.tools["crew_run"](
        repo="/tmp",
        goal="implement auth",
        parallel=True,
        max_workers=3,
    ))
    data = json.loads(result[0].text)

    assert "job_id" in data
    assert data["status"] == "running"


def test_crew_run_parallel_false_uses_serial():
    """crew_run with parallel=False should use the serial path."""
    server = FakeServer()
    jm = JobManager()
    runner = FakeRunner(delay=0.0)
    register_run_tools(server, None, jm, runner=runner)

    result = asyncio.run(server.tools["crew_run"](
        repo="/tmp",
        goal="implement auth",
        parallel=False,
    ))
    data = json.loads(result[0].text)

    assert "job_id" in data
    assert data["status"] == "running"


def test_crew_run_parallel_completes():
    """crew_run with parallel=True should complete successfully."""
    server = FakeServer()
    jm = JobManager()
    runner = FakeRunner(delay=0.0)
    register_run_tools(server, None, jm, runner=runner)

    result = asyncio.run(server.tools["crew_run"](
        repo="/tmp",
        goal="implement feature",
        parallel=True,
        max_workers=2,
    ))
    job_id = json.loads(result[0].text)["job_id"]

    time.sleep(0.3)
    status = asyncio.run(server.tools["crew_job_status"](job_id=job_id))
    data = json.loads(status[0].text)

    assert data["status"] == "done"
    assert data["result"]["status"] == "ready_for_codex_accept"


def test_crew_job_status_shows_subtasks_in_parallel_mode():
    """crew_job_status should show subtask progress for parallel jobs."""
    server = FakeServer()
    jm = JobManager()
    runner = FakeRunner(delay=0.0)
    register_run_tools(server, None, jm, runner=runner)

    # Create a parallel job
    result = asyncio.run(server.tools["crew_run"](
        repo="/tmp",
        goal="implement auth",
        parallel=True,
        max_workers=2,
    ))
    job_id = json.loads(result[0].text)["job_id"]

    # Manually update subtasks
    jm.update_job_subtasks(job_id, [
        {"task_id": "st-1", "description": "Auth", "status": "passed"},
        {"task_id": "st-2", "description": "Users", "status": "running"},
    ])

    status = asyncio.run(server.tools["crew_job_status"](job_id=job_id))
    data = json.loads(status[0].text)

    assert "subtasks" in data
    assert len(data["subtasks"]) == 2
    assert data["subtasks"][0]["task_id"] == "st-1"
    assert data["subtasks"][0]["status"] == "passed"
    assert data["subtasks"][1]["task_id"] == "st-2"
    assert data["subtasks"][1]["status"] == "running"
