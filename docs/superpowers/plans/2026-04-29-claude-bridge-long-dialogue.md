# Claude Bridge Long Dialogue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a recoverable Claude Code bridge so Codex can keep sending follow-up instructions into one Claude conversation.

**Architecture:** Add a focused `claude_bridge.py` module for command construction, Claude JSON parsing, bridge records, turn logs, and optional Terminal watcher scripts. Wire `claude bridge start/send/tail/list` into the existing argparse CLI while leaving `claude open` as a compatibility path and making `bridge start --visual terminal` the recommended visible workflow.

**Tech Stack:** Python stdlib, Claude CLI `--print` / `--resume`, JSONL persistence, pytest.

---

## Tasks

- [x] Write failing bridge core tests for `start`, `send`, latest bridge resolution, and missing session protection.
- [x] Write failing CLI tests for `claude bridge start/send/tail/list`.
- [x] Implement `ClaudeBridge` storage, parsing, and command execution.
- [x] Wire bridge commands into `cli.py`.
- [x] Add `bridge start --visual terminal` watcher window support.
- [x] Launch the visual watcher before the first Claude turn blocks.
- [x] Fail fast if the Terminal watcher cannot be opened.
- [x] Run targeted tests.
- [x] Run the full pytest suite.
- [x] Commit docs, implementation, and tests.
