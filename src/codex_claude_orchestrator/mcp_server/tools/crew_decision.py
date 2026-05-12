from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent


def register_decision_tools(server: FastMCP, controller) -> None:

    @server.tool("crew_accept")
    async def crew_accept(crew_id: str, summary: str = "") -> list[TextContent]:
        """Accept the current crew result (finalize the job)."""
        try:
            result = controller.accept(crew_id=crew_id, summary=summary or "Accepted by user")
            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]
        except FileNotFoundError as exc:
            return [TextContent(type="text", text=json.dumps({"error": str(exc)}, ensure_ascii=False))]
        except ValueError as exc:
            return [TextContent(type="text", text=json.dumps({"error": str(exc)}, ensure_ascii=False))]
        except Exception as exc:
            return [TextContent(type="text", text=json.dumps({"error": f"internal: {exc}"}, ensure_ascii=False))]

    @server.tool("crew_challenge")
    async def crew_challenge(
        crew_id: str,
        summary: str,
        task_id: str | None = None,
    ) -> list[TextContent]:
        """Challenge a worker with a risk entry."""
        try:
            result = controller.challenge(crew_id=crew_id, summary=summary, task_id=task_id)
            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]
        except FileNotFoundError as exc:
            return [TextContent(type="text", text=json.dumps({"error": str(exc)}, ensure_ascii=False))]
        except ValueError as exc:
            return [TextContent(type="text", text=json.dumps({"error": str(exc)}, ensure_ascii=False))]
        except Exception as exc:
            return [TextContent(type="text", text=json.dumps({"error": f"internal: {exc}"}, ensure_ascii=False))]
