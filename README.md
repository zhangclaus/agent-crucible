# Agent Crucible

Multi-agent code review with adversarial verification for Claude Code. One agent implements, another actively tries to break it.

## The Problem

You ask Claude Code to implement a feature. It writes 500 lines, runs the tests, says "done." You merge it. Two days later you find a subtle race condition it never considered.

**One AI agent reviewing its own work has blind spots.** It optimizes for "make the tests pass," not "find what could go wrong." It won't challenge its own assumptions.

Agent Crucible solves this by pitting multiple Claude CLI instances against each other — one implements, another actively tries to break it. The implementer has to defend its code against a hostile reviewer. Bad code doesn't survive.

## How It Works

![Architecture Flow](liuchengtu.png)

1. **User** sends a task request (e.g. "Add user registration with email verification")
2. **LongTaskSupervisor** drives multi-stage execution:
   - **Stage 1**: Think — brainstorming and planning
   - **Stage 2**: PlanAdversary — validate plan quality
   - **Stage 3**: Do — implement with parallel workers
   - Each stage: Workers execute → adversarial agent reviews → challenge/repair loop → merge results
3. **Worktree Isolation** — each worker operates in an independent git worktree
4. **Event Store** (SQLite) — persists all events for full replay

The key insight: **the Reviewer is adversarial**. It doesn't just check "do tests pass?" — it looks for edge cases, race conditions, security holes, and architectural problems. When it finds issues, it emits targeted challenges to specific workers. The Implementer must fix them and prove the fix works.

## Why Multiple Agents?

| Single Claude CLI | Agent Crucible |
|---|---|
| Reviews its own code (blind spots) | Separate reviewer with fresh context |
| One long context window (polluted) | Isolated contexts per role |
| Sequential: write → test → done | Adversarial: write → attack → defend → verify |
| "Tests pass, ship it" | "Tests pass, but what about X?" |

## Quick Start

### Install

```bash
pip install git+https://github.com/zhangclaus/agent-crucible.git

# Verify prerequisites
acr doctor
```

### Claude Code Integration (MCP)

```bash
# Auto-generate .mcp.json
acr init

# Restart Claude Code, then use:
crew_run(repo="/path/to/project", goal="Refactor auth module")
```

### CLI

```bash
# Run adversarial code review
acr crew run \
  --repo /path/to/your/project \
  --goal "Add user registration with email verification" \
  --verification-command "pytest" \
  --max-rounds 3

# Check status
acr crew status --repo /path/to/your/project

# Accept results
acr crew accept --repo /path/to/your/project
```

## Requirements

- Python >= 3.11
- [Claude CLI](https://docs.anthropic.com/en/docs/claude-code) (Anthropic's Claude Code)
- tmux

## Features

- **Adversarial Verification** — Reviewer actively attacks code; Implementer defends; up to 3 challenge/repair rounds
- **AI Supervisor Mode** — Supervisor agent directly controls workers via MCP tools (supervisor_mode=True)
- **Long Task Supervisor** — Multi-stage execution with dynamic planning for complex tasks
- **Git Worktree Isolation** — Each worker gets an independent worktree; no file conflicts
- **Event-Sourced Audit Trail** — Every state change recorded in SQLite; full replay capability
- **MCP Server** — Integrates with Claude Code as native MCP tools
- **Non-blocking Jobs** — `crew_run` returns immediately; delta-status polling minimizes context usage
- **Parallel Subtasks** — Multiple workers execute concurrently with adversarial review
- **Worker Templates** — Predefined roles for common tasks (frontend, backend, test, review)

## Two Modes

### Default Mode (Python Loop)
```python
crew_run(repo="/path", goal="Add auth")
```
- V4CrewRunner drives the orchestration loop
- Automatic verification, challenge, and retry
- Minimal context usage

### Supervisor Mode (AI Control)
```python
crew_run(repo="/path", goal="Add auth", supervisor_mode=True)
```
- Supervisor agent directly controls workers
- Full flexibility in orchestration strategy
- Access to all supervisor tools

## MCP Tools

### Core Tools
| Tool | Description |
|------|-------------|
| `crew_run` | Start a non-blocking review job (returns `job_id`) |
| `crew_job_status` | Poll job status with delta tracking |
| `crew_cancel` | Cancel a running job |
| `crew_verify` | Run a verification command |
| `crew_accept` | Accept and finalize results |

### Supervisor Mode Tools
| Tool | Description |
|------|-------------|
| `crew_spawn` | Spawn worker agent with template or custom label |
| `crew_observe` | Observe worker output (structured, not raw) |
| `crew_changes` | View changed files across all workers |
| `crew_diff` | View diff for specific file |
| `crew_stop_worker` | Stop specific worker |
| `crew_challenge` | Challenge worker with issues |

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

## CLI Commands

| Command | Description |
|---------|-------------|
| `acr init` | Generate `.mcp.json` for Claude Code |
| `acr doctor` | Check prerequisites (Python, Claude CLI, tmux) |
| `acr crew run` | Start adversarial code review |
| `acr crew status` | Show crew status |
| `acr crew accept` | Accept crew results |
| `acr crew stop` | Stop all workers |
| `acr crew verify` | Run verification command |

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
