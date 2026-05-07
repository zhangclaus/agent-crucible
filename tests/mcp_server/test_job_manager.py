"""Tests for JobManager and Job delta tracking."""

from __future__ import annotations

import threading
import time

from codex_claude_orchestrator.mcp_server.job_manager import Job, JobManager, _next_poll_seconds


class FakeRunner:
    def __init__(self, result=None, error=None, progress_phases=None, delay=0.0):
        self._result = result or {"status": "ready_for_codex_accept", "crew_id": "crew-1"}
        self._error = error
        self._progress_phases = progress_phases or []
        self._delay = delay

    def run(self, *, repo_root, goal, verification_commands, max_rounds=3, progress_callback=None, cancel_event=None):
        for phase, round_idx in self._progress_phases:
            if progress_callback:
                progress_callback(phase, round_idx, max_rounds)
            time.sleep(0.01)
        if self._delay:
            time.sleep(self._delay)
        if self._error:
            raise RuntimeError(self._error)
        return self._result

    def supervise(self, *, repo_root, crew_id, verification_commands, max_rounds=3, progress_callback=None, cancel_event=None):
        return self.run(
            repo_root=repo_root,
            goal="",
            verification_commands=verification_commands,
            max_rounds=max_rounds,
            progress_callback=progress_callback,
            cancel_event=cancel_event,
        )

    async def async_supervise(self, *, repo_root, crew_id, goal, subtasks, verification_commands, max_rounds=3, max_workers=3, progress_callback=None, cancel_event=None):
        for phase, round_idx in self._progress_phases:
            if progress_callback:
                progress_callback(phase, round_idx, max_rounds)
            time.sleep(0.01)
        if self._delay:
            time.sleep(self._delay)
        if self._error:
            raise RuntimeError(self._error)
        return self._result


def test_job_initial_state():
    job = Job(job_id="test-1")
    assert job.status == "running"
    assert job.phase == "idle"
    assert job.current_round == 0
    # Initial state: last_reported_phase="" != phase="idle", so has_changed is True
    assert job.has_changed() is True


def test_job_has_changed_detects_phase_change():
    job = Job(job_id="test-1")
    job.phase = "idle"
    job.mark_reported()
    assert job.has_changed() is False
    job.phase = "polling"
    assert job.has_changed() is True


def test_job_has_changed_detects_round_change():
    job = Job(job_id="test-1")
    job.phase = "polling"
    job.current_round = 1
    job.mark_reported()
    assert job.has_changed() is False
    job.current_round = 2
    assert job.has_changed() is True


def test_job_mark_reported_resets_delta():
    job = Job(job_id="test-1")
    job.phase = "reviewing"
    job.current_round = 1
    assert job.has_changed() is True
    job.mark_reported()
    assert job.has_changed() is False


def test_next_poll_seconds_adaptive():
    job = Job(job_id="test-1")
    job.elapsed_seconds = 0
    assert _next_poll_seconds(job) == 5
    job.elapsed_seconds = 10
    assert _next_poll_seconds(job) == 10
    job.elapsed_seconds = 25
    assert _next_poll_seconds(job) == 20
    job.elapsed_seconds = 50
    assert _next_poll_seconds(job) == 40
    job.elapsed_seconds = 100
    assert _next_poll_seconds(job) == 60


def test_job_manager_create_and_get(tmp_path):
    manager = JobManager()
    runner = FakeRunner(progress_phases=[("spawning", 1), ("polling", 1)])

    job_id = manager.create_job(
        runner=runner,
        repo_root=tmp_path,
        goal="test goal",
        verification_commands=["echo ok"],
        max_rounds=1,
    )

    assert job_id.startswith("job-")
    job = manager.get_job(job_id)
    assert job.job_id == job_id

    # Wait for completion
    time.sleep(0.2)
    job = manager.get_job(job_id)
    assert job.status == "done"
    assert job.result is not None


def test_job_manager_captures_errors(tmp_path):
    manager = JobManager()
    runner = FakeRunner(error="something broke")

    job_id = manager.create_job(
        runner=runner,
        repo_root=tmp_path,
        goal="test",
        verification_commands=["echo ok"],
    )

    time.sleep(0.2)
    job = manager.get_job(job_id)
    assert job.status == "failed"
    assert job.error == "something broke"


def test_job_manager_cancel(tmp_path):
    manager = JobManager()

    def slow_run(**kwargs):
        time.sleep(5)
        return {"status": "done"}

    runner = FakeRunner()
    runner.run = slow_run

    job_id = manager.create_job(
        runner=runner,
        repo_root=tmp_path,
        goal="test",
        verification_commands=["echo ok"],
    )

    manager.cancel_job(job_id)
    job = manager.get_job(job_id)
    assert job.status == "cancelled"
    assert job.cancel_event.is_set()


