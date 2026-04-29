from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from pathlib import Path
from subprocess import CompletedProcess
from typing import Any
from uuid import uuid4

from codex_claude_orchestrator.models import utc_now


CommandRunner = Callable[..., CompletedProcess[str]]


class ClaudeBridge:
    def __init__(
        self,
        state_root: Path,
        *,
        runner: CommandRunner | None = None,
        bridge_id_factory: Callable[[], str] | None = None,
        turn_id_factory: Callable[[], str] | None = None,
    ):
        self._state_root = state_root
        self._bridges_root = state_root / "claude-bridge"
        self._bridges_root.mkdir(parents=True, exist_ok=True)
        self._runner = runner or subprocess.run
        self._bridge_id_factory = bridge_id_factory or (lambda: f"bridge-{uuid4().hex}")
        self._turn_id_factory = turn_id_factory or (lambda: f"turn-{uuid4().hex}")

    def start(
        self,
        *,
        repo_root: Path,
        goal: str,
        workspace_mode: str = "readonly",
        dry_run: bool = False,
    ) -> dict[str, Any]:
        repo = self._resolve_repo(repo_root)
        bridge_id = self._bridge_id_factory()
        created_at = utc_now()
        record = {
            "bridge_id": bridge_id,
            "repo": str(repo),
            "goal": goal,
            "workspace_mode": workspace_mode,
            "status": "created",
            "claude_session_id": None,
            "turn_count": 0,
            "created_at": created_at,
            "updated_at": created_at,
        }
        bridge_dir = self._bridge_dir(bridge_id)
        bridge_dir.mkdir(parents=True, exist_ok=False)
        self._write_record(bridge_id, record)

        turn = self._run_turn(
            repo=repo,
            bridge_id=bridge_id,
            turn_kind="start",
            message=self._render_start_prompt(repo, goal, workspace_mode),
            workspace_mode=workspace_mode,
            resume_session_id=None,
            dry_run=dry_run,
        )
        record = self._advance_record(record, turn, dry_run=dry_run)
        self._write_record(bridge_id, record)
        self._write_latest(bridge_id)
        return {"bridge": record, "latest_turn": turn}

    def send(
        self,
        *,
        repo_root: Path,
        bridge_id: str | None,
        message: str,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        repo = self._resolve_repo(repo_root)
        resolved_bridge_id = self._resolve_bridge_id(bridge_id)
        record = self._read_record(resolved_bridge_id)
        resume_session_id = record.get("claude_session_id")
        if not resume_session_id and not dry_run:
            raise ValueError(f"bridge {resolved_bridge_id} has no Claude session id")

        turn = self._run_turn(
            repo=repo,
            bridge_id=resolved_bridge_id,
            turn_kind="send",
            message=message,
            workspace_mode=str(record["workspace_mode"]),
            resume_session_id=str(resume_session_id) if resume_session_id else None,
            dry_run=dry_run,
        )
        record = self._advance_record(record, turn, dry_run=dry_run)
        self._write_record(resolved_bridge_id, record)
        self._write_latest(resolved_bridge_id)
        return {"bridge": record, "latest_turn": turn}

    def tail(self, *, repo_root: Path, bridge_id: str | None, limit: int = 5) -> dict[str, Any]:
        self._resolve_repo(repo_root)
        resolved_bridge_id = self._resolve_bridge_id(bridge_id)
        record = self._read_record(resolved_bridge_id)
        turns = self._read_turns(resolved_bridge_id)
        if limit >= 0:
            turns = turns[-limit:] if limit else []
        return {"bridge": record, "turns": turns}

    def list(self, *, repo_root: Path) -> list[dict[str, Any]]:
        self._resolve_repo(repo_root)
        bridges = []
        for path in self._iter_bridge_dirs():
            record = self._read_record(path.name)
            bridges.append(
                {
                    "bridge_id": record["bridge_id"],
                    "repo": record["repo"],
                    "goal": record["goal"],
                    "workspace_mode": record["workspace_mode"],
                    "status": record["status"],
                    "claude_session_id": record.get("claude_session_id"),
                    "turn_count": record["turn_count"],
                    "created_at": record["created_at"],
                    "updated_at": record["updated_at"],
                }
            )
        return sorted(bridges, key=lambda item: item["updated_at"], reverse=True)

    def _run_turn(
        self,
        *,
        repo: Path,
        bridge_id: str,
        turn_kind: str,
        message: str,
        workspace_mode: str,
        resume_session_id: str | None,
        dry_run: bool,
    ) -> dict[str, Any]:
        command = self._build_command(
            message=message,
            workspace_mode=workspace_mode,
            resume_session_id=resume_session_id,
        )
        if dry_run:
            completed = CompletedProcess(command, 0, stdout="", stderr="")
        else:
            completed = self._runner(
                command,
                cwd=str(repo),
                text=True,
                capture_output=True,
                check=False,
            )

        parsed = self._parse_stdout(completed.stdout or "")
        turn = {
            "turn_id": self._turn_id_factory(),
            "kind": turn_kind,
            "message": message,
            "command": command,
            "returncode": completed.returncode,
            "stdout": completed.stdout or "",
            "stderr": completed.stderr or "",
            "result_text": parsed["result_text"],
            "claude_session_id": parsed["session_id"],
            "parse_error": parsed["parse_error"],
            "created_at": utc_now(),
        }
        self._append_turn(bridge_id, turn)
        return turn

    def _build_command(
        self,
        *,
        message: str,
        workspace_mode: str,
        resume_session_id: str | None,
    ) -> list[str]:
        command = [
            "claude",
            "--print",
            message,
            "--output-format",
            "json",
            "--permission-mode",
            "auto",
        ]
        if resume_session_id:
            command.extend(["--resume", resume_session_id])
        allowed_tools = self._allowed_tools(workspace_mode)
        if allowed_tools:
            command.extend(["--allowedTools", ",".join(allowed_tools)])
        return command

    def _allowed_tools(self, workspace_mode: str) -> list[str]:
        if workspace_mode == "readonly":
            return ["Read", "Glob", "Grep", "LS"]
        return []

    def _render_start_prompt(self, repo: Path, goal: str, workspace_mode: str) -> str:
        lines = [
            "You are Claude Code being controlled by Codex through a long-dialogue bridge.",
            f"Repository: {repo}",
            f"Goal: {goal}",
            f"Workspace mode: {workspace_mode}",
        ]
        if workspace_mode == "readonly":
            lines.append("Do not modify files. Use read-only inspection tools and report findings.")
        else:
            lines.append("Preserve unrelated user work and summarize every file you change.")
        lines.extend(
            [
                "",
                "After each turn, answer with:",
                "- what you did",
                "- important findings or changes",
                "- verification performed",
                "- what you need next from Codex or the user",
            ]
        )
        return "\n".join(lines) + "\n"

    def _parse_stdout(self, stdout: str) -> dict[str, str | None]:
        if not stdout.strip():
            return {"session_id": None, "result_text": "", "parse_error": None}
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError as exc:
            return {
                "session_id": None,
                "result_text": stdout.strip(),
                "parse_error": str(exc),
            }
        if not isinstance(payload, dict):
            return {
                "session_id": None,
                "result_text": stdout.strip(),
                "parse_error": "Claude output was not a JSON object",
            }
        result = payload.get("result", "")
        if isinstance(result, str):
            result_text = result
        elif result is None:
            result_text = ""
        else:
            result_text = json.dumps(result, ensure_ascii=False)
        session_id = payload.get("session_id")
        return {
            "session_id": session_id if isinstance(session_id, str) else None,
            "result_text": result_text,
            "parse_error": None,
        }

    def _advance_record(self, record: dict[str, Any], turn: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
        updated = dict(record)
        if turn.get("claude_session_id"):
            updated["claude_session_id"] = turn["claude_session_id"]
        if not dry_run:
            updated["status"] = "active" if turn["returncode"] == 0 else "failed"
        updated["turn_count"] = int(updated["turn_count"]) + 1
        updated["updated_at"] = turn["created_at"]
        return updated

    def _resolve_repo(self, repo_root: Path) -> Path:
        repo = repo_root.resolve()
        if not repo.is_dir():
            raise FileNotFoundError(f"repo not found: {repo}")
        return repo

    def _resolve_bridge_id(self, bridge_id: str | None) -> str:
        if bridge_id:
            return bridge_id
        latest_path = self._bridges_root / "latest"
        if not latest_path.exists():
            raise FileNotFoundError("latest Claude bridge not found")
        return latest_path.read_text(encoding="utf-8").strip()

    def _write_latest(self, bridge_id: str) -> None:
        self._write_text(self._bridges_root / "latest", bridge_id)

    def _iter_bridge_dirs(self) -> list[Path]:
        if not self._bridges_root.exists():
            return []
        return [path for path in self._bridges_root.iterdir() if path.is_dir()]

    def _bridge_dir(self, bridge_id: str) -> Path:
        return self._bridges_root / bridge_id

    def _read_record(self, bridge_id: str) -> dict[str, Any]:
        record_path = self._bridge_dir(bridge_id) / "record.json"
        if not record_path.exists():
            raise FileNotFoundError(f"Claude bridge not found: {bridge_id}")
        return json.loads(record_path.read_text(encoding="utf-8"))

    def _write_record(self, bridge_id: str, record: dict[str, Any]) -> None:
        self._write_json(self._bridge_dir(bridge_id) / "record.json", record)

    def _append_turn(self, bridge_id: str, turn: dict[str, Any]) -> None:
        turns_path = self._bridge_dir(bridge_id) / "turns.jsonl"
        turns_path.parent.mkdir(parents=True, exist_ok=True)
        with turns_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(turn, ensure_ascii=False) + "\n")

    def _read_turns(self, bridge_id: str) -> list[dict[str, Any]]:
        turns_path = self._bridge_dir(bridge_id) / "turns.jsonl"
        if not turns_path.exists():
            return []
        return [json.loads(line) for line in turns_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        self._write_text(path, json.dumps(payload, indent=2, ensure_ascii=False))

    def _write_text(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f".{path.name}.tmp")
        tmp_path.write_text(content, encoding="utf-8")
        tmp_path.replace(path)
