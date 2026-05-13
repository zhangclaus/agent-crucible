# Agent Crucible Plugin

Multi-agent adversarial orchestration for software engineering tasks.

## What It Does

1. One agent implements the code
2. Another agent actively tries to break it
3. The implementer must defend against challenges
4. This cycle repeats until verification passes

## IMPORTANT: Before Using crew_run()

**You MUST check if the project is a git repository first.** If not, initialize it:

```bash
# Check if git repository
git status

# If not a git repository, initialize it
git init
git add -A
git commit -m "Initial commit"
```

**Why:** Adversarial code review requires git for worktree isolation and change tracking.

## IMPORTANT: When to Use Adversarial Verification

**You MUST use `crew_run()` for these tasks:**
- Implementing new features
- Fixing bugs
- Code review
- Security audit
- Refactoring with behavioral changes

**You can do directly (without crew_run):**
- Cleaning up redundant code
- Querying information
- Reading files
- Simple formatting changes

## Available Tools

### Job Management
- `crew_run(repo, goal)` — Start non-blocking orchestration job (returns job_id)
- `crew_run(repo, goal, verification_commands=["pytest"])` — With verification
- `crew_job_status(job_id)` — Poll job status (delta mode)
- `crew_cancel(job_id)` — Cancel a running job

### Crew Lifecycle
- `crew_spawn(repo, crew_id, label)` — Spawn worker with template
- `crew_stop_worker(repo, crew_id, worker_id)` — Stop specific worker
- `crew_verify(crew_id, command)` — Run verification command
- `crew_accept(crew_id, summary)` — Accept and finalize results
- `crew_challenge(crew_id, summary)` — Challenge worker with issues

### Context & Observation
- `crew_observe(repo, crew_id, worker_id)` — Observe worker output (structured)
- `crew_changes(crew_id)` — View changed files across all workers
- `crew_diff(crew_id, file)` — View diff for specific file
- `crew_blackboard(crew_id)` — Read shared knowledge base
- `crew_events(repo, crew_id)` — Read key events

## Worker Templates

| Template | Authority | Use Case |
|----------|-----------|----------|
| `targeted-code-editor` | source_write | Implementing code changes |
| `repo-context-scout` | readonly | Exploring codebase |
| `patch-risk-auditor` | readonly | Reviewing changes for risks |
| `verification-failure-analyst` | source_write | Diagnosing test failures |
| `frontend-developer` | source_write | Frontend changes |
| `backend-developer` | source_write | Backend changes |
| `test-writer` | source_write | Writing tests |

## Usage

### Implement Feature (MUST use crew_run)
```
# First, ensure git repository exists
git status || (git init && git add -A && git commit -m "Initial commit")

# Then start adversarial review
crew_run(repo="/path/to/project", goal="Add user authentication", verification_commands=["pytest"])
```

### Fix Bug (MUST use crew_run)
```
crew_run(repo="/path/to/project", goal="Fix login validation error", verification_commands=["pytest"])
```

### Code Review (MUST use crew_run)
```
crew_run(repo="/path/to/project", goal="Review authentication module for security issues")
```

### Clean Up (Can do directly)
```
Just do it directly, no need for crew_run()
```

## Notes

- **Default mode** uses V4CrewRunner Python loop (stable, recommended)
- **Terminal auto-attach** — Worker tmux sessions automatically open in Terminal.app
- **Always check git repository** before calling crew_run()
- **Always use crew_run() for implementation tasks** to trigger adversarial verification
