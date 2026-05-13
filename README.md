# Agent Crucible

Multi-agent adversarial orchestration for software engineering tasks. Spawn specialized workers that implement, review, and verify code — with an adversarial agent that actively tries to break it.

## The Problem

You ask an AI agent to implement a feature. It writes 500 lines, runs the tests, says "done." You merge it. Two days later you find a subtle race condition it never considered.

**One AI agent reviewing its own work has blind spots.** It optimizes for "make the tests pass," not "find what could go wrong." It won't challenge its own assumptions.

Agent Crucible solves this by pitting multiple specialized agents against each other — one implements, another actively tries to break it. The implementer has to defend its code against a hostile reviewer. Bad code doesn't survive.

## How It Works

![Architecture Flow](liuchengtu.png)

```
User → crew_run(repo, goal) → MCP Server
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
              Worker (tmux)   Worker (tmux)   Worker (tmux)
              [implementer]   [reviewer]      [explorer]
                    │               │               │
                    └───────┬───────┘               │
                            ▼                       │
                    Adversarial Review ◄────────────┘
                            │
                    challenge/repair loop (up to 3 rounds)
                            │
                            ▼
                    Verification (pytest, etc.)
                            │
                            ▼
                    Merge → Done
```

1. **User** sends a task request (e.g. "Add user registration with email verification")
2. **MCP Server** spawns specialized workers in isolated git worktrees
3. **Workers** execute their roles — implementer writes code, explorer maps the codebase, reviewer attacks
4. **Adversarial loop** — reviewer finds issues, emits targeted challenges, implementer fixes and proves the fix works
5. **Verification** — automated tests run; failures trigger more challenge rounds
6. **Merge** — verified changes merge into the main branch

## Why Multiple Agents?

| Single AI Agent | Agent Crucible |
|---|---|
| Reviews its own code (blind spots) | Separate reviewer with fresh context |
| One long context window (polluted) | Isolated contexts per role |
| Sequential: write → test → done | Adversarial: write → attack → defend → verify |
| "Tests pass, ship it" | "Tests pass, but what about X?" |

## Quick Start

### 1. Install Plugin (Claude Code)

```bash
# 1. Start Claude Code
claude

# 2. Add marketplace (in Claude Code session)
/plugin marketplace add zhangclaus/agent-crucible

# 3. Install plugin (note: @marketplace-name suffix required)
/plugin install agent-crucible@agent-crucible

# 4. Restart Claude Code
# Press Ctrl+C to exit, then run `claude` again
```

### 2. Use in Claude Code

After restarting Claude Code, the plugin is automatically loaded. Use the `/agent-crucible` skill:

```
/agent-crucible 帮我审查这个模块的代码质量
```

Or directly call MCP tools:

```
# Simple review — returns job_id, polls automatically in background
crew_run(repo="/path/to/project", goal="Add user authentication")

# With verification commands
crew_run(repo="/path/to/project", goal="Add auth", verification_commands=["pytest"])
```

### 3. Use with Any MCP Client

The MCP server runs as a standard stdio process. Any MCP-compatible agent (Codex, Cursor, custom agents) can connect:

```json
{
  "mcpServers": {
    "agent-crucible": {
      "command": "acr-mcp",
      "env": { "V4_EVENT_STORE_BACKEND": "sqlite" }
    }
  }
}
```

### 4. CLI (Alternative)

```bash
# Install package
pip install -e .

# Check prerequisites
acr doctor

# Run adversarial code review
acr crew run \
  --repo /path/to/your/project \
  --goal "Add user registration" \
  --verification-command "pytest" \
  --max-rounds 3
```

## Requirements

- Python >= 3.11
- [Claude CLI](https://docs.anthropic.com/en/docs/claude-code) — runtime for workers (each worker is a Claude CLI instance in tmux)
- tmux

## Features

- **Adversarial Verification** — Reviewer actively attacks code; Implementer defends; up to 3 challenge/repair rounds
- **Parallel Workers** — Multiple workers execute concurrently in isolated worktrees (`parallel=True`)
- **Long Task Supervisor** — Multi-stage execution (Think → Plan → Do) with dynamic planning for complex tasks
- **Terminal Auto-Attach** — Worker tmux sessions automatically open in Terminal.app so you can watch them work
- **Git Worktree Isolation** — Each worker gets an independent worktree; no file conflicts
- **Event-Sourced Audit Trail** — Every state change recorded in SQLite; full replay capability
- **MCP Server** — Standard MCP protocol; integrates with any MCP-compatible agent
- **Delta Polling** — Non-blocking job system; `crew_job_status` only returns changes, minimizing context usage
- **Worker Templates** — Predefined roles for common tasks (frontend, backend, test, review)

## MCP Tools

### Job Management
| Tool | Description |
|------|-------------|
| `crew_run` | Start a non-blocking orchestration job (returns `job_id` + `background_agent_prompt`) |
| `crew_job_status` | Poll job status — delta mode: only returns changes to minimize context |
| `crew_cancel` | Cancel a running job |

### Crew Lifecycle
| Tool | Description |
|------|-------------|
| `crew_spawn` | Spawn a worker with template or custom label |
| `crew_stop_worker` | Stop a specific worker |
| `crew_verify` | Run a verification command |
| `crew_accept` | Accept results and trigger merge |
| `crew_challenge` | Challenge a worker with issues found |

### Context & Observation
| Tool | Description |
|------|-------------|
| `crew_observe` | Observe worker output (structured report, not raw tmux dump) |
| `crew_changes` | View changed files across all workers |
| `crew_diff` | View diff for a specific file |
| `crew_blackboard` | Read shared knowledge base entries |
| `crew_events` | Read key events (turns, challenges, reviews) |

### `crew_run` Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `repo` | str | required | Repository root path |
| `goal` | str | `""` | Task description |
| `verification_commands` | list[str] | `None` | Commands to verify completion (e.g. `["pytest"]`) |
| `max_rounds` | int | `3` | Max challenge/repair rounds |
| `parallel` | bool | `False` | Enable parallel worker mode |
| `max_workers` | int | `3` | Max concurrent workers (1-5, clamped) |
| `long_task` | bool | `False` | Multi-stage execution (Think → Plan → Do) |
| `subtasks` | list[dict] | `None` | Explicit subtask definitions for parallel mode |

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

## Testing

```bash
# Run all tests
pytest

# Run specific module tests
pytest tests/v4/ -v
pytest tests/mcp_server/ -v
```

## License

MIT
