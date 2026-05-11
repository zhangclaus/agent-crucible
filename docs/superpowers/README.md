# Design Docs

本目录保留 codex-claude-orchestrator 的设计演进历史。

## 项目文档

完整项目文档见 `docs/项目完整文档.md`，包含架构、模块实现、MCP Server、CLI 命令等全部内容。

## 当前核心架构

### V4 事件溯源运行时

系统已演进到 V4 架构，核心设计：

| 主题 | Spec | Plan |
|------|------|------|
| V4 事件原生基础设施 | `specs/2026-05-02-v4-event-native-agent-filesystem-design.md` | `plans/2026-05-02-v4-event-native-foundation.md` |
| V4 对抗性治理学习 | - | `plans/2026-05-02-v4-adversarial-governed-learning.md` |
| Worker 生命周期统一 | `specs/2026-05-03-worker-lifecycle-unification-design.md` | `plans/2026-05-03-worker-lifecycle-unification.md` |
| Accept Readiness + Worker Safety | `specs/2026-05-03-v4-accept-readiness-worker-safety-design.md` | `plans/2026-05-03-v4-accept-readiness-worker-safety.md` |

### MCP Server

| 主题 | Spec | Plan |
|------|------|------|
| MCP Server 驱动的 Supervisor | `specs/2026-05-05-mcp-server-driven-supervisor-design.md` | `plans/2026-05-05-mcp-server-driven-supervisor.md` |
| LLM Supervisor + MCP | `specs/2026-05-05-llm-supervisor-mcp-design.md` | `plans/2026-05-05-llm-supervisor-mcp-server.md` |
| MCP 模式完整运行时流程 | `specs/2026-05-06-mcp-mode-complete-runtime-flow.md` | - |

### Long Task 多阶段执行

系统核心特性——将单阶段对抗性验证扩展为多阶段、并行 Worker 的长任务执行运行时：

| 主题 | Spec | Plan |
|------|------|------|
| Long Task 对抗性 Agent | `specs/2026-05-09-long-task-adversarial-agent.md` | `plans/2026-05-11-long-task-adversarial-agent.md` |
| LongTaskSupervisor Stub 修复 | `specs/2026-05-11-fix-long-task-stubs-design.md` | `plans/2026-05-11-fix-long-task-stubs.md` |

### 对抗性验证

| 主题 | Spec | Plan |
|------|------|------|
| Supervisor 对抗性验证 | `specs/2026-05-07-supervisor-adversarial-verify-design.md` | `plans/2026-05-07-supervisor-adversarial-verify.md` |
| 对抗性摘要 Worker | `specs/2026-05-06-adversarial-summarizer-worker-design.md` | `plans/2026-05-06-adversarial-summarizer-worker.md` |
| 并行 Supervisor | `specs/2026-05-07-parallel-supervisor-design.md` | `plans/2026-05-07-parallel-supervisor.md` |

### Bug 修复与加固

| 主题 | Spec | Plan |
|------|------|------|
| Cancel 与清理 Bug 修复 | `specs/2026-05-06-bugfix-cancel-and-cleanup-design.md` | `plans/2026-05-06-bugfix-cancel-and-cleanup.md` |
| Marker Poll Waiting | `specs/2026-05-06-marker-poll-waiting-design.md` | `plans/2026-05-06-marker-poll-waiting.md` |
| Core Path 审计 + 修复 | `specs/2026-05-07-core-path-audit.md` | `plans/2026-05-07-core-path-batch1-fix.md` |
| 审计 Bug 修复加固 | `specs/2026-05-07-audit-bugfix-hardening-design.md` | `plans/2026-05-07-audit-bugfix-hardening.md` |
| 聚焦与简化 | `specs/2026-05-09-focus-and-simplify.md` | `plans/2026-05-09-focus-and-simplify.md` |
| 并行 Supervisor Bug 修复 | - | `plans/2026-05-07-parallel-supervisor-bugfix.md` |

### 当前架构审计

| 文档 |
|------|
| `specs/2026-05-02-current-system-architecture.zh.md` — 当前系统架构全景 |
| `specs/2026-05-02-v4-current-implemented-architecture.zh.md` — V4 已实现架构 |
| `specs/2026-05-07-core-path-audit.md` — 核心路径审计 |
| `specs/2026-05-09-focus-and-simplify.md` — 聚焦与简化方向 |

## 历史文档

早期文件保留在原位，因为之前的讨论和实现笔记引用了它们的精确路径。将它们视为设计历史，除非当前文档明确引用。

主要历史脉络：
- **V1/V2 会话引擎**: `specs/2026-04-29-adversarial-codex-agent-session-design.md`
- **V3 Crew 编排**: `specs/2026-04-29-codex-managed-claude-crew-v3-design.zh.md`
- **桥接与长对话**: `specs/2026-04-29-claude-bridge-long-dialogue-design.md`
- **终端与运行时**: `specs/2026-04-29-tmux-terminal-console-design.md`
- **Agent 框架调研**: `specs/diaoyan/agent-framework-research.zh.md`

## 目录规则

- **Spec** (`specs/`): 架构规格文档，描述"是什么"和"为什么"，不包含实现代码
- **Plan** (`plans/`): 实现计划，描述"怎么做"，包含具体的代码变更和步骤
- 命名格式: `YYYY-MM-DD-<简短主题>.md`（spec 加 `-design` 后缀）
- 中文文档加 `.zh` 后缀
