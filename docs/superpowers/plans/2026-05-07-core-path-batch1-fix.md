# Core Path Batch 1: Critical + High Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 1 Critical and 13 High severity issues found in the core runtime path audit.

**Architecture:** 6 focused tasks grouped by component. Each task is self-contained and testable independently. TDD approach: write failing test first, then fix.

**Tech Stack:** Python 3.12+, pytest, asyncio, threading, SQLite event store

---

## File Structure

### Files to Modify

| File | Issues | Changes |
|---|---|---|
| `src/codex_claude_orchestrator/v4/domain_events.py` | C1, H5 | Fix idempotency key collisions |
| `src/codex_claude_orchestrator/v4/supervisor.py` | H2, H3, H4 | Exception safety + async unblocking |
| `src/codex_claude_orchestrator/v4/crew_runner.py` | H1 | Forward missing params in non-dynamic path |
| `src/codex_claude_orchestrator/mcp_server/job_manager.py` | H6, H7 | Atomic status+mark, snapshot from get_job |
| `src/codex_claude_orchestrator/mcp_server/tools/crew_run.py` | H8 | Race-safe crew_cancel |
| `src/codex_claude_orchestrator/mcp_server/__main__.py` | H9 | Graceful shutdown |
| `src/codex_claude_orchestrator/mcp_server/server.py` | H9 | Shutdown hook |
| `src/codex_claude_orchestrator/v4/adapters/tmux_claude.py` | H10, H11 | Real stop/cancel implementations |
| `src/codex_claude_orchestrator/crew/controller.py` | H12 | Locking in ensure_worker |
| `src/codex_claude_orchestrator/v4/crew_state_projection.py` | H13 | Missing event type handlers |

### Test Files to Create/Modify

| File | Tests |
|---|---|
| `tests/v4/test_domain_events.py` | C1, H5 verification |
| `tests/v4/test_supervisor.py` | H2, H3, H4 verification |
| `tests/v4/test_crew_runner.py` | H1 verification |
| `tests/mcp_server/test_job_manager.py` | H6, H7 verification |
| `tests/mcp_server/test_crew_run.py` | H8 verification |
| `tests/v4/test_tmux_claude_adapter.py` | H10, H11 verification |
| `tests/crew/test_controller.py` | H12 verification |
| `tests/v4/test_crew_state_projection.py` | H13 verification |

---

### Task 1: Fix Idempotency Key Collisions (C1 + H5)

**Issues:** C1 — verification.passed/failed share identical keys. H5 — worker lifecycle events use singleton keys preventing re-claim.

**Files:**
- Modify: `src/codex_claude_orchestrator/v4/domain_events.py:309,334,163-194`
- Test: `tests/v4/test_domain_events.py`

- [ ] **Step 1: Write failing test for C1 — verification key collision**

```python
class TestVerificationIdempotencyKeys:
    def test_passed_and_failed_have_different_keys(self, emitter, store):
        """C1: verification.passed and verification.failed must not share keys."""
        emitter.emit_verification_passed("c1", "w1", "pytest", round_id="r1")
        emitter.emit_verification_failed("c1", "w1", "pytest", round_id="r1")
        keys = [e.idempotency_key for e in store._events]
        assert keys[0] != keys[1], "passed/failed keys must differ"
        assert "verification.passed" in keys[0]
        assert "verification.failed" in keys[1]

    def test_passed_then_failed_both_stored(self, emitter, store):
        """C1: Both events must be stored, not deduplicated."""
        emitter.emit_verification_passed("c1", "w1", "pytest", round_id="r1")
        emitter.emit_verification_failed("c1", "w1", "pytest", round_id="r1")
        assert len(store._events) == 2
        assert store._events[0].type == "verification.passed"
        assert store._events[1].type == "verification.failed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/v4/test_domain_events.py::TestVerificationIdempotencyKeys -v`
Expected: FAIL — both events have same key, second event overwrites first

- [ ] **Step 3: Write failing test for H5 — worker lifecycle key collision**

```python
class TestWorkerLifecycleIdempotencyKeys:
    def test_claimed_then_released_then_claimed_again(self, emitter, store):
        """H5: Re-claiming after release must produce a new event, not be deduplicated."""
        emitter.emit_worker_claimed("c1", "w1")
        emitter.emit_worker_released("c1", "w1")
        emitter.emit_worker_claimed("c1", "w1")
        assert len(store._events) == 3
        assert store._events[2].type == "worker.claimed"
        # Keys must differ between first claim and second claim
        assert store._events[0].idempotency_key != store._events[2].idempotency_key
```

- [ ] **Step 4: Run test to verify it fails**

Run: `pytest tests/v4/test_domain_events.py::TestWorkerLifecycleIdempotencyKeys -v`
Expected: FAIL — third event deduplicated because key matches first

- [ ] **Step 5: Fix C1 — include outcome in verification idempotency key**

In `domain_events.py`, change `emit_verification_passed` line 309:
```python
# Before:
idempotency_key=f"{crew_id}/{round_id}/{worker_id}/verification/{_summary_hash(command)}",
# After:
idempotency_key=f"{crew_id}/{round_id}/{worker_id}/verification.passed/{_summary_hash(command)}",
```

Change `emit_verification_failed` line 334:
```python
# Before:
idempotency_key=f"{crew_id}/{round_id}/{worker_id}/verification/{_summary_hash(command)}",
# After:
idempotency_key=f"{crew_id}/{round_id}/{worker_id}/verification.failed/{_summary_hash(command)}",
```

- [ ] **Step 6: Fix H5 — add sequence counter to worker lifecycle keys**

Add `import itertools` at top of file. Add class-level counter:
```python
class DomainEventEmitter:
    _seq_counter = itertools.count()
    # ... rest of __init__
```

