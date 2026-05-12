from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from codex_claude_orchestrator.mcp_server.tools.crew_lifecycle import register_lifecycle_tools
from codex_claude_orchestrator.mcp_server.tools.crew_decision import register_decision_tools
from codex_claude_orchestrator.mcp_server.tools.crew_run import register_run_tools
from codex_claude_orchestrator.mcp_server.tools.crew_context import register_context_tools


def create_server(controller=None, job_manager=None) -> FastMCP:
    server = FastMCP("adversarial-code-review")

    if controller is not None:
        register_lifecycle_tools(server, controller)
        register_decision_tools(server, controller)
        register_context_tools(server, controller)

    if controller is not None and job_manager is not None:
        register_run_tools(server, controller, job_manager)

    return server
