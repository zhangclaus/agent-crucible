from pathlib import Path

from codex_claude_orchestrator.models import (
    EvaluationOutcome,
    EventRecord,
    NextAction,
    RunRecord,
    TaskRecord,
    WorkerResult,
    WorkspaceMode,
)
from codex_claude_orchestrator.prompt_compiler import CompiledPrompt
from codex_claude_orchestrator.run_recorder import RunRecorder


def test_run_recorder_persists_task_run_event_and_evaluation(tmp_path: Path):
    recorder = RunRecorder(tmp_path / ".orchestrator")
    task = TaskRecord(
        task_id="task-record",
        parent_task_id=None,
        origin="user",
        assigned_agent="claude",
        goal="Record a run",
        task_type="review",
        scope="repo root",
        workspace_mode=WorkspaceMode.READONLY,
    )
    run = RunRecord(
        run_id="run-1",
        task_id="task-record",
        agent="claude",
        adapter="claude-cli",
        workspace_id="workspace-1",
    )
    compiled = CompiledPrompt(
        system_prompt="system",
        user_prompt="goal",
        schema={"type": "object"},
        metadata={"task_id": task.task_id},
    )
    event = EventRecord(
        event_id="event-1",
        task_id="task-record",
        run_id="run-1",
        from_agent="codex",
        to_agent="claude",
        event_type="task_dispatched",
        payload={"goal": task.goal},
    )
    result = WorkerResult(
        raw_output='{"summary":"done"}',
        stdout='{"summary":"done"}',
        stderr="",
        exit_code=0,
        structured_output={"summary": "done"},
    )
    evaluation = EvaluationOutcome(
        accepted=True,
        next_action=NextAction.ACCEPT,
        summary="worker result accepted",
    )

    recorder.start_run(run, task, compiled)
    recorder.append_event(run.run_id, event)
    recorder.write_result(run.run_id, result, evaluation)

    run_dir = tmp_path / ".orchestrator" / "runs" / "run-1"
    assert (run_dir / "task.json").exists()
    assert (run_dir / "events.jsonl").exists()
    assert (run_dir / "result.json").exists()
    assert (run_dir / "evaluation.json").exists()
    assert (run_dir / "artifacts" / "prompt.txt").exists()
    assert (run_dir / "artifacts" / "stdout.txt").exists()
    assert (run_dir / "artifacts" / "stderr.txt").exists()
