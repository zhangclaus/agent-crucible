import shlex
import sys
from pathlib import Path

from codex_claude_orchestrator.v4.adapters.verification import VerificationAdapter
from codex_claude_orchestrator.v4.artifacts import ArtifactStore


PYTHON = shlex.quote(sys.executable)


def test_verification_adapter_records_passed_command(tmp_path: Path):
    adapter = VerificationAdapter(artifact_store=ArtifactStore(tmp_path / "artifacts"))

    result = adapter.run(command=f"{PYTHON} -c 'print(123)'", cwd=tmp_path, verification_id="verification-1")

    assert result["passed"] is True
    assert result["exit_code"] == 0
    assert result["stdout_artifact"] == "verification/verification-1/stdout.txt"
    assert "123" in (tmp_path / "artifacts" / result["stdout_artifact"]).read_text(encoding="utf-8")


def test_verification_adapter_records_failed_command(tmp_path: Path):
    adapter = VerificationAdapter(artifact_store=ArtifactStore(tmp_path / "artifacts"))

    result = adapter.run(
        command=f"{PYTHON} -c 'import sys; print(\"bad\"); sys.exit(3)'",
        cwd=tmp_path,
        verification_id="verification-2",
    )

    assert result["passed"] is False
    assert result["exit_code"] == 3
    assert "bad" in (tmp_path / "artifacts" / result["stdout_artifact"]).read_text(encoding="utf-8")


def test_verification_adapter_records_empty_command_setup_error(tmp_path: Path):
    adapter = VerificationAdapter(artifact_store=ArtifactStore(tmp_path / "artifacts"))

    result = adapter.run(command="", cwd=tmp_path, verification_id="verification-empty")

    assert result["passed"] is False
    assert result["exit_code"] is None
    stderr = (tmp_path / "artifacts" / result["stderr_artifact"]).read_text(encoding="utf-8")
    assert "empty command" in stderr


def test_verification_adapter_records_malformed_quoting_setup_error(tmp_path: Path):
    adapter = VerificationAdapter(artifact_store=ArtifactStore(tmp_path / "artifacts"))

    result = adapter.run(command=f"{PYTHON} -c 'print(123)", cwd=tmp_path, verification_id="verification-quote")

    assert result["passed"] is False
    assert result["exit_code"] is None
    stderr = (tmp_path / "artifacts" / result["stderr_artifact"]).read_text(encoding="utf-8")
    assert "command setup failed" in stderr
    assert "No closing quotation" in stderr


def test_verification_adapter_records_missing_executable_setup_error(tmp_path: Path):
    adapter = VerificationAdapter(artifact_store=ArtifactStore(tmp_path / "artifacts"))

    result = adapter.run(command="./missing-executable --version", cwd=tmp_path, verification_id="verification-missing")

    assert result["passed"] is False
    assert result["exit_code"] is None
    stderr = (tmp_path / "artifacts" / result["stderr_artifact"]).read_text(encoding="utf-8")
    assert "command setup failed" in stderr
    assert "missing-executable" in stderr


def test_verification_adapter_records_non_executable_setup_error(tmp_path: Path):
    adapter = VerificationAdapter(artifact_store=ArtifactStore(tmp_path / "artifacts"))
    not_executable = tmp_path / "not-exec"
    not_executable.write_text("#!/bin/sh\necho nope\n", encoding="utf-8")
    not_executable.chmod(0o644)

    result = adapter.run(command="./not-exec", cwd=tmp_path, verification_id="verification-not-exec")

    assert result["passed"] is False
    assert result["exit_code"] is None
    stderr = (tmp_path / "artifacts" / result["stderr_artifact"]).read_text(encoding="utf-8")
    assert "command setup failed" in stderr
    assert "not-exec" in stderr


def test_verification_adapter_records_timeout(tmp_path: Path):
    adapter = VerificationAdapter(artifact_store=ArtifactStore(tmp_path / "artifacts"), timeout_seconds=0.01)

    result = adapter.run(
        command=f"{PYTHON} -c 'import time; time.sleep(1)'",
        cwd=tmp_path,
        verification_id="verification-timeout",
    )

    assert result["passed"] is False
    assert result["exit_code"] is None
    assert result["summary"] == "command timed out after 0.01s"
    stderr = (tmp_path / "artifacts" / result["stderr_artifact"]).read_text(encoding="utf-8")
    assert "command timed out after 0.01s" in stderr
