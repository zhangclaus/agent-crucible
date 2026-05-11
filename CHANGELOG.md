# Changelog

## 0.1.0 (2026-05-11)

Initial release.

### Features

- Multi-agent crew orchestration with role-based workers (explorer, implementer, reviewer)
- Adversarial verification loop with challenge/repair cycle
- Event-sourced runtime with SQLite event store and CQRS projections
- Git worktree isolation for concurrent worker execution
- Blackboard pattern for inter-worker communication
- Safety policy gate (blocks destructive commands, shell injection, sensitive path access)
- MCP server with 5 core tools: `crew_run`, `crew_job_status`, `crew_cancel`, `crew_verify`, `crew_accept`
- Non-blocking job system with delta-status polling and adaptive intervals
- Parallel subtask execution with two-layer adversarial review
- Long task supervisor for multi-stage execution with dynamic planning
- CLI interface (`orchestrator` command)
- Worker-to-worker messaging via `AgentMessageBus`
