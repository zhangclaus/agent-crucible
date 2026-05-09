from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path

import pytest

from codex_claude_orchestrator.cli import main
from codex_claude_orchestrator.core.models import (
    EvaluationOutcome,
    NextAction,
    RunRecord,
    TaskRecord,
    WorkspaceMode,
)
from codex_claude_orchestrator.crew.models import WorkerRole
from codex_claude_orchestrator.state.run_recorder import RunRecorder


def test_build_parser_exposes_dispatch_subcommand():
    from codex_claude_orchestrator.cli import build_parser

    parser = build_parser()
    subparsers_action = next(action for action in parser._actions if action.dest == "command")
    assert "dispatch" in subparsers_action.choices


class FakeSupervisor:
    def dispatch(self, task, source_repo):
        return EvaluationOutcome(
            accepted=True,
            next_action=NextAction.ACCEPT,
            summary=f"accepted {task.goal}",
        )


def test_main_dispatch_prints_json_summary(tmp_path: Path, monkeypatch):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    monkeypatch.setattr(
        "codex_claude_orchestrator.cli.build_supervisor",
        lambda state_root: FakeSupervisor(),
    )

    stdout = StringIO()
    with redirect_stdout(stdout):
        exit_code = main(
            [
                "dispatch",
                "--task-id",
                "task-cli",
                "--goal",
                "Inspect the repository",
                "--repo",
                str(repo_root),
                "--workspace-mode",
                "readonly",
            ]
        )

    payload = json.loads(stdout.getvalue())
    assert exit_code == 0
    assert payload["accepted"] is True
    assert payload["summary"] == "accepted Inspect the repository"


def test_agents_list_prints_configured_profiles():
    stdout = StringIO()

    with redirect_stdout(stdout):
        exit_code = main(["agents", "list"])

    payload = json.loads(stdout.getvalue())
    assert exit_code == 0
    assert payload["agents"][0]["name"] == "claude"
    assert payload["agents"][0]["adapter"] == "claude-cli"


def test_doctor_reports_python_and_claude_checks():
    stdout = StringIO()

    with redirect_stdout(stdout):
        exit_code = main(["doctor"])

    payload = json.loads(stdout.getvalue())
    assert exit_code == 0
    assert payload["python"]["ok"] is True
    assert "claude_cli" in payload


def test_runs_list_prints_recorded_run_summaries(tmp_path: Path):
    repo_root = tmp_path / "repo"
    recorder = RunRecorder(repo_root / ".orchestrator")
    task = TaskRecord(
        task_id="task-cli-run",
        parent_task_id=None,
        origin="cli",
        assigned_agent="claude",
        goal="List this run",
        task_type="review",
        scope=str(repo_root),
        workspace_mode=WorkspaceMode.READONLY,
    )
    run = RunRecord(
        run_id="run-cli-list",
        task_id=task.task_id,
        agent="claude",
        adapter="claude-cli",
        workspace_id="workspace-cli",
    )
    recorder.start_run(run, task)
    recorder.write_result(
        run.run_id,
        result=FakeWorkerResult(summary="listed"),
        evaluation=EvaluationOutcome(
            accepted=True,
            next_action=NextAction.ACCEPT,
            summary="listed",
        ),
    )

    stdout = StringIO()
    with redirect_stdout(stdout):
        exit_code = main(["runs", "list", "--repo", str(repo_root)])

    payload = json.loads(stdout.getvalue())
    assert exit_code == 0
    assert payload["runs"][0]["run_id"] == "run-cli-list"
    assert payload["runs"][0]["summary"] == "listed"


