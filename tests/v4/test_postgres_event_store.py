from __future__ import annotations

import pytest

from codex_claude_orchestrator.v4.postgres_event_store import (
    PostgresConfigurationError,
    PostgresEventStore,
    PostgresEventStoreConfig,
)


def test_postgres_config_uses_safe_defaults_without_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PG_HOST", raising=False)
    monkeypatch.delenv("PG_DB", raising=False)
    monkeypatch.delenv("PG_USER", raising=False)
    monkeypatch.delenv("PG_PASSWORD", raising=False)
    monkeypatch.delenv("PG_PORT", raising=False)

    config = PostgresEventStoreConfig.from_env()

    assert config.host == "124.222.58.173"
    assert config.database == "ragbase"
    assert config.user == "ragbase"
    assert config.port == 5432
    assert config.password is None


def test_postgres_config_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PG_HOST", "db.example.test")
    monkeypatch.setenv("PG_DB", "agents")
    monkeypatch.setenv("PG_USER", "runner")
    monkeypatch.setenv("PG_PASSWORD", "secret")
    monkeypatch.setenv("PG_PORT", "15432")

    config = PostgresEventStoreConfig.from_env()

    assert config.host == "db.example.test"
    assert config.database == "agents"
    assert config.user == "runner"
    assert config.password == "secret"
    assert config.port == 15432


def test_postgres_store_requires_password_before_connect(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PG_PASSWORD", raising=False)
    store = PostgresEventStore(PostgresEventStoreConfig.from_env())

    with pytest.raises(PostgresConfigurationError, match="PG_PASSWORD"):
        store.initialize()


def test_postgres_config_rejects_invalid_port(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PG_PORT", "not-a-port")

    with pytest.raises(PostgresConfigurationError, match="PG_PORT"):
        PostgresEventStoreConfig.from_env()
