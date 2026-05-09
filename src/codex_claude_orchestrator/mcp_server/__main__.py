from __future__ import annotations

import asyncio
import os
import signal
from pathlib import Path


def _build_controller():
    """从环境变量构建 CrewController。"""
    from codex_claude_orchestrator.crew.controller import CrewController
    from codex_claude_orchestrator.state.crew_recorder import CrewRecorder
    from codex_claude_orchestrator.state.blackboard import BlackboardStore
    from codex_claude_orchestrator.workers.pool import WorkerPool
    from codex_claude_orchestrator.runtime.native_claude_session import NativeClaudeSession
    from codex_claude_orchestrator.crew.task_graph import TaskGraphPlanner
    from codex_claude_orchestrator.workspace.worktree_manager import WorktreeManager
    from codex_claude_orchestrator.v4.event_store_factory import build_v4_event_store

    repo = Path(os.environ.get("CREW_REPO", "."))
    state_root = repo / ".orchestrator"
    recorder = CrewRecorder(state_root)
    event_store = build_v4_event_store(repo, readonly=False)
    blackboard = BlackboardStore(recorder, event_store=event_store)
    session = NativeClaudeSession()
    worktree_manager = WorktreeManager(state_root)
    pool = WorkerPool(
        recorder=recorder,
        blackboard=blackboard,
        worktree_manager=worktree_manager,
        native_session=session,
        event_store=event_store,
    )
    controller = CrewController(
        recorder=recorder,
        blackboard=blackboard,
        worker_pool=pool,
        task_graph=TaskGraphPlanner(),
        event_store=event_store,
    )
    return controller


def _handle_shutdown(job_manager: "JobManager", loop: asyncio.AbstractEventLoop) -> None:
    """Graceful shutdown: cancel jobs, then stop the event loop."""
    job_manager.shutdown(timeout=3.0)
    loop.call_soon(loop.stop)


async def main() -> None:
    from codex_claude_orchestrator.mcp_server.job_manager import JobManager
    from codex_claude_orchestrator.mcp_server.server import create_server

    controller = _build_controller()
    job_manager = JobManager()
    server = create_server(controller=controller, job_manager=job_manager)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(
            sig, lambda: _handle_shutdown(job_manager, loop)
        )

    await server.run_stdio_async()


if __name__ == "__main__":
    asyncio.run(main())