def test_runs_show_prints_recorded_run_details(tmp_path: Path):
    repo_root = tmp_path / "repo"
    recorder = RunRecorder(repo_root / ".orchestrator")
    task = TaskRecord(
        task_id="task-cli-show",
        parent_task_id=None,
        origin="cli",
        assigned_agent="claude",
        goal="Show this run",
        task_type="review",
        scope=str(repo_root),
        workspace_mode=WorkspaceMode.READONLY,
    )
    run = RunRecord(
        run_id="run-cli-show",
        task_id=task.task_id,
        agent="claude",
        adapter="claude-cli",
        workspace_id="workspace-cli",
    )
    recorder.start_run(run, task)

    stdout = StringIO()
    with redirect_stdout(stdout):
        exit_code = main(["runs", "show", "--repo", str(repo_root), "--run-id", run.run_id])

    payload = json.loads(stdout.getvalue())
    assert exit_code == 0
    assert payload["run"]["run_id"] == "run-cli-show"
    assert payload["task"]["goal"] == "Show this run"
    assert "artifacts" in payload


class FakeWorkerResult:
    def __init__(self, summary: str):
        self.raw_output = f'{{"summary":"{summary}"}}'
        self.stdout = self.raw_output
        self.stderr = ""
        self.exit_code = 0
        self.structured_output = {"summary": summary}
        self.changed_files = []
        self.parse_error = None

    def to_dict(self):
        return {
            "raw_output": self.raw_output,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exit_code": self.exit_code,
            "structured_output": self.structured_output,
            "changed_files": self.changed_files,
            "parse_error": self.parse_error,
        }


class FakeCrewController:
    def __init__(self):
        self.calls = []

    def start(self, **kwargs):
        self.calls.append({"method": "start", **kwargs})
        return type(
            "Crew",
            (),
            {
                "crew_id": "crew-cli",
                "status": "running",
                "to_dict": lambda self: {"crew_id": "crew-cli", "status": "running"},
            },
        )()

    def start_dynamic(self, **kwargs):
        self.calls.append({"method": "start_dynamic", **kwargs})
        return type(
            "Crew",
            (),
            {
                "crew_id": "crew-cli",
                "status": "running",
                "to_dict": lambda self: {"crew_id": "crew-cli", "status": "running"},
            },
        )()

    def status(self, **kwargs):
        self.calls.append({"method": "status", **kwargs})
        return {"crew": {"crew_id": kwargs["crew_id"]}}

    def status_worker(self, **kwargs):
        self.calls.append({"method": "status_worker", **kwargs})
        return {"running": True}

    def stop_worker(self, **kwargs):
        self.calls.append({"method": "stop_worker", **kwargs})
        return {"stopped": True, "worker_id": kwargs["worker_id"]}

    def stop(self, **kwargs):
        self.calls.append({"method": "stop", **kwargs})
        return {"crew_id": kwargs["crew_id"], "stopped_workers": [{"worker_id": "worker-explorer"}]}

