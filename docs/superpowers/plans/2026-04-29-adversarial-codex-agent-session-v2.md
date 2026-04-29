# Adversarial Codex-Agent Session V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the V2 MVP that wraps V1 dispatch runs into durable adversarial sessions with output traces, final verification records, bounded repair rounds, and governed pending skills.

**Architecture:** Keep V1 `Supervisor.dispatch` behavior intact and add a report-returning dispatch path for V2. Add focused session, verification, and skill modules that persist under `.orchestrator/sessions/` and `.orchestrator/skills/`, while the CLI exposes `session start`, `sessions list/show`, and `skills list/show/approve/reject`.

**Tech Stack:** Python 3.11+, stdlib dataclasses/enums/json/pathlib/subprocess/shlex/uuid, existing orchestrator package, pytest

---

## Scope Check

This plan implements the V2 MVP only. It does not build the browser UI, a Codex worker adapter, or model fine-tuning. It preserves the midpoint observability requirement by writing `OutputTrace` records that point back to V1 run artifacts.

## File Structure

- Modify: `src/codex_claude_orchestrator/models.py`
  - Add session, turn, challenge, verification, learning, skill, output trace, and dispatch report dataclasses/enums.
- Modify: `src/codex_claude_orchestrator/supervisor.py`
  - Add a `dispatch_with_report()` method returning run id plus evaluation while keeping `dispatch()` backwards compatible.
- Create: `src/codex_claude_orchestrator/session_recorder.py`
  - Persist sessions, turns, output traces, challenges, verifications, learning notes, final reports, and session artifacts.
- Create: `src/codex_claude_orchestrator/verification_runner.py`
  - Run user-provided verification commands with policy guard and artifact capture.
- Create: `src/codex_claude_orchestrator/skill_evolution.py`
  - Generate pending skill files, list/show skills, and approve/reject candidates.
- Create: `src/codex_claude_orchestrator/session_engine.py`
  - Coordinate bounded execute/verify/challenge/repair/finalize session flow.
- Modify: `src/codex_claude_orchestrator/cli.py`
  - Add `session start`, `sessions list/show`, and `skills list/show/approve/reject`.
- Create: `tests/test_session_recorder.py`
- Create: `tests/test_verification_runner.py`
- Create: `tests/test_skill_evolution.py`
- Create: `tests/test_session_engine.py`
- Modify: `tests/test_models.py`
- Modify: `tests/test_supervisor.py`
- Modify: `tests/test_cli.py`

## Task 1: V2 Models

**Files:**
- Modify: `src/codex_claude_orchestrator/models.py`
- Modify: `tests/test_models.py`

- [ ] **Step 1: Write failing tests for session and output trace serialization**

Add tests that import `SessionRecord`, `SessionStatus`, `TurnRecord`, `TurnPhase`, `OutputTrace`, `ChallengeRecord`, `ChallengeType`, `VerificationRecord`, `VerificationKind`, `LearningNote`, `SkillRecord`, `SkillStatus`, and `DispatchReport`.

Run: `.venv/bin/python -m pytest tests/test_models.py -v`
Expected: FAIL with import errors for the new model names.

- [ ] **Step 2: Implement dataclasses and enums**

Add enums:

```python
class SessionStatus(StrEnum):
    RUNNING = "running"
    ACCEPTED = "accepted"
    NEEDS_HUMAN = "needs_human"
    FAILED = "failed"
    BLOCKED = "blocked"


class TurnPhase(StrEnum):
    EXECUTE = "execute"
    LIGHT_VERIFY = "light_verify"
    CHALLENGE = "challenge"
    REPAIR = "repair"
    FINAL_VERIFY = "final_verify"


class ChallengeType(StrEnum):
    COUNTEREXAMPLE = "counterexample"
    MISSING_TEST = "missing_test"
    SCOPE_RISK = "scope_risk"
    POLICY_RISK = "policy_risk"
    QUALITY_RISK = "quality_risk"


class VerificationKind(StrEnum):
    COMMAND = "command"
    POLICY = "policy"
    DIFF = "diff"
    GENERATED_CHECK = "generated_check"
    HUMAN = "human"


class SkillStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    REJECTED = "rejected"
    ARCHIVED = "archived"
```

Add dataclasses with `to_dict()` using `_normalize`, matching the V2 spec fields. `DispatchReport` should contain `run_id`, `task_id`, and `evaluation`.