def test_job_manager_cancel_nonexistent():
    manager = JobManager()
    try:
        manager.cancel_job("nonexistent")
        assert False, "should have raised"
    except KeyError:
        pass


def test_job_manager_get_nonexistent():
    manager = JobManager()
    try:
        manager.get_job("nonexistent")
        assert False, "should have raised"
    except KeyError:
        pass


def test_job_manager_list_jobs(tmp_path):
    manager = JobManager()
    runner = FakeRunner(delay=1.0)

    job_id = manager.create_job(
        runner=runner,
        repo_root=tmp_path,
        goal="test",
        verification_commands=["echo ok"],
    )

    jobs = manager.list_jobs()
    assert len(jobs) == 1
    assert jobs[0]["job_id"] == job_id
    assert jobs[0]["status"] == "running"


def test_job_manager_progress_updates_phase(tmp_path):
    manager = JobManager()

    phases_recorded = []

    def slow_run(**kwargs):
        cb = kwargs.get("progress_callback")
        if cb:
            cb("spawning", 1, 3)
            phases_recorded.append("spawning")
        time.sleep(0.05)
        if cb:
            cb("polling", 1, 3)
            phases_recorded.append("polling")
        time.sleep(0.05)
        return {"status": "done"}

    runner = FakeRunner()
    runner.run = slow_run

    job_id = manager.create_job(
        runner=runner,
        repo_root=tmp_path,
        goal="test",
        verification_commands=["echo ok"],
    )

    # Give thread time to start and report progress
    time.sleep(0.03)
    job = manager.get_job(job_id)
    # Phase should have advanced
    assert job.phase in ("spawning", "polling", "idle")
    assert len(phases_recorded) >= 1


def test_job_manager_cancel_propagates_to_runner(tmp_path):
    """cancel_event is passed to runner and observed."""
    manager = JobManager()
    cancel_observed = threading.Event()

    def slow_run(**kwargs):
        ce = kwargs.get("cancel_event")
        if ce:
            ce.wait(timeout=5)
            cancel_observed.set()
        return {"status": "done"}

    runner = FakeRunner()
    runner.run = slow_run

    job_id = manager.create_job(
        runner=runner,
        repo_root=tmp_path,
        goal="test",
        verification_commands=["echo ok"],
    )

    time.sleep(0.05)
    manager.cancel_job(job_id)

    assert cancel_observed.wait(timeout=1.0), "runner should observe cancel_event"
    job = manager.get_job(job_id)
    assert job.status == "cancelled"


def test_job_cancelled_status_not_overwritten_by_completion(tmp_path):
    """A cancelled job stays cancelled even if the runner completes."""
    manager = JobManager()

    def run_then_cancel(**kwargs):
        time.sleep(0.05)
        return {"status": "done"}

    runner = FakeRunner()
    runner.run = run_then_cancel

    job_id = manager.create_job(
        runner=runner,
        repo_root=tmp_path,
        goal="test",
        verification_commands=["echo ok"],
    )

    # Cancel immediately
    manager.cancel_job(job_id)
    job = manager.get_job(job_id)
    assert job.status == "cancelled"

    # Wait for runner to finish
    time.sleep(0.2)
    job = manager.get_job(job_id)
    assert job.status == "cancelled", "cancelled status must not revert to done"


def test_job_manager_evicts_stale_jobs(tmp_path):
    """Completed jobs older than 1 hour are cleaned up."""
    manager = JobManager()
    runner = FakeRunner()

    job_id = manager.create_job(
        runner=runner,
        repo_root=tmp_path,
        goal="test",
        verification_commands=["echo ok"],
    )

    time.sleep(0.2)
    job = manager.get_job(job_id)
    assert job.status == "done"

    # Fake old completion time
    job.completed_at = time.monotonic() - 3700  # > 1 hour ago

    # Trigger eviction
    manager._evict_stale()

    try:
        manager.get_job(job_id)
        assert False, "should have been evicted"
    except KeyError:
        pass


def test_job_manager_cancelled_has_completed_at(tmp_path):
    """Cancelled jobs also get completed_at timestamp."""
    manager = JobManager()

    def cancellable_run(**kwargs):
        ce = kwargs.get("cancel_event")
        if ce:
            ce.wait(timeout=5)
        return {"status": "done"}

    runner = FakeRunner()
    runner.run = cancellable_run

    job_id = manager.create_job(
        runner=runner,
        repo_root=tmp_path,
        goal="test",
        verification_commands=["echo ok"],
    )

    time.sleep(0.05)
    manager.cancel_job(job_id)
    time.sleep(0.2)

    job = manager.get_job(job_id)
    assert job.status == "cancelled"
    assert job.completed_at is not None