class FakeV4MergeTransaction:
    def __init__(self, response=None):
        self.response = response or {"crew_id": "crew-cli", "status": "accepted"}
        self.calls = []

    def accept(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class FakeV4CrewRunner:
    def __init__(self):
        self.calls = []

    def run(self, **kwargs):
        self.calls.append({"method": "run", **kwargs})
        return {"crew_id": "crew-cli", "status": "ready_for_codex_accept", "runtime": "v4"}


def test_build_parser_exposes_crew_start_and_worker_commands():
    from codex_claude_orchestrator.cli import build_parser

    parser = build_parser()
    subparsers_action = next(action for action in parser._actions if action.dest == "command")

    assert "crew" in subparsers_action.choices


def test_main_crew_start_prints_json_and_propagates_dirty_flag(tmp_path: Path, monkeypatch):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    fake_controller = FakeCrewController()
    monkeypatch.setattr("codex_claude_orchestrator.cli.build_crew_controller", lambda repo_root: fake_controller)

    stdout = StringIO()
    with redirect_stdout(stdout):
        exit_code = main(
            [
                "crew",
                "start",
                "--repo",
                str(repo_root),
                "--goal",
                "Build V3 MVP",
                "--workers",
                "explorer,implementer",
                "--allow-dirty-base",
            ]
        )

    payload = json.loads(stdout.getvalue())
    assert exit_code == 0
    assert payload["crew_id"] == "crew-cli"
    assert fake_controller.calls[0]["allow_dirty_base"] is True


def test_main_crew_start_defaults_to_dynamic_control_plane(tmp_path: Path, monkeypatch):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    fake_controller = FakeCrewController()
    monkeypatch.setattr("codex_claude_orchestrator.cli.build_crew_controller", lambda repo_root: fake_controller)

    stdout = StringIO()
    with redirect_stdout(stdout):
        exit_code = main(
            [
                "crew",
                "start",
                "--repo",
                str(repo_root),
                "--goal",
                "修复 README typo",
            ]
        )

    payload = json.loads(stdout.getvalue())
    assert exit_code == 0
    assert payload["spawn_policy"] == "dynamic"
    assert fake_controller.calls[0]["method"] == "start_dynamic"


def test_main_crew_stop_and_worker_stop_route_to_controller(tmp_path: Path, monkeypatch):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    fake_controller = FakeCrewController()
    monkeypatch.setattr("codex_claude_orchestrator.cli.build_crew_controller", lambda repo_root: fake_controller)

    stdout = StringIO()
    with redirect_stdout(stdout):
        worker_stop_exit = main(
            [
                "crew",
                "worker",
                "stop",
                "--repo",
                str(repo_root),
                "--crew",
                "crew-cli",
                "--worker",
                "worker-explorer",
            ]
        )
    worker_payload = json.loads(stdout.getvalue())

    stdout = StringIO()
    with redirect_stdout(stdout):
        crew_stop_exit = main(["crew", "stop", "--repo", str(repo_root), "--crew", "crew-cli"])
    crew_payload = json.loads(stdout.getvalue())

    assert worker_stop_exit == 0
    assert crew_stop_exit == 0
    assert worker_payload["stopped"] is True
    assert crew_payload["stopped_workers"][0]["worker_id"] == "worker-explorer"
    assert [call["method"] for call in fake_controller.calls] == ["stop_worker", "stop"]


def test_main_crew_worker_stop_accepts_workspace_cleanup_policy(tmp_path: Path, monkeypatch):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    fake_controller = FakeCrewController()
    monkeypatch.setattr("codex_claude_orchestrator.cli.build_crew_controller", lambda repo_root: fake_controller)

    stdout = StringIO()
    with redirect_stdout(stdout):
        exit_code = main(
            [
                "crew",
                "worker",
                "stop",
                "--repo",
                str(repo_root),
                "--crew",
                "crew-cli",
                "--worker",
                "worker-implementer",
                "--workspace-cleanup",
                "remove",
            ]
        )

    payload = json.loads(stdout.getvalue())
    assert exit_code == 0
    assert payload["stopped"] is True
    assert fake_controller.calls[0]["workspace_cleanup"] == "remove"


def test_main_crew_accept_routes_to_v4_merge_transaction(tmp_path: Path, monkeypatch):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    fake_controller = FakeCrewController()
    fake_transaction = FakeV4MergeTransaction(
        {"crew_id": "crew-cli", "status": "accepted", "summary": "accepted"}
    )
    monkeypatch.setattr("codex_claude_orchestrator.cli.build_crew_controller", lambda repo_root: fake_controller)
    monkeypatch.setattr(
        "codex_claude_orchestrator.cli.build_v4_merge_transaction",
        lambda repo_root, recorder, controller: fake_transaction,
    )

    stdout = StringIO()
    with redirect_stdout(stdout):
        exit_code = main(
            [
                "crew",
                "accept",
                "--repo",
                str(repo_root),
                "--crew",
                "crew-cli",
                "--summary",
                "accepted",
                "--verification-command",
                "pytest -q",
            ]
        )

    payload = json.loads(stdout.getvalue())
    assert exit_code == 0
    assert payload["status"] == "accepted"
    assert fake_transaction.calls == [
        {
            "crew_id": "crew-cli",
            "summary": "accepted",
            "verification_commands": ["pytest -q"],
        }
    ]
    assert fake_controller.calls == []


def test_main_crew_accept_without_verification_command_is_blocked(
    tmp_path: Path,
    monkeypatch,
):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    fake_controller = FakeCrewController()
    fake_transaction = FakeV4MergeTransaction(
        {
            "crew_id": "crew-cli",
            "status": "blocked",
            "reason": "verification command required",
        }
    )
    monkeypatch.setattr("codex_claude_orchestrator.cli.build_crew_controller", lambda repo_root: fake_controller)
    monkeypatch.setattr(
        "codex_claude_orchestrator.cli.build_v4_merge_transaction",
        lambda repo_root, recorder, controller: fake_transaction,
    )

    stdout = StringIO()
    with redirect_stdout(stdout):
        exit_code = main(
            [
                "crew",
                "accept",
                "--repo",
                str(repo_root),
                "--crew",
                "crew-cli",
                "--summary",
                "accepted",
            ]
        )

    payload = json.loads(stdout.getvalue())
    assert exit_code == 0
    assert payload["status"] == "blocked"
    assert payload["reason"] == "verification command required"
    assert fake_transaction.calls[0]["verification_commands"] == []
    assert fake_controller.calls == []


def test_main_crew_run_routes_to_v4_crew_runner_by_default(
    tmp_path: Path,
    monkeypatch,
):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    fake_controller = FakeCrewController()
    fake_runner = FakeV4CrewRunner()
    monkeypatch.setattr("codex_claude_orchestrator.cli.build_crew_controller", lambda repo_root: fake_controller)
    monkeypatch.setattr(
        "codex_claude_orchestrator.cli.build_v4_crew_runner",
        lambda repo_root, controller, poll_timeout=1800.0, poll_retries=3: fake_runner,
    )

    stdout = StringIO()
    with redirect_stdout(stdout):
        run_exit = main(
            [
                "crew",
                "run",
                "--repo",
                str(repo_root),
                "--goal",
                "Build V3 MVP",
                "--verification-command",
                "pytest -q",
                "--max-rounds",
                "3",
                "--poll-interval",
                "0",
                "--allow-dirty-base",
            ]
        )
    run_payload = json.loads(stdout.getvalue())

    assert run_exit == 0
    assert run_payload["crew_id"] == "crew-cli"
    assert run_payload["runtime"] == "v4"
    assert fake_runner.calls == [
        {
            "method": "run",
            "repo_root": repo_root.resolve(),
            "goal": "Build V3 MVP",
            "verification_commands": ["pytest -q"],
            "max_rounds": 3,
            "poll_interval_seconds": 0.0,
            "allow_dirty_base": True,
            "spawn_policy": "dynamic",
            "seed_contract": None,
        },
    ]


def test_main_crew_run_defaults_to_dynamic_even_for_review_heavy_goal(tmp_path: Path, monkeypatch):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    fake_controller = FakeCrewController()
    fake_runner = FakeV4CrewRunner()
    monkeypatch.setattr("codex_claude_orchestrator.cli.build_crew_controller", lambda repo_root: fake_controller)
    monkeypatch.setattr(
        "codex_claude_orchestrator.cli.build_v4_crew_runner",
        lambda repo_root, controller, poll_timeout=1800.0, poll_retries=3: fake_runner,
    )

    stdout = StringIO()
    with redirect_stdout(stdout):
        exit_code = main(
            [
                "crew",
                "run",
                "--repo",
                str(repo_root),
                "--goal",
                "让 Claude 检查这个项目，根据 llm-wiki 思想完善代码",
                "--verification-command",
                "pytest -q",
                "--poll-interval",
                "0",
            ]
        )

    payload = json.loads(stdout.getvalue())
    assert exit_code == 0
    assert payload["spawn_policy"] == "dynamic"
    assert fake_runner.calls[0]["spawn_policy"] == "dynamic"
    assert "worker_roles" not in fake_runner.calls[0]


def test_main_crew_run_can_use_static_legacy_worker_selection(tmp_path: Path, monkeypatch):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    fake_controller = FakeCrewController()
    fake_runner = FakeV4CrewRunner()
    monkeypatch.setattr("codex_claude_orchestrator.cli.build_crew_controller", lambda repo_root: fake_controller)
    monkeypatch.setattr(
        "codex_claude_orchestrator.cli.build_v4_crew_runner",
        lambda repo_root, controller, poll_timeout=1800.0, poll_retries=3: fake_runner,
    )

    stdout = StringIO()
    with redirect_stdout(stdout):
        exit_code = main(
            [
                "crew",
                "run",
                "--repo",
                str(repo_root),
                "--goal",
                "让 Claude 检查这个项目，根据 llm-wiki 思想完善代码",
                "--verification-command",
                "pytest -q",
                "--poll-interval",
                "0",
                "--spawn-policy",
                "static",
            ]
        )

    payload = json.loads(stdout.getvalue())
    assert exit_code == 0
    assert payload["selected_workers"] == ["explorer", "implementer", "reviewer"]
    assert payload["selection_mode"] == "full"
    assert fake_runner.calls[0]["worker_roles"] == [WorkerRole.EXPLORER, WorkerRole.IMPLEMENTER, WorkerRole.REVIEWER]


def test_cli_crew_event_store_health_prints_factory_health(tmp_path, monkeypatch):
    from codex_claude_orchestrator.cli import main

    class FakeStore:
        def health(self):
            return {
                "backend": "fake",
                "ok": True,
                "expected_schema_version": 2,
                "latest_schema_version": 2,
            }

    monkeypatch.setattr("codex_claude_orchestrator.cli.build_v4_event_store", lambda repo_root, *, readonly=False: FakeStore())

    stdout = StringIO()
    with redirect_stdout(stdout):
        result = main(["crew", "event-store-health", "--repo", str(tmp_path)])

    payload = json.loads(stdout.getvalue())
    assert result == 0
    assert payload["backend"] == "fake"
    assert payload["ok"] is True


def test_cli_crew_status_uses_v4_projection_when_events_exist(tmp_path, monkeypatch):
    from codex_claude_orchestrator.cli import main
    from codex_claude_orchestrator.v4.events import AgentEvent

    class FakeStore:
        def list_stream(self, stream_id: str, after_sequence: int = 0):
            return [
                AgentEvent(
                    event_id="evt-1",
                    stream_id=stream_id,
                    sequence=1,
                    type="crew.started",
                    crew_id=stream_id,
                    payload={"goal": "Fix tests"},
                ),
                AgentEvent(
                    event_id="evt-2",
                    stream_id=stream_id,
                    sequence=2,
                    type="crew.ready_for_accept",
                    crew_id=stream_id,
                ),
            ]

    fake_controller = FakeCrewController()
    monkeypatch.setattr("codex_claude_orchestrator.cli.build_v4_event_store", lambda repo_root, *, readonly=False: FakeStore())
    monkeypatch.setattr("codex_claude_orchestrator.cli.build_crew_controller", lambda repo_root: fake_controller)

    stdout = StringIO()
    with redirect_stdout(stdout):
        result = main(["crew", "status", "--repo", str(tmp_path), "--crew", "crew-1"])

    payload = json.loads(stdout.getvalue())
    assert result == 0
    assert payload["runtime"] == "v4"
    assert payload["crew"]["crew_id"] == "crew-1"
    assert payload["crew"]["status"] == "ready"
    assert payload["crew"]["root_goal"] == "Fix tests"
    assert fake_controller.calls == []
