# MCP Server 驱动 + Sampling 决策架构设计

> 日期: 2026-05-05 | 状态: 待 review

## 1. 问题

当前 MCP 模式有两个根本问题：

1. **轮询不工作**：`run_step()` 不阻塞，`crew_run` 的 for 循环在毫秒级耗尽，轮询形同虚设
2. **控制流反了**：Codex 驱动循环（调 tool → 等返回 → 再调），但 Codex 不能 sleep 轮询

此外还有：
3. **规则引擎多余**：`CrewDecisionPolicy`（6 个 if/elif）被 LLM 完全替代，`auto_decide` 没有意义
4. **supervisor 被绑死在 Codex**：架构上 supervisor 应该是可替换的

## 2. 目标

- MCP Server 驱动完整监督循环（阻塞轮询，和原始 CLI 一样）
- 战略决策通过 MCP `sampling/createMessage` 请求 supervisor（LLM）
- supervisor 可替换：Codex、Claude API、任意 MCP client、甚至人工 operator
- 删除规则引擎 fallback
- `crew_run` 是长时间运行的 tool，调用方调一次等最终结果

## 3. 架构

```
MCP Client（supervisor，可替换）
┌──────────────────────────────────┐
│  Codex / Claude API / 任意 agent │
│  接收 sampling 请求，返回决策     │
└──────────────┬───────────────────┘
               │ MCP protocol (stdio)
               │ sampling/createMessage (server→client)
               ▼
┌──────────────────────────────────────────────────────────┐
│  MCP Server (Python)                                     │
│                                                          │
│  crew_run(crew_id, max_rounds, verification_commands)    │
│    │                                                     │
│    └─ 内部循环:                                          │
│        _wait_for_marker() 阻塞轮询                       │
│        → Worker 完成 → 自动验证                          │
│        → 验证通过 → sampling → "accept 吗?"              │
│        → 验证失败 < 3 → 自动挑战 → 继续                  │
│        → 验证失败 >= 3 → sampling → "你决定"              │
│        → max_rounds → 返回最终状态                       │
│                                                          │
│  crew_start / crew_stop / crew_status                    │
│  crew_accept / crew_challenge                            │
│  crew_blackboard / crew_events / crew_observe / ...      │
└──────────────┬──────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────┐
│  CrewController / WorkerPool / Blackboard                │
└──────────────┬──────────────────────────────────────────┘
               │
        ┌──────┼──────┐
        ▼      ▼      ▼
   tmux Worker tmux Worker tmux Worker
```

### 3.1 控制流对比

| | 旧（Codex 驱动） | 新（Server 驱动） |
|--|------------------|------------------|
| 循环在哪 | Codex 反复调 tool | MCP Server 内部 |
| 轮询 | run_step 不阻塞，瞬间耗尽 | _wait_for_marker 阻塞轮询 |
| 决策 | tool 返回 → Codex 再调 | sampling 请求 → Codex 回复 |
| supervisor | 绑死 Codex | 可替换任意 MCP client |
| crew_run | Codex 调多次 | 调一次等最终结果 |

## 4. MCP Tools 变化

### 4.1 保留的 tools

| Tool | 说明 |
|------|------|
| `crew_start` | 启动 Crew |
| `crew_stop` | 停止 Crew |
| `crew_status` | 获取压缩状态 |
| `crew_run` | **改造**：长时间运行，内部完整循环 |
| `crew_accept` | 接受结果（供 Codex 在 sampling 回复之外主动调用） |
| `crew_challenge` | 发出挑战（同上） |
| `crew_blackboard` | 读黑板 |
| `crew_events` | 读事件 |
| `crew_observe` | 观察 Worker |
| `crew_changes` | 查看变更 |
| `crew_diff` | 查看 diff |

### 4.2 删除的 tools

| Tool | 原因 |
|------|------|
| `crew_decide` | 决策通过 sampling 自然发生，不需要单独 record |
| `crew_spawn` | Codex 在 sampling 回复中指定 spawn，MCP Server 执行 |
| `crew_verify` | 验证是 crew_run 内部自动的 |
| `crew_merge_plan` | 合并是 accept 的一部分 |

