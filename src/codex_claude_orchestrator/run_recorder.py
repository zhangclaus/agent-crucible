from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from codex_claude_orchestrator.models import (
    EvaluationOutcome,
    EventRecord,
    RunRecord,
    TaskRecord,
    WorkerResult,
)


class RunRecorder:
    def __init__(self, state_root: Path):
        self._state_root = state_root
        self._runs_root = state_root / "runs"
        self._runs_root.mkdir(parents=True, exist_ok=True)

    def start_run(self, run: RunRecord, task: TaskRecord, compiled_prompt: Any | None = None) -> Path:
        run_dir = self._run_dir(run.run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        self._write_json(run_dir / "task.json", task.to_dict())
        self._write_json(run_dir / "run.json", run.to_dict())
        if compiled_prompt is not None:
            prompt_text = "\n\n".join(
                [
                    "SYSTEM:",
                    compiled_prompt.system_prompt,
                    "USER:",
                    compiled_prompt.user_prompt,
                ]
            )
            self.write_text_artifact(run.run_id, "prompt.txt", prompt_text)
            self._write_json(run_dir / "artifacts" / "prompt_metadata.json", compiled_prompt.metadata)
            self._write_json(run_dir / "artifacts" / "output_schema.json", compiled_prompt.schema)
        return run_dir

    def append_event(self, run_id: str, event: EventRecord) -> None:
        run_dir = self._run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        events_path = run_dir / "events.jsonl"
        with events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")

    def write_result(self, run_id: str, result: WorkerResult, evaluation: EvaluationOutcome) -> None:
        run_dir = self._run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        self._write_json(run_dir / "result.json", result.to_dict())
        self._write_json(run_dir / "evaluation.json", evaluation.to_dict())
        self.write_text_artifact(run_id, "stdout.txt", result.stdout)
        self.write_text_artifact(run_id, "stderr.txt", result.stderr)

    def write_text_artifact(self, run_id: str, artifact_name: str, content: str) -> Path:
        artifacts_dir = self._run_dir(run_id) / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = artifacts_dir / artifact_name
        self._write_text(artifact_path, content)
        return artifact_path

    def _run_dir(self, run_id: str) -> Path:
        return self._runs_root / run_id

    def _write_json(self, path: Path, payload: dict) -> None:
        self._write_text(path, json.dumps(payload, indent=2, ensure_ascii=False))

    def _write_text(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f".{path.name}.tmp")
        tmp_path.write_text(content, encoding="utf-8")
        tmp_path.replace(path)
