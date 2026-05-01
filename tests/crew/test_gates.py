from codex_claude_orchestrator.crew.gates import WriteScopeGate


def test_write_scope_gate_passes_when_changed_files_are_in_scope():
    result = WriteScopeGate().evaluate(
        changed_files=["src/app.py", "tests/test_app.py"],
        write_scope=["src/", "tests/"],
        evidence_refs=["workers/worker-source/changes.json"],
    )

    assert result.status == "pass"
    assert result.reason == "all changed files are inside write_scope"
    assert result.details["out_of_scope"] == []
    assert result.evidence_refs == ["workers/worker-source/changes.json"]


def test_write_scope_gate_passes_when_no_files_changed():
    result = WriteScopeGate().evaluate(changed_files=[], write_scope=[])

    assert result.status == "pass"
    assert result.reason == "no changed files"


def test_write_scope_gate_challenges_low_risk_out_of_scope_file():
    result = WriteScopeGate().evaluate(
        changed_files=["docs/notes.md"],
        write_scope=["src/", "tests/"],
    )

    assert result.status == "challenge"
    assert result.details["out_of_scope"] == ["docs/notes.md"]
    assert result.details["protected"] == []
    assert "outside write_scope" in result.reason


def test_write_scope_gate_blocks_protected_out_of_scope_file():
    result = WriteScopeGate().evaluate(
        changed_files=[".github/workflows/ci.yml"],
        write_scope=["src/", "tests/"],
    )

    assert result.status == "block"
    assert result.details["protected"] == [".github/workflows/ci.yml"]
    assert "protected" in result.reason


def test_write_scope_gate_blocks_changes_when_scope_is_empty():
    result = WriteScopeGate().evaluate(changed_files=["src/app.py"], write_scope=[])

    assert result.status == "block"
    assert result.reason == "write_scope is empty but files changed"
    assert result.details["out_of_scope"] == ["src/app.py"]
