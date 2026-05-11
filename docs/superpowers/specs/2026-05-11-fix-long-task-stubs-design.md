# Fix LongTaskSupervisor Stubs & crew_accept Bug

## Goal

Make LongTaskSupervisor end-to-end executable by wiring 8 stub methods to existing infrastructure (V4CrewRunner, WorktreeManager, EventStore, Controller). Fix the crew_accept MCP tool signature mismatch.

## Architecture

LongTaskSupervisor owns **multi-stage orchestration + dynamic planning**. Each stage's execution is delegated to V4CrewRunner, which already has a working adversarial loop (spawn → review → challenge → verify). Lightweight sub-agents (reviewer, stage planner, plan adversary) use supervisor.run_worker_turn directly.

## Changes

### 1. `_spawn_sub_agent(prompt, tools)` — Wire to Supervisor

**File:** `src/codex_claude_orchestrator/v4/long_task_supervisor.py:330-348`

Replace `raise NotImplementedError` with:
- Create a temporary worker contract for the sub-agent role
- Call `self.supervisor.run_worker_turn()` with the prompt
- Wait for completion, extract output from the turn result
- Return the output string

Uses the same pattern as `crew_runner.py:_run_review()` but simplified for one-shot sub-agents.

### 2. `_run_sub_tasks(stage, briefing)` — Delegate to V4CrewRunner

**File:** `src/codex_claude_orchestrator/v4/long_task_supervisor.py:460-466`

Replace `return []` with:
- For each sub_task in stage.sub_tasks:
  - Create a V4CrewRunner instance with the sub_task's goal, write_scope, verification_commands
  - Call `runner.supervise()` — this runs the full adversarial loop
  - Collect the result dict (status, changes, review verdict)
- Return list of results
- Independent sub_tasks run via `concurrent.futures.ThreadPoolExecutor`

### 3. `merge_stage_results(stage, results)` — Use WorktreeManager

**File:** `src/codex_claude_orchestrator/v4/long_task_supervisor.py:314-324`

Replace `pass` with:
- For each successful result, get the worker's worktree path
- Call `self.controller._worker_pool.worktree_manager.get_diff()` to get the patch
- Apply patch to the main worktree via `git apply`
- Skip failed results (already has the `hasattr(result, "success")` check)

### 4. `_read_worker_outbox(worker_id)` — Read from EventStore

**File:** `src/codex_claude_orchestrator/v4/long_task_supervisor.py:306-308`

Replace `raise NotImplementedError` with:
- Query `self.event_store.list_stream(worker_id)` for the worker's event stream
- Find the latest `artifact.written` or `turn.completed` event
- Extract and return the payload (contains the worker's output)

### 5. `get_active_turns(stage)` — From Supervisor

**File:** `src/codex_claude_orchestrator/v4/long_task_supervisor.py:289-292`

Replace `return {}` with:
- Query the supervisor for active turns associated with the current stage's workers
- Return dict mapping worker_id → turn object
- Falls back to empty dict if supervisor doesn't track turns

### 6. `get_updated_results(stage, active_turns)` — Already has logic

**File:** `src/codex_claude_orchestrator/v4/long_task_supervisor.py:294-304`

This method already calls `self.supervisor.watch_turn()` and `self._read_worker_outbox()`. Once `_read_worker_outbox` works, this method works automatically. No changes needed to the method body itself.

### 7. `_run_final_verification()` — subprocess.run

**File:** `src/codex_claude_orchestrator/v4/long_task_supervisor.py:472-475`

Replace `pass` with:
- For each command in `self.verification_commands`:
  - Run `subprocess.run(command, shell=True, cwd=self.repo_root, capture_output=True, text=True)`
  - If returncode != 0, emit `verification.failed` domain event
  - If all pass, emit `verification.passed` domain event
- Uses the same pattern as `controller.verify()` but runs directly

### 8. `_accept()` — Call controller.accept()

**File:** `src/codex_claude_orchestrator/v4/long_task_supervisor.py:477-480`

Replace `pass` with:
- Build a summary from completed_stages
- Call `self.controller.accept(crew_id=self._crew_id, summary=summary)`

### 9. crew_accept Bug Fix

**File:** `src/codex_claude_orchestrator/mcp_server/tools/crew_decision.py:11-12`

Change:
```python
async def crew_accept(crew_id: str) -> list[TextContent]:
    result = controller.accept(crew_id=crew_id)
```
To:
```python
async def crew_accept(crew_id: str, summary: str = "") -> list[TextContent]:
    result = controller.accept(crew_id=crew_id, summary=summary or "Accepted by user")
```

## Testing

- `tests/v4/test_long_task_supervisor.py` — Add integration tests for `supervise_long_task()` that mock the supervisor/controller but exercise the full loop
- `tests/mcp_server/test_crew_decision.py` — Test crew_accept with and without summary parameter
- Existing tests must still pass

## Out of Scope

- Rewriting the LongTaskSupervisor architecture
- Changing the V4CrewRunner adversarial loop
- Adding new MCP tools
- Refactoring CrewController or WorkerPool
