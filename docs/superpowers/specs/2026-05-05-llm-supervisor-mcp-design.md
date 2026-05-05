# LLM Supervisor MCP Server 设计

> 日期: 2026-05-05 | 状态: 已实现

## 1. 问题陈述

当前系统的 supervisor 是纯 Python 规则引擎 (`CrewDecisionPolicy`)，只能处理 6 种预设场景，对复杂任务不够聪明。黑板写了但没人读，上下文膨胀无控制。需要将决策权交给 LLM（Codex），同时保留规则引擎作为 fallback。

## 2. 目标

- Codex (Claude Code) 作为 supervisor，通过 MCP tools 管理 Worker
- 战略决策（派谁、做什么、是否验收）由 Codex 的 LLM 推理完成
- 战术执行（轮询、验证、挑战循环、超时）保留为自动循环
- 上下文通过 Context Layer 压缩，防止膨胀
- 规则引擎保留为 fallback，简单任务可全自动

## 3. 架构

```
┌─────────────────────────────────────────────────────────┐
│                    Codex (Claude Code)                   │
│              supervisor，有 Claude 推理能力               │
│                                                          │
│   tools: MCP tools (crew_*)                              │
│   fallback: CrewDecisionPolicy (规则引擎)                │
└──────────────┬──────────────────────────────────────────┘
               │ MCP protocol (stdio)
               ▼
┌─────────────────────────────────────────────────────────┐
│                   MCP Server (新增)                      │
│                                                          │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────┐  │
│  │ Tool Layer  │  │ Context Layer│  │ Fallback Layer │  │
│  │ crew_start  │  │ 摘要/过滤/   │  │ 规则引擎兜底   │  │
│  │ crew_status │  │ 压缩         │  │ (auto_decide)  │  │
│  │ crew_verify │  │              │  │                │  │
│  │ ...         │  │              │  │                │  │
│  └──────┬──────┘  └──────┬───────┘  └───────┬────────┘  │
│         └────────────────┴──────────────────┘           │
│                          │                               │
│              CrewController / WorkerPool                 │
└──────────────────┬──────────────────────────────────────┘
                   │
        ┌──────────┼──────────┐
        ▼          ▼          ▼
   tmux Worker  tmux Worker  tmux Worker
   (Claude CLI) (Claude CLI) (Claude CLI)
```

### 3.1 战略/战术分层

| 层级 | 职责 | 执行者 |
|------|------|--------|
| 战略层 | 派谁、做什么、是否验收、是否 spawn 新 Worker | Codex (LLM) |
| 战术层 | 轮询 tmux、自动验证、自动挑战、超时检测、3 次升级 | Supervision Loop (Python) |

战术循环在以下战略决策点暂停，返回给 Codex：
- 验证失败 3 次 → "需要你决定：继续修、换人、还是叫人"
- 没有 source_write worker → "需要你决定 spawn 什么 Worker"
- 需要浏览器测试 → "需要你决定是否启动 browser flow"
- 验证通过 → "需要你确认验收"
- context 不足 → "需要你决定是否先侦察"
- 循环跑完 max_steps → "跑了 N 轮，给你看结果"

规则引擎作为 fallback：`crew_run(auto_decide=True)` 时循环在战略决策点不暂停，自动走规则引擎。

## 4. MCP Tools 清单

### 4.1 Crew 生命周期

| Tool | 参数 | 返回 | 说明 |
|------|------|------|------|
| `crew_start` | repo, goal, roles[], auto_decide | crew_id, worker_ids | 启动 Crew |
| `crew_stop` | crew_id | 确认 | 停止 Crew |
| `crew_status` | crew_id | 结构化摘要 | Crew 状态（非原始 dump） |

### 4.2 战略决策

| Tool | 参数 | 返回 | 说明 |
|------|------|------|------|
| `crew_decide` | crew_id, action, contract? | 确认 | Codex 做战略决策 |
| `crew_accept` | crew_id | 合并结果 | 接受并合并 |
| `crew_challenge` | crew_id, worker_id, goal | 确认 | 发出自定义挑战 |
| `crew_spawn` | crew_id, contract | worker_id | 动态 spawn Worker |

