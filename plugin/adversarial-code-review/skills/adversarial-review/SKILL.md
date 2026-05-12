---
name: adversarial-review
description: "Multi-agent adversarial code review. One agent implements, another actively tries to break it."
---

# Adversarial Code Review

Use this skill when you need thorough code review with adversarial verification.

## When to Use

- Reviewing code changes before merge
- Verifying complex features
- Finding edge cases and security issues
- Ensuring code quality with multiple perspectives

## How It Works

1. **Implementer** writes code to fulfill the goal
2. **Reviewer** actively tries to find issues (not just check tests)
3. If issues found, **challenge** the implementer
4. Implementer fixes and defends
5. Repeat until verification passes

## Quick Start

### Option 1: Simple Review
```
crew_run(repo="/path/to/project", goal="Your task description")
```

### Option 2: Supervisor Mode (Full Control)
```
crew_run(repo="/path/to/project", goal="Your task description", supervisor_mode=True)
```

Then orchestrate manually:
```
# Spawn workers
crew_spawn(repo="/path", crew_id="crew-1", label="backend-developer", mission="Implement API")
crew_spawn(repo="/path", crew_id="crew-1", label="test-writer", mission="Write tests")

# Monitor progress
crew_observe(repo="/path", crew_id="crew-1", worker_id="worker-1")

# Challenge if issues found
crew_challenge(crew_id="crew-1", summary="Missing error handling")

# Verify and accept
crew_verify(crew_id="crew-1", command="pytest")
crew_accept(crew_id="crew-1", summary="All tests pass")
```

## Worker Templates

| Template | Use When |
|----------|----------|
| `targeted-code-editor` | Small, focused changes |
| `frontend-developer` | UI, components, styles |
| `backend-developer` | API, services, database |
| `test-writer` | Writing/updating tests |
| `repo-context-scout` | Exploring codebase first |
| `patch-risk-auditor` | Reviewing before accept |
| `verification-failure-analyst` | Diagnosing test failures |

## Tips

- Use `write_scope` to limit which files a worker can modify
- Challenge with specific, actionable feedback
- Verify early and often
- Prefer challenging existing workers over spawning new ones
