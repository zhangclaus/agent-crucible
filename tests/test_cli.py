from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path

from codex_claude_orchestrator.cli import main
from codex_claude_orchestrator.models import EvaluationOutcome, NextAction


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