### 4.3 crew_run 改造

```python
@server.tool("crew_run")
async def crew_run(
    crew_id: str,
    max_rounds: int = 3,
    verification_commands: list[str] | None = None,
) -> list[TextContent]:
    """运行完整监督循环。需要决策时通过 sampling 请求 supervisor。"""
    result = supervision_loop.run(
        crew_id=crew_id,
        max_rounds=max_rounds,
        verification_commands=verification_commands or [],
        sampling_fn=server.request_sampling,  # sampling 回调
    )
    return [TextContent(type="text", text=json.dumps(result))]
```

## 5. Supervision Loop 改造

### 5.1 run() 方法重写

```python
class CrewSupervisorLoop:
    def run(
        self,
        crew_id: str,
        max_rounds: int,
        verification_commands: list[str],
        sampling_fn,  # MCP sampling 回调
    ) -> dict:
        """完整监督循环。阻塞运行，需要决策时调 sampling_fn。"""
        for round_index in range(1, max_rounds + 1):
            # 1. 轮询 Worker（阻塞）
            self._wait_for_workers(crew_id)

            # 2. 自动验证
            verify_result = self._auto_verify(crew_id, verification_commands)

            if verify_result["passed"]:
                # 3a. 验证通过 → 询问 supervisor 是否 accept
                decision = self._ask_supervisor(
                    sampling_fn, crew_id, "verification_passed", verify_result
                )
                if decision["action"] == "accept":
                    return self._do_accept(crew_id)
                # supervisor 可能选择继续挑战或其他

            failure_count = verify_result.get("failure_count", 0)
            if failure_count >= 3:
                # 3b. 失败 >= 3 次 → 询问 supervisor
                decision = self._ask_supervisor(
                    sampling_fn, crew_id, "verification_failed", verify_result
                )
                self._execute_decision(crew_id, decision)
                continue

            # 3c. 失败 < 3 次 → 自动挑战
            self._auto_challenge(crew_id, verify_result)

        return {"crew_id": crew_id, "status": "max_rounds_reached"}

    def _wait_for_workers(self, crew_id: str) -> None:
        """阻塞轮询，直到所有 Worker 完成。"""
        while True:
            details = self._controller.status(crew_id=crew_id)
            workers = details.get("workers", [])
            all_done = all(
                w.get("status") in ("idle", "stopped", "failed")
                for w in workers
            )
            if all_done:
                return
            time.sleep(self._poll_interval_seconds)

    def _ask_supervisor(
        self, sampling_fn, crew_id: str, situation: str, context: dict
    ) -> dict:
        """通过 sampling 请求 supervisor 做战略决策。"""
        compressed = compress_crew_status(
            self._controller.status(crew_id=crew_id)
        )
        prompt = self._build_decision_prompt(situation, context, compressed)
        response = sampling_fn(
            messages=[{"role": "user", "content": prompt}],
            system_prompt="你是 Crew supervisor。根据 context 做战略决策。",
            max_tokens=500,
        )
        return self._parse_decision(response)

    def _build_decision_prompt(self, situation, context, status) -> str:
        """构建决策提示。"""
        # 根据 situation 类型构建不同的提示
        # 附带压缩后的 status 和 context
        ...

    def _parse_decision(self, response: str) -> dict:
        """解析 supervisor 的决策回复。"""
        # 解析 "accept" / "spawn_worker(label, mission)" / "challenge(worker_id, goal)"
        ...

    def _execute_decision(self, crew_id: str, decision: dict) -> None:
        """执行 supervisor 的决策。"""
        if decision["action"] == "spawn_worker":
            contract = WorkerContract(...)
            self._controller.ensure_worker(crew_id=crew_id, contract=contract)
        elif decision["action"] == "accept":
            self._controller.accept(crew_id=crew_id)
        elif decision["action"] == "challenge":
            self._controller.challenge(crew_id=crew_id, ...)
```

### 5.2 删除的代码

- `run_step()` 方法 — 不再需要暂停/恢复
- `LoopStepResult` 数据类 — 不再需要
- `_poll_workers()` — 被 `_wait_for_workers()` 替代（阻塞版本）