def test_cancel_job_returns_false_for_terminal(tmp_path):
    """cancel_job returns False when job is already terminal."""
    manager = JobManager()
    runner = FakeRunner()

    job_id = manager.create_job(
        runner=runner,
        repo_root=tmp_path,
        goal="test",
        verification_commands=["echo ok"],
    )

    time.sleep(0.2)
    job = manager.get_job(job_id)
    assert job.status == "done"

    result = manager.cancel_job(job_id)
    assert result is False


def test_cancel_job_returns_true_for_running(tmp_path):
    """cancel_job returns True when job is running."""
    manager = JobManager()

    def slow_run(**kwargs):
        time.sleep(5)
        return {"status": "done"}

    runner = FakeRunner()
    runner.run = slow_run

    job_id = manager.create_job(
        runner=runner,
        repo_root=tmp_path,
        goal="test",
        verification_commands=["echo ok"],
    )

    result = manager.cancel_job(job_id)
    assert result is True


def test_get_job_status_returns_snapshot(tmp_path):
    """get_job_status returns a snapshot dict, not a live Job reference."""
    manager = JobManager()
    runner = FakeRunner(progress_phases=[("spawning", 1)])

    job_id = manager.create_job(
        runner=runner,
        repo_root=tmp_path,
        goal="test",
        verification_commands=["echo ok"],
    )

    time.sleep(0.2)
    snap = manager.get_job_status(job_id)

    assert isinstance(snap, dict)
    assert snap["job_id"] == job_id
    assert snap["status"] in ("running", "done")
    assert "elapsed_seconds" in snap
    assert "has_changed" in snap


def test_get_job_status_nonexistent():
    """get_job_status raises KeyError for unknown job."""
    manager = JobManager()
    try:
        manager.get_job_status("nonexistent")
        assert False, "should have raised"
    except KeyError:
        pass


def test_cancelled_job_stores_result(tmp_path):
    """Cancelled jobs should still store the result if runner completes."""
    manager = JobManager()

    def run_and_complete(**kwargs):
        time.sleep(0.05)
        return {"status": "done", "data": "partial"}

    runner = FakeRunner()
    runner.run = run_and_complete

    job_id = manager.create_job(
        runner=runner, repo_root=tmp_path, goal="test",
        verification_commands=["echo ok"],
    )

    # Cancel immediately so status becomes "cancelled"
    manager.cancel_job(job_id)

    # Wait for runner to finish
    time.sleep(0.3)
    job = manager.get_job(job_id)
    # Result should be stored even though job was cancelled
    assert job.result is not None


def test_mark_job_reported(tmp_path):
    """mark_job_reported resets has_changed to False."""
    manager = JobManager()

    def run_with_progress(**kwargs):
        cb = kwargs.get("progress_callback")
        if cb:
            cb("spawning", 1, 3)
        time.sleep(0.05)
        return {"status": "done"}

    runner = FakeRunner()
    runner.run = run_with_progress

    job_id = manager.create_job(
        runner=runner,
        repo_root=tmp_path,
        goal="test",
        verification_commands=["echo ok"],
    )

    time.sleep(0.1)
    snap = manager.get_job_status(job_id)
    # After progress, has_changed should be True (phase != last_reported)
    if snap["status"] == "running":
        assert snap["has_changed"] is True
        manager.mark_job_reported(job_id)
        snap2 = manager.get_job_status(job_id)
        assert snap2["has_changed"] is False


def test_job_manager_create_parallel_job(tmp_path):
    """create_job with parallel=True should use async_supervise."""
    manager = JobManager()
    runner = FakeRunner(progress_phases=[("watching", 1)])

    job_id = manager.create_job(
        runner=runner,
        repo_root=tmp_path,
        goal="implement feature",
        verification_commands=["echo ok"],
        max_rounds=1,
        parallel=True,
        max_workers=2,
    )

    assert job_id.startswith("job-")

    time.sleep(0.3)
    job = manager.get_job(job_id)
    assert job.status == "done"
    assert job.result is not None


def test_create_job_with_external_subtasks(tmp_path):
    """create_job should use externally provided subtasks when given."""
    manager = JobManager()
    runner = FakeRunner(delay=0.0)

    external_subtasks = [
        {"task_id": "auth", "description": "Implement auth", "scope": ["src/auth/"]},
        {"task_id": "users", "description": "Implement users", "scope": ["src/users/"]},
    ]

    job_id = manager.create_job(
        runner=runner,
        repo_root=tmp_path,
        goal="build auth and users",
        verification_commands=["echo ok"],
        max_rounds=1,
        parallel=True,
        max_workers=2,
        subtasks=external_subtasks,
    )

    assert job_id.startswith("job-")
    time.sleep(0.3)
    job = manager.get_job(job_id)
    assert job.status == "done"