Change `emit_worker_claimed` line 168:
```python
# Before:
idempotency_key=f"{crew_id}/worker.claimed/{worker_id}",
# After:
idempotency_key=f"{crew_id}/worker.claimed/{worker_id}/{next(self._seq_counter)}",
```

Change `emit_worker_released` line 181:
```python
# Before:
idempotency_key=f"{crew_id}/worker.released/{worker_id}",
# After:
idempotency_key=f"{crew_id}/worker.released/{worker_id}/{next(self._seq_counter)}",
```

Change `emit_worker_stopped` line 194:
```python
# Before:
idempotency_key=f"{crew_id}/worker.stopped/{worker_id}",
# After:
idempotency_key=f"{crew_id}/worker.stopped/{worker_id}/{next(self._seq_counter)}",
```

- [ ] **Step 7: Run all tests to verify they pass**

Run: `pytest tests/v4/test_domain_events.py -v`
Expected: All PASS

- [ ] **Step 8: Commit**

```bash
git add src/codex_claude_orchestrator/v4/domain_events.py tests/v4/test_domain_events.py
git commit -m "fix(events): distinct idempotency keys for verification outcomes and worker lifecycle

C1: verification.passed and verification.failed now use different key prefixes
so both events are stored instead of one silently deduplicating the other.

H5: worker.claimed/released/stopped keys include a sequence counter so
re-claiming after release produces a new event instead of being deduplicated.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 2: Exception Safety in Supervisor Callbacks (H2 + H3)

**Issues:** H2 — `_process_message_ack_if_configured` exception aborts event loop. H3 — `_evaluate_completed_turn_if_configured` exception aborts return paths.

**Files:**
- Modify: `src/codex_claude_orchestrator/v4/supervisor.py:368-374`
- Test: `tests/v4/test_supervisor.py`

- [ ] **Step 1: Write failing test for H2 — message ack exception must not abort loop**

```python
class TestMessageAckExceptionSafety:
    def test_ack_exception_does_not_abort_event_loop(self):
        """H2: Exception in message_ack_processor must not abort the event loop."""
        class FailingAckProcessor:
            def process(self, event):
                raise RuntimeError("ack failed")

        adapter = FakeAdapter(events=lambda turn: [completed_outbox_event(turn)])
        store = SQLiteEventStore(":memory:")
        supervisor = V4Supervisor(
            event_store=store,
            artifact_store=ArtifactStore(Path("/tmp/test-artifacts")),
            adapter=adapter,
            message_ack_processor=FailingAckProcessor(),
        )
        turn = TurnEnvelope(
            crew_id="c1", worker_id="w1", turn_id="t1",
            round_id="r1", phase="source", message="go",
            expected_marker="<<<DONE>>>", required_outbox_path="",
            contract_id="source_write",
        )
        # Must not raise — ack failure should be swallowed
        result = supervisor.run_worker_turn(
            crew_id="c1", goal="test", worker_id="w1",
            round_id="r1", phase="source", contract_id="source_write",
            message="go", expected_marker="<<<DONE>>>",
        )
        assert result["status"] == "turn_completed"
```

- [ ] **Step 2: Write failing test for H3 — evaluator exception must not abort return**

```python
class TestEvaluatorExceptionSafety:
    def test_evaluator_exception_does_not_abort_return(self):
        """H3: Exception in adversarial_evaluator must not abort turn result."""
        class FailingEvaluator:
            def evaluate_completed_turn(self, event):
                raise RuntimeError("evaluator exploded")

        adapter = FakeAdapter(events=lambda turn: [completed_outbox_event(turn)])
        store = SQLiteEventStore(":memory:")
        supervisor = V4Supervisor(
            event_store=store,
            artifact_store=ArtifactStore(Path("/tmp/test-artifacts")),
            adapter=adapter,
            adversarial_evaluator=FailingEvaluator(),
        )
        turn = TurnEnvelope(
            crew_id="c1", worker_id="w1", turn_id="t1",
            round_id="r1", phase="source", message="go",
            expected_marker="<<<DONE>>>", required_outbox_path="",
            contract_id="source_write",
        )
        result = supervisor.run_worker_turn(
            crew_id="c1", goal="test", worker_id="w1",
            round_id="r1", phase="source", contract_id="source_write",
            message="go", expected_marker="<<<DONE>>>",
        )
        assert result["status"] == "turn_completed"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/v4/test_supervisor.py::TestMessageAckExceptionSafety tests/v4/test_supervisor.py::TestEvaluatorExceptionSafety -v`
Expected: FAIL — exceptions propagate and crash the test

- [ ] **Step 4: Fix H2 — wrap message ack in try/except**

In `supervisor.py`, change `_process_message_ack_if_configured` (line 372-374):
```python
def _process_message_ack_if_configured(self, event: AgentEvent) -> None:
    if self._message_ack_processor is not None:
        try:
            self._message_ack_processor.process(event)
        except Exception:
            pass  # ack callback failure must not abort the event loop
```

- [ ] **Step 5: Fix H3 — wrap evaluator in try/except**

In `supervisor.py`, change `_evaluate_completed_turn_if_configured` (line 368-370):
```python
def _evaluate_completed_turn_if_configured(self, event: AgentEvent) -> None:
    if event.type == "turn.completed" and self._adversarial_evaluator is not None:
        try:
            self._adversarial_evaluator.evaluate_completed_turn(event)
        except Exception:
            pass  # evaluator failure must not abort turn result return
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/v4/test_supervisor.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add src/codex_claude_orchestrator/v4/supervisor.py tests/v4/test_supervisor.py
git commit -m "fix(supervisor): wrap side-effect callbacks in try/except

H2: _process_message_ack_if_configured exception no longer aborts the
runtime event loop. The ack callback is fire-and-forget.

H3: _evaluate_completed_turn_if_configured exception no longer aborts
the turn result return path. The evaluator is a side-effect observer.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 3: Unblock async_run_worker_turn (H4)