- [ ] **Step 3: Verify model tests pass**

Run: `.venv/bin/python -m pytest tests/test_models.py -v`
Expected: PASS.

## Task 2: Supervisor Dispatch Report

**Files:**
- Modify: `src/codex_claude_orchestrator/supervisor.py`
- Modify: `tests/test_supervisor.py`

- [ ] **Step 1: Write failing test for `dispatch_with_report`**

Add a test that calls `Supervisor.dispatch_with_report(task, repo_root)` and asserts:

- `report.evaluation.accepted is True`
- `report.run_id` names an existing run directory
- existing `dispatch()` still returns `EvaluationOutcome`

Run: `.venv/bin/python -m pytest tests/test_supervisor.py -v`
Expected: FAIL because `dispatch_with_report` does not exist.

- [ ] **Step 2: Implement report path without breaking existing API**

Refactor `dispatch()` to:

```python
def dispatch(self, task: TaskRecord, source_repo: Path):
    return self.dispatch_with_report(task, source_repo).evaluation
```

Move current logic into `dispatch_with_report()` and return `DispatchReport(run_id=run.run_id, task_id=task.task_id, evaluation=evaluation)` at each exit path.

- [ ] **Step 3: Verify supervisor tests pass**

Run: `.venv/bin/python -m pytest tests/test_supervisor.py -v`
Expected: PASS.

## Task 3: Session Recorder

**Files:**
- Create: `src/codex_claude_orchestrator/session_recorder.py`
- Create: `tests/test_session_recorder.py`

- [ ] **Step 1: Write failing persistence tests**

Test that `SessionRecorder` can:

- `start_session(session)`
- `append_turn(session_id, turn)`
- `append_output_trace(session_id, trace)`
- `append_challenge(session_id, challenge)`
- `append_verification(session_id, verification)`
- `append_learning_note(session_id, learning_note)`
- `finalize_session(session_id, status, final_summary)`
- `list_sessions()`
- `read_session(session_id)`

Run: `.venv/bin/python -m pytest tests/test_session_recorder.py -v`
Expected: FAIL because the module does not exist.

- [ ] **Step 2: Implement file-backed recorder**

Persist:

- `.orchestrator/sessions/<session_id>/session.json`
- `turns.jsonl`
- `output_traces.jsonl`
- `challenges.jsonl`
- `verifications.jsonl`
- `learning.json`
- `final_report.json`

Use atomic JSON writes for whole files and append JSON lines for streams. `list_sessions()` should sort newest first by `created_at`.

- [ ] **Step 3: Verify recorder tests pass**

Run: `.venv/bin/python -m pytest tests/test_session_recorder.py -v`
Expected: PASS.

## Task 4: Verification Runner

**Files:**
- Create: `src/codex_claude_orchestrator/verification_runner.py`
- Create: `tests/test_verification_runner.py`

- [ ] **Step 1: Write failing verification tests**

Test that a passing command records `passed=True`, stdout artifact path, and summary. Test that a blocked command such as `rm -rf something` records `passed=False` and does not execute.

Run: `.venv/bin/python -m pytest tests/test_verification_runner.py -v`
Expected: FAIL because the module does not exist.

- [ ] **Step 2: Implement guarded command execution**

Use `shlex.split(command)` and `PolicyGate.guard_command(argv)` before `subprocess.run(argv, cwd=repo_root, capture_output=True, text=True, timeout=timeout_seconds)`.

Return `VerificationRecord` and write stdout/stderr artifacts through `SessionRecorder.write_text_artifact(session_id, artifact_name, content)`.

- [ ] **Step 3: Verify runner tests pass**

Run: `.venv/bin/python -m pytest tests/test_verification_runner.py -v`
Expected: PASS.

## Task 5: Skill Evolution

**Files:**
- Create: `src/codex_claude_orchestrator/skill_evolution.py`
- Create: `tests/test_skill_evolution.py`

- [ ] **Step 1: Write failing skill lifecycle tests**

Test that `SkillEvolution.create_pending_skill(...)` writes:

- `.orchestrator/skills/pending/<name>/SKILL.md`
- `metadata.json`
- `evidence.json`
- index entry with status `pending`

Test `approve_skill()` moves the skill to `active`, and `reject_skill()` moves it to `rejected`.

