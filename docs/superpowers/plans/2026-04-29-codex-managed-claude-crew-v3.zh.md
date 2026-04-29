# Codex-Managed Claude Crew V3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有 V2 Claude Bridge/Session 之上实现 V3：由 Codex 管理多个 Claude worker 的本地 crew 编排层。

**Architecture:** 新增 crew 级数据模型、持久化记录、blackboard、task graph、worker pool、crew controller、merge arbiter 和 CLI/UI 接口。V3 不替换 V1/V2，而是通过 `WorkerPool` 组合多个现有 `ClaudeBridge` 会话，并让 Codex 继续拥有验证、挑战、验收和合并裁决权。

**Tech Stack:** Python 3.11+, stdlib (`argparse`, `dataclasses`, `enum`, `json`, `pathlib`, `subprocess`, `uuid`), pytest, existing Claude Code CLI bridge

---

## Scope Check

V3 spec 是一个完整但可分层的子系统：crew 记录、worker 调度、黑板、任务图、验证、合并建议和 UI 展示。它不需要重新拆 spec，但实现必须分阶段提交，避免一次性改穿 V1/V2。

本计划采用保守 MVP：

- 第一版 implementer 使用现有 `WorkspaceMode.ISOLATED` 作为写入隔离，不直接改用户主工作区。
- `worktree` 作为明确扩展点保留在模型和 merge plan 中，不在第一批任务里强行实现真实 `git worktree`。
- worker 之间不直接通信，只通过 `BlackboardStore` 和 Codex/CrewController 交互。
- 所有新增能力必须保留现有 `dispatch`、`session`、`claude bridge`、`ui` 测试。

## Execution Preconditions

开始实现前运行：

```bash
.venv/bin/python -m pytest -q
```

Expected: 当前测试全部通过。如果失败，先记录失败项并判断是否和 V3 无关；不要在 V3 任务里顺手重构无关问题。

每个任务完成后至少运行该任务列出的定向测试。任务 10 再运行完整回归：

```bash
.venv/bin/python -m pytest -q
```

## File Structure

新增文件：

- `src/codex_claude_orchestrator/crew_models.py`：V3 专用 enum/dataclass，避免继续撑大 `models.py`。
- `src/codex_claude_orchestrator/crew_recorder.py`：`.orchestrator/crews/<crew_id>/` 持久化。
- `src/codex_claude_orchestrator/blackboard.py`：append-only blackboard 的追加、读取、过滤接口。
- `src/codex_claude_orchestrator/task_graph.py`：默认 crew task graph 生成和状态转换。
- `src/codex_claude_orchestrator/worker_pool.py`：基于 `ClaudeBridge` 管理多个 role-specific worker。
- `src/codex_claude_orchestrator/crew_controller.py`：V3 编排入口，连接 recorder、task graph、worker pool、blackboard、verification、merge arbiter。
- `src/codex_claude_orchestrator/crew_verification.py`：crew 级命令验证，逻辑复用 `VerificationRunner` 的 policy/command/artifact 规则。
- `src/codex_claude_orchestrator/merge_arbiter.py`：写入范围冲突检测和 merge plan 生成。
- `tests/test_crew_models.py`
- `tests/test_crew_recorder.py`
- `tests/test_blackboard.py`
- `tests/test_task_graph.py`
- `tests/test_worker_pool.py`
- `tests/test_crew_controller.py`
- `tests/test_crew_verification.py`
- `tests/test_merge_arbiter.py`

修改文件：

- `src/codex_claude_orchestrator/cli.py`：增加 `crew` 命令和 `build_crew_controller()`。
- `src/codex_claude_orchestrator/ui_server.py`：增加 crew state/API/HTML 展示。
- `tests/test_cli.py`：增加 crew parser 和 CLI JSON 测试。
- `tests/test_ui_server.py`：增加 crew state/API/UI 文案测试。

## Task 1: Crew Models

**Files:**
- Create: `src/codex_claude_orchestrator/crew_models.py`
- Create: `tests/test_crew_models.py`

- [ ] **Step 1: Write the failing model serialization tests**

```python
# tests/test_crew_models.py
from pathlib import Path

from codex_claude_orchestrator.crew_models import (
    ActorType,
    BlackboardEntry,
    BlackboardEntryType,
    CrewRecord,
    CrewStatus,
    CrewTaskRecord,
    CrewTaskStatus,
    WorkerRecord,
    WorkerRole,
    WorkerStatus,
)
from codex_claude_orchestrator.models import WorkspaceMode


def test_crew_record_to_dict_normalizes_enums_and_paths():
    crew = CrewRecord(
        crew_id="crew-1",
        root_goal="Implement V3",
        repo=Path("/repo"),
        status=CrewStatus.RUNNING,
        max_workers=3,
        active_worker_ids=["worker-1"],
        task_graph_path=Path(".orchestrator/crews/crew-1/tasks.json"),
        blackboard_path=Path(".orchestrator/crews/crew-1/blackboard.jsonl"),
    )

    data = crew.to_dict()

    assert data["status"] == "running"
    assert data["repo"] == "/repo"
    assert data["max_workers"] == 3
    assert data["active_worker_ids"] == ["worker-1"]


def test_worker_task_and_blackboard_entries_serialize_consistently():
    worker = WorkerRecord(
        worker_id="worker-1",
        crew_id="crew-1",
        role=WorkerRole.EXPLORER,
        agent_profile="claude",
        bridge_id="bridge-1",
        workspace_mode=WorkspaceMode.READONLY,
        workspace_path=Path("/repo"),
        write_scope=[],
        allowed_tools=["Read", "Glob", "Grep", "LS"],
        status=WorkerStatus.RUNNING,
        assigned_task_ids=["task-1"],
    )
    task = CrewTaskRecord(
        task_id="task-1",
        crew_id="crew-1",
        title="Map architecture",
        instructions="Read the repo and report facts.",
        role_required=WorkerRole.EXPLORER,
        status=CrewTaskStatus.ASSIGNED,
        owner_worker_id="worker-1",
        expected_outputs=["facts", "risks"],
    )
    entry = BlackboardEntry(
        entry_id="entry-1",
        crew_id="crew-1",
        task_id="task-1",
        actor_type=ActorType.WORKER,
        actor_id="worker-1",
        type=BlackboardEntryType.FACT,
        content="The CLI entrypoint is codex_claude_orchestrator.cli:main.",
        evidence_refs=["src/codex_claude_orchestrator/cli.py"],
        confidence=0.9,
    )

    assert worker.to_dict()["role"] == "explorer"
    assert worker.to_dict()["workspace_mode"] == "readonly"
    assert task.to_dict()["status"] == "assigned"
    assert entry.to_dict()["type"] == "fact"
    assert entry.to_dict()["actor_type"] == "worker"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_crew_models.py -v
```

Expected: FAIL with `ModuleNotFoundError` for `codex_claude_orchestrator.crew_models`.

- [ ] **Step 3: Implement V3 dataclasses and enums**

Use this structure in `src/codex_claude_orchestrator/crew_models.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from codex_claude_orchestrator.models import WorkspaceMode, utc_now


def _normalize(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value):
        return {item.name: _normalize(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, dict):
        return {key: _normalize(inner) for key, inner in value.items()}
    if isinstance(value, list):
        return [_normalize(inner) for inner in value]
    return value


class CrewStatus(StrEnum):
    PLANNING = "planning"
    RUNNING = "running"
    BLOCKED = "blocked"
    NEEDS_HUMAN = "needs_human"
    ACCEPTED = "accepted"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkerRole(StrEnum):
    EXPLORER = "explorer"
    IMPLEMENTER = "implementer"
    REVIEWER = "reviewer"
    VERIFIER = "verifier"
    COMPETITOR = "competitor"


class WorkerStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    IDLE = "idle"
    FAILED = "failed"
    STOPPED = "stopped"


class CrewTaskStatus(StrEnum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    RUNNING = "running"
    SUBMITTED = "submitted"
    CHALLENGED = "challenged"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    BLOCKED = "blocked"


class BlackboardEntryType(StrEnum):
    FACT = "fact"
    CLAIM = "claim"
    QUESTION = "question"
    RISK = "risk"
    PATCH = "patch"
    VERIFICATION = "verification"
    REVIEW = "review"
    DECISION = "decision"


class ActorType(StrEnum):
    CODEX = "codex"
    WORKER = "worker"


@dataclass(slots=True)
class CrewRecord:
    crew_id: str
    root_goal: str
    repo: str | Path
    status: CrewStatus = CrewStatus.PLANNING
    planner_summary: str = ""
    max_workers: int = 3
    active_worker_ids: list[str] = field(default_factory=list)
    task_graph_path: str | Path = ""
    blackboard_path: str | Path = ""
    verification_summary: str = ""
    merge_summary: str = ""
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    ended_at: str | None = None
    final_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _normalize(self)


@dataclass(slots=True)
class WorkerRecord:
    worker_id: str
    crew_id: str
    role: WorkerRole
    agent_profile: str
    bridge_id: str | None
    workspace_mode: WorkspaceMode
    workspace_path: str | Path
    write_scope: list[str] = field(default_factory=list)
    allowed_tools: list[str] = field(default_factory=list)
    status: WorkerStatus = WorkerStatus.CREATED
    assigned_task_ids: list[str] = field(default_factory=list)
    last_seen_at: str | None = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return _normalize(self)


@dataclass(slots=True)
class CrewTaskRecord:
    task_id: str
    crew_id: str
    title: str
    instructions: str
    role_required: WorkerRole
    status: CrewTaskStatus = CrewTaskStatus.PENDING
    owner_worker_id: str | None = None
    blocked_by: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    allowed_paths: list[str] = field(default_factory=list)
    forbidden_paths: list[str] = field(default_factory=list)
    expected_outputs: list[str] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return _normalize(self)


@dataclass(slots=True)
class BlackboardEntry:
    entry_id: str
    crew_id: str
    task_id: str | None
    actor_type: ActorType
    actor_id: str
    type: BlackboardEntryType
    content: str
    evidence_refs: list[str] = field(default_factory=list)
    confidence: float = 0.0
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return _normalize(self)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
.venv/bin/python -m pytest tests/test_crew_models.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/codex_claude_orchestrator/crew_models.py tests/test_crew_models.py
git commit -m "feat: add crew v3 data models"
```