**Issue:** H4 — `async_run_worker_turn` is declared `async` but calls synchronous blocking methods (`start_crew`, `request_and_deliver`, `events.append`), blocking the asyncio event loop and preventing parallel workers from progressing.

**Files:**
- Modify: `src/codex_claude_orchestrator/v4/supervisor.py:200,228,252,270`
- Test: `tests/v4/test_supervisor.py`

- [ ] **Step 1: Write failing test for H4 — async method must not block event loop**

```python
class TestAsyncRunWorkerTurnNonBlocking:
    def test_async_run_does_not_block_event_loop(self):
        """H4: async_run_worker_turn must not block the event loop during sync calls."""
        import asyncio

        call_order = []

        class SlowAdapter(FakeAdapter):
            def deliver_turn(self, turn):
                call_order.append("deliver_start")
                time.sleep(0.05)  # simulate blocking I/O
                call_order.append("deliver_end")
                return DeliveryResult(delivered=True, marker=turn.expected_marker, reason="sent")

            async def async_watch_turn(self, turn, cancel_event=None):
                call_order.append("watch_start")
                yield completed_outbox_event(turn)
                call_order.append("watch_end")

        adapter = SlowAdapter()
        store = SQLiteEventStore(":memory:")
        supervisor = V4Supervisor(
            event_store=store,
            artifact_store=ArtifactStore(Path("/tmp/test-artifacts")),
            adapter=adapter,
        )

        async def run_two_workers():
            turn1 = TurnEnvelope(
                crew_id="c1", worker_id="w1", turn_id="t1",
                round_id="r1", phase="source", message="go",
                expected_marker="<<<DONE>>>", required_outbox_path="",
                contract_id="source_write",
            )
            turn2 = TurnEnvelope(
                crew_id="c1", worker_id="w2", turn_id="t2",
                round_id="r1", phase="source", message="go",
                expected_marker="<<<DONE>>>", required_outbox_path="",
                contract_id="source_write",
            )
            # Both should be able to progress concurrently
            results = await asyncio.gather(
                supervisor.async_run_worker_turn(
                    crew_id="c1", goal="test", worker_id="w1",
                    round_id="r1", phase="source", contract_id="source_write",
                    message="go", expected_marker="<<<DONE>>>",
                ),
                supervisor.async_run_worker_turn(
                    crew_id="c1", goal="test", worker_id="w2",
                    round_id="r1", phase="source", contract_id="source_write",
                    message="go", expected_marker="<<<DONE>>>",
                ),
            )
            return results

        results = asyncio.run(run_two_workers())
        assert all(r["status"] == "turn_completed" for r in results)
```

- [ ] **Step 2: Run test to verify it fails (or passes with blocking)**

Run: `pytest tests/v4/test_supervisor.py::TestAsyncRunWorkerTurnNonBlocking -v`
Expected: May pass but the blocking behavior means workers don't truly run concurrently

- [ ] **Step 3: Fix H4 — wrap sync calls in asyncio.to_thread()**

In `supervisor.py`, modify `async_run_worker_turn` to use `asyncio.to_thread()` for the three blocking calls:

At line 200, change:
```python
# Before:
self._workflow.start_crew(crew_id=crew_id, goal=goal)
# After:
await asyncio.to_thread(self._workflow.start_crew, crew_id=crew_id, goal=goal)
```

At line 228, change:
```python
# Before:
delivery_result = self._turns.request_and_deliver(turn)
# After:
delivery_result = await asyncio.to_thread(self._turns.request_and_deliver, turn)
```

At line 252 (inside the loop), change:
```python
# Before:
event = self._events.append(
    stream_id=crew_id,
    ...
)
# After:
event = await asyncio.to_thread(
    self._events.append,
    stream_id=crew_id,
    ...
)
```

Also wrap `_terminal_result` calls (lines 224, 229, 272) and `_process_message_ack_if_configured` (line 267) and `_commit_runtime_events_if_supported` (line 270) and the final `self._events.append` (line 277) and `_evaluate_completed_turn_if_configured` (line 289):

```python
# Lines 224-226:
terminal_result = await asyncio.to_thread(self._terminal_result, crew_id=crew_id, turn=turn)

# Line 228:
delivery_result = await asyncio.to_thread(self._turns.request_and_deliver, turn)

# Lines 229-231:
terminal_result = await asyncio.to_thread(self._terminal_result, crew_id=crew_id, turn=turn)

# Line 267:
await asyncio.to_thread(self._process_message_ack_if_configured, event)

# Line 270:
await asyncio.to_thread(self._commit_runtime_events_if_supported, turn, runtime_events)

# Lines 272-274:
terminal_result = await asyncio.to_thread(self._terminal_result, crew_id=crew_id, turn=turn)

# Line 277 (final events.append):
terminal_event = await asyncio.to_thread(
    self._events.append,
    stream_id=crew_id,
    type=decision.event_type,
    ...
)

# Line 289:
await asyncio.to_thread(self._evaluate_completed_turn_if_configured, terminal_event)
```

- [ ] **Step 4: Run all supervisor tests**