Run: `.venv/bin/python -m pytest tests/test_skill_evolution.py -v`
Expected: FAIL because the module does not exist.

- [ ] **Step 2: Implement governed local skills**

Implement a conservative security scan that rejects content containing obvious credential labels such as `API_KEY=`, `BEGIN PRIVATE KEY`, or instructions to bypass policy gates.

Generate `SKILL.md` with sections:

- `When to Use`
- `Procedure`
- `Pitfalls`
- `Verification`
- `Source Evidence`

- [ ] **Step 3: Verify skill tests pass**

Run: `.venv/bin/python -m pytest tests/test_skill_evolution.py -v`
Expected: PASS.

## Task 6: Session Engine

**Files:**
- Create: `src/codex_claude_orchestrator/session_engine.py`
- Create: `tests/test_session_engine.py`

- [ ] **Step 1: Write failing engine tests with fake supervisor**

Use fake supervisors that return `DispatchReport` values. Test:

- accepted dispatch plus passing verification marks session `accepted`
- failed dispatch retries when `max_rounds=2`
- final verification failure creates a challenge and retries when rounds remain
- max rounds with failure marks `needs_human`
- a session with a challenge generates at least one pending skill
- every dispatch produces an `OutputTrace`

Run: `.venv/bin/python -m pytest tests/test_session_engine.py -v`
Expected: FAIL because the module does not exist.

- [ ] **Step 2: Implement bounded deterministic session loop**

Implement `SessionEngine.start(...)`:

1. Create `SessionRecord`.
2. For each round up to `max_rounds`, build a `TaskRecord`.
3. Call `supervisor.dispatch_with_report()`.
4. Append execute `TurnRecord`.
5. Read run details from `RunRecorder.read_run(report.run_id)` and append `OutputTrace`.
6. If evaluation is accepted, run final verification commands.
7. If verification passes, finalize accepted.
8. If evaluation or verification fails and rounds remain, append `ChallengeRecord` and continue with a repair goal.
9. If rounds are exhausted, finalize `needs_human`.
10. If at least one challenge was recorded, create a `LearningNote` and pending skill.

- [ ] **Step 3: Verify engine tests pass**

Run: `.venv/bin/python -m pytest tests/test_session_engine.py -v`
Expected: PASS.

## Task 7: CLI Commands

**Files:**
- Modify: `src/codex_claude_orchestrator/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing CLI tests**

Add tests for:

- parser exposes `session`, `sessions`, and `skills`
- `sessions list/show` reads `SessionRecorder`
- `skills list/show/approve/reject` delegates to `SkillEvolution`
- `session start` prints JSON with `session_id`, `status`, and `final_summary`

Run: `.venv/bin/python -m pytest tests/test_cli.py -v`
Expected: FAIL for missing commands.

- [ ] **Step 2: Implement CLI wiring**

Add:

```bash
orchestrator session start --repo ... --goal ... --assigned-agent claude --workspace-mode isolated --max-rounds 3 --verification-command "..."
orchestrator sessions list --repo ...
orchestrator sessions show --repo ... --session-id ...
orchestrator skills list --repo ...
orchestrator skills show --repo ... --skill-id ...
orchestrator skills approve --repo ... --skill-id ...
orchestrator skills reject --repo ... --skill-id ... --reason "..."
```

Use existing `AgentRegistry`, `build_supervisor`, `RunRecorder`, `SessionRecorder`, `VerificationRunner`, and `SkillEvolution`.

- [ ] **Step 3: Verify CLI tests pass**

Run: `.venv/bin/python -m pytest tests/test_cli.py -v`
Expected: PASS.

## Task 8: Full Verification and Commit

**Files:**
- All files modified above

- [ ] **Step 1: Run full test suite**

Run: `.venv/bin/python -m pytest -v`
Expected: PASS.

- [ ] **Step 2: Run CLI smoke**

Run:

```bash
.venv/bin/orchestrator --help
.venv/bin/orchestrator sessions list --repo /private/tmp/codex-claude-orchestrator-smoke
.venv/bin/orchestrator skills list --repo /private/tmp/codex-claude-orchestrator-smoke
```

Expected: commands exit 0 and print JSON for list commands.

- [ ] **Step 3: Commit**

Run:

```bash
git add src tests docs/superpowers/plans/2026-04-29-adversarial-codex-agent-session-v2.md
git commit -m "feat: add adversarial session v2 mvp"
```