`crew_decide` 的 `action` 枚举值：`spawn_worker` | `observe` | `accept` | `challenge` | `stop` | `needs_human`

`crew_spawn` 的 `contract` 参数结构：

```json
{
  "label": "targeted-code-editor",
  "mission": "实现最小安全补丁",
  "required_capabilities": ["inspect_code", "edit_source"],
  "authority_level": "source_write",
  "workspace_policy": "worktree",
  "write_scope": ["src/auth/"],
  "expected_outputs": ["patch", "changed_files"],
  "acceptance_criteria": ["所有验证命令通过"]
}
```

### 4.3 上下文获取（Context Layer）

| Tool | 参数 | 返回 | 压缩策略 |
|------|------|------|---------|
| `crew_blackboard` | crew_id, worker_id?, type?, limit? | 过滤后的条目 | 按 worker_id/type 过滤，默认 limit=10 |
| `crew_events` | crew_id, limit? | 关键事件 | 只返回 turn.completed/failed/challenge/review 等 |
| `crew_observe` | crew_id, worker_id | 当前轮次文本 | 只返回当前轮次，非全量 tmux 快照 |
| `crew_changes` | crew_id | 变更文件列表 | 结构化变更 |
| `crew_diff` | crew_id, file? | patch 内容 | 按文件返回 |

### 4.4 战术执行

| Tool | 参数 | 返回 | 说明 |
|------|------|------|------|
| `crew_run` | crew_id, max_steps?, auto_decide? | 循环结果 | 运行监督循环，遇战略决策点暂停 |
| `crew_verify` | crew_id, worker_id, commands? | 验证结果 | 手动触发验证 |
| `crew_merge_plan` | crew_id | 合并方案 | 检测冲突，返回合并计划 |

## 5. Context Layer 设计

### 5.1 crew_status 压缩

返回结构化摘要，不返回原始 JSON dump：

```json
{
  "crew_id": "crew-abc",
  "goal": "重构认证模块",
  "status": "running",
  "round": 2,
  "workers": [
    {"id": "w1", "role": "explorer", "status": "idle", "summary": "已完成代码库分析"},
    {"id": "w2", "role": "implementer", "status": "busy", "summary": "正在修改 auth/login.py"}
  ],
  "verification_passed": false,
  "verification_failures": 1,
  "changed_files": ["src/auth/login.py", "src/auth/middleware.py"],
  "pending_decisions": []
}
```

### 5.2 黑板压缩

- 按 `worker_id`、`entry_type`、`task_id` 过滤
- 默认只返回最近 10 条
- 超过 20 条时自动触发摘要
- 条目增加 `summary` 字段（截取 content 前 100 字符或第一句话）
- 超过 100 条时旧条目压缩为摘要（每 10 条合并为 1 条）

### 5.3 事件流过滤

只返回关键事件：
- 保留: crew.started, turn.completed, turn.failed, challenge.issued, review.verdict, readiness.evaluated, crew.ready_for_accept
- 跳过: turn.delivered, scope.evaluated（重复性中间事件）

### 5.4 token 预算控制

每个 tool 有 `max_tokens` 参数（默认 2000），超过时自动截断并标注"已截断"。

## 6. Supervision Loop 改造

### 6.1 从完整循环变为可暂停协程

当前 `CrewSupervisorLoop.run()` 是一个完整循环。改造为 `run_step()` 方法，执行一步战术逻辑后返回。

