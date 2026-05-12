# Agent Crucible Plugin

Multi-agent code review with adversarial verification for Claude Code.

## What It Does

1. One agent implements the code
2. Another agent actively tries to break it
3. The implementer must defend against challenges
4. This cycle repeats until verification passes

## Available Tools

### Core Tools (Default Mode)
- `crew_run(repo, goal)` — Start adversarial review
- `crew_job_status(job_id)` — Poll job status
- `crew_cancel(job_id)` — Cancel a running job
- `crew_verify(crew_id, command)` — Run verification command
- `crew_accept(crew_id, summary)` — Accept and finalize results

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

### Basic Review (Recommended)
```
crew_run(repo="/path/to/project", goal="Add user authentication")
```

### With Verification Command
```
crew_run(repo="/path/to/project", goal="Add user authentication", verification_commands=["pytest"])
```

## Notes

- **Default mode** uses V4CrewRunner Python loop (stable, recommended)
- **Supervisor mode** (`supervisor_mode=True`) is experimental and not recommended for production use
