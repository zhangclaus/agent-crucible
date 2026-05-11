# Codex Claude Orchestrator

A local, multi-agent orchestration system for Claude Code. Coordinates multiple Claude CLI workers in isolated tmux sessions with adversarial verification, event-sourced state management, and safety policy gating.

## Why

Complex software tasks benefit from multiple AI agents working in parallel — one explores the codebase, another implements, a third reviews. But coordinating them requires isolation (so they don't overwrite each other), verification (so bad code doesn't ship), and auditability (so you know what happened). This system provides all three.

## Architecture

```
Supervisor Agent (Claude CLI in tmux + MCP Tools + Orchestration Skill)
    |
    | MCP protocol (stdio)
    v
MCP Server (Python, FastMCP)
    |
    v
CrewController / WorkerPool / Blackboard / EventStore
    |
    +-- tmux Worker A (Claude CLI) — explorer
    +-- tmux Worker B (Claude CLI) — implementer (git worktree)
    +-- tmux Worker C (Claude CLI) — reviewer
```

The Supervisor is not a framework primitive — it's just another Claude CLI agent with MCP tools. Orchestration logic lives in Markdown prompt files, not Python code. Changing the orchestration strategy means editing a `.md` file.

## Features

- **Multi-Agent Crew Orchestration** — Role-based workers (explorer, implementer, reviewer) in isolated tmux panes
- **Adversarial Verification Loop** — Spawn → observe → verify → challenge/repair, up to 3 retries
- **Event-Sourced Runtime** — All state changes stored as immutable events in SQLite; full audit trail via CQRS projections
- **Git Worktree Isolation** — Each implementer gets an independent worktree; no file conflicts between workers
- **Blackboard Pattern** — Workers share information through typed entries (fact, claim, risk, patch, verification)
- **Safety Policy Gate** — Blocks destructive commands (`rm -rf`, `git reset --hard`), shell injection, and sensitive path access
- **MCP Server** — Exposes orchestration as MCP tools for Claude Code integration
- **Non-blocking Jobs** — `crew_run` returns immediately; delta-status polling minimizes context usage
- **Parallel Subtasks** — Concurrent worker execution with two-layer adversarial review
- **Long Task Supervisor** — Multi-stage execution with dynamic planning for complex, long-running tasks

## Requirements

- Python >= 3.11
- [Claude CLI](https://docs.anthropic.com/en/docs/claude-code) (Anthropic's Claude Code)
- tmux

## Installation

```bash
# Clone
git clone https://github.com/<your-org>/codex-claude-orchestrator.git
cd codex-claude-orchestrator

# Install
pip install -e .

# Or with dev dependencies
pip install -e ".[dev]"

# Verify prerequisites
orchestrator doctor
```

## Quick Start

### CLI

```bash
# Run a crew with full supervision loop
orchestrator crew run \
  --repo /path/to/your/project \
  --goal "Add user registration with email verification" \
  --verification-command "pytest" \
  --max-rounds 3

# Check status
orchestrator crew status --repo /path/to/your/project

# Accept results when ready
orchestrator crew accept --repo /path/to/your/project
```

### MCP Server (Claude Code Integration)

Add to your `.mcp.json`:

```json
{
  "mcpServers": {
    "crew-orchestrator": {
      "command": "python",
      "args": ["-m", "codex_claude_orchestrator.mcp_server"]
    }
  }
}
```

Then use from Claude Code:

```
crew_run(repo="/path/to/project", goal="Refactor auth module", verification_commands=["pytest"])
crew_job_status(job_id="job-abc123")
crew_accept(crew_id="crew-xyz")
```

## MCP Tools

| Tool | Description |
|------|-------------|
| `crew_run` | Start a non-blocking crew job (returns `job_id`) |
| `crew_job_status` | Poll job status with delta tracking (only returns changes) |
| `crew_cancel` | Cancel a running job |
| `crew_verify` | Run a verification command (pytest, ruff, etc.) |
| `crew_accept` | Accept and finalize crew results |

## CLI Commands

```
orchestrator crew run       # Start a crew with supervision loop
orchestrator crew status    # Show crew status
orchestrator crew accept    # Accept crew results
orchestrator crew stop      # Stop all workers
orchestrator crew verify    # Run verification
orchestrator doctor         # Check prerequisites
```

## How It Works

1. **Dispatch** — `crew_run` spawns workers in tmux panes with role-specific prompts
2. **Execute** — Workers operate in isolated git worktrees, writing code within their assigned scope
3. **Review** — Reviewer reads changes, runs tests, emits a verdict (pass/challenge/replan)
4. **Challenge** — If issues found, specific workers get targeted fix instructions
5. **Verify** — Verification commands (pytest, ruff, etc.) run against the merged result
6. **Accept** — On success, worktrees merge into the main branch

Every step is recorded as an immutable event in the SQLite event store. You can replay the full history with `crew_state_projection`.

## Project Structure

```
src/codex_claude_orchestrator/
├── core/              # Domain models, safety policy gate
├── crew/              # CrewController, worker contracts, merge arbitration
├── v4/                # Event-sourced runtime (primary)
│   ├── event_store.py # SQLite event store
│   ├── crew_runner.py # Main orchestration loop
│   ├── supervisor.py  # V4 supervisor facade
│   ├── parallel_supervisor.py    # Parallel subtask execution
│   ├── long_task_supervisor.py   # Multi-stage long task execution
│   └── adapters/      # tmux Claude adapter
├── mcp_server/        # MCP server (FastMCP, stdio transport)
├── runtime/           # tmux session management
├── workspace/         # Git worktree management
├── messaging/         # Worker-to-worker communication
└── state/             # Blackboard, recorders

skills/
└── orchestration-default.md  # Orchestration protocol (editable)
```

## Configuration

The orchestration protocol is defined in `skills/orchestration-default.md`. Key settings:

- **Worker templates** — `targeted-code-editor`, `repo-context-scout`, `patch-risk-auditor`, etc.
- **Max rounds** — Challenge/repair iterations before escalation (default: 3)
- **Poll interval** — How often to check worker status (adaptive: 5s → 60s)
- **Write scope** — File paths each worker is allowed to modify

Environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `V4_EVENT_STORE_BACKEND` | `sqlite` | Event store backend (`sqlite` or `postgres`) |

## Testing

```bash
# Run all tests
pytest

# Run specific module tests
pytest tests/v4/ -v
pytest tests/mcp_server/ -v

# Run with coverage
pytest --cov=codex_claude_orchestrator
```

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feat/my-feature`)
3. Write tests first (TDD)
4. Implement the feature
5. Run tests (`pytest`)
6. Commit with conventional commits (`feat:`, `fix:`, `test:`, `docs:`)
7. Open a Pull Request

## License

MIT
