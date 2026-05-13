# Agent Crucible Plugin for Claude Code

Multi-agent adversarial orchestration for software engineering tasks. Workers implement, reviewers attack, verification loops until it's solid.

## Installation

```bash
claude plugin install agent-crucible
```

Or manually:
1. Clone this repository
2. Copy `plugin/agent-crucible/` to `~/.claude/plugins/agent-crucible/`

## What You Get

- `/agent-crucible` skill for adversarial code review
- MCP tools for multi-agent orchestration
- Worker templates for common roles
- Automatic terminal attach — watch workers in real time

## Quick Start

After installation, use in Claude Code:

```
# Simple review — returns job_id, polls in background
crew_run(repo="/path/to/project", goal="Add user authentication")

# With verification
crew_run(repo="/path/to/project", goal="Add auth", verification_commands=["pytest"])

# Parallel workers for complex tasks
crew_run(repo="/path/to/project", goal="Refactor auth module", parallel=True, max_workers=3)
```

## Features

- **Adversarial Verification** — Reviewer actively attacks code
- **Parallel Workers** — Multiple workers in isolated worktrees
- **Terminal Auto-Attach** — Worker sessions open in Terminal.app automatically
- **Structured Output** — Compressed, actionable feedback
- **Delta Polling** — Minimal context usage for status checks

## License

MIT