### 5.3 保留的代码

- `_wait_for_marker()` — 阻塞轮询（已有，直接复用）
- `_auto_challenge()` — 自动挑战
- `_auto_verify()` — 自动验证（需要补全实现）
- `_build_snapshot()` — 改为 `_build_decision_prompt()`

## 6. Sampling 交互协议

### 6.1 sampling 请求格式

```python
# MCP Server → Client
{
    "messages": [{
        "role": "user",
        "content": "## 验证失败 3 次\n\n当前状态：...\n变更文件：...\n\n请选择下一步：\n1. spawn_worker(label, mission)\n2. accept（跳过验证）\n3. challenge(worker_id, goal)"
    }],
    "systemPrompt": "你是 Crew supervisor，负责战略决策。根据提供的 context 选择下一步行动。",
    "maxTokens": 500
}
```

### 6.2 sampling 响应格式

```
# Supervisor 回复（自由文本，MCP Server 解析）
spawn_worker(label="fixer", mission="修复 pytest 失败的测试用例")
```

### 6.3 决策解析

MCP Server 解析 supervisor 的文本回复，提取 action 和参数：

```python
def _parse_decision(self, response: str) -> dict:
    text = response.strip()
    if text.startswith("accept"):
        return {"action": "accept"}
    if text.startswith("spawn_worker"):
        # 解析 label, mission
        return {"action": "spawn_worker", "label": ..., "mission": ...}
    if text.startswith("challenge"):
        # 解析 worker_id, goal
        return {"action": "challenge", "worker_id": ..., "goal": ...}
    # 默认 observe
    return {"action": "observe"}
```

## 7. Context Layer 保留

Context Layer 功能不变，用途变化：

| 之前用途 | 现在用途 |
|---------|---------|
| Codex 通过 tool 主动读取 | sampling 请求中附带压缩 context |
| crew_status 返回压缩状态 | _ask_supervisor 中构建 prompt 用 |
| crew_blackboard 过滤条目 | 同上 |

保留 `compress_crew_status()`、`compress_blackboard()`、`filter_events()`、`truncate_json()`。

## 8. 删除规则引擎

- 删除 `crew_run` 的 `auto_decide` 参数
- 删除 `CrewDecisionPolicy` 的调用（代码文件保留，不被 MCP Server 使用）
- 删除 `crew_decide` tool
- 删除 `crew_spawn` tool
- 删除 `LoopStepResult` 数据类

## 9. 文件结构变化

```
src/codex_claude_orchestrator/mcp_server/
    __init__.py           ← 不变
    __main__.py           ← 不变
    server.py             ← 不变
    tools/
        __init__.py       ← 不变
        crew_lifecycle.py ← 不变
        crew_context.py   ← 不变
        crew_decision.py  ← 大幅简化（只保留 accept, challenge）
        crew_execution.py ← 改造（crew_run 长时间运行）
    context/
        __init__.py       ← 不变
        compressor.py     ← 不变
        token_budget.py   ← 不变

删除:
    crew/loop_step_result.py

改造:
    crew/supervisor_loop.py ← run_step → run（完整循环 + sampling）
```

## 10. 测试策略

| 层级 | 变化 |
|------|------|
| crew_run | mock sampling_fn，验证长时间运行 + 决策交互 |
| Supervision Loop | mock sleep + tmux + sampling，验证完整循环 |
| sampling 解析 | 单元测试 _parse_decision，验证各种回复格式 |
| Context Layer | 不变 |
| 现有 tests | 删除 test_loop_step_result.py，更新 test_supervisor_loop_step.py |

## 11. Supervisor 可替换性

MCP Server 不关心谁是 supervisor。`sampling_fn` 是一个回调：

```python
# 任何 MCP client 都可以接
sampling_fn = server.request_sampling  # MCP 标准
sampling_fn = custom_llm_client.ask    # 自定义 LLM
sampling_fn = human_operator.prompt    # 人工
```

这使得 MCP Server 成为通用的多 agent 编排引擎。
