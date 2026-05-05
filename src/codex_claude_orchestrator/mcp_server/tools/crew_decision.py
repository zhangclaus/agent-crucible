from __future__ import annotations

import json

from mcp.server import Server
from mcp.types import TextContent

from codex_claude_orchestrator.crew.models import (
    AuthorityLevel,
    WorkerContract,
    WorkspacePolicy,
)


def register_decision_tools(server: Server, controller) -> None:

    @server.tool("crew_decide")
    async def crew_decide(
        crew_id: str,
        action: str,
        reason: str = "",
    ) -> list[TextContent]:
        """Codex 做战略决策。action: spawn_worker|observe|accept|challenge|stop|needs_human。"""
        controller.record_decision(
            crew_id=crew_id,
            action={"action_type": action, "reason": reason},
        )
        return [TextContent(type="text", text=json.dumps({"status": "recorded", "action": action}))]

    @server.tool("crew_accept")
    async def crew_accept(crew_id: str) -> list[TextContent]:
        """接受当前 Crew 结果，触发合并。"""
        result = controller.accept(crew_id=crew_id)
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]

    @server.tool("crew_challenge")
    async def crew_challenge(
        crew_id: str,
        worker_id: str,
        goal: str,
    ) -> list[TextContent]:
        """对 Worker 发出自定义挑战。"""
        result = controller.challenge(crew_id=crew_id, worker_id=worker_id, goal=goal)
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]

    @server.tool("crew_spawn")
    async def crew_spawn(
        crew_id: str,
        label: str,
        mission: str,
        required_capabilities: list[str],
        authority_level: str = "source_write",
        workspace_policy: str = "worktree",
        write_scope: list[str] | None = None,
        expected_outputs: list[str] | None = None,
        acceptance_criteria: list[str] | None = None,
    ) -> list[TextContent]:
        """动态 spawn 一个新 Worker。"""
        contract = WorkerContract(
            contract_id=f"contract-{label}",
            label=label,
            mission=mission,
            required_capabilities=required_capabilities,
            authority_level=AuthorityLevel(authority_level),
            workspace_policy=WorkspacePolicy(workspace_policy),
            write_scope=write_scope or [],
            expected_outputs=expected_outputs or [],
            acceptance_criteria=acceptance_criteria or [],
        )
        worker = controller.ensure_worker(
            crew_id=crew_id,
            contract=contract,
        )
        return [TextContent(type="text", text=json.dumps({
            "worker_id": worker.get("worker_id"),
            "contract_id": contract.contract_id,
            "label": label,
        }))]
