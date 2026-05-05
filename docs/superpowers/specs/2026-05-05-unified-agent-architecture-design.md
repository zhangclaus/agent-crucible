# Unified Agent Architecture Design

> Date: 2026-05-05 | Status: Draft

## 1. Problem

The current architecture treats the supervisor as a special framework component (`CrewSupervisorLoop`), separate from workers. This creates:

1. **Unnecessary indirection**: MCP `crew_run` uses sampling to round-trip decisions through the MCP client
2. **Fragile coupling**: Supervisor is tied to the MCP client (Codex) via `ctx.session.create_message()`
3. **Inflexibility**: Changing orchestration rules requires modifying Python code
4. **Inconsistency**: Supervisor and workers are both agent processes (Claude CLI in tmux), but the framework treats them differently

## 2. Core Insight

From the OpenAI Agents SDK: **there is no supervisor class**. A "supervisor" is just an agent whose instructions tell it to orchestrate. The framework provides `Agent` (dataclass) + `Runner` (loop) + `Handoff` (tool-based delegation). Orchestration is an application-level pattern.

In our system:
- Agent = Claude CLI process in tmux
- Instructions = mission prompt
- Tools = MCP tools (via MCP Server)
- Communication = filesystem (blackboard JSONL + completion markers)

The supervisor doesn't need to be a framework primitive. It's just another agent.

## 3. Architecture

```
Human
  │
  │ spawns supervisor with mission + orchestration skill
  ▼
┌──────────────────────────────────────────────────────────────┐
│  Supervisor Agent (Claude CLI in tmux)                        │
│                                                              │
│  Mission = task goal + orchestration skill content            │
│  MCP tools = crew_spawn, crew_blackboard, crew_observe, ...  │
│                                                              │
│  Loop: read blackboard → decide → call MCP tool → repeat     │
└──────────────────────┬───────────────────────────────────────┘
                       │ MCP protocol (stdio)
                       ▼
┌──────────────────────────────────────────────────────────────┐
│  MCP Server (Python) — pure infrastructure                    │
│                                                              │
│  crew_spawn(label, mission, ...)    → create tmux process    │
│  crew_stop(worker_id)               → kill process           │
│  crew_status()                      → read state             │
│  crew_blackboard(crew_id, ...)      → read/write blackboard  │
│  crew_events(crew_id, ...)          → read event log         │
│  crew_observe(worker_id)            → read tmux output       │
│  crew_verify(crew_id, commands)     → run verification       │
│  crew_accept(crew_id)               → finalize + merge       │
│  crew_challenge(worker_id, goal)    → send challenge         │
│                                                              │
│  NO crew_run, NO sampling, NO supervision loop               │
└──────────────────────┬───────────────────────────────────────┘
                       │
              ┌────────┼────────┐
              ▼        ▼        ▼
         Worker 1  Worker 2  Worker 3
        (Claude CLI in tmux, filesystem communication)
```

### 3.1 What changes vs current

| Component | Current | New |
|-----------|---------|-----|
| `CrewSupervisorLoop` | Core supervisor class | **Delete** |
| `crew_run` MCP tool | Long-running + sampling | **Delete** |
| `crew_decide` MCP tool | Decision recording | **Delete** |
| `crew_spawn` (old, in `crew_decision.py`) | Spawn via decision tool | **Replace** with new `crew_spawn` (in `crew_lifecycle.py`) |
| `loop_step_result.py` | Step result dataclass | **Delete** |
| MCP `crew_spawn` | N/A | **New**: spawn agent via WorkerPool |
| Orchestration skill | N/A | **New**: prompt file for supervisor |
| Supervisor agent | Built into MCP Server | **New**: independent tmux process |

### 3.2 What stays the same

- Worker spawning mechanism (`WorkerPool`, `NativeClaudeSession`, tmux)
- Blackboard (`BlackboardStore`, JSONL format)
- Message bus (`MessageBus`, `<<<CODEX_MESSAGE>>>` blocks)
- Completion markers (`<<<CODEX_TURN_DONE>>>`)
- Verification (`CrewVerificationRunner`)
- Change recording (`WorkerChangeRecorder`)
- Merge (`MergeArbiter`)
- V4 event store (`EventStore`, `CrewProjection`)
- Context tools (`crew_blackboard`, `crew_events`, `crew_observe`, `crew_changes`, `crew_diff`)
- Lifecycle tools (`crew_start`, `crew_stop`, `crew_status`)