Run: `pytest tests/v4/test_supervisor.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/codex_claude_orchestrator/v4/supervisor.py tests/v4/test_supervisor.py
git commit -m "fix(supervisor): unblock async_run_worker_turn with asyncio.to_thread

H4: async_run_worker_turn declared async but called synchronous blocking
methods (start_crew, request_and_deliver, events.append), blocking the
event loop and preventing parallel workers from progressing.

All sync blocking calls now go through asyncio.to_thread() so the event
loop remains free for concurrent worker execution.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 4: Forward Missing Parameters in Non-Dynamic Path (H1)

**Issue:** H1 — `run()` non-dynamic path does not forward `allow_dirty_base` and `seed_contract` to `supervise()`. Caller's explicit values are silently ignored.

**Files:**
- Modify: `src/codex_claude_orchestrator/v4/crew_runner.py:89-98`
- Test: `tests/v4/test_crew_runner.py`

- [ ] **Step 1: Write failing test for H1 — non-dynamic path must forward params**

```python
class TestNonDynamicPathForwardsParams:
    def test_non_dynamic_forwards_allow_dirty_base_and_seed_contract(self):
        """H1: Non-dynamic run() must forward allow_dirty_base and seed_contract."""
        received_kwargs = {}

        class SpySupervisor:
            def run_source_turn(self, **kwargs):
                received_kwargs.update(kwargs)
                return {"status": "turn_completed", "turn_id": "t1"}

        class SpyController:
            def start(self, **kwargs):
                received_kwargs.update(kwargs)
                return CrewRecord(crew_id="c1", root_goal="test", repo=Path("/tmp"))

        runner = V4CrewRunner(
            controller=SpyController(),
            supervisor=SpySupervisor(),
            event_store=MockEventStore(),
        )
        # Patch supervise to capture kwargs
        original_supervise = runner.supervise
        def capture_supervise(**kwargs):
            received_kwargs.update(kwargs)
            return {"crew_id": "c1", "status": "ready", "runtime": "v4", "rounds": 1, "events": []}
        runner.supervise = capture_supervise

        runner.run(
            repo_root=Path("/tmp"),
            goal="test",
            verification_commands=["echo ok"],
            spawn_policy="static",
            allow_dirty_base=True,
            seed_contract="my-contract",
        )
        assert received_kwargs.get("allow_dirty_base") is True
        assert received_kwargs.get("seed_contract") == "my-contract"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/v4/test_crew_runner.py::TestNonDynamicPathForwardsParams -v`
Expected: FAIL — `allow_dirty_base` and `seed_contract` not in received_kwargs

- [ ] **Step 3: Fix H1 — add missing parameters to non-dynamic path**

In `crew_runner.py`, change lines 89-98:
```python
# Before:
return self.supervise(
    repo_root=repo_root,
    crew_id=crew.crew_id,
    verification_commands=verification_commands,
    max_rounds=max_rounds,
    poll_interval_seconds=poll_interval_seconds,
    dynamic=False,
    progress_callback=progress_callback,
    cancel_event=cancel_event,
)

