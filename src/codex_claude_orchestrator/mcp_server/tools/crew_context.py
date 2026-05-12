"""Context tools: crew_observe, crew_changes, crew_diff."""

from __future__ import annotations

import json
from pathlib import Path

from mcp.server import Server
from mcp.types import TextContent

from codex_claude_orchestrator.mcp_server.context.compressor import (
    compress_observe_result,
    read_latest_outbox,
)
from codex_claude_orchestrator.mcp_server.context.token_budget import truncate_json


def register_context_tools(server: Server, controller) -> None:

    @server.tool("crew_observe")
    async def crew_observe(repo: str, crew_id: str, worker_id: str) -> list[TextContent]:
        """观察某个 Worker 的当前轮次输出（结构化报告，非原始文本）。"""
        try:
            observation = controller.observe_worker(repo_root=Path(repo), crew_id=crew_id, worker_id=worker_id)
            outbox = read_latest_outbox(Path(repo), crew_id, worker_id)
            report = compress_observe_result(observation, outbox, worker_id=worker_id)
            return [TextContent(type="text", text=truncate_json(report))]
        except FileNotFoundError as exc:
            return [TextContent(type="text", text=json.dumps({"error": str(exc)}, ensure_ascii=False))]
        except ValueError as exc:
            return [TextContent(type="text", text=json.dumps({"error": str(exc)}, ensure_ascii=False))]
        except Exception as exc:
            return [TextContent(type="text", text=json.dumps({"error": f"internal: {exc}"}, ensure_ascii=False))]

    @server.tool("crew_changes")
    async def crew_changes(crew_id: str) -> list[TextContent]:
        """查看 Crew 的文件变更列表（所有 Worker 聚合）。"""
        try:
            result = controller.changes(crew_id=crew_id)
            if isinstance(result, list):
                all_files = []
                for entry in result:
                    for f in entry.get("changed_files", []):
                        if f not in all_files:
                            all_files.append(f)
                return [TextContent(type="text", text=json.dumps(all_files, ensure_ascii=False))]
            return [TextContent(type="text", text=json.dumps(result.get("changed_files", []), ensure_ascii=False))]
        except FileNotFoundError as exc:
            return [TextContent(type="text", text=json.dumps({"error": str(exc)}, ensure_ascii=False))]
        except ValueError as exc:
            return [TextContent(type="text", text=json.dumps({"error": str(exc)}, ensure_ascii=False))]
        except Exception as exc:
            return [TextContent(type="text", text=json.dumps({"error": f"internal: {exc}"}, ensure_ascii=False))]

    @server.tool("crew_diff")
    async def crew_diff(crew_id: str, file: str | None = None) -> list[TextContent]:
        """查看具体文件的 diff（或所有变更摘要）。"""
        try:
            result = controller.changes(crew_id=crew_id)
            entries = result if isinstance(result, list) else [result]
            if file:
                entries = [e for e in entries if file in e.get("changed_files", [])]
            summaries = [
                {
                    "worker_id": e.get("worker_id", ""),
                    "changed_files": e.get("changed_files", []),
                    "branch": e.get("branch", ""),
                }
                for e in entries
            ]
            return [TextContent(type="text", text=truncate_json(summaries))]
        except FileNotFoundError as exc:
            return [TextContent(type="text", text=json.dumps({"error": str(exc)}, ensure_ascii=False))]
        except ValueError as exc:
            return [TextContent(type="text", text=json.dumps({"error": str(exc)}, ensure_ascii=False))]
        except Exception as exc:
            return [TextContent(type="text", text=json.dumps({"error": f"internal: {exc}"}, ensure_ascii=False))]
