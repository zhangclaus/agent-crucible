"""Tests for crew_run (blocking), crew_job_status, and crew_cancel MCP tools."""

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
    controller = None
    job_manager = JobManager()
    runner = FakeRunner(delay=0.1)
    register_run_tools(server, controller, job_manager, runner=runner)
    return server, job_manager


# --- crew_run: blocking mode ---

def test_crew_run_blocks_and_returns_final_result(setup):
    """crew_run should block until job completes and return final result."""
    server, job_manager = setup
    crew_run = server.tools["crew_run"]

    result = asyncio.run(crew_run(repo="/tmp", goal="test goal"))
    data = json.loads(result[0].text)

    assert data["status"] == "done"
    assert data["result"]["status"] == "ready_for_codex_accept"
    assert "elapsed" in data
    assert "rounds" in data


def test_crew_run_returns_error_on_failure():
    """crew_run should return error when job fails."""
    server = FakeServer()
    jm = JobManager()

    class FailingRunner:
        def run(self, **kwargs):
            raise RuntimeError("boom")
        def supervise(self, **kwargs):
            raise RuntimeError("boom")

    register_run_tools(server, None, jm, runner=FailingRunner())

    result = asyncio.run(server.tools["crew_run"](repo="/tmp", goal="test"))
    data = json.loads(result[0].text)

    assert data["status"] == "failed"
    assert "boom" in data["error"]


def test_crew_run_parallel_completes():
    """crew_run with parallel=True should block and return final result."""
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
    data = json.loads(result[0].text)

    assert data["status"] == "done"
    assert data["result"]["status"] == "ready_for_codex_accept"


# --- crew_job_status (still available for direct use) ---

def test_crew_job_status_unchanged_when_no_change():
    """crew_job_status should return 'unchanged' when state hasn't changed."""
    jm = JobManager()
    runner = FakeRunner(delay=5.0)  # slow job
    server = FakeServer()
    register_run_tools(server, None, jm, runner=runner)

    # Start job directly via job_manager (non-blocking) to test polling
    job_id = jm.create_job(
        runner=runner,
        repo_root=Path("/tmp"),
        goal="test",
    )

    # First poll reports initial state
    time.sleep(0.05)
    crew_job_status = server.tools["crew_job_status"]
    status1 = asyncio.run(crew_job_status(job_id=job_id))
    data1 = json.loads(status1[0].text)
    assert data1["status"] == "running"

    # Second poll - unchanged
    time.sleep(0.05)
    status2 = asyncio.run(crew_job_status(job_id=job_id))
    data2 = json.loads(status2[0].text)
    assert data2["status"] == "unchanged"

    # Cleanup
    jm.cancel_job(job_id)


def test_crew_job_status_terminal_returns_full_result():
    """crew_job_status should return full result for terminal jobs."""
    jm = JobManager()
    runner = FakeRunner(delay=0.0)
    server = FakeServer()
    register_run_tools(server, None, jm, runner=runner)

    job_id = jm.create_job(runner=runner, repo_root=Path("/tmp"), goal="test")
    time.sleep(0.3)

    crew_job_status = server.tools["crew_job_status"]
    status = asyncio.run(crew_job_status(job_id=job_id))
    data = json.loads(status[0].text)

    assert data["status"] == "done"
    assert data["result"]["status"] == "ready_for_codex_accept"


def test_crew_job_status_nonexistent():
    """crew_job_status should return error for unknown job_id."""
    jm = JobManager()
    server = FakeServer()
    register_run_tools(server, None, jm)

    result = asyncio.run(server.tools["crew_job_status"](job_id="nonexistent"))
    data = json.loads(result[0].text)
    assert "error" in data


# --- crew_cancel ---

def test_crew_cancel():
    """crew_cancel should cancel a running job."""
    jm = JobManager()
    slow_runner = FakeRunner(delay=5)
    server = FakeServer()
    register_run_tools(server, None, jm, runner=slow_runner)

    job_id = jm.create_job(runner=slow_runner, repo_root=Path("/tmp"), goal="test")

    cancel_result = asyncio.run(server.tools["crew_cancel"](job_id=job_id))
    data = json.loads(cancel_result[0].text)
    assert data["status"] == "cancelling"

    time.sleep(0.1)
    status = asyncio.run(server.tools["crew_job_status"](job_id=job_id))
    status_data = json.loads(status[0].text)
    assert status_data["status"] == "cancelled"


def test_crew_cancel_nonexistent():
    """crew_cancel should return error for unknown job_id."""
    jm = JobManager()
    server = FakeServer()
    register_run_tools(server, None, jm)

    result = asyncio.run(server.tools["crew_cancel"](job_id="nonexistent"))
    data = json.loads(result[0].text)
    assert "error" in data


def test_crew_cancel_terminal_job_returns_warning():
    """Cancelling an already-done job returns a warning."""
    jm = JobManager()
    fast_runner = FakeRunner(delay=0.0)
    server = FakeServer()
    register_run_tools(server, None, jm, runner=fast_runner)

    job_id = jm.create_job(runner=fast_runner, repo_root=Path("/tmp"), goal="test")
    time.sleep(0.3)

    cancel_result = asyncio.run(server.tools["crew_cancel"](job_id=job_id))
    data = json.loads(cancel_result[0].text)
    assert data["status"] == "done"
    assert "warning" in data