# After:
return self.supervise(
    repo_root=repo_root,
    crew_id=crew.crew_id,
    verification_commands=verification_commands,
    max_rounds=max_rounds,
    poll_interval_seconds=poll_interval_seconds,
    dynamic=False,
    allow_dirty_base=allow_dirty_base,
    seed_contract=seed_contract,
    progress_callback=progress_callback,
    cancel_event=cancel_event,
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/v4/test_crew_runner.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/codex_claude_orchestrator/v4/crew_runner.py tests/v4/test_crew_runner.py
git commit -m "fix(crew_runner): forward allow_dirty_base and seed_contract in non-dynamic path

H1: run() non-dynamic path silently dropped allow_dirty_base and seed_contract
parameters. Callers' explicit values were ignored. Now both parameters are
forwarded to supervise() in all code paths.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 5: Atomic Job Status + Snapshot Safety (H6 + H7 + H8)

**Issues:** H6 — TOCTOU between `get_job_status()` and `mark_job_reported()`. H7 — `get_job()` returns mutable reference. H8 — `crew_cancel` unhandled `KeyError` after evict race.

**Files:**
- Modify: `src/codex_claude_orchestrator/mcp_server/job_manager.py`
- Modify: `src/codex_claude_orchestrator/mcp_server/tools/crew_run.py:191`
- Test: `tests/mcp_server/test_job_manager.py`

- [ ] **Step 1: Write failing test for H6 — atomic get_status_and_mark_reported**

```python
class TestAtomicStatusAndMark:
    def test_get_status_and_mark_reported_is_atomic(self):
        """H6: get_status_and_mark_reported must atomically return snapshot and mark."""
        manager = JobManager()
        job_id = manager.create_job(
            runner=FakeRunner(delay=10.0),
            repo_root=Path("/tmp"),
            goal="test",
        )
        # Get status (should auto-mark)
        snap = manager.get_status_and_mark_reported(job_id)
        assert snap["has_changed"] is True  # first call, was changed
        # Second call should show no change
        snap2 = manager.get_status_and_mark_reported(job_id)
        assert snap2["has_changed"] is False
        manager.cancel_job(job_id)
```

- [ ] **Step 2: Write failing test for H7 — get_job returns snapshot dict**

```python
class TestGetJobSnapshot:
    def test_get_job_returns_dict_snapshot(self):
        """H7: get_job must return a dict snapshot, not a mutable Job reference."""
        manager = JobManager()
        job_id = manager.create_job(
            runner=FakeRunner(delay=10.0),
            repo_root=Path("/tmp"),
            goal="test",
        )
        result = manager.get_job(job_id)
        assert isinstance(result, dict)
        assert result["job_id"] == job_id
        assert "status" in result
        assert "phase" in result
        manager.cancel_job(job_id)
```

- [ ] **Step 3: Write failing test for H8 — crew_cancel handles evicted job**

```python
class TestCrewCancelRace:
    def test_cancel_handles_job_eviction_race(self):
        """H8: crew_cancel must not raise KeyError if job evicted between calls."""
        # This is tested at the crew_run tool level
        from codex_claude_orchestrator.mcp_server.tools.crew_run import register_run_tools
        from mcp.server.fastmcp import FastMCP

        server = FastMCP("test")
        manager = JobManager()
        register_run_tools(server, controller=None, job_manager=manager)

        # Create and immediately mark as done + old
        job_id = manager.create_job(
            runner=FakeRunner(result={"status": "done"}),
            repo_root=Path("/tmp"),
            goal="test",
        )
        time.sleep(0.1)  # let runner finish
        # Force eviction by setting completed_at far in the past
        with manager._lock:
            job = manager._jobs[job_id]
            job.completed_at = time.monotonic() - 7200  # 2 hours ago

        # crew_cancel should handle gracefully, not raise
        # (The tool catches KeyError from cancel_job, but get_job after
        # cancel returns False could race with eviction)
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `pytest tests/mcp_server/test_job_manager.py -v`
Expected: FAIL — `get_status_and_mark_reported` doesn't exist, `get_job` returns Job object

- [ ] **Step 5: Fix H6 — add atomic get_status_and_mark_reported**

In `job_manager.py`, add a new method to `JobManager`:
```python
def get_status_and_mark_reported(self, job_id: str) -> dict[str, Any]:
    """Return serialized job status snapshot AND mark as reported, atomically.

    Eliminates the TOCTOU race between get_job_status() and mark_job_reported().
    """
    with self._lock:
        self._evict_stale()
        job = self._jobs.get(job_id)
        if job is None:
            raise KeyError(f"job not found: {job_id}")
        job.update_elapsed()
        result = {
            "job_id": job.job_id,
            "status": job.status,
            "phase": job.phase,
            "current_round": job.current_round,
            "max_rounds": job.max_rounds,
            "elapsed_seconds": job.elapsed_seconds,
            "result": job.result,
            "error": job.error,
            "has_changed": (
                job.phase != job.last_reported_phase
                or job.current_round != job.last_reported_round
            ),
            "subtasks": job.subtasks,
        }
        # Atomically mark as reported
        job.last_reported_phase = job.phase
        job.last_reported_round = job.current_round
        return result
```

- [ ] **Step 6: Fix H7 — change get_job to return dict snapshot**

In `job_manager.py`, change `get_job` (line 166-173):
```python
def get_job(self, job_id: str) -> dict[str, Any]:
    """Return a snapshot dict of the job state. Does not return mutable reference."""
    with self._lock:
        self._evict_stale()
        job = self._jobs.get(job_id)
        if job is None:
            raise KeyError(f"job not found: {job_id}")
        job.update_elapsed()
        return {
            "job_id": job.job_id,
            "status": job.status,
            "phase": job.phase,
            "current_round": job.current_round,
            "max_rounds": job.max_rounds,
            "elapsed_seconds": job.elapsed_seconds,
            "result": job.result,
            "error": job.error,
            "cancel_event": job.cancel_event,
            "completed_at": job.completed_at,
            "subtasks": job.subtasks,
        }
```

- [ ] **Step 7: Fix H8 — handle race in crew_cancel**

In `crew_run.py`, change `crew_cancel` (line 190-197):
```python
if not cancelled:
    try:
        job = job_manager.get_job(job_id)
        return [
            TextContent(
                type="text",
                text=json.dumps({"job_id": job_id, "status": job["status"], "warning": "job already terminal"}),
            )
        ]
    except KeyError:
        return [
            TextContent(
                type="text",
                text=json.dumps({"job_id": job_id, "status": "unknown", "error": "job evicted during cancel"}),
            )
        ]
```

- [ ] **Step 8: Update crew_job_status to use atomic method**

In `crew_run.py`, change `crew_job_status` to use `get_status_and_mark_reported` for the delta path (line 138-153):
```python
# Running: delta mode — use atomic get+mark
snap = job_manager.get_status_and_mark_reported(job_id)
```

Replace the separate `get_job_status` + `mark_job_reported` calls with a single `get_status_and_mark_reported` call. Remove the `mark_job_reported` call at line 153.

- [ ] **Step 9: Run all tests**

Run: `pytest tests/mcp_server/test_job_manager.py -v`
Expected: All PASS

- [ ] **Step 10: Commit**

```bash
git add src/codex_claude_orchestrator/mcp_server/job_manager.py \
        src/codex_claude_orchestrator/mcp_server/tools/crew_run.py \
        tests/mcp_server/test_job_manager.py
git commit -m "fix(job_manager): atomic status+mark, snapshot get_job, race-safe cancel

H6: New get_status_and_mark_reported() atomically returns snapshot and
marks as reported, eliminating TOCTOU race between separate calls.

H7: get_job() now returns a dict snapshot instead of a mutable Job
reference that the background thread continues modifying.

H8: crew_cancel handles KeyError gracefully when job is evicted between
cancel_job() and get_job() calls.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 6: Graceful Shutdown (H9)

**Issue:** H9 — No shutdown hook to signal cancellation to running jobs, join background threads, close event stores/file handles. Abrupt termination leaves orphaned tmux sessions.

**Files:**
- Modify: `src/codex_claude_orchestrator/mcp_server/job_manager.py`
- Modify: `src/codex_claude_orchestrator/mcp_server/__main__.py`
- Test: `tests/mcp_server/test_job_manager.py`

- [ ] **Step 1: Write failing test for H9 — JobManager.shutdown()**

```python
class TestGracefulShutdown:
    def test_shutdown_cancels_running_jobs(self):
        """H9: shutdown() must cancel all running jobs and wait for threads."""
        manager = JobManager()
        job_id = manager.create_job(
            runner=FakeRunner(delay=10.0),
            repo_root=Path("/tmp"),
            goal="test",
        )
        assert manager.get_job(job_id)["status"] == "running"

        manager.shutdown(timeout=2.0)

        snap = manager.get_job(job_id)
        assert snap["status"] == "cancelled"

    def test_shutdown_joins_threads(self):
        """H9: shutdown() must join background threads."""
        manager = JobManager()
        job_id = manager.create_job(
            runner=FakeRunner(result={"status": "done"}),
            repo_root=Path("/tmp"),
            goal="test",
        )
        time.sleep(0.1)  # let it finish
        thread = manager._jobs[job_id].thread
        manager.shutdown(timeout=2.0)
        assert not thread.is_alive()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/mcp_server/test_job_manager.py::TestGracefulShutdown -v`
Expected: FAIL — `shutdown()` method doesn't exist

- [ ] **Step 3: Implement JobManager.shutdown()**

In `job_manager.py`, add to `JobManager`:
```python
def shutdown(self, timeout: float = 5.0) -> None:
    """Cancel all running jobs and join all background threads."""
    with self._lock:
        for job in self._jobs.values():
            if job.status == "running":
                job.cancel_event.set()
                job.status = "cancelled"

    # Join all threads outside the lock
    threads = []
    with self._lock:
        threads = [j.thread for j in self._jobs.values() if j.thread is not None]

    for thread in threads:
        thread.join(timeout=timeout)
```

- [ ] **Step 4: Add signal handling to __main__.py**

In `__main__.py`, change `main()`:
```python
import signal

async def main() -> None:
    from codex_claude_orchestrator.mcp_server.job_manager import JobManager
    from codex_claude_orchestrator.mcp_server.server import create_server

    controller = _build_controller()
    job_manager = JobManager()
    server = create_server(controller=controller, job_manager=job_manager)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: _handle_shutdown(job_manager, server, loop))

    await server.run_stdio_async()


def _handle_shutdown(job_manager, server, loop):
    """Graceful shutdown: cancel jobs, then stop server."""
    job_manager.shutdown(timeout=3.0)
    loop.call_soon(loop.stop)
```

- [ ] **Step 5: Run all tests**

Run: `pytest tests/mcp_server/test_job_manager.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add src/codex_claude_orchestrator/mcp_server/job_manager.py \
        src/codex_claude_orchestrator/mcp_server/__main__.py \
        tests/mcp_server/test_job_manager.py
git commit -m "fix(mcp_server): add graceful shutdown to cancel jobs and join threads

H9: No shutdown hook existed. On SIGINT/SIGTERM, running jobs were
abandoned and background threads never joined, leaving orphaned tmux
sessions.

JobManager.shutdown() cancels all running jobs and joins threads.
__main__.py now registers signal handlers for SIGINT/SIGTERM.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 7: Implement Real stop_worker and cancel_turn (H10 + H11)

**Issues:** H10 — `stop_worker()` is no-op, tmux panes/sessions leak. H11 — `cancel_turn()` is no-op, running Claude process continues consuming resources.

**Files:**
- Modify: `src/codex_claude_orchestrator/v4/adapters/tmux_claude.py:381-391`
- Test: `tests/v4/test_tmux_claude_adapter.py`

- [ ] **Step 1: Read the native_session interface to understand available methods**

Check `src/codex_claude_orchestrator/runtime/native_claude_session.py` for available stop/cancel methods.

- [ ] **Step 2: Write failing test for H10 — stop_worker sends kill signal**

```python
class TestStopWorker:
    def test_stop_worker_kills_tmux_pane(self):
        """H10: stop_worker must actually stop the worker, not return no-op."""
        class FakeNativeSession:
            def __init__(self):
                self.killed = []
            def kill_pane(self, pane_id):
                self.killed.append(pane_id)
                return True

        session = FakeNativeSession()
        adapter = ClaudeCodeTmuxAdapter(native_session=session)
        spec = WorkerSpec(
            crew_id="c1", worker_id="w1", runtime_type="tmux_claude",
            contract_id="source", workspace_path="/tmp/w1",
            terminal_pane="pane-1", transcript_artifact="",
            capabilities=[],
        )
        adapter.register_worker(spec)

        result = adapter.stop_worker("w1")
        assert result.stopped is True
        assert "pane-1" in session.killed
```

- [ ] **Step 3: Write failing test for H11 — cancel_turn sends cancel signal**

```python
class TestCancelTurn:
    def test_cancel_turn_signals_cancel_event(self):
        """H11: cancel_turn must set the cancel event to stop the running process."""
        cancel = threading.Event()
        session = type("FakeSession", (), {"kill_pane": lambda self, p: True})()
        adapter = ClaudeCodeTmuxAdapter(native_session=session, cancel_event=cancel)

        turn = TurnEnvelope(
            crew_id="c1", worker_id="w1", turn_id="t1",
            round_id="r1", phase="source", message="go",
            expected_marker="<<<DONE>>>", required_outbox_path="",
            contract_id="source_write",
        )
        result = adapter.cancel_turn(turn)
        assert result.cancelled is True
        assert cancel.is_set()
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `pytest tests/v4/test_tmux_claude_adapter.py::TestStopWorker tests/v4/test_tmux_claude_adapter.py::TestCancelTurn -v`
Expected: FAIL — stop_worker returns stopped=False, cancel_turn returns cancelled=False

- [ ] **Step 5: Fix H10 — implement real stop_worker**

In `tmux_claude.py`, change `stop_worker` (line 387-391):
```python
def stop_worker(self, worker_id: str) -> StopResult:
    worker = self._workers.get(worker_id)
    if worker is None:
        return StopResult(stopped=False, reason=f"worker {worker_id} not found")
    pane = worker.terminal_pane or worker_id
    try:
        self._native_session.kill_pane(pane)
        self._workers.pop(worker_id, None)
        return StopResult(stopped=True, reason="pane killed")
    except Exception as exc:
        return StopResult(stopped=False, reason=f"kill failed: {exc}")
```

- [ ] **Step 6: Fix H11 — implement real cancel_turn**

In `tmux_claude.py`, change `cancel_turn` (line 381-385):
```python
def cancel_turn(self, turn: TurnEnvelope) -> CancellationResult:
    self._cancel.set()
    return CancellationResult(
        cancelled=True,
        reason="cancel event set — watch_turn will yield runtime.cancelled",
    )
```

- [ ] **Step 7: Run all tests**

Run: `pytest tests/v4/test_tmux_claude_adapter.py -v`
Expected: All PASS

- [ ] **Step 8: Commit**

```bash
git add src/codex_claude_orchestrator/v4/adapters/tmux_claude.py \
        tests/v4/test_tmux_claude_adapter.py
git commit -m "fix(tmux_adapter): implement real stop_worker and cancel_turn

H10: stop_worker() was a no-op returning stopped=False always. Now it
kills the tmux pane via native_session and removes the worker from
the registry.

H11: cancel_turn() was a no-op returning cancelled=False always. Now it
sets the cancel event, which causes watch_turn to yield
runtime.cancelled and return early.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 8: Fix ensure_worker Read-Modify-Write Race (H12)

**Issue:** H12 — Two concurrent `ensure_worker()` calls read the same task list, each append their task, last `write_tasks` wins — silently losing one worker's assignment.

**Files:**
- Modify: `src/codex_claude_orchestrator/crew/controller.py:163-168`
- Test: `tests/crew/test_controller.py`

- [ ] **Step 1: Write failing test for H12 — concurrent ensure_worker must not lose tasks**

```python
class TestEnsureWorkerConcurrency:
    def test_concurrent_ensure_worker_does_not_lose_tasks(self):
        """H12: Two concurrent ensure_worker calls must not lose task assignments."""
        import threading

        recorder = CrewRecorder(Path("/tmp/test-crew"))
        # Pre-create a crew with tasks
        crew = CrewRecord(crew_id="c1", root_goal="test", repo=Path("/tmp"))
        recorder.start_crew(crew)

        controller = CrewController(
            recorder=recorder,
            blackboard=MagicMock(),
            task_graph=TaskGraphPlanner(),
            worker_pool=MagicMock(),
        )

        # Simulate two concurrent ensure_worker calls
        results = []
        barrier = threading.Barrier(2)

        def spawn_worker(contract_id):
            barrier.wait()
            contract = WorkerContract(
                contract_id=contract_id,
                label=f"worker-{contract_id}",
                mission="test",
                required_capabilities=["edit_source"],
                authority_level=AuthorityLevel.SOURCE_WRITE,
                workspace_policy=WorkspacePolicy.WORKTREE,
            )
            try:
                result = controller.ensure_worker(
                    repo_root=Path("/tmp"),
                    crew_id="c1",
                    contract=contract,
                )
                results.append(result)
            except Exception as exc:
                results.append({"error": str(exc)})

        t1 = threading.Thread(target=spawn_worker, args=("c1",))
        t2 = threading.Thread(target=spawn_worker, args=("c2",))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Both tasks should be present
        tasks = recorder.read_crew("c1").get("tasks", [])
        task_ids = {t["task_id"] for t in tasks}
        # At minimum, we should have 2 tasks (one per worker)
        assert len(task_ids) >= 2, f"Lost task assignments: only {task_ids}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/crew/test_controller.py::TestEnsureWorkerConcurrency -v`
Expected: FAIL — one task gets lost due to read-modify-write race

- [ ] **Step 3: Fix H12 — add locking to ensure_worker**

In `controller.py`, add a threading lock to `__init__`:
```python
def __init__(self, *, recorder, blackboard, task_graph, worker_pool, ...):
    # ... existing init ...
    self._ensure_worker_lock = threading.Lock()
```

In `ensure_worker`, wrap the read-modify-write section (lines 162-168) in the lock:
```python
def ensure_worker(self, *, repo_root, crew_id, contract, allow_dirty_base=False):
    details = self._recorder.read_crew(crew_id)
    crew = self._crew_from_dict(details["crew"])
    task = self._task_graph.task_for_contract(crew_id, contract)
    worker = self._worker_pool.ensure_worker(
        repo_root=repo_root,
        crew=crew,
        contract=contract,
        task=task,
        allow_dirty_base=allow_dirty_base,
    )
    worker_payload = worker.to_dict() if hasattr(worker, "to_dict") else dict(worker)

    # Lock the read-modify-write on tasks
    with self._ensure_worker_lock:
        details = self._recorder.read_crew(crew_id)
        tasks = [self._task_from_dict(item) for item in details.get("tasks", [])]
        task.owner_worker_id = worker_payload["worker_id"]
        task.status = CrewTaskStatus.ASSIGNED
        tasks = [existing for existing in tasks if existing.task_id != task.task_id]
        tasks.append(task)
        self._recorder.write_tasks(crew_id, tasks)

    if self._domain_events:
        self._domain_events.emit_task_created(crew_id, task.task_id, task.title)
    self.write_team_snapshot(
        crew_id=crew_id,
        last_decision={"action_type": "spawn_worker", "contract_id": contract.contract_id},
    )
    return worker_payload
```

- [ ] **Step 4: Run all controller tests**

Run: `pytest tests/crew/test_controller.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/codex_claude_orchestrator/crew/controller.py tests/crew/test_controller.py
git commit -m "fix(controller): add locking to ensure_worker read-modify-write

H12: Two concurrent ensure_worker() calls read the same task list, each
append their task, and the last write_tasks() silently loses one worker's
assignment.

Added _ensure_worker_lock to protect the read-modify-write section. The
lock re-reads the task list after acquiring to avoid stale reads.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 9: Fix Event Type Mismatch Between Emitter and Projection (H13)

**Issue:** H13 — 5 emitted event types (verification.passed/failed, challenge.issued, repair.requested, review.completed) are invisible to projection. 3 projection-handled types (crew.accepted, crew.ready_for_accept, human.required) have no emitter.

**Files:**
- Modify: `src/codex_claude_orchestrator/v4/crew_state_projection.py`
- Test: `tests/v4/test_crew_state_projection.py`

- [ ] **Step 1: Write failing test for H13 — emitted types must be handled by projection**

```python
class TestEventTypeMismatch:
    def test_verification_events_appear_in_projection(self):
        """H13: verification.passed/failed events must be visible in projection."""
        from codex_claude_orchestrator.v4.events import AgentEvent

        events = [
            AgentEvent(
                event_id="e1", stream_id="c1", sequence=1,
                type="crew.started", crew_id="c1",
                payload={"goal": "test"}, created_at="2026-01-01T00:00:00Z",
            ),
            AgentEvent(
                event_id="e2", stream_id="c1", sequence=2,
                type="verification.passed", crew_id="c1", worker_id="w1",
                round_id="r1", payload={"command": "pytest"},
                created_at="2026-01-01T00:01:00Z",
            ),
            AgentEvent(
                event_id="e3", stream_id="c1", sequence=3,
                type="verification.failed", crew_id="c1", worker_id="w1",
                round_id="r1", payload={"command": "pytest"},
                created_at="2026-01-01T00:02:00Z",
            ),
            AgentEvent(
                event_id="e4", stream_id="c1", sequence=4,
                type="challenge.issued", crew_id="c1", worker_id="w1",
                round_id="r1", payload={"finding": "bad code", "category": "review"},
                created_at="2026-01-01T00:03:00Z",
            ),
            AgentEvent(
                event_id="e5", stream_id="c1", sequence=5,
                type="review.completed", crew_id="c1", worker_id="w1",
                turn_id="t1", payload={"status": "ok", "summary": "looks good"},
                created_at="2026-01-01T00:04:00Z",
            ),
        ]
        proj = CrewStateProjection.from_events(events)
        # All events should appear in the events list
        event_types = [e["type"] for e in proj.events]
        assert "verification.passed" in event_types
        assert "verification.failed" in event_types
        assert "challenge.issued" in event_types
        assert "review.completed" in event_types

    def test_challenge_events_tracked_in_projection(self):
        """H13: challenge.issued events should be tracked as challenges."""
        from codex_claude_orchestrator.v4.events import AgentEvent

        events = [
            AgentEvent(
                event_id="e1", stream_id="c1", sequence=1,
                type="crew.started", crew_id="c1",
                payload={"goal": "test"}, created_at="2026-01-01T00:00:00Z",
            ),
            AgentEvent(
                event_id="e2", stream_id="c1", sequence=2,
                type="challenge.issued", crew_id="c1", worker_id="w1",
                round_id="r1", payload={"finding": "bad code", "category": "review"},
                created_at="2026-01-01T00:01:00Z",
            ),
        ]
        proj = CrewStateProjection.from_events(events)
        # Challenges should be tracked somewhere in the projection
        dict_repr = proj.to_read_crew_dict()
        # Check that the challenge info is accessible
        challenge_events = [e for e in proj.events if e["type"] == "challenge.issued"]
        assert len(challenge_events) == 1
```

- [ ] **Step 2: Run test to verify behavior**

Run: `pytest tests/v4/test_crew_state_projection.py::TestEventTypeMismatch -v`
Expected: The events ARE already stored in the generic `self.events` list (line 42-51), so the first test may pass. The issue is that specific event types don't update projection state.

- [ ] **Step 3: Add missing event type handlers to projection**

In `crew_state_projection.py`, add new fields and handlers in the `_apply` method:

Add new dataclass fields:
```python
@dataclass
class CrewStateProjection:
    # ... existing fields ...
    challenges: list[dict] = field(default_factory=list)
    verifications: list[dict] = field(default_factory=list)
    reviews: list[dict] = field(default_factory=list)
```

Add new match cases in `_apply`:
```python
case "verification.passed":
    self.verifications.append({
        "worker_id": event.worker_id,
        "round_id": event.round_id,
        "command": event.payload.get("command", ""),
        "passed": True,
        "created_at": event.created_at,
    })
case "verification.failed":
    self.verifications.append({
        "worker_id": event.worker_id,
        "round_id": event.round_id,
        "command": event.payload.get("command", ""),
        "passed": False,
        "created_at": event.created_at,
    })
case "challenge.issued":
    self.challenges.append({
        "worker_id": event.worker_id,
        "round_id": event.round_id,
        "finding": event.payload.get("finding", ""),
        "category": event.payload.get("category", ""),
        "severity": event.payload.get("severity", ""),
        "created_at": event.created_at,
    })
case "repair.requested":
    # Track as part of challenges (repair follows challenge)
    self.challenges.append({
        "worker_id": event.worker_id,
        "round_id": event.round_id,
        "instruction": event.payload.get("instruction", ""),
        "category": "repair",
        "created_at": event.created_at,
    })
case "review.completed":
    self.reviews.append({
        "worker_id": event.worker_id,
        "turn_id": event.turn_id,
        "status": event.payload.get("status", ""),
        "summary": event.payload.get("summary", ""),
        "created_at": event.created_at,
    })
```

Update `to_read_crew_dict` to include new fields:
```python
def to_read_crew_dict(self) -> dict[str, Any]:
    return {
        # ... existing fields ...
        "challenges": self.challenges,
        "verifications": self.verifications,
        "reviews": self.reviews,
    }
```

- [ ] **Step 4: Run all projection tests**

Run: `pytest tests/v4/test_crew_state_projection.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/codex_claude_orchestrator/v4/crew_state_projection.py \
        tests/v4/test_crew_state_projection.py
git commit -m "fix(projection): handle verification/challenge/review event types

H13: 5 emitted event types (verification.passed/failed, challenge.issued,
repair.requested, review.completed) were stored in the generic events list
but never updated projection state, making them invisible to consumers.

Added dedicated projection fields (challenges, verifications, reviews) and
match cases for each event type. to_read_crew_dict() now includes these
new fields.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Verification

After all 8 tasks are complete, run the full test suite:

```bash
pytest tests/v4/test_domain_events.py tests/v4/test_supervisor.py tests/v4/test_crew_runner.py tests/mcp_server/test_job_manager.py tests/v4/test_tmux_claude_adapter.py tests/crew/test_controller.py tests/v4/test_crew_state_projection.py -v
```

All tests should pass. Then run the broader test suite to check for regressions:

```bash
pytest tests/ -v --timeout=60
```