## 4. MCP Server Tools

### 4.1 Final tool inventory

| Tool | Source | Description |
|------|--------|-------------|
| `crew_start` | Keep | Start a crew (creates crew record) |
| `crew_stop` | Keep | Stop crew and all workers |
| `crew_status` | Keep | Get compressed crew status |
| `crew_spawn` | **New** | Spawn a worker agent |
| `crew_stop_worker` | **New** | Stop a specific worker |
| `crew_observe` | Keep | Read worker's tmux output |
| `crew_blackboard` | Keep | Read/write blackboard entries |
| `crew_events` | Keep | Read event log |
| `crew_changes` | Keep | View changed files |
| `crew_diff` | Keep | View diff |
| `crew_verify` | Keep | Run verification commands |
| `crew_accept` | Keep | Accept results, trigger merge |
| `crew_challenge` | Keep | Challenge a worker |

### 4.2 `crew_spawn` implementation

```python
@server.tool("crew_spawn")
async def crew_spawn(
    crew_id: str,
    label: str,
    mission: str,
    required_capabilities: list[str] | None = None,
    authority_level: str = "source_write",
    workspace_policy: str = "worktree",
) -> list[TextContent]:
    """Spawn a worker agent in tmux."""
    contract = WorkerContract(
        contract_id=f"contract-{label}",
        label=label,
        mission=mission,
        required_capabilities=required_capabilities or ["inspect_code", "edit_source"],
        authority_level=AuthorityLevel(authority_level),
        workspace_policy=WorkspacePolicy(workspace_policy),
    )
    result = controller.ensure_worker(crew_id=crew_id, contract=contract)
    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]
```

### 4.3 `crew_stop_worker` implementation

```python
@server.tool("crew_stop_worker")
async def crew_stop_worker(worker_id: str) -> list[TextContent]:
    """Stop a specific worker."""
    result = controller.stop_worker(worker_id=worker_id)
    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]
```

### 4.4 Deleted tools

| Tool | Reason |
|------|--------|
| `crew_run` | Supervisor runs the loop itself via MCP tools |
| `crew_decide` | Decisions are made by supervisor agent, not recorded by tool |
| `crew_spawn` (old, `crew_decision.py`) | Replaced by new `crew_spawn` (`crew_lifecycle.py`) with different interface |

## 5. Orchestration Skill

### 5.1 What it is

A markdown file (`skills/orchestration.md`) that gets included in the supervisor agent's mission prompt. It defines the orchestration protocol — when to spawn, observe, challenge, verify, accept.

### 5.2 Skill content

```markdown
# Crew Orchestration Protocol

You are a crew supervisor. Your job is to coordinate worker agents to complete a task.

## Tools Available

- `crew_spawn(crew_id, label, mission)` — spawn a worker
- `crew_observe(worker_id)` — read worker output
- `crew_blackboard(crew_id)` — read shared blackboard
- `crew_verify(crew_id, commands)` — run verification
- `crew_accept(crew_id)` — accept results
- `crew_challenge(worker_id, goal)` — challenge a worker
- `crew_stop_worker(worker_id)` — stop a worker

## Orchestration Loop

1. **Understand the task**. Read the goal from your mission.
2. **Spawn initial workers**. Typically:
   - `targeted-code-editor` — implement changes
   - `repo-context-scout` — gather context (if task is complex)
3. **Monitor progress**. Use `crew_observe` and `crew_blackboard` to track worker output.
4. **When workers complete**:
   - Read their results from the blackboard
   - Run `crew_verify` with appropriate commands (e.g., `pytest`, `ruff check`)
5. **If verification passes**:
   - Use `crew_accept` to finalize
6. **If verification fails**:
   - First failure: `crew_challenge(worker_id, goal="fix the failing tests")`
   - Second failure: spawn `verification-failure-analyst` to diagnose
   - Third failure: spawn `guardrail-maintainer` or escalate to human
7. **If workers are stuck**: spawn additional workers or change strategy

## Decision Guidelines

- Prefer challenging existing workers over spawning new ones (cheaper)
- Spawn `patch-risk-auditor` before accepting if files changed outside scope
- Use `crew_observe` liberally — don't guess, read actual output
- Keep missions specific and actionable
- If unsure, observe more before acting
```

### 5.3 Customization

Different orchestration strategies = different skill files:

| Skill | Use case |
|-------|----------|
| `orchestration-default.md` | General-purpose development |
| `orchestration-review-heavy.md` | Extra review steps for critical code |
| `orchestration-fast.md` | Minimal oversight, trust workers |
| `orchestration-learning.md` | Records challenges/skills for feedback loop |

The supervisor's mission prompt = task goal + skill content. Example:

```
Your task: Add input validation to the user registration API.

[orchestration skill content here]
```

## 6. Supervisor Agent

### 6.1 How it's spawned

The supervisor is a tmux process, just like a worker. The human (or a higher-level system) spawns it:

```bash
# In tmux:
claude --mcp-config mcp.json \
  --system-prompt "You are a crew supervisor." \
  --prompt "Task: Add input validation to user registration API.

[orchestration skill content]"
```

Or via the CLI:

```bash
orchestrator crew supervisor \
  --task "Add input validation" \
  --skill orchestration-default \
  --crew-id crew-abc123
```

### 6.2 MCP Server connection

The supervisor needs MCP tools. It connects to the MCP Server via stdio:

```json
// mcp.json
{
  "mcpServers": {
    "crew": {
      "command": "python",
      "args": ["-m", "codex_claude_orchestrator.mcp_server"],
      "env": {
        "CREW_REPO": "/path/to/repo",
        "CREW_ID": "crew-abc123"
      }
    }
  }
}
```

### 6.3 Supervisor vs Worker

| | Supervisor | Worker |
|--|-----------|--------|
| Process | Claude CLI in tmux | Claude CLI in tmux |
| Mission | Task goal + orchestration skill | Specific implementation task |
| MCP tools | All crew tools | None (writes to blackboard directly) |
| Communication | Reads blackboard, calls MCP tools | Writes to blackboard, prints markers |
| Lifecycle | Spawned by human | Spawned by supervisor via `crew_spawn` |

## 7. Worker Communication (Unchanged)

Workers communicate through the filesystem:

### 7.1 Blackboard writes

Workers append structured entries to the blackboard JSONL file:

```json
{"type": "CLAIM", "content": "Implemented input validation in routes/auth.py", "confidence": 0.9}
{"type": "FACT", "content": "Found missing email format check in registration endpoint", "confidence": 1.0}
```

### 7.2 Completion markers

Workers signal turn completion by printing:

```
<<<CODEX_TURN_DONE crew=crew-abc123 worker=worker-editor-a1b2 phase=source round=1>>>
```

### 7.3 Messages

Workers can send structured messages to other agents:

```
<<<CODEX_MESSAGE to=supervisor type=QUESTION>
Should I also validate phone numbers?
<<<END_CODEX_MESSAGE>>>
```

The supervisor reads these via `crew_observe` (tmux output) or `crew_blackboard` (parsed entries).

## 8. Worker Templates

Predefined worker contracts for common roles, used by the orchestration skill:

```python
WORKER_TEMPLATES = {
    "targeted-code-editor": WorkerContract(
        label="targeted-code-editor",
        mission="Implement the requested changes in the source code.",
        required_capabilities=["inspect_code", "edit_source"],
        authority_level=AuthorityLevel.SOURCE_WRITE,
        workspace_policy=WorkspacePolicy.WORKTREE,
    ),
    "repo-context-scout": WorkerContract(
        label="repo-context-scout",
        mission="Explore the codebase and report findings on the blackboard.",
        required_capabilities=["inspect_code"],
        authority_level=AuthorityLevel.READONLY,
        workspace_policy=WorkspacePolicy.READONLY,
    ),
    "patch-risk-auditor": WorkerContract(
        label="patch-risk-auditor",
        mission="Review the changed files for risks and quality issues.",
        required_capabilities=["inspect_code"],
        authority_level=AuthorityLevel.READONLY,
        workspace_policy=WorkspacePolicy.READONLY,
    ),
    "verification-failure-analyst": WorkerContract(
        label="verification-failure-analyst",
        mission="Analyze verification failures and propose fixes.",
        required_capabilities=["inspect_code", "edit_source"],
        authority_level=AuthorityLevel.SOURCE_WRITE,
        workspace_policy=WorkspacePolicy.WORKTREE,
    ),
}
```

The orchestration skill references these by name. `crew_spawn` can accept a template name instead of full contract parameters:

```python
@server.tool("crew_spawn")
async def crew_spawn(
    crew_id: str,
    label: str,          # "targeted-code-editor" or custom
    mission: str = "",   # overrides template mission if provided
    ...
) -> list[TextContent]:
    template = WORKER_TEMPLATES.get(label)
    if template:
        contract = replace(template, mission=mission or template.mission)
    else:
        contract = WorkerContract(label=label, mission=mission, ...)
    ...
```

## 9. What Gets Deleted

| File/Component | Reason |
|----------------|--------|
| `crew/supervisor_loop.py` — `run()` method | Replaced by supervisor agent + skill |
| `crew/supervisor_loop.py` — `_ask_supervisor()` | No sampling |
| `crew/supervisor_loop.py` — `_parse_decision()` | Supervisor makes decisions itself |
| `crew/supervisor_loop.py` — `_execute_decision()` | Supervisor calls MCP tools directly |
| `crew/supervisor_loop.py` — `_wait_for_workers()` | Supervisor uses `crew_observe` |
| `crew/supervisor_loop.py` — `_build_decision_prompt()` | Skill handles this |
| `mcp_server/tools/crew_execution.py` | `crew_run` deleted |
| `mcp_server/tools/crew_decision.py` | `crew_decide` deleted |
| `crew/loop_step_result.py` | No longer needed |
| `mcp_server/__main__.py` — `CrewSupervisorLoop` wiring | No supervision loop |

### 9.1 What stays in supervisor_loop.py

The file contains other methods that are still useful:

- `supervise()` — static mode, called by CLI `crew supervise`
- `supervise_dynamic()` — dynamic mode, called by CLI `crew run --legacy-loop`
- `_wait_for_marker()` — used by the above
- `_auto_verify()` — could be extracted to a utility
- `_auto_challenge()` — could be extracted to a utility

These legacy CLI paths remain functional. The MCP Server no longer uses `CrewSupervisorLoop`.

## 10. Data Flow

### 10.1 MCP mode (new)

```
Human
  │ spawns supervisor (claude --mcp-config mcp.json --prompt "task + skill")
  ▼
Supervisor (Claude CLI)
  │ reads mission, follows skill
  │ calls crew_spawn("targeted-code-editor", "implement changes")
  ▼
MCP Server
  │ WorkerPool.ensure_worker() → NativeClaudeSession.start()
  ▼
Worker (Claude CLI in tmux)
  │ reads mission, implements changes
  │ writes to blackboard: {"type": "CLAIM", "content": "done"}
  │ prints: <<<CODEX_TURN_DONE ...>>>
  ▼
Supervisor (Claude CLI)
  │ calls crew_observe("worker-editor-xxx") → sees marker
  │ calls crew_blackboard("crew-abc") → reads worker results
  │ calls crew_verify("crew-abc", ["pytest"]) → runs tests
  │ tests pass → calls crew_accept("crew-abc")
  ▼
MCP Server
  │ controller.accept() → MergeArbiter → finalize
  ▼
Done
```

### 10.2 CLI mode (unchanged)

```
orchestrator crew run --task "..." --legacy-loop
  → CrewSupervisorLoop.supervise_dynamic()
  → same as before
```

## 11. Testing Strategy

| Layer | What to test |
|-------|-------------|
| `crew_spawn` tool | Mock WorkerPool, verify contract creation and delegation |
| `crew_stop_worker` tool | Mock controller, verify stop delegation |
| Orchestration skill | Integration test: spawn supervisor with skill + mock task, verify it spawns workers and follows protocol |
| Tool registration | Verify all tools registered, deleted tools absent |
| Blackboard writes | Verify workers can write structured entries |
| Existing tests | All existing tests for kept tools continue to pass |

## 12. Migration Path

1. Add `crew_spawn` and `crew_stop_worker` tools to MCP Server
2. Add worker templates
3. Create orchestration skill file
4. Remove `CrewSupervisorLoop` from MCP Server (`__main__.py`)
5. Remove `crew_run` tool and `crew_execution.py`
6. Remove `crew_decide` tool
7. Remove `loop_step_result.py`
8. Update tests
9. Update CLI to support spawning supervisor agents
10. Update documentation

## 13. Future Extensions

- **Multiple orchestration skills**: Different strategies for different task types
- **Supervisor-as-worker**: A supervisor can be spawned by another supervisor (hierarchical)
- **Agent handoff**: Like OpenAI's handoffs — supervisor transfers control to a specialist agent
- **Streaming**: Supervisor can stream its reasoning to the human via MCP notifications
- **Session persistence**: Resume a supervisor from blackboard state after crash
