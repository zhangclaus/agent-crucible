# Claude Bridge Long Dialogue Design

## Goal

Let Codex keep directing the same Claude Code conversation from inside the Codex App.

## Approach

Add `orchestrator claude bridge`, a command-oriented bridge that stores local bridge state under `.orchestrator/claude-bridge/`. It does not run a daemon. Each Codex instruction invokes one CLI command, and the bridge resumes the stored Claude Code session with `claude --print ... --resume <session_id>`.

The human-facing path is a visible bridge, not a raw Claude terminal. `start --visual terminal` opens a Terminal watcher that refreshes bridge records and turn output, while Codex keeps control of all `send` calls.

## Commands

```bash
orchestrator claude bridge start --repo /path/to/repo --goal "..." --visual terminal
orchestrator claude bridge send --repo /path/to/repo --message "继续检查"
orchestrator claude bridge tail --repo /path/to/repo --limit 5
orchestrator claude bridge list --repo /path/to/repo
```

`start` creates a bridge id and marks it as the latest bridge for the repo. With `--visual terminal`, it writes `watch.zsh` and opens Terminal before the initial Claude turn starts, so the user can see a watcher immediately while Claude is still running. The initial Claude result stores Claude's `session_id`. `send` defaults to that latest bridge, resumes the Claude session, and records the turn. `tail` and `list` are read-only inspection commands.

## Data Model

Each bridge gets:

- `record.json`: bridge id, repo, goal, workspace mode, status, Claude session id, timestamps, and turn count.
- `turns.jsonl`: every user message, command, return code, stdout/stderr, parsed result text, and Claude session id.
- `watch.zsh`: optional Terminal watcher script for `--visual terminal`.
- `latest`: a repo-local pointer to the default bridge.

## Safety

`readonly` mode passes `--allowedTools Read,Glob,Grep,LS` and prompts Claude not to modify files. `shared` mode keeps Claude's normal permissions and asks it to preserve unrelated user work. The bridge never bypasses Claude permissions.

If a requested Terminal watcher cannot be opened, `start --visual terminal` fails before launching Claude. This avoids the misleading state where Claude is running but no visual window exists.

## Non-Goals

This version does not implement a background daemon, browser streaming UI, or true isolated worktree allocation. Those can build on the stored bridge session once the visible resume flow is reliable.
