# Adversarial Code Review Plugin for Claude Code

Multi-agent adversarial code review. One agent implements, another actively tries to break it.

## Installation

```bash
claude plugin install adversarial-code-review
```

Or manually:
1. Clone this repository
2. Copy `plugin/adversarial-code-review/` to `~/.claude/plugins/adversarial-code-review/`

## What You Get

- `/adversarial-review` skill for code review
- MCP tools for multi-agent orchestration
- Worker templates for common roles
- Supervisor mode for direct control

## Quick Start

After installation, use in Claude Code:

```
# Simple review
crew_run(repo="/path/to/project", goal="Add user authentication")

# Supervisor mode (direct control)
crew_run(repo="/path/to/project", goal="Add user auth", supervisor_mode=True)
```

## Features

- **Adversarial Verification** — Reviewer actively attacks code
- **Worker Templates** — Predefined roles for common tasks
- **Supervisor Mode** — Direct control over workers
- **Structured Output** — Compressed, actionable feedback
- **Delta Polling** — Minimal context usage

## License

MIT
