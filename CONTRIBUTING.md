# Contributing

Thanks for your interest in contributing! Here's how to get started.

## Setup

```bash
git clone https://github.com/zhangzhang123/codex-claude-orchestrator.git
cd codex-claude-orchestrator
pip install -e ".[dev]"
```

## Development Workflow

1. Fork the repo and create a branch from `main`
2. Make your changes
3. Write tests for new functionality
4. Run tests: `pytest`
5. Commit with [conventional commits](https://www.conventionalcommits.org/) format
6. Open a Pull Request

## Commit Convention

- `feat:` — new feature
- `fix:` — bug fix
- `test:` — adding or updating tests
- `docs:` — documentation changes
- `refactor:` — code restructuring without behavior change
- `chore:` — tooling, CI, dependencies

## Code Style

- Python 3.11+ (we use `StrEnum`, `slots=True`, `match` statements)
- Type hints on all public functions
- Docstrings on classes and public methods
- Keep functions focused — if a function does two things, split it

## Testing

- Write tests for all new code
- Run `pytest` before submitting
- Tests should be deterministic — no real network calls, no real tmux sessions
- Use fixtures and mocks for external dependencies

## Pull Requests

- Keep PRs focused on one change
- Include a description of what changed and why
- Reference related issues if applicable
- Ensure all tests pass

## Reporting Issues

- Use GitHub Issues
- Include steps to reproduce
- Include Python version and OS
- Include relevant logs or error messages
