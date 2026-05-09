# Channel 聚焦精简设计

## 目标

将 channel 从"通用多 Agent 编排框架"聚焦为"对抗验证 + 长任务执行运行时"。用户接口极简：一个 `/run` Skill 入口，底层保留核心竞争力（tmux 隔离、worktree、对抗验证、PolicyGate）。

## 核心用户流

```
用户: /run 重构 auth 模块，确保 pytest 通过
系统: 任务已启动 (job-abc123)，后台执行中...
      [用户继续做别的事]
系统: ✅ 任务完成，所有测试通过。已自动 accept。
```

一个入口，全自动：tmux 隔离 → 写代码 → 对抗审查 → 验证 → 失败重试 → 完成通知。

---

## 线 1：Skill 入口

### /run Skill

**文件:** `~/.claude/skills/run.md`（或项目内 `.claude/skills/run.md`）

**行为:**
1. 解析用户输入：goal + verification commands
2. 调用 `crew_run` MCP 工具（repo=当前目录, goal, verification_commands）
3. 启动后台 Agent（`Agent tool, run_in_background=true`）
4. 后台 Agent 轮询 `crew_job_status`，按返回的 `poll_after_seconds` 等待
5. 终态时调用 `crew_accept`（如果 status=done）
6. 向用户报告最终结果

**不需要:** `/verify`（对抗验证已内置）、`/status`（后台 Agent 自动轮询）

### MCP 工具精简

当前 15 个工具 → 保留 5 个核心工具：

| 保留 | 用途 |
|------|------|
| `crew_run` | 启动任务（后台执行） |
| `crew_job_status` | 轮询状态（delta 模式） |
| `crew_accept` | 接受结果 |
| `crew_cancel` | 取消任务 |
| `crew_verify` | 手动触发验证命令（调试用） |

**删除的工具:**
- `crew_start` / `crew_stop` → 被 `crew_run` / `crew_cancel` 替代
- `crew_spawn` / `crew_stop_worker` → 内部实现细节，用户不需要
- `crew_observe` / `crew_changes` / `crew_diff` → 合并到 `crew_job_status` 的详情字段
- `crew_blackboard` / `crew_events` → 内部实现细节
- `crew_challenge` → 对抗验证自动处理，用户不需要手动 challenge
- `crew_status` → 被 `crew_job_status` 替代

---

## 线 2：代码精简

### 原则

**只砍没用的，不动能用的。** EventStore（SQLite）、双写模式、CrewStateProjection 都能用且有审计价值，不做改动。

### Phase 1 — 砍掉没用的模块

| 删除 | 代码量 | 理由 |
|------|--------|------|
| `v4/postgres_event_store.py` | 471 行 | 本地工具不需要两个事件存储后端 |
| `v4/learning.py` + `learning_projection.py` + `learning_feedback.py` | 801 行 | 学习系统没有证据它有效，增加复杂度 |
| `crew/supervisor_loop.py` | 901 行 | 遗留 supervisor，已被 V4 crew_runner 替代 |
| `v4/reconciler.py` | 30 行 | stub，无实现 |

**不动的：**
- `v4/event_store.py`（SQLite）— 保留，有审计和调试价值
- `v4/domain_events.py` — 保留，EventStore 的配套
- `v4/crew_state_projection.py` — 保留，从事件流读状态
- 双写模式 — 能用，不重构

**Phase 1 合计:** ~2,200 行删除

### Phase 2 — 精简 MCP 工具

| 删除 | 代码量 | 理由 |
|------|--------|------|
| `crew_lifecycle.py` 中的 start/stop/spawn/stop_worker | ~150 行 | 被 crew_run 替代 |
| `crew_context.py` 全部 | 132 行 | 合并到 crew_job_status |
| `crew_decision.py` 中的 challenge | ~20 行 | 自动处理 |

**保留:**
- `crew_run.py`（crew_run, crew_job_status, crew_cancel）
- `crew_decision.py` 中的 crew_accept
- `crew_lifecycle.py` 中的 crew_verify

**Phase 2 合计:** ~300 行删除

### Phase 3 — 精简 CLI

**保留的子命令:**
```
orchestrator crew run       # 启动任务
orchestrator crew status    # 查看状态
orchestrator crew accept    # 接受结果
orchestrator crew stop      # 停止
orchestrator doctor         # 检查依赖
```

**删除:**
- V2 session 命令（`session start`, `sessions list/show`）
- bridge 命令（`claude open/bridge`）
- term 命令（`term session`）
- skills 命令（`skills list/show/approve/reject`）
- ui 命令（`ui`）
- 大部分 crew 子命令（blackboard, events, inbox, protocols, decisions, snapshot, contracts, messages, merge-plan, supervise, prune, resume-context, capabilities, worker send/observe/attach/tail）

**Phase 3 合计:** ~800 行删除

### 精简总计

| Phase | 删除量 | 风险 |
|-------|--------|------|
| Phase 1 | ~2,200 行 | 低 |
| Phase 2 | ~300 行 | 低 |
| Phase 3 | ~800 行 | 低 |
| **合计** | **~3,300 行** | |

从 ~20,000 行减到 ~16,700 行（-17%）。只砍没用的，核心路径完全不动。

---

## 保留的核心竞争力

| 能力 | 代码位置 | 为什么保留 |
|------|----------|-----------|
| tmux 进程隔离 | `v4/adapters/tmux_claude.py` | 后台执行 + 崩溃隔离 |
| worktree 隔离 | `workspace/worktree_manager.py` | 并发修改不冲突 |
| 对抗验证循环 | `v4/crew_runner.py` + `v4/supervisor.py` | 核心价值：自动审查 |
| PolicyGate | `v4/gates.py` | 强制安全策略 |
| EventStore（SQLite） | `v4/event_store.py` | 审计日志 + 崩溃恢复 |
| MCP Server | `mcp_server/` | 通用接口 |
| 后台任务管理 | `mcp_server/job_manager.py` | 非阻塞执行 |

---

## 不做的事情

- **不重写任何模块** — 只删除，不重构
- **不改变核心循环** — source → review → verify → challenge 保持不变
- **不碰 EventStore** — SQLite 事件存储保留原样
- **不碰双写模式** — 能用就不动
- **不添加新功能** — 聚焦是做减法

---

## 验证标准

1. `/run` Skill 能端到端工作：输入 goal → 后台执行 → 完成通知
2. 精简后所有保留测试通过
3. MCP Server 启动正常，5 个核心工具可用
4. 现有 crew_run 流程不受影响