## Task 2: Crew Recorder And Blackboard Store

**Files:**
- Create: `src/codex_claude_orchestrator/crew_recorder.py`
- Create: `src/codex_claude_orchestrator/blackboard.py`
- Create: `tests/test_crew_recorder.py`
- Create: `tests/test_blackboard.py`

- [ ] **Step 1: Write failing persistence tests**

```python
# tests/test_crew_recorder.py
from pathlib import Path

from codex_claude_orchestrator.crew_models import CrewRecord, CrewStatus, CrewTaskRecord, WorkerRole
from codex_claude_orchestrator.crew_recorder import CrewRecorder


def test_crew_recorder_persists_crew_tasks_workers_and_final_report(tmp_path: Path):
    recorder = CrewRecorder(tmp_path / ".orchestrator")
    crew = CrewRecord(crew_id="crew-1", root_goal="Build V3", repo="/repo")
    task = CrewTaskRecord(
        task_id="task-1",
        crew_id=crew.crew_id,
        title="Explore",
        instructions="Read only.",
        role_required=WorkerRole.EXPLORER,
    )

    crew_dir = recorder.start_crew(crew)
    recorder.write_tasks(crew.crew_id, [task])
    recorder.finalize_crew(crew.crew_id, CrewStatus.ACCEPTED, "accepted")
    details = recorder.read_crew(crew.crew_id)

    assert crew_dir == tmp_path / ".orchestrator" / "crews" / "crew-1"
    assert details["crew"]["status"] == "accepted"
    assert details["tasks"][0]["task_id"] == "task-1"
    assert details["final_report"]["final_summary"] == "accepted"
    assert recorder.list_crews()[0]["crew_id"] == "crew-1"
```

```python
# tests/test_blackboard.py
from pathlib import Path

from codex_claude_orchestrator.blackboard import BlackboardStore
from codex_claude_orchestrator.crew_models import (
    ActorType,
    BlackboardEntry,
    BlackboardEntryType,
    CrewRecord,
)
from codex_claude_orchestrator.crew_recorder import CrewRecorder


def test_blackboard_appends_and_filters_entries(tmp_path: Path):
    recorder = CrewRecorder(tmp_path / ".orchestrator")
    recorder.start_crew(CrewRecord(crew_id="crew-1", root_goal="Build V3", repo="/repo"))
    store = BlackboardStore(recorder)
    entry = BlackboardEntry(
        entry_id="entry-1",
        crew_id="crew-1",
        task_id="task-1",
        actor_type=ActorType.CODEX,
        actor_id="codex",
        type=BlackboardEntryType.DECISION,
        content="Start explorer first.",
        confidence=1.0,
    )

    store.append(entry)

    assert store.list_entries("crew-1")[0]["entry_id"] == "entry-1"
    assert store.list_entries("crew-1", entry_type=BlackboardEntryType.DECISION)[0]["content"] == "Start explorer first."
    assert store.list_entries("crew-1", entry_type=BlackboardEntryType.FACT) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_crew_recorder.py tests/test_blackboard.py -v
```

Expected: FAIL because `crew_recorder` and `blackboard` do not exist.

- [ ] **Step 3: Implement `CrewRecorder`**

Implement `src/codex_claude_orchestrator/crew_recorder.py` with these public methods:

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from codex_claude_orchestrator.crew_models import CrewRecord, CrewStatus, CrewTaskRecord, WorkerRecord, BlackboardEntry
from codex_claude_orchestrator.models import utc_now


