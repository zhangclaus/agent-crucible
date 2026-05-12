---
description: Multi-agent adversarial code review for Claude Code
disable-model-invocation: false
---

# Agent Crucible

Use this command to perform adversarial code review with multiple agents.

## How It Works

1. One agent implements the code
2. Another agent actively tries to break it
3. If issues found, challenge the implementer
4. Implementer fixes and defends
5. Repeat until verification passes

## Usage

### Simple Review
```
/agent-crucible 帮我审查这个模块的代码质量
```

### With Specific Goal
```
/agent-crucible Add user authentication with email verification
```

## Available MCP Tools

The following tools are available for code review:

### Core Tools (Default Mode)
- `crew_run(repo, goal)` — Start adversarial review (default mode)
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
| `frontend-developer` | source_write | Frontend changes (UI, components, styles) |
| `backend-developer` | source_write | Backend changes (API, services, database) |
| `test-writer` | source_write | Writing and updating tests |

## Examples

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
