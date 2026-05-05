from __future__ import annotations

import json

from mcp.server import Server
from mcp.types import TextContent


def register_execution_tools(server: Server, controller, supervision_loop=None) -> None:

    @server.tool("crew_run")
    async def crew_run(
        crew_id: str,
        max_steps: int = 10,
        auto_decide: bool = False,
        verification_commands: list[str] | None = None,
    ) -> list[TextContent]:
        """运行监督循环。auto_decide=True 时规则引擎兜底。遇战略决策点暂停返回。"""
        if supervision_loop is None:
            return [TextContent(type="text", text=json.dumps({
                "error": "supervision_loop not initialized"
            }))]

        for i in range(max_steps):
            result = supervision_loop.run_step(crew_id, verification_commands=verification_commands)

            if result.action == "needs_decision":
                if auto_decide:
                    from codex_claude_orchestrator.crew.decision_policy import CrewDecisionPolicy
                    policy = CrewDecisionPolicy()
                    decision = policy.decide(result.snapshot)
                    # 执行规则引擎的决策
                    if decision.contract:
                        controller.ensure_worker(crew_id=crew_id, contract=decision.contract)
                    continue
                return [TextContent(type="text", text=json.dumps(result.to_dict(), ensure_ascii=False))]

            if result.action == "ready_for_accept":
                return [TextContent(type="text", text=json.dumps(result.to_dict(), ensure_ascii=False))]

            if result.action == "challenged":
                continue  # 挑战已发出，继续下一轮

        return [TextContent(type="text", text=json.dumps({
            "action": "max_steps_reached",
            "steps": max_steps,
        }))]

    @server.tool("crew_verify")
    async def crew_verify(
        crew_id: str,
        worker_id: str,
        commands: list[str] | None = None,
    ) -> list[TextContent]:
        """手动触发验证。"""
        result = controller.verify(crew_id=crew_id, worker_id=worker_id)
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]

    @server.tool("crew_merge_plan")
    async def crew_merge_plan(crew_id: str) -> list[TextContent]:
        """查看合并计划。"""
        result = controller.merge_plan(crew_id=crew_id)
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]