```python
@dataclass
class LoopStepResult:
    action: str          # "waiting" | "needs_decision" | "ready_for_accept" | "max_steps_reached"
    reason: str = ""     # 暂停原因
    context: dict = field(default_factory=dict)  # 相关上下文（验证结果、Worker 状态等）
    snapshot: dict = field(default_factory=dict)  # 供规则引擎 fallback 使用的快照

class SupervisionLoop:
    def run_step(self, crew_id: str) -> LoopStepResult:
        # 1. 轮询 Worker 状态
        # 2. Worker 完成 → 自动验证
        # 3. 验证失败 → 自动挑战（< 3 次）
        # 4. 验证失败 >= 3 次 → 返回 needs_decision
        # 5. 验证通过 → 返回 ready_for_accept
        # 6. 等待中 → 返回 waiting
```

### 6.2 crew_run 调用逻辑

```
Codex 调用 crew_run(crew_id, max_steps=10, auto_decide=False)
    │
    └─ MCP Server 内部循环:
        for i in range(max_steps):
            result = loop.run_step(crew_id)
            if result.action == "needs_decision":
                if auto_decide:
                    # 规则引擎兜底
                    decision = fallback_policy.decide(result.snapshot)
                    loop.execute_decision(crew_id, decision)
                    continue
                return result  # 暂停，返回给 Codex
            if result.action == "ready_for_accept":
                return result  # 暂停，等 Codex 确认
        return "max_steps_reached"
```

### 6.3 规则引擎 fallback

保留 `CrewDecisionPolicy`，在 `auto_decide=True` 时自动触发。现有测试不改动。

## 7. 黑板重新定位

| 维度 | 现在 | 改造后 |
|------|------|--------|
| 写入方 | pool、controller、verification | 不变 |
| 读取方 | CLI 命令（给人看） | Context Layer（给 Codex 看） |
| 读取方式 | 全量 dump | 按需过滤 + 自动摘要 |
| 上下文膨胀 | 有，无上限 | 无，Context Layer 控制 |

黑板不再直接暴露给 Codex，通过 MCP tools 消费。

## 8. 文件结构

```
src/codex_claude_orchestrator/
    mcp_server/
        __init__.py
        __main__.py            # python -m codex_claude_orchestrator.mcp_server 入口
        server.py              # MCP Server 实例创建、tool 注册、依赖注入
        tools/
            __init__.py
            crew_lifecycle.py   # crew_start, crew_stop, crew_status
            crew_decision.py    # crew_decide, crew_accept, crew_challenge, crew_spawn
            crew_context.py     # crew_blackboard, crew_events, crew_observe, crew_changes, crew_diff
            crew_execution.py   # crew_run, crew_verify, crew_merge_plan
        context/
            __init__.py
            compressor.py       # 黑板压缩、事件过滤、摘要生成
            token_budget.py     # token 预算控制
```

`__main__.py` 负责：解析环境变量、初始化 CrewController/WorkerPool 等依赖、创建 MCP Server 实例、启动 stdio 传输。

## 9. MCP Server 启动配置

```json
{
  "mcpServers": {
    "crew-orchestrator": {
      "command": "python",
      "args": ["-m", "codex_claude_orchestrator.mcp_server"],
      "env": {
        "V4_EVENT_STORE_BACKEND": "sqlite"
      }
    }
  }
}
```

## 10. 测试策略

| 层级 | 测试方式 |
|------|---------|
| MCP Server | 模拟 MCP client 调用，验证 tool 注册和响应格式 |
| Context Layer | 单元测试压缩函数，验证 token 预算 |
| Supervision Loop | 现有测试改造，验证可暂停行为 |
| Fallback | 保留现有 `test_decision_policy.py` |
| 集成测试 | MCP Server + 真实 controller + mock tmux |

## 11. 依赖

- `mcp` Python SDK（新增）
- 现有 controller、worker pool、event store 等（复用）

## 12. 与现有代码的关系

| 现有模块 | 变化 |
|---------|------|
| `crew/supervisor_loop.py` | 改造为可暂停的 `run_step()` |
| `crew/decision_policy.py` | 保留为 fallback，不删除 |
| `crew/controller.py` | 不变，被 MCP Server 调用 |
| `state/blackboard.py` | 增加 `summary` 字段支持 |
| `cli.py` | 保留，MCP Server 是新入口 |
