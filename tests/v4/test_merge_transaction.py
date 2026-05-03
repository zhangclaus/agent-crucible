from __future__ import annotations

import json
from pathlib import Path
import subprocess
from subprocess import CompletedProcess
import sys

from codex_claude_orchestrator.crew.models import CrewRecord
from codex_claude_orchestrator.state.crew_recorder import CrewRecorder
from codex_claude_orchestrator.v4.event_store import SQLiteEventStore
from codex_claude_orchestrator.v4.merge_transaction import V4MergeTransaction
from codex_claude_orchestrator.v4.merge_inputs import V4MergeInputRecorder
from codex_claude_orchestrator.v4.paths import V4Paths


def test_merge_transaction_applies_verified_patch_and_accepts_crew(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    recorder = _crew_with_patch(repo_root, tmp_path, base_ref="base-sha")
    store = SQLiteEventStore(tmp_path / "events.sqlite3")
    _record_ready_events(store)
    git = FakeGitRunner(heads=["base-sha", "base-sha"])
    verifier = FakeCommandRunner([0])
    stopped = []

    result = V4MergeTransaction(
        repo_root=repo_root,
        recorder=recorder,
        event_store=store,
        git_runner=git,
        command_runner=verifier,
        stop_workers=lambda **kwargs: stopped.append(kwargs) or {"stopped": True},
    ).accept(
        crew_id="crew-1",
        summary="accepted",
        verification_commands=["python -c 'print(123)'"],
    )

    details = recorder.read_crew("crew-1")
    assert result["status"] == "accepted"
    assert details["crew"]["status"] == "accepted"
    assert details["final_report"]["status"] == "accepted"
    assert stopped == [{"repo_root": repo_root, "crew_id": "crew-1"}]
    assert ["worktree", "add", "--detach"] in [call["args"][:3] for call in git.calls]
    assert any(call["args"][:2] == ["apply", "--check"] for call in git.calls)
    assert any(call["args"][:1] == ["apply"] and call["cwd"] == repo_root for call in git.calls)
    assert verifier.calls[0]["cwd"].name.startswith("integration-")


def test_merge_transaction_prefers_v4_merge_inputs_over_legacy_changes(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    recorder = _crew_with_patch(
        repo_root,
        tmp_path,
        base_ref="base-sha",
        patch_path="src/legacy.py",
    )
    store = SQLiteEventStore(tmp_path / "events.sqlite3")
    _record_ready_events(store)
    paths = V4Paths(repo_root=repo_root, crew_id="crew-1")
    legacy_root = paths.crew_root / "artifacts"
    legacy_patch = legacy_root / "workers/worker-1/diff.patch"
    legacy_patch.parent.mkdir(parents=True, exist_ok=True)
    legacy_patch.write_text(_patch_for("src/app.py"), encoding="utf-8")
    V4MergeInputRecorder(event_store=store, paths=paths).record_from_changes(
        changes={
            "worker_id": "worker-1",
            "base_ref": "base-sha",
            "changed_files": ["src/app.py"],
            "artifact": "workers/worker-1/changes.json",
            "diff_artifact": "workers/worker-1/diff.patch",
        },
        turn_id="round-1-worker-1-source",
        round_id="round-1",
        contract_id="source_write",
    )
    git = FakeGitRunner(heads=["base-sha", "base-sha"])

    result = V4MergeTransaction(
        repo_root=repo_root,
        recorder=recorder,
        event_store=store,
        git_runner=git,
        command_runner=FakeCommandRunner([0]),
    ).accept(
        crew_id="crew-1",
        summary="accepted",
        verification_commands=["python -c 'print(123)'"],
    )

    assert result["status"] == "accepted"
    combined_patch = next(
        artifact
        for artifact in recorder.read_crew("crew-1")["artifacts"]
        if artifact.startswith("merge/combined-")
    )
    assert combined_patch.startswith("merge/combined-")
    assert "src/app.py" in (recorder._crew_dir("crew-1") / "artifacts" / combined_patch).read_text(encoding="utf-8")
    assert "src/legacy.py" not in (recorder._crew_dir("crew-1") / "artifacts" / combined_patch).read_text(encoding="utf-8")
    assert "merge.legacy_patch_source_used" not in [event.type for event in store.list_stream("crew-1")]


def test_merge_transaction_falls_back_to_legacy_changes_and_records_evidence(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    recorder = _crew_with_patch(repo_root, tmp_path, base_ref="base-sha")
    store = SQLiteEventStore(tmp_path / "events.sqlite3")
    _record_ready_events(store)

    result = V4MergeTransaction(
        repo_root=repo_root,
        recorder=recorder,
        event_store=store,
        git_runner=FakeGitRunner(heads=["base-sha", "base-sha"]),
        command_runner=FakeCommandRunner([0]),
    ).accept(
        crew_id="crew-1",
        summary="accepted",
        verification_commands=["python -c 'print(123)'"],
    )

    assert result["status"] == "accepted"
    legacy_events = [event for event in store.list_stream("crew-1") if event.type == "merge.legacy_patch_source_used"]
    assert len(legacy_events) == 1
    assert legacy_events[0].payload["worker_ids"] == ["worker-1"]


def test_merge_transaction_blocks_v4_merge_input_with_bad_patch_sha(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    recorder = _crew_with_patch(repo_root, tmp_path, base_ref="base-sha")
    store = SQLiteEventStore(tmp_path / "events.sqlite3")
    _record_ready_events(store)
    paths = V4Paths(repo_root=repo_root, crew_id="crew-1")
    legacy_patch = paths.crew_root / "artifacts/workers/worker-1/diff.patch"
    legacy_patch.parent.mkdir(parents=True, exist_ok=True)
    legacy_patch.write_text(_patch_for("src/app.py"), encoding="utf-8")
    manifest = V4MergeInputRecorder(event_store=store, paths=paths).record_from_changes(
        changes={
            "worker_id": "worker-1",
            "base_ref": "base-sha",
            "changed_files": ["src/app.py"],
            "artifact": "workers/worker-1/changes.json",
            "diff_artifact": "workers/worker-1/diff.patch",
        },
        turn_id="round-1-worker-1-source",
        round_id="round-1",
        contract_id="source_write",
    )
    paths.patch_path("worker-1", "round-1-worker-1-source").write_text(
        _patch_for("src/other.py"),
        encoding="utf-8",
    )

    result = V4MergeTransaction(
        repo_root=repo_root,
        recorder=recorder,
        event_store=store,
        git_runner=FakeGitRunner(heads=["base-sha"]),
        command_runner=FakeCommandRunner([0]),
    ).accept(
        crew_id="crew-1",
        summary="accepted",
        verification_commands=["python -c 'print(123)'"],
    )

    assert manifest["patch_sha256"]
    assert result["status"] == "blocked"
    assert result["reason"] == "invalid v4 merge input"
    assert result["errors"] == ["patch sha256 does not match manifest for worker worker-1"]


def test_merge_transaction_applies_patch_in_real_git_repo(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _run_git(["init"], repo_root)
    _run_git(["config", "user.email", "codex@example.test"], repo_root)
    _run_git(["config", "user.name", "Codex"], repo_root)
    (repo_root / "src").mkdir()
    (repo_root / "src" / "app.py").write_text("", encoding="utf-8")
    _run_git(["add", "src/app.py"], repo_root)
    _run_git(["commit", "-m", "base"], repo_root)
    base_ref = _run_git(["rev-parse", "HEAD"], repo_root).stdout.strip()

    (repo_root / "src" / "app.py").write_text("hello\n", encoding="utf-8")
    patch = _run_git(["diff", "--binary", "HEAD"], repo_root).stdout
    (repo_root / "src" / "app.py").write_text("", encoding="utf-8")
    recorder = _crew_with_patch(
        repo_root,
        tmp_path,
        base_ref=base_ref,
        patch=patch,
    )
    store = SQLiteEventStore(tmp_path / "events.sqlite3")
    _record_ready_events(store)

    result = V4MergeTransaction(
        repo_root=repo_root,
        recorder=recorder,
        event_store=store,
        stop_workers=lambda **_: {"stopped": True},
    ).accept(
        crew_id="crew-1",
        summary="accepted",
        verification_commands=[
            f"{sys.executable} -c \"from pathlib import Path; assert Path('src/app.py').read_text() == 'hello\\\\n'\""
        ],
    )

    assert result["status"] == "accepted"
    assert (repo_root / "src" / "app.py").read_text(encoding="utf-8") == "hello\n"


def test_merge_transaction_ignores_in_repo_orchestrator_state_for_dirty_checks(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _run_git(["init"], repo_root)
    _run_git(["config", "user.email", "codex@example.test"], repo_root)
    _run_git(["config", "user.name", "Codex"], repo_root)
    (repo_root / "src").mkdir()
    (repo_root / "src" / "app.py").write_text("", encoding="utf-8")
    _run_git(["add", "src/app.py"], repo_root)
    _run_git(["commit", "-m", "base"], repo_root)
    base_ref = _run_git(["rev-parse", "HEAD"], repo_root).stdout.strip()

    (repo_root / "src" / "app.py").write_text("hello\n", encoding="utf-8")
    patch = _run_git(["diff", "--binary", "HEAD"], repo_root).stdout
    (repo_root / "src" / "app.py").write_text("", encoding="utf-8")
    recorder = _crew_with_patch(
        repo_root,
        tmp_path,
        base_ref=base_ref,
        patch=patch,
        state_root=repo_root / ".orchestrator",
    )
    store = SQLiteEventStore(tmp_path / "events.sqlite3")
    _record_ready_events(store)

    result = V4MergeTransaction(
        repo_root=repo_root,
        recorder=recorder,
        event_store=store,
        stop_workers=lambda **_: {"stopped": True},
    ).accept(
        crew_id="crew-1",
        summary="accepted",
        verification_commands=[
            f"{sys.executable} -c \"from pathlib import Path; assert Path('src/app.py').read_text() == 'hello\\\\n'\""
        ],
    )

    assert result["status"] == "accepted"
    assert (repo_root / "src" / "app.py").read_text(encoding="utf-8") == "hello\n"


def test_merge_transaction_blocks_dirty_main_workspace(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    recorder = _crew_with_patch(repo_root, tmp_path, base_ref="base-sha")
    store = SQLiteEventStore(tmp_path / "events.sqlite3")
    _record_ready_events(store)
    git = FakeGitRunner(statuses=[" M src/app.py\n"], heads=["base-sha"])

    result = V4MergeTransaction(
        repo_root=repo_root,
        recorder=recorder,
        event_store=store,
        git_runner=git,
        command_runner=FakeCommandRunner([0]),
    ).accept(
        crew_id="crew-1",
        summary="accepted",
        verification_commands=["python -c 'print(123)'"],
    )

    assert result["status"] == "blocked"
    assert result["reason"] == "main workspace has uncommitted changes"
    assert not any(call["args"][:2] == ["worktree", "add"] for call in git.calls)


def test_merge_transaction_blocks_base_ref_mismatch(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    recorder = _crew_with_patch(repo_root, tmp_path, base_ref="base-sha")
    store = SQLiteEventStore(tmp_path / "events.sqlite3")
    _record_ready_events(store)
    git = FakeGitRunner(heads=["other-sha"])

    result = V4MergeTransaction(
        repo_root=repo_root,
        recorder=recorder,
        event_store=store,
        git_runner=git,
        command_runner=FakeCommandRunner([0]),
    ).accept(
        crew_id="crew-1",
        summary="accepted",
        verification_commands=["python -c 'print(123)'"],
    )

    assert result["status"] == "blocked"
    assert result["reason"] == "main workspace base ref changed"


def test_merge_transaction_blocks_patch_outside_recorded_changed_files(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    recorder = _crew_with_patch(
        repo_root,
        tmp_path,
        base_ref="base-sha",
        changed_files=["src/app.py"],
        patch_path="src/other.py",
    )
    store = SQLiteEventStore(tmp_path / "events.sqlite3")
    _record_ready_events(store)

    result = V4MergeTransaction(
        repo_root=repo_root,
        recorder=recorder,
        event_store=store,
        git_runner=FakeGitRunner(heads=["base-sha"]),
        command_runner=FakeCommandRunner([0]),
    ).accept(
        crew_id="crew-1",
        summary="accepted",
        verification_commands=["python -c 'print(123)'"],
    )

    assert result["status"] == "blocked"
    assert result["reason"] == "patch touches paths outside recorded changed_files"
    assert result["paths"] == ["src/other.py"]


def test_merge_transaction_blocks_failed_final_verification(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    recorder = _crew_with_patch(repo_root, tmp_path, base_ref="base-sha")
    store = SQLiteEventStore(tmp_path / "events.sqlite3")
    _record_ready_events(store)
    git = FakeGitRunner(heads=["base-sha", "base-sha"])

    result = V4MergeTransaction(
        repo_root=repo_root,
        recorder=recorder,
        event_store=store,
        git_runner=git,
        command_runner=FakeCommandRunner([1]),
    ).accept(
        crew_id="crew-1",
        summary="accepted",
        verification_commands=["python -c 'raise SystemExit(1)'"],
    )

    assert result["status"] == "blocked"
    assert result["reason"] == "final verification failed"
    assert not any(call["args"][:1] == ["apply"] and call["cwd"] == repo_root for call in git.calls)


def test_merge_transaction_blocks_missing_ready_before_git(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    recorder = _crew_with_patch(repo_root, tmp_path, base_ref="base-sha")
    git = FakeGitRunner(heads=["base-sha"])

    result = V4MergeTransaction(
        repo_root=repo_root,
        recorder=recorder,
        event_store=SQLiteEventStore(tmp_path / "events.sqlite3"),
        git_runner=git,
        command_runner=FakeCommandRunner([0]),
    ).accept(
        crew_id="crew-1",
        summary="accepted",
        verification_commands=["python -c 'print(123)'"],
    )

    assert result["status"] == "blocked"
    assert result["reason"] == "missing_ready_for_accept"
    assert result["readiness"]["reason"] == "missing_ready_for_accept"
    assert git.calls == []


def test_merge_transaction_blocks_ready_round_with_no_worker_patches(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    recorder = _crew_without_patch(repo_root, tmp_path)
    store = SQLiteEventStore(tmp_path / "events.sqlite3")
    _record_ready_events(store)
    git = FakeGitRunner(heads=["base-sha"])

    result = V4MergeTransaction(
        repo_root=repo_root,
        recorder=recorder,
        event_store=store,
        git_runner=git,
        command_runner=FakeCommandRunner([0]),
    ).accept(
        crew_id="crew-1",
        summary="accepted",
        verification_commands=["python -c 'print(123)'"],
    )

    assert result["status"] == "blocked"
    assert result["reason"] == "no_worker_patches_for_ready_round"
    assert result["readiness"]["round_id"] == "round-1"
    assert git.calls == []


def test_merge_transaction_ignores_stale_v4_results_without_legacy_fallback(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    recorder = _crew_with_patch(
        repo_root,
        tmp_path,
        base_ref="base-sha",
        patch_path="src/legacy.py",
    )
    store = SQLiteEventStore(tmp_path / "events.sqlite3")
    _record_ready_events(store, round_id="round-2")
    paths = V4Paths(repo_root=repo_root, crew_id="crew-1")
    legacy_root = paths.crew_root / "artifacts"
    legacy_patch = legacy_root / "workers/worker-1/diff.patch"
    legacy_patch.parent.mkdir(parents=True, exist_ok=True)
    legacy_patch.write_text(_patch_for("src/app.py"), encoding="utf-8")
    V4MergeInputRecorder(event_store=store, paths=paths).record_from_changes(
        changes={
            "worker_id": "worker-1",
            "base_ref": "base-sha",
            "changed_files": ["src/app.py"],
            "artifact": "workers/worker-1/changes.json",
            "diff_artifact": "workers/worker-1/diff.patch",
        },
        turn_id="round-1-worker-1-source",
        round_id="round-1",
        contract_id="source_write",
    )
    git = FakeGitRunner(heads=["base-sha"])

    result = V4MergeTransaction(
        repo_root=repo_root,
        recorder=recorder,
        event_store=store,
        git_runner=git,
        command_runner=FakeCommandRunner([0]),
    ).accept(
        crew_id="crew-1",
        summary="accepted",
        verification_commands=["python -c 'print(123)'"],
    )

    assert result["status"] == "blocked"
    assert result["reason"] == "no_worker_patches_for_ready_round"
    assert "merge.legacy_patch_source_used" not in [event.type for event in store.list_stream("crew-1")]
    assert git.calls == []


class FakeGitRunner:
    def __init__(
        self,
        *,
        statuses: list[str] | None = None,
        heads: list[str] | None = None,
    ) -> None:
        self.statuses = statuses or [""]
        self.heads = heads or ["base-sha"]
        self.calls: list[dict] = []

    def __call__(self, args, *, cwd, text=True, capture_output=True, check=False):
        args = list(args)
        self.calls.append({"args": args[1:] if args[:1] == ["git"] else args, "cwd": Path(cwd)})
        git_args = args[1:] if args[:1] == ["git"] else args
        if git_args == ["status", "--porcelain"]:
            return _completed(args, stdout=self.statuses.pop(0) if self.statuses else "")
        if git_args == ["rev-parse", "HEAD"]:
            return _completed(args, stdout=f"{self.heads.pop(0) if self.heads else 'base-sha'}\n")
        if git_args[:3] == ["worktree", "add", "--detach"]:
            Path(git_args[3]).mkdir(parents=True, exist_ok=True)
            return _completed(args)
        if git_args[:3] == ["worktree", "remove", "--force"]:
            return _completed(args)
        if git_args[:2] == ["apply", "--check"]:
            return _completed(args)
        if git_args[:1] == ["apply"]:
            return _completed(args)
        return _completed(args)


class FakeCommandRunner:
    def __init__(self, returncodes: list[int]) -> None:
        self.returncodes = returncodes
        self.calls: list[dict] = []

    def __call__(self, args, *, cwd, text=True, capture_output=True, check=False):
        self.calls.append({"args": args, "cwd": Path(cwd)})
        return _completed(args, returncode=self.returncodes.pop(0), stdout="", stderr="")


def _crew_with_patch(
    repo_root: Path,
    tmp_path: Path,
    *,
    base_ref: str,
    changed_files: list[str] | None = None,
    patch_path: str = "src/app.py",
    patch: str | None = None,
    state_root: Path | None = None,
) -> CrewRecorder:
    recorder = CrewRecorder(state_root or tmp_path / ".orchestrator")
    recorder.start_crew(
        CrewRecord(
            crew_id="crew-1",
            root_goal="goal",
            repo=repo_root,
        )
    )
    changed_files = changed_files or [patch_path]
    changes = {
        "crew_id": "crew-1",
        "worker_id": "worker-1",
        "branch": "worker-branch",
        "base_ref": base_ref,
        "changed_files": changed_files,
        "diff_artifact": "workers/worker-1/diff.patch",
        "artifact": "workers/worker-1/changes.json",
    }
    recorder.write_text_artifact(
        "crew-1",
        "workers/worker-1/changes.json",
        json.dumps(changes, ensure_ascii=False),
    )
    recorder.write_text_artifact(
        "crew-1",
        "workers/worker-1/diff.patch",
        patch or _patch_for(patch_path),
    )
    return recorder


def _crew_without_patch(repo_root: Path, tmp_path: Path) -> CrewRecorder:
    recorder = CrewRecorder(tmp_path / ".orchestrator")
    recorder.start_crew(
        CrewRecord(
            crew_id="crew-1",
            root_goal="goal",
            repo=repo_root,
        )
    )
    return recorder


def _record_ready_events(store: SQLiteEventStore, round_id: str = "round-1") -> None:
    store.append(
        stream_id="crew-1",
        type="review.completed",
        crew_id="crew-1",
        round_id=round_id,
        payload={"round_id": round_id, "status": "ok"},
    )
    store.append(
        stream_id="crew-1",
        type="verification.passed",
        crew_id="crew-1",
        round_id=round_id,
        payload={"round_id": round_id, "command": "pytest -q"},
    )
    store.append(
        stream_id="crew-1",
        type="crew.ready_for_accept",
        crew_id="crew-1",
        round_id=round_id,
        payload={"round_id": round_id},
    )


def _patch_for(path: str) -> str:
    return "\n".join(
        [
            f"diff --git a/{path} b/{path}",
            "index e69de29..4b825dc 100644",
            f"--- a/{path}",
            f"+++ b/{path}",
            "@@ -0,0 +1 @@",
            "+hello",
            "",
        ]
    )


def _completed(args, *, returncode: int = 0, stdout: str = "", stderr: str = ""):
    return CompletedProcess(args=args, returncode=returncode, stdout=stdout, stderr=stderr)


def _run_git(args: list[str], cwd: Path) -> CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    return result