class CrewRecorder:
    def __init__(self, state_root: Path):
        self._state_root = state_root
        self._crews_root = state_root / "crews"
        self._crews_root.mkdir(parents=True, exist_ok=True)

    def start_crew(self, crew: CrewRecord) -> Path:
        crew_dir = self._crew_dir(crew.crew_id)
        crew_dir.mkdir(parents=True, exist_ok=True)
        self._write_json(crew_dir / "crew.json", crew.to_dict())
        self._write_latest(crew.crew_id)
        return crew_dir

    def update_crew(self, crew_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        path = self._crew_dir(crew_id) / "crew.json"
        crew = self._read_json(path)
        crew.update({**updates, "updated_at": utc_now()})
        self._write_json(path, crew)
        return crew

    def append_worker(self, crew_id: str, worker: WorkerRecord) -> None:
        self._append_jsonl(crew_id, "workers.jsonl", worker.to_dict())

    def write_tasks(self, crew_id: str, tasks: list[CrewTaskRecord]) -> None:
        self._write_json(self._crew_dir(crew_id) / "tasks.json", [task.to_dict() for task in tasks])

    def append_blackboard(self, crew_id: str, entry: BlackboardEntry) -> None:
        self._append_jsonl(crew_id, "blackboard.jsonl", entry.to_dict())

    def write_text_artifact(self, crew_id: str, artifact_name: str, content: str) -> Path:
        artifact_path = self._crew_dir(crew_id) / "artifacts" / artifact_name
        self._write_text(artifact_path, content)
        return artifact_path

    def finalize_crew(self, crew_id: str, status: CrewStatus, final_summary: str) -> None:
        ended_at = utc_now()
        crew = self.update_crew(
            crew_id,
            {"status": status.value, "final_summary": final_summary, "ended_at": ended_at},
        )
        self._write_json(
            self._crew_dir(crew_id) / "final_report.json",
            {
                "crew_id": crew_id,
                "status": crew["status"],
                "final_summary": final_summary,
                "ended_at": ended_at,
            },
        )

    def list_crews(self) -> list[dict[str, Any]]:
        crews = [self._crew_summary(path.name) for path in self._iter_crew_dirs()]
        return sorted(crews, key=lambda item: item["created_at"], reverse=True)

    def read_crew(self, crew_id: str) -> dict[str, Any]:
        crew_dir = self._crew_dir(crew_id)
        if not crew_dir.is_dir():
            raise FileNotFoundError(f"crew not found: {crew_id}")
        return {
            "crew": self._read_json(crew_dir / "crew.json"),
            "tasks": self._read_optional_list(crew_dir / "tasks.json"),
            "workers": self._read_jsonl(crew_dir / "workers.jsonl"),
            "blackboard": self._read_jsonl(crew_dir / "blackboard.jsonl"),
            "final_report": self._read_optional_json(crew_dir / "final_report.json"),
            "artifacts": self._list_artifacts(crew_dir / "artifacts"),
        }

    def latest_crew_id(self) -> str | None:
        latest = self._crews_root / "latest"
        if not latest.exists():
            return None
        value = latest.read_text(encoding="utf-8").strip()
        return value or None

    def _crew_summary(self, crew_id: str) -> dict[str, Any]:
        crew = self.read_crew(crew_id)["crew"]
        return {
            "crew_id": crew["crew_id"],
            "root_goal": crew["root_goal"],
            "status": crew["status"],
            "summary": crew.get("final_summary", ""),
            "created_at": crew["created_at"],
            "ended_at": crew.get("ended_at"),
        }

    def _crew_dir(self, crew_id: str) -> Path:
        return self._crews_root / crew_id

    def _iter_crew_dirs(self) -> list[Path]:
        if not self._crews_root.exists():
            return []
        return [path for path in self._crews_root.iterdir() if path.is_dir()]

    def _write_latest(self, crew_id: str) -> None:
        self._write_text(self._crews_root / "latest", crew_id)

    def _append_jsonl(self, crew_id: str, filename: str, payload: dict[str, Any]) -> None:
        path = self._crew_dir(crew_id) / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _read_json(self, path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    def _read_optional_json(self, path: Path) -> dict[str, Any] | None:
        return self._read_json(path) if path.exists() else None

    def _read_optional_list(self, path: Path) -> list[dict[str, Any]]:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []

    def _read_jsonl(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def _list_artifacts(self, artifacts_dir: Path) -> list[str]:
        if not artifacts_dir.exists():
            return []
        return sorted(path.relative_to(artifacts_dir).as_posix() for path in artifacts_dir.rglob("*") if path.is_file())

    def _write_json(self, path: Path, payload: dict[str, Any] | list[dict[str, Any]]) -> None:
        self._write_text(path, json.dumps(payload, indent=2, ensure_ascii=False))

    def _write_text(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f".{path.name}.tmp")
        tmp_path.write_text(content, encoding="utf-8")
        tmp_path.replace(path)
```

- [ ] **Step 4: Implement `BlackboardStore`**

```python
# src/codex_claude_orchestrator/blackboard.py
from __future__ import annotations

from codex_claude_orchestrator.crew_models import BlackboardEntry, BlackboardEntryType
from codex_claude_orchestrator.crew_recorder import CrewRecorder


class BlackboardStore:
    def __init__(self, recorder: CrewRecorder):
        self._recorder = recorder

    def append(self, entry: BlackboardEntry) -> dict:
        self._recorder.append_blackboard(entry.crew_id, entry)
        return entry.to_dict()

    def list_entries(
        self,
        crew_id: str,
        *,
        entry_type: BlackboardEntryType | None = None,
        task_id: str | None = None,
        actor_id: str | None = None,
    ) -> list[dict]:
        entries = self._recorder.read_crew(crew_id)["blackboard"]
        if entry_type is not None:
            entries = [entry for entry in entries if entry["type"] == entry_type.value]
        if task_id is not None:
            entries = [entry for entry in entries if entry.get("task_id") == task_id]
        if actor_id is not None:
            entries = [entry for entry in entries if entry.get("actor_id") == actor_id]
        return entries
```

- [ ] **Step 5: Run tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_crew_recorder.py tests/test_blackboard.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/codex_claude_orchestrator/crew_recorder.py src/codex_claude_orchestrator/blackboard.py tests/test_crew_recorder.py tests/test_blackboard.py
git commit -m "feat: persist crew records and blackboard"
```

## Task 3: Task Graph Planner

**Files:**
- Create: `src/codex_claude_orchestrator/task_graph.py`
- Create: `tests/test_task_graph.py`

- [ ] **Step 1: Write failing task graph tests**

```python
# tests/test_task_graph.py
from codex_claude_orchestrator.crew_models import CrewTaskStatus, WorkerRole
from codex_claude_orchestrator.task_graph import TaskGraphPlanner


def test_default_graph_creates_role_specific_tasks_with_dependencies():
    planner = TaskGraphPlanner(task_id_factory=lambda role: f"task-{role.value}")

    tasks = planner.default_graph("crew-1", "Fix failing tests", [WorkerRole.EXPLORER, WorkerRole.IMPLEMENTER, WorkerRole.REVIEWER])

    by_role = {task.role_required: task for task in tasks}
    assert by_role[WorkerRole.EXPLORER].title == "Explore repository context"
    assert by_role[WorkerRole.IMPLEMENTER].depends_on == ["task-explorer"]
    assert by_role[WorkerRole.REVIEWER].depends_on == ["task-implementer"]
    assert by_role[WorkerRole.REVIEWER].expected_outputs == ["review", "risks", "acceptance recommendation"]


def test_assign_task_marks_owner_and_status():
    planner = TaskGraphPlanner(task_id_factory=lambda role: f"task-{role.value}")
    tasks = planner.default_graph("crew-1", "Fix failing tests", [WorkerRole.EXPLORER])

    assigned = planner.assign(tasks, "task-explorer", "worker-explorer")

    assert assigned[0].owner_worker_id == "worker-explorer"
    assert assigned[0].status == CrewTaskStatus.ASSIGNED
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_task_graph.py -v
```

Expected: FAIL because `task_graph` does not exist.

- [ ] **Step 3: Implement `TaskGraphPlanner`**

```python
# src/codex_claude_orchestrator/task_graph.py
from __future__ import annotations

from collections.abc import Callable

from codex_claude_orchestrator.crew_models import CrewTaskRecord, CrewTaskStatus, WorkerRole
from codex_claude_orchestrator.models import utc_now


class TaskGraphPlanner:
    def __init__(self, task_id_factory: Callable[[WorkerRole], str] | None = None):
        self._task_id_factory = task_id_factory or (lambda role: f"task-{role.value}")

    def default_graph(self, crew_id: str, goal: str, roles: list[WorkerRole]) -> list[CrewTaskRecord]:
        tasks: list[CrewTaskRecord] = []
        previous_task_id: str | None = None
        for role in roles:
            task_id = self._task_id_factory(role)
            task = self._task_for_role(crew_id, goal, role, task_id)
            if previous_task_id and role in {WorkerRole.IMPLEMENTER, WorkerRole.REVIEWER, WorkerRole.VERIFIER}:
                task.depends_on = [previous_task_id]
                task.blocked_by = [previous_task_id]
            tasks.append(task)
            previous_task_id = task_id
        return tasks

    def assign(self, tasks: list[CrewTaskRecord], task_id: str, worker_id: str) -> list[CrewTaskRecord]:
        updated: list[CrewTaskRecord] = []
        for task in tasks:
            if task.task_id == task_id:
                task.owner_worker_id = worker_id
                task.status = CrewTaskStatus.ASSIGNED
                task.updated_at = utc_now()
            updated.append(task)
        return updated

    def _task_for_role(self, crew_id: str, goal: str, role: WorkerRole, task_id: str) -> CrewTaskRecord:
        if role is WorkerRole.EXPLORER:
            return CrewTaskRecord(
                task_id=task_id,
                crew_id=crew_id,
                title="Explore repository context",
                instructions=f"Read the repository for this goal without modifying files: {goal}",
                role_required=role,
                expected_outputs=["facts", "risks", "relevant files"],
                acceptance_criteria=["facts are grounded in file paths", "risks are specific"],
            )
        if role is WorkerRole.IMPLEMENTER:
            return CrewTaskRecord(
                task_id=task_id,
                crew_id=crew_id,
                title="Implement scoped patch",
                instructions=f"Implement the requested change in an isolated workspace: {goal}",
                role_required=role,
                expected_outputs=["patch", "changed files", "verification notes"],
                acceptance_criteria=["patch is scoped", "unrelated files are preserved"],
            )
        if role is WorkerRole.REVIEWER:
            return CrewTaskRecord(
                task_id=task_id,
                crew_id=crew_id,
                title="Review proposed patch",
                instructions=f"Review the implementer output against this goal: {goal}",
                role_required=role,
                expected_outputs=["review", "risks", "acceptance recommendation"],
                acceptance_criteria=["review references evidence", "blocking risks are explicit"],
            )
        if role is WorkerRole.VERIFIER:
            return CrewTaskRecord(
                task_id=task_id,
                crew_id=crew_id,
                title="Verify crew evidence",
                instructions=f"Run or propose verification for this goal: {goal}",
                role_required=role,
                expected_outputs=["verification", "command results", "remaining risks"],
                acceptance_criteria=["commands and results are recorded"],
            )
        return CrewTaskRecord(
            task_id=task_id,
            crew_id=crew_id,
            title="Produce competing implementation",
            instructions=f"Produce an alternate isolated implementation for this goal: {goal}",
            role_required=role,
            expected_outputs=["alternate patch", "tradeoffs", "verification notes"],
            acceptance_criteria=["tradeoffs are explicit", "patch is isolated"],
        )
```

- [ ] **Step 4: Run tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_task_graph.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/codex_claude_orchestrator/task_graph.py tests/test_task_graph.py
git commit -m "feat: add crew task graph planner"
```

## Task 4: WorkerPool Over ClaudeBridge

**Files:**
- Create: `src/codex_claude_orchestrator/worker_pool.py`
- Create: `tests/test_worker_pool.py`

- [ ] **Step 1: Write failing WorkerPool tests**

```python
# tests/test_worker_pool.py
from pathlib import Path

from codex_claude_orchestrator.blackboard import BlackboardStore
from codex_claude_orchestrator.crew_models import (
    BlackboardEntryType,
    CrewRecord,
    CrewTaskRecord,
    WorkerRole,
    WorkerStatus,
)
from codex_claude_orchestrator.crew_recorder import CrewRecorder
from codex_claude_orchestrator.models import WorkspaceMode
from codex_claude_orchestrator.worker_pool import WorkerPool
from codex_claude_orchestrator.workspace_manager import WorkspaceManager


class FakeBridge:
    def __init__(self):
        self.starts = []

    def start(self, **kwargs):
        self.starts.append(kwargs)
        return {
            "bridge": {
                "bridge_id": "bridge-1",
                "status": "active",
                "workspace_mode": kwargs["workspace_mode"],
            },
            "latest_turn": {"turn_id": "turn-1", "result_text": "worker started"},
        }


def test_worker_pool_starts_readonly_explorer_and_records_worker(tmp_path: Path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    recorder = CrewRecorder(repo_root / ".orchestrator")
    crew = CrewRecord(crew_id="crew-1", root_goal="Build V3", repo=repo_root)
    recorder.start_crew(crew)
    blackboard = BlackboardStore(recorder)
    fake_bridge = FakeBridge()
    pool = WorkerPool(
        recorder=recorder,
        blackboard=blackboard,
        workspace_manager=WorkspaceManager(repo_root / ".orchestrator"),
        bridge_factory=lambda: fake_bridge,
        worker_id_factory=lambda role: f"worker-{role.value}",
        entry_id_factory=lambda: "entry-worker-started",
    )
    task = CrewTaskRecord(
        task_id="task-explorer",
        crew_id=crew.crew_id,
        title="Explore",
        instructions="Read only.",
        role_required=WorkerRole.EXPLORER,
    )

    worker = pool.start_worker(repo_root=repo_root, crew=crew, task=task)

    assert worker.worker_id == "worker-explorer"
    assert worker.role == WorkerRole.EXPLORER
    assert worker.status == WorkerStatus.RUNNING
    assert worker.workspace_mode == WorkspaceMode.READONLY
    assert fake_bridge.starts[0]["repo_root"] == repo_root.resolve()
    assert fake_bridge.starts[0]["workspace_mode"] == "readonly"
    details = recorder.read_crew(crew.crew_id)
    assert details["workers"][0]["bridge_id"] == "bridge-1"
    assert details["blackboard"][0]["type"] == BlackboardEntryType.DECISION.value


def test_worker_pool_uses_isolated_workspace_for_implementer(tmp_path: Path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "app.py").write_text("print('one')\n", encoding="utf-8")
    recorder = CrewRecorder(repo_root / ".orchestrator")
    crew = CrewRecord(crew_id="crew-1", root_goal="Build V3", repo=repo_root)
    recorder.start_crew(crew)
    fake_bridge = FakeBridge()
    pool = WorkerPool(
        recorder=recorder,
        blackboard=BlackboardStore(recorder),
        workspace_manager=WorkspaceManager(repo_root / ".orchestrator"),
        bridge_factory=lambda: fake_bridge,
        worker_id_factory=lambda role: f"worker-{role.value}",
        entry_id_factory=lambda: "entry-impl-started",
    )
    task = CrewTaskRecord(
        task_id="task-implementer",
        crew_id=crew.crew_id,
        title="Implement",
        instructions="Modify app.py.",
        role_required=WorkerRole.IMPLEMENTER,
    )

    worker = pool.start_worker(repo_root=repo_root, crew=crew, task=task)

    assert worker.workspace_mode == WorkspaceMode.ISOLATED
    assert Path(worker.workspace_path) != repo_root
    assert fake_bridge.starts[0]["repo_root"] == Path(worker.workspace_path)
    assert fake_bridge.starts[0]["workspace_mode"] == "shared"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_worker_pool.py -v
```

Expected: FAIL because `worker_pool` does not exist.

- [ ] **Step 3: Implement `WorkerPool`**

```python
# src/codex_claude_orchestrator/worker_pool.py
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

from codex_claude_orchestrator.blackboard import BlackboardStore
from codex_claude_orchestrator.claude_bridge import ClaudeBridge
from codex_claude_orchestrator.crew_models import (
    ActorType,
    BlackboardEntry,
    BlackboardEntryType,
    CrewRecord,
    CrewTaskRecord,
    WorkerRecord,
    WorkerRole,
    WorkerStatus,
)
from codex_claude_orchestrator.crew_recorder import CrewRecorder
from codex_claude_orchestrator.models import TaskRecord, WorkspaceMode, utc_now
from codex_claude_orchestrator.workspace_manager import WorkspaceManager


BridgeFactory = Callable[[], ClaudeBridge]


class WorkerPool:
    def __init__(
        self,
        *,
        recorder: CrewRecorder,
        blackboard: BlackboardStore,
        workspace_manager: WorkspaceManager,
        bridge_factory: BridgeFactory,
        worker_id_factory: Callable[[WorkerRole], str] | None = None,
        entry_id_factory: Callable[[], str] | None = None,
    ):
        self._recorder = recorder
        self._blackboard = blackboard
        self._workspace_manager = workspace_manager
        self._bridge_factory = bridge_factory
        self._worker_id_factory = worker_id_factory or (lambda role: f"worker-{role.value}-{uuid4().hex}")
        self._entry_id_factory = entry_id_factory or (lambda: f"entry-{uuid4().hex}")

    def start_worker(self, *, repo_root: Path, crew: CrewRecord, task: CrewTaskRecord) -> WorkerRecord:
        worker_id = self._worker_id_factory(task.role_required)
        allocation_mode = self._allocation_mode(task.role_required)
        allocation = self._workspace_manager.prepare(
            repo_root,
            TaskRecord(
                task_id=f"{crew.crew_id}-{worker_id}",
                parent_task_id=None,
                origin="crew",
                assigned_agent="claude",
                goal=task.instructions,
                task_type=f"crew-{task.role_required.value}",
                scope=str(repo_root),
                workspace_mode=allocation_mode,
                allowed_tools=self._allowed_tools(task.role_required),
            ),
        )
        bridge_workspace_mode = "readonly" if allocation_mode is WorkspaceMode.READONLY else "shared"
        bridge = self._bridge_factory()
        result = bridge.start(
            repo_root=allocation.path,
            goal=self._render_worker_goal(crew, task),
            workspace_mode=bridge_workspace_mode,
            visual="none",
            dry_run=False,
            supervised=True,
        )
        bridge_id = str(result["bridge"]["bridge_id"])
        now = utc_now()
        worker = WorkerRecord(
            worker_id=worker_id,
            crew_id=crew.crew_id,
            role=task.role_required,
            agent_profile="claude",
            bridge_id=bridge_id,
            workspace_mode=allocation.mode,
            workspace_path=allocation.path,
            write_scope=task.allowed_paths,
            allowed_tools=self._allowed_tools(task.role_required),
            status=WorkerStatus.RUNNING,
            assigned_task_ids=[task.task_id],
            last_seen_at=now,
            updated_at=now,
        )
        self._recorder.append_worker(crew.crew_id, worker)
        self._blackboard.append(
            BlackboardEntry(
                entry_id=self._entry_id_factory(),
                crew_id=crew.crew_id,
                task_id=task.task_id,
                actor_type=ActorType.CODEX,
                actor_id="codex",
                type=BlackboardEntryType.DECISION,
                content=f"Started {task.role_required.value} worker {worker_id} with bridge {bridge_id}.",
                evidence_refs=[bridge_id],
                confidence=1.0,
            )
        )
        return worker

    def _allocation_mode(self, role: WorkerRole) -> WorkspaceMode:
        if role in {WorkerRole.IMPLEMENTER, WorkerRole.COMPETITOR}:
            return WorkspaceMode.ISOLATED
        return WorkspaceMode.READONLY

    def _allowed_tools(self, role: WorkerRole) -> list[str]:
        if role in {WorkerRole.EXPLORER, WorkerRole.REVIEWER, WorkerRole.VERIFIER}:
            return ["Read", "Glob", "Grep", "LS"]
        return []

    def _render_worker_goal(self, crew: CrewRecord, task: CrewTaskRecord) -> str:
        return (
            f"Crew goal: {crew.root_goal}\n"
            f"Your role: {task.role_required.value}\n"
            f"Task: {task.title}\n"
            f"Instructions: {task.instructions}\n"
            "Report concrete evidence. Preserve unrelated user work."
        )
```

- [ ] **Step 4: Run tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_worker_pool.py -v
```

Expected: PASS.

- [ ] **Step 5: Run existing bridge/workspace regression tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_claude_bridge.py tests/test_workspace_manager.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/codex_claude_orchestrator/worker_pool.py tests/test_worker_pool.py
git commit -m "feat: manage claude bridge crew workers"
```

## Task 5: CrewController Start Flow

**Files:**
- Create: `src/codex_claude_orchestrator/crew_controller.py`
- Create: `tests/test_crew_controller.py`

- [ ] **Step 1: Write failing controller tests**

```python
# tests/test_crew_controller.py
from pathlib import Path

from codex_claude_orchestrator.blackboard import BlackboardStore
from codex_claude_orchestrator.crew_controller import CrewController
from codex_claude_orchestrator.crew_models import CrewStatus, WorkerRole
from codex_claude_orchestrator.crew_recorder import CrewRecorder
from codex_claude_orchestrator.task_graph import TaskGraphPlanner


class FakeWorkerPool:
    def __init__(self):
        self.started = []

    def start_worker(self, *, repo_root, crew, task):
        self.started.append((repo_root, crew.crew_id, task.task_id, task.role_required))
        return type(
            "Worker",
            (),
            {
                "worker_id": f"worker-{task.role_required.value}",
                "to_dict": lambda self: {"worker_id": self.worker_id},
            },
        )()


def test_crew_controller_starts_default_crew_and_records_tasks(tmp_path: Path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    recorder = CrewRecorder(repo_root / ".orchestrator")
    pool = FakeWorkerPool()
    controller = CrewController(
        recorder=recorder,
        blackboard=BlackboardStore(recorder),
        task_graph=TaskGraphPlanner(task_id_factory=lambda role: f"task-{role.value}"),
        worker_pool=pool,
        crew_id_factory=lambda: "crew-1",
        entry_id_factory=lambda: "entry-created",
    )

    crew = controller.start(
        repo_root=repo_root,
        goal="Build V3",
        worker_roles=[WorkerRole.EXPLORER, WorkerRole.IMPLEMENTER, WorkerRole.REVIEWER],
    )

    details = recorder.read_crew("crew-1")
    assert crew.status == CrewStatus.RUNNING
    assert crew.active_worker_ids == ["worker-explorer", "worker-implementer", "worker-reviewer"]
    assert [item[3] for item in pool.started] == [WorkerRole.EXPLORER, WorkerRole.IMPLEMENTER, WorkerRole.REVIEWER]
    assert [task["task_id"] for task in details["tasks"]] == ["task-explorer", "task-implementer", "task-reviewer"]
    assert details["blackboard"][0]["type"] == "decision"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_crew_controller.py -v
```

Expected: FAIL because `crew_controller` does not exist.

- [ ] **Step 3: Implement `CrewController.start()`**

```python
# src/codex_claude_orchestrator/crew_controller.py
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

from codex_claude_orchestrator.blackboard import BlackboardStore
from codex_claude_orchestrator.crew_models import (
    ActorType,
    BlackboardEntry,
    BlackboardEntryType,
    CrewRecord,
    CrewStatus,
    WorkerRole,
)
from codex_claude_orchestrator.crew_recorder import CrewRecorder
from codex_claude_orchestrator.task_graph import TaskGraphPlanner
from codex_claude_orchestrator.worker_pool import WorkerPool


class CrewController:
    def __init__(
        self,
        *,
        recorder: CrewRecorder,
        blackboard: BlackboardStore,
        task_graph: TaskGraphPlanner,
        worker_pool: WorkerPool,
        crew_id_factory: Callable[[], str] | None = None,
        entry_id_factory: Callable[[], str] | None = None,
    ):
        self._recorder = recorder
        self._blackboard = blackboard
        self._task_graph = task_graph
        self._worker_pool = worker_pool
        self._crew_id_factory = crew_id_factory or (lambda: f"crew-{uuid4().hex}")
        self._entry_id_factory = entry_id_factory or (lambda: f"entry-{uuid4().hex}")

    def start(self, *, repo_root: Path, goal: str, worker_roles: list[WorkerRole]) -> CrewRecord:
        crew_id = self._crew_id_factory()
        crew = CrewRecord(
            crew_id=crew_id,
            root_goal=goal,
            repo=repo_root.resolve(),
            status=CrewStatus.PLANNING,
            max_workers=len(worker_roles),
            task_graph_path=repo_root / ".orchestrator" / "crews" / crew_id / "tasks.json",
            blackboard_path=repo_root / ".orchestrator" / "crews" / crew_id / "blackboard.jsonl",
        )
        self._recorder.start_crew(crew)
        self._blackboard.append(
            BlackboardEntry(
                entry_id=self._entry_id_factory(),
                crew_id=crew.crew_id,
                task_id=None,
                actor_type=ActorType.CODEX,
                actor_id="codex",
                type=BlackboardEntryType.DECISION,
                content=f"Created crew for goal: {goal}",
                confidence=1.0,
            )
        )
        tasks = self._task_graph.default_graph(crew.crew_id, goal, worker_roles)
        active_worker_ids: list[str] = []
        for task in tasks:
            worker = self._worker_pool.start_worker(repo_root=repo_root, crew=crew, task=task)
            active_worker_ids.append(worker.worker_id)
            tasks = self._task_graph.assign(tasks, task.task_id, worker.worker_id)
            self._recorder.write_tasks(crew.crew_id, tasks)
        updated = self._recorder.update_crew(
            crew.crew_id,
            {"status": CrewStatus.RUNNING.value, "active_worker_ids": active_worker_ids},
        )
        return CrewRecord(
            crew_id=updated["crew_id"],
            root_goal=updated["root_goal"],
            repo=updated["repo"],
            status=CrewStatus(updated["status"]),
            planner_summary=updated.get("planner_summary", ""),
            max_workers=updated.get("max_workers", len(worker_roles)),
            active_worker_ids=updated.get("active_worker_ids", []),
            task_graph_path=updated.get("task_graph_path", ""),
            blackboard_path=updated.get("blackboard_path", ""),
            verification_summary=updated.get("verification_summary", ""),
            merge_summary=updated.get("merge_summary", ""),
            created_at=updated["created_at"],
            updated_at=updated["updated_at"],
            ended_at=updated.get("ended_at"),
            final_summary=updated.get("final_summary", ""),
        )
```

- [ ] **Step 4: Run tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_crew_controller.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/codex_claude_orchestrator/crew_controller.py tests/test_crew_controller.py
git commit -m "feat: add crew controller start flow"
```

## Task 6: Crew CLI Commands

**Files:**
- Modify: `src/codex_claude_orchestrator/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Add failing parser and CLI tests**

Append these tests to `tests/test_cli.py`:

```python
def test_build_parser_exposes_crew_commands():
    from codex_claude_orchestrator.cli import build_parser

    parser = build_parser()
    subparsers_action = next(action for action in parser._actions if action.dest == "command")

    assert "crew" in subparsers_action.choices


class FakeCrewController:
    def __init__(self):
        self.started = []

    def start(self, **kwargs):
        self.started.append(kwargs)
        return type(
            "Crew",
            (),
            {
                "to_dict": lambda self: {
                    "crew_id": "crew-cli",
                    "root_goal": "Build V3",
                    "status": "running",
                    "active_worker_ids": ["worker-explorer", "worker-implementer"],
                }
            },
        )()


def test_main_crew_start_prints_json_summary(tmp_path: Path, monkeypatch):
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
                "--goal",
                "Build V3",
                "--repo",
                str(repo_root),
                "--workers",
                "explorer,implementer",
            ]
        )

    payload = json.loads(stdout.getvalue())
    assert exit_code == 0
    assert payload["crew_id"] == "crew-cli"
    assert fake_controller.started[0]["worker_roles"][0].value == "explorer"
    assert fake_controller.started[0]["worker_roles"][1].value == "implementer"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_cli.py::test_build_parser_exposes_crew_commands tests/test_cli.py::test_main_crew_start_prints_json_summary -v
```

Expected: FAIL because `crew` command and `build_crew_controller` do not exist.

- [ ] **Step 3: Modify imports in `cli.py`**

Add:

```python
from codex_claude_orchestrator.blackboard import BlackboardStore
from codex_claude_orchestrator.crew_controller import CrewController
from codex_claude_orchestrator.crew_models import WorkerRole
from codex_claude_orchestrator.crew_recorder import CrewRecorder
from codex_claude_orchestrator.task_graph import TaskGraphPlanner
from codex_claude_orchestrator.worker_pool import WorkerPool
```

- [ ] **Step 4: Add parser branch in `build_parser()`**

Add near the other top-level commands:

```python
    crew = subparsers.add_parser("crew", help="Manage Codex-managed Claude crews")
    crew_subparsers = crew.add_subparsers(dest="crew_command", required=True)
    crew_start = crew_subparsers.add_parser("start", help="Start a V3 crew")
    crew_start.add_argument("--repo", required=True)
    crew_start.add_argument("--goal", required=True)
    crew_start.add_argument(
        "--workers",
        default="explorer,implementer,reviewer",
        help="Comma-separated worker roles such as explorer,implementer,reviewer",
    )
    crew_status = crew_subparsers.add_parser("status", help="Show a crew")
    crew_status.add_argument("--repo", required=True)
    crew_status.add_argument("--crew", required=False)
    crew_blackboard = crew_subparsers.add_parser("blackboard", help="Show crew blackboard entries")
    crew_blackboard.add_argument("--repo", required=True)
    crew_blackboard.add_argument("--crew", required=False)
```

- [ ] **Step 5: Add builder and role parser**

Add below `build_claude_bridge()`:

```python
def build_crew_controller(repo_root: Path) -> CrewController:
    state_root = repo_root / ".orchestrator"
    recorder = CrewRecorder(state_root)
    blackboard = BlackboardStore(recorder)
    return CrewController(
        recorder=recorder,
        blackboard=blackboard,
        task_graph=TaskGraphPlanner(),
        worker_pool=WorkerPool(
            recorder=recorder,
            blackboard=blackboard,
            workspace_manager=WorkspaceManager(state_root),
            bridge_factory=lambda: build_claude_bridge(repo_root),
        ),
    )


def parse_worker_roles(value: str) -> list[WorkerRole]:
    roles = [part.strip() for part in value.split(",") if part.strip()]
    if not roles:
        raise ValueError("at least one worker role is required")
    return [WorkerRole(role) for role in roles]
```

- [ ] **Step 6: Route `crew` in `resolve_root_command()`**

Add:

```python
        ("crew_command", "crew"),
```

- [ ] **Step 7: Route `crew` in `main()`**

Add before `runs` handling:

```python
    if root_command == "crew":
        repo_root = Path(args.repo).resolve()
        recorder = CrewRecorder(repo_root / ".orchestrator")
        if args.crew_command == "start":
            crew = build_crew_controller(repo_root).start(
                repo_root=repo_root,
                goal=args.goal,
                worker_roles=parse_worker_roles(args.workers),
            )
            print(json.dumps(crew.to_dict(), ensure_ascii=False))
            return 0
        if args.crew_command == "status":
            crew_id = args.crew or recorder.latest_crew_id()
            if not crew_id:
                raise ValueError("no crew id provided and no latest crew exists")
            print(json.dumps(recorder.read_crew(crew_id), ensure_ascii=False))
            return 0
        if args.crew_command == "blackboard":
            crew_id = args.crew or recorder.latest_crew_id()
            if not crew_id:
                raise ValueError("no crew id provided and no latest crew exists")
            print(json.dumps({"blackboard": recorder.read_crew(crew_id)["blackboard"]}, ensure_ascii=False))
            return 0
        raise ValueError(f"Unsupported crew command: {args.crew_command}")
```

- [ ] **Step 8: Run CLI tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_cli.py -v
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/codex_claude_orchestrator/cli.py tests/test_cli.py
git commit -m "feat: expose crew cli commands"
```

## Task 7: Crew Verification, Challenge, And Accept

**Files:**
- Create: `src/codex_claude_orchestrator/crew_verification.py`
- Modify: `src/codex_claude_orchestrator/crew_controller.py`
- Modify: `src/codex_claude_orchestrator/cli.py`
- Create: `tests/test_crew_verification.py`
- Modify: `tests/test_crew_controller.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing crew verification test**

```python
# tests/test_crew_verification.py
from pathlib import Path
from subprocess import CompletedProcess

from codex_claude_orchestrator.crew_models import CrewRecord
from codex_claude_orchestrator.crew_recorder import CrewRecorder
from codex_claude_orchestrator.crew_verification import CrewVerificationRunner
from codex_claude_orchestrator.policy_gate import PolicyGate


def test_crew_verification_records_command_artifacts_and_blackboard_entry(tmp_path: Path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    recorder = CrewRecorder(repo_root / ".orchestrator")
    recorder.start_crew(CrewRecord(crew_id="crew-1", root_goal="Build V3", repo=repo_root))

    runner = CrewVerificationRunner(
        repo_root=repo_root,
        recorder=recorder,
        policy_gate=PolicyGate(),
        command_runner=lambda argv, **kwargs: CompletedProcess(argv, 0, stdout="ok\n", stderr=""),
        entry_id_factory=lambda: "entry-verification",
        verification_id_factory=lambda: "verification-1",
    )

    result = runner.run("crew-1", "pytest -q")

    details = recorder.read_crew("crew-1")
    assert result["passed"] is True
    assert result["command"] == "pytest -q"
    assert details["blackboard"][0]["type"] == "verification"
    assert details["artifacts"] == [
        "verification/verification-1/stderr.txt",
        "verification/verification-1/stdout.txt",
    ]
```

- [ ] **Step 2: Run verification test to verify it fails**

Run:

```bash
.venv/bin/python -m pytest tests/test_crew_verification.py -v
```

Expected: FAIL because `crew_verification` does not exist.

- [ ] **Step 3: Implement `CrewVerificationRunner`**

```python
# src/codex_claude_orchestrator/crew_verification.py
from __future__ import annotations

import shlex
import subprocess
from collections.abc import Callable
from pathlib import Path
from subprocess import CompletedProcess
from uuid import uuid4

from codex_claude_orchestrator.crew_models import ActorType, BlackboardEntry, BlackboardEntryType
from codex_claude_orchestrator.crew_recorder import CrewRecorder
from codex_claude_orchestrator.policy_gate import PolicyGate


CommandRunner = Callable[..., CompletedProcess[str]]


class CrewVerificationRunner:
    def __init__(
        self,
        *,
        repo_root: Path,
        recorder: CrewRecorder,
        policy_gate: PolicyGate,
        timeout_seconds: int = 120,
        command_runner: CommandRunner | None = None,
        entry_id_factory: Callable[[], str] | None = None,
        verification_id_factory: Callable[[], str] | None = None,
    ):
        self._repo_root = repo_root
        self._recorder = recorder
        self._policy_gate = policy_gate
        self._timeout_seconds = timeout_seconds
        self._command_runner = command_runner or subprocess.run
        self._entry_id_factory = entry_id_factory or (lambda: f"entry-{uuid4().hex}")
        self._verification_id_factory = verification_id_factory or (lambda: f"verification-{uuid4().hex}")

    def run(self, crew_id: str, command: str) -> dict:
        verification_id = self._verification_id_factory()
        stdout_name = f"verification/{verification_id}/stdout.txt"
        stderr_name = f"verification/{verification_id}/stderr.txt"
        argv = shlex.split(command)
        decision = self._policy_gate.guard_command(argv)
        if not decision.allowed:
            reason = decision.reason or "command blocked by policy"
            stdout_path = self._recorder.write_text_artifact(crew_id, stdout_name, "")
            stderr_path = self._recorder.write_text_artifact(crew_id, stderr_name, f"{reason}\n")
            payload = {
                "verification_id": verification_id,
                "command": command,
                "passed": False,
                "exit_code": None,
                "summary": f"command blocked: {reason}",
                "stdout_artifact": str(stdout_path),
                "stderr_artifact": str(stderr_path),
            }
        else:
            result = self._command_runner(
                argv,
                cwd=self._repo_root,
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
            )
            stdout_path = self._recorder.write_text_artifact(crew_id, stdout_name, result.stdout)
            stderr_path = self._recorder.write_text_artifact(crew_id, stderr_name, result.stderr)
            payload = {
                "verification_id": verification_id,
                "command": command,
                "passed": result.returncode == 0,
                "exit_code": result.returncode,
                "summary": f"command {'passed' if result.returncode == 0 else 'failed'}: exit code {result.returncode}",
                "stdout_artifact": str(stdout_path),
                "stderr_artifact": str(stderr_path),
            }
        self._recorder.append_blackboard(
            crew_id,
            BlackboardEntry(
                entry_id=self._entry_id_factory(),
                crew_id=crew_id,
                task_id=None,
                actor_type=ActorType.CODEX,
                actor_id="codex",
                type=BlackboardEntryType.VERIFICATION,
                content=payload["summary"],
                evidence_refs=[payload["stdout_artifact"], payload["stderr_artifact"]],
                confidence=1.0,
            ),
        )
        return payload
```

- [ ] **Step 4: Extend `CrewController` with verify/challenge/accept**

Add constructor argument:

```python
        verification_runner=None,
```

Store it as `self._verification_runner`.

Add methods:

```python
    def verify(self, *, crew_id: str, command: str) -> dict:
        if self._verification_runner is None:
            raise ValueError("crew verification runner is not configured")
        result = self._verification_runner.run(crew_id, command)
        self._recorder.update_crew(crew_id, {"verification_summary": result["summary"]})
        return result

    def challenge(self, *, crew_id: str, summary: str, task_id: str | None = None) -> dict:
        entry = BlackboardEntry(
            entry_id=self._entry_id_factory(),
            crew_id=crew_id,
            task_id=task_id,
            actor_type=ActorType.CODEX,
            actor_id="codex",
            type=BlackboardEntryType.RISK,
            content=summary,
            confidence=0.8,
        )
        return self._blackboard.append(entry)

    def accept(self, *, crew_id: str, summary: str) -> dict:
        self._recorder.finalize_crew(crew_id, CrewStatus.ACCEPTED, summary)
        return self._recorder.read_crew(crew_id)["crew"]
```

- [ ] **Step 5: Add CLI parser commands**

In `build_parser()`, add:

```python
    crew_verify = crew_subparsers.add_parser("verify", help="Run crew verification")
    crew_verify.add_argument("--repo", required=True)
    crew_verify.add_argument("--crew", required=False)
    crew_verify.add_argument("--command", required=True)
    crew_challenge = crew_subparsers.add_parser("challenge", help="Record a Codex crew challenge")
    crew_challenge.add_argument("--repo", required=True)
    crew_challenge.add_argument("--crew", required=False)
    crew_challenge.add_argument("--task", required=False)
    crew_challenge.add_argument("--summary", required=True)
    crew_accept = crew_subparsers.add_parser("accept", help="Accept a crew")
    crew_accept.add_argument("--repo", required=True)
    crew_accept.add_argument("--crew", required=False)
    crew_accept.add_argument("--summary", required=True)
```

- [ ] **Step 6: Wire verification runner into `build_crew_controller()`**

Add imports:

```python
from codex_claude_orchestrator.crew_verification import CrewVerificationRunner
```

Pass:

```python
        verification_runner=CrewVerificationRunner(
            repo_root=repo_root,
            recorder=recorder,
            policy_gate=PolicyGate(),
        ),
```

- [ ] **Step 7: Add CLI command routing**

Inside `root_command == "crew"`:

```python
        controller = build_crew_controller(repo_root)
        if args.crew_command == "verify":
            crew_id = args.crew or recorder.latest_crew_id()
            if not crew_id:
                raise ValueError("no crew id provided and no latest crew exists")
            print(json.dumps(controller.verify(crew_id=crew_id, command=args.command), ensure_ascii=False))
            return 0
        if args.crew_command == "challenge":
            crew_id = args.crew or recorder.latest_crew_id()
            if not crew_id:
                raise ValueError("no crew id provided and no latest crew exists")
            print(
                json.dumps(
                    controller.challenge(crew_id=crew_id, task_id=args.task, summary=args.summary),
                    ensure_ascii=False,
                )
            )
            return 0
        if args.crew_command == "accept":
            crew_id = args.crew or recorder.latest_crew_id()
            if not crew_id:
                raise ValueError("no crew id provided and no latest crew exists")
            print(json.dumps(controller.accept(crew_id=crew_id, summary=args.summary), ensure_ascii=False))
            return 0
```

- [ ] **Step 8: Run tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_crew_verification.py tests/test_crew_controller.py tests/test_cli.py -v
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/codex_claude_orchestrator/crew_verification.py src/codex_claude_orchestrator/crew_controller.py src/codex_claude_orchestrator/cli.py tests/test_crew_verification.py tests/test_crew_controller.py tests/test_cli.py
git commit -m "feat: add crew verification challenge and accept"
```

## Task 8: Merge Arbiter

**Files:**
- Create: `src/codex_claude_orchestrator/merge_arbiter.py`
- Create: `tests/test_merge_arbiter.py`
- Modify: `src/codex_claude_orchestrator/crew_controller.py`

- [ ] **Step 1: Write failing merge arbiter tests**

```python
# tests/test_merge_arbiter.py
from codex_claude_orchestrator.crew_models import WorkerRecord, WorkerRole
from codex_claude_orchestrator.merge_arbiter import MergeArbiter
from codex_claude_orchestrator.models import WorkspaceMode


def test_merge_arbiter_detects_overlapping_write_scopes():
    workers = [
        WorkerRecord(
            worker_id="worker-a",
            crew_id="crew-1",
            role=WorkerRole.IMPLEMENTER,
            agent_profile="claude",
            bridge_id="bridge-a",
            workspace_mode=WorkspaceMode.ISOLATED,
            workspace_path="/tmp/a",
            write_scope=["src/app.py"],
        ),
        WorkerRecord(
            worker_id="worker-b",
            crew_id="crew-1",
            role=WorkerRole.COMPETITOR,
            agent_profile="claude",
            bridge_id="bridge-b",
            workspace_mode=WorkspaceMode.ISOLATED,
            workspace_path="/tmp/b",
            write_scope=["src/app.py"],
        ),
    ]

    plan = MergeArbiter().build_plan("crew-1", workers, changed_files_by_worker={"worker-a": ["src/app.py"], "worker-b": ["src/app.py"]})

    assert plan["can_merge"] is False
    assert plan["conflicts"][0]["path"] == "src/app.py"
    assert plan["recommendation"] == "requires_codex_decision"


def test_merge_arbiter_allows_non_overlapping_scopes():
    workers = [
        WorkerRecord(
            worker_id="worker-a",
            crew_id="crew-1",
            role=WorkerRole.IMPLEMENTER,
            agent_profile="claude",
            bridge_id="bridge-a",
            workspace_mode=WorkspaceMode.ISOLATED,
            workspace_path="/tmp/a",
            write_scope=["src/app.py"],
        ),
        WorkerRecord(
            worker_id="worker-b",
            crew_id="crew-1",
            role=WorkerRole.IMPLEMENTER,
            agent_profile="claude",
            bridge_id="bridge-b",
            workspace_mode=WorkspaceMode.ISOLATED,
            workspace_path="/tmp/b",
            write_scope=["tests/test_app.py"],
        ),
    ]

    plan = MergeArbiter().build_plan("crew-1", workers, changed_files_by_worker={"worker-a": ["src/app.py"], "worker-b": ["tests/test_app.py"]})

    assert plan["can_merge"] is True
    assert plan["conflicts"] == []
    assert plan["recommendation"] == "ready_for_codex_review"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_merge_arbiter.py -v
```

Expected: FAIL because `merge_arbiter` does not exist.

- [ ] **Step 3: Implement `MergeArbiter`**

```python
# src/codex_claude_orchestrator/merge_arbiter.py
from __future__ import annotations

from codex_claude_orchestrator.crew_models import WorkerRecord


class MergeArbiter:
    def build_plan(
        self,
        crew_id: str,
        workers: list[WorkerRecord],
        *,
        changed_files_by_worker: dict[str, list[str]],
    ) -> dict:
        path_owners: dict[str, list[str]] = {}
        for worker in workers:
            for path in changed_files_by_worker.get(worker.worker_id, []):
                path_owners.setdefault(path, []).append(worker.worker_id)

        conflicts = [
            {"path": path, "workers": owners}
            for path, owners in sorted(path_owners.items())
            if len(set(owners)) > 1
        ]
        can_merge = len(conflicts) == 0
        return {
            "crew_id": crew_id,
            "can_merge": can_merge,
            "conflicts": conflicts,
            "changed_files_by_worker": changed_files_by_worker,
            "recommendation": "ready_for_codex_review" if can_merge else "requires_codex_decision",
        }
```

- [ ] **Step 4: Add `CrewController.merge_plan()`**

Add constructor argument:

```python
        merge_arbiter=None,
```

Store it as `self._merge_arbiter`.

Add method:

```python
    def merge_plan(self, *, crew_id: str, changed_files_by_worker: dict[str, list[str]] | None = None) -> dict:
        if self._merge_arbiter is None:
            raise ValueError("crew merge arbiter is not configured")
        details = self._recorder.read_crew(crew_id)
        workers = [
            WorkerRecord(
                worker_id=item["worker_id"],
                crew_id=item["crew_id"],
                role=WorkerRole(item["role"]),
                agent_profile=item["agent_profile"],
                bridge_id=item.get("bridge_id"),
                workspace_mode=WorkspaceMode(item["workspace_mode"]),
                workspace_path=item["workspace_path"],
                write_scope=item.get("write_scope", []),
                allowed_tools=item.get("allowed_tools", []),
            )
            for item in details["workers"]
        ]
        plan = self._merge_arbiter.build_plan(crew_id, workers, changed_files_by_worker=changed_files_by_worker or {})
        self._recorder.update_crew(crew_id, {"merge_summary": plan["recommendation"]})
        return plan
```

Add imports:

```python
from codex_claude_orchestrator.crew_models import WorkerRecord
from codex_claude_orchestrator.models import WorkspaceMode
```

- [ ] **Step 5: Wire `MergeArbiter` in CLI builder and add CLI command**

In `cli.py`, import:

```python
from codex_claude_orchestrator.merge_arbiter import MergeArbiter
```

Pass into `CrewController`:

```python
        merge_arbiter=MergeArbiter(),
```

Add parser:

```python
    crew_merge_plan = crew_subparsers.add_parser("merge-plan", help="Build a crew merge plan")
    crew_merge_plan.add_argument("--repo", required=True)
    crew_merge_plan.add_argument("--crew", required=False)
```

Add route:

```python
        if args.crew_command == "merge-plan":
            crew_id = args.crew or recorder.latest_crew_id()
            if not crew_id:
                raise ValueError("no crew id provided and no latest crew exists")
            print(json.dumps(controller.merge_plan(crew_id=crew_id), ensure_ascii=False))
            return 0
```

- [ ] **Step 6: Run tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_merge_arbiter.py tests/test_crew_controller.py tests/test_cli.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/codex_claude_orchestrator/merge_arbiter.py src/codex_claude_orchestrator/crew_controller.py src/codex_claude_orchestrator/cli.py tests/test_merge_arbiter.py tests/test_crew_controller.py tests/test_cli.py
git commit -m "feat: add crew merge arbitration"
```

## Task 9: UI Crew Visibility

**Files:**
- Modify: `src/codex_claude_orchestrator/ui_server.py`
- Modify: `tests/test_ui_server.py`

- [ ] **Step 1: Add failing UI tests**

Append to `tests/test_ui_server.py`:

```python
from codex_claude_orchestrator.crew_models import CrewRecord
from codex_claude_orchestrator.crew_recorder import CrewRecorder


def test_build_ui_state_includes_crews(tmp_path: Path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    CrewRecorder(repo_root / ".orchestrator").start_crew(
        CrewRecord(crew_id="crew-ui", root_goal="Show crew", repo=repo_root)
    )

    state = build_ui_state(repo_root)

    assert state["crews"][0]["crew_id"] == "crew-ui"


def test_ui_routes_serve_crew_details(tmp_path: Path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    CrewRecorder(repo_root / ".orchestrator").start_crew(
        CrewRecord(crew_id="crew-ui", root_goal="Show crew", repo=repo_root)
    )

    content_type, body = resolve_ui_request(repo_root, "/api/crews/crew-ui")
    payload = json.loads(body)

    assert content_type == "application/json; charset=utf-8"
    assert payload["crew"]["crew_id"] == "crew-ui"


def test_render_index_html_contains_crew_surface(tmp_path: Path):
    html = render_index_html(tmp_path)

    assert "Crews" in html
    assert "Blackboard" in html
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_ui_server.py::test_build_ui_state_includes_crews tests/test_ui_server.py::test_ui_routes_serve_crew_details tests/test_ui_server.py::test_render_index_html_contains_crew_surface -v
```

Expected: FAIL because UI does not include crews.

- [ ] **Step 3: Modify `ui_server.py` imports and state**

Add import:

```python
from codex_claude_orchestrator.crew_recorder import CrewRecorder
```

Modify `build_ui_state()`:

```python
    return {
        "repo": str(repo_root),
        "crews": CrewRecorder(state_root).list_crews(),
        "sessions": SessionRecorder(state_root).list_sessions(),
        "runs": RunRecorder(state_root).list_runs(),
        "skills": SkillEvolution(state_root).list_skills(),
    }
```

- [ ] **Step 4: Add `/api/crews/<crew_id>` route**

In `resolve_ui_request()`:

```python
    crew_recorder = CrewRecorder(state_root)
```

Add before sessions route:

```python
    if path.startswith("/api/crews/"):
        crew_id = _safe_resource_id(path.removeprefix("/api/crews/"))
        return "application/json; charset=utf-8", _json(crew_recorder.read_crew(crew_id))
```

- [ ] **Step 5: Update HTML labels minimally**

In `render_index_html()`, change the title from `Orchestrator V2 Console` to:

```html
<title>Orchestrator Console</title>
```

Update visible heading and panes so these strings exist:

```html
<h1>Orchestrator Console</h1>
```

Add a crew section label near the existing session list:

```html
<div class="pane-head">Crews</div>
```

Add a details label in the main content area:

```html
<h2>Blackboard</h2>
```

Keep existing session/run/skill labels so old tests can be updated deliberately in the same step.

- [ ] **Step 6: Update older UI tests that assert old title**

Replace assertions expecting `"Orchestrator V2 Console"` with `"Orchestrator Console"`.

- [ ] **Step 7: Run UI tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_ui_server.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/codex_claude_orchestrator/ui_server.py tests/test_ui_server.py
git commit -m "feat: show crews in orchestrator ui"
```

## Task 10: End-To-End Fake Crew Flow And Regression

**Files:**
- Modify: `tests/test_crew_controller.py`

- [ ] **Step 1: Add an end-to-end fake crew flow test**

Append to `tests/test_crew_controller.py`:

```python
def test_crew_controller_fake_flow_start_verify_challenge_accept(tmp_path: Path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    recorder = CrewRecorder(repo_root / ".orchestrator")
    pool = FakeWorkerPool()

    class FakeVerificationRunner:
        def run(self, crew_id, command):
            return {"verification_id": "verification-1", "command": command, "passed": True, "summary": "command passed: exit code 0"}

    controller = CrewController(
        recorder=recorder,
        blackboard=BlackboardStore(recorder),
        task_graph=TaskGraphPlanner(task_id_factory=lambda role: f"task-{role.value}"),
        worker_pool=pool,
        verification_runner=FakeVerificationRunner(),
        crew_id_factory=lambda: "crew-1",
        entry_id_factory=lambda: "entry-flow",
    )

    crew = controller.start(repo_root=repo_root, goal="Build V3", worker_roles=[WorkerRole.EXPLORER])
    verification = controller.verify(crew_id=crew.crew_id, command="pytest -q")
    challenge = controller.challenge(crew_id=crew.crew_id, summary="Need more evidence", task_id="task-explorer")
    accepted = controller.accept(crew_id=crew.crew_id, summary="accepted with evidence")

    assert verification["passed"] is True
    assert challenge["type"] == "risk"
    assert accepted["status"] == "accepted"
    assert recorder.read_crew("crew-1")["final_report"]["final_summary"] == "accepted with evidence"
```

- [ ] **Step 2: Run the fake flow test**

Run:

```bash
.venv/bin/python -m pytest tests/test_crew_controller.py::test_crew_controller_fake_flow_start_verify_challenge_accept -v
```

Expected: PASS.

- [ ] **Step 3: Run all V3-focused tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_crew_models.py tests/test_crew_recorder.py tests/test_blackboard.py tests/test_task_graph.py tests/test_worker_pool.py tests/test_crew_controller.py tests/test_crew_verification.py tests/test_merge_arbiter.py -q
```

Expected: PASS.

- [ ] **Step 4: Run V1/V2 regression tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_supervisor.py tests/test_session_engine.py tests/test_claude_bridge.py tests/test_cli.py tests/test_ui_server.py -q
```

Expected: PASS.

- [ ] **Step 5: Run full test suite**

Run:

```bash
.venv/bin/python -m pytest -q
```

Expected: PASS.

- [ ] **Step 6: Commit final flow/regression test adjustments**

```bash
git add tests/test_crew_controller.py
git commit -m "test: cover crew v3 end to end flow"
```

## Manual Smoke Test

After all tasks pass, run a dry fake-friendly manual check on a small repo where invoking real Claude is acceptable:

```bash
.venv/bin/orchestrator crew start --repo /path/to/repo --goal "Inspect this repo and propose one safe improvement" --workers explorer
.venv/bin/orchestrator crew status --repo /path/to/repo
.venv/bin/orchestrator crew blackboard --repo /path/to/repo
.venv/bin/orchestrator crew verify --repo /path/to/repo --command ".venv/bin/python -m pytest -q"
.venv/bin/orchestrator crew accept --repo /path/to/repo --summary "accepted after verification"
```

Expected:

- `.orchestrator/crews/<crew_id>/crew.json` exists.
- `.orchestrator/crews/<crew_id>/tasks.json` exists.
- `.orchestrator/crews/<crew_id>/workers.jsonl` exists.
- `.orchestrator/crews/<crew_id>/blackboard.jsonl` contains decision and verification entries.
- `crew status` returns JSON with `crew`, `tasks`, `workers`, `blackboard`, `final_report`, and `artifacts`.

## Spec Coverage Checklist

- Version boundary V1/V2/V3: covered by Tasks 4-6 without changing existing V1/V2 entrypoints.
- Crew record: covered by Tasks 1-2.
- Worker roles: covered by Tasks 1, 3, and 4.
- TaskGraph: covered by Task 3.
- Blackboard: covered by Task 2.
- WorkerPool over ClaudeBridge: covered by Task 4.
- CrewController orchestration: covered by Task 5.
- Verification/challenge/accept: covered by Task 7.
- MergeArbiter: covered by Task 8.
- CLI/UX: covered by Task 6 and Task 7.
- UI visibility: covered by Task 9.
- Regression protection: covered by Task 10.
