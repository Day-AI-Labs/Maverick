from __future__ import annotations

from contextlib import contextmanager

import pytest
from maverick.world_model_backends import postgres
from maverick.world_model_backends.postgres import PostgresWorldModel


class RecordingCursor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...] | None]] = []

    def execute(self, sql: str, params: tuple[object, ...] | None = None) -> None:
        self.calls.append((sql, params))


def test_rls_sets_fail_closed_sentinel_without_active_tenant(monkeypatch):
    monkeypatch.setattr(postgres, "_active_tenant", lambda: None)
    world = PostgresWorldModel.__new__(PostgresWorldModel)
    world._rls = True
    cur = RecordingCursor()

    world._set_tenant_guc(cur)

    assert cur.calls == [
        ("SELECT set_config('maverick.tenant', %s, true)", ("__maverick_no_tenant__",))
    ]


def test_rls_policy_does_not_allow_unset_tenant_bypass():
    sql = PostgresWorldModel._rls_policy_sql("goals").lower()

    assert "current_setting('maverick.tenant'" in sql
    assert "tenant_id = nullif" in sql
    assert " with check " in f" {sql} "
    assert " or " not in sql
    assert "is null" not in sql


def test_rls_apply_raises_when_policy_cannot_be_installed_or_verified(monkeypatch):
    world = PostgresWorldModel.__new__(PostgresWorldModel)

    @contextmanager
    def failing_tx():
        raise PermissionError("no alter table")
        yield  # pragma: no cover

    monkeypatch.setattr(postgres, "_TENANT_TABLES", ["goals"])
    monkeypatch.setattr(world, "_tx", failing_tx)
    monkeypatch.setattr(world, "_rls_policy_is_active", lambda table: False)

    with pytest.raises(RuntimeError, match="could not be installed or verified on goals"):
        world._apply_rls()

def test_rls_covers_projects_and_fact_history():
    # Council #7: projects (v15) and fact_history (v18) carry tenant_id but were
    # absent from the RLS set, so a PG deployment left them app-layer-only. They
    # must be RLS-scoped, while staying OUT of the v10 column-add migration list.
    assert "projects" in postgres._RLS_TABLES
    assert "fact_history" in postgres._RLS_TABLES
    assert "projects" not in postgres._TENANT_TABLES      # not in the v10 ALTER set
    assert "fact_history" not in postgres._TENANT_TABLES
    # Every v10 tenant table is still RLS-covered.
    assert set(postgres._TENANT_TABLES).issubset(set(postgres._RLS_TABLES))


# --- #51/#57: enterprise auto-on for strict isolation + RLS ----------------

@pytest.fixture
def _clean_toggle_env(monkeypatch):
    for var in ("MAVERICK_STRICT_TENANT_ISOLATION", "MAVERICK_PG_RLS"):
        monkeypatch.delenv(var, raising=False)
    # No config and not enterprise unless a test opts in.
    monkeypatch.setattr("maverick.config.load_config", lambda *a, **k: {})
    monkeypatch.setattr("maverick.enterprise.enterprise_enabled", lambda: False)


def test_toggles_default_off_without_enterprise(_clean_toggle_env):
    assert postgres._strict_tenant_isolation() is False
    assert postgres._rls_enabled() is False
    assert postgres._rls_explicitly_set() is False


def test_toggles_auto_on_under_enterprise(_clean_toggle_env, monkeypatch):
    monkeypatch.setattr("maverick.enterprise.enterprise_enabled", lambda: True)
    assert postgres._strict_tenant_isolation() is True
    assert postgres._rls_enabled() is True
    # Auto-on is NOT an explicit operator choice -> the boot preflight applies.
    assert postgres._rls_explicitly_set() is False


def test_explicit_env_off_overrides_enterprise(_clean_toggle_env, monkeypatch):
    monkeypatch.setattr("maverick.enterprise.enterprise_enabled", lambda: True)
    monkeypatch.setenv("MAVERICK_PG_RLS", "0")
    monkeypatch.setenv("MAVERICK_STRICT_TENANT_ISOLATION", "off")
    assert postgres._rls_enabled() is False
    assert postgres._strict_tenant_isolation() is False
    assert postgres._rls_explicitly_set() is True


def test_explicit_env_on_is_explicit(_clean_toggle_env, monkeypatch):
    monkeypatch.setenv("MAVERICK_PG_RLS", "1")
    assert postgres._rls_enabled() is True
    assert postgres._rls_explicitly_set() is True


def test_config_toggle_resolves_when_env_absent(_clean_toggle_env, monkeypatch):
    monkeypatch.setattr(
        "maverick.config.load_config",
        lambda *a, **k: {"world_model": {"rls": True, "strict_tenant_isolation": "yes"}},
    )
    assert postgres._rls_enabled() is True
    assert postgres._strict_tenant_isolation() is True
    assert postgres._rls_explicitly_set() is True


def test_preflight_refuses_boot_on_legacy_null_rows_when_auto_on(monkeypatch):
    # Enterprise auto-on (not explicit) + a table with NULL-tenant rows -> refuse.
    monkeypatch.setattr(postgres, "_rls_explicitly_set", lambda: False)
    monkeypatch.setattr(
        "maverick.world_model_backends.pg_rls.preflight",
        lambda conn: {"role": "app", "ready": False, "tables": {
            "goals": {"null_tenant_rows": 3, "owned_by_current_role": True},
            "facts": {"null_tenant_rows": 0, "owned_by_current_role": True},
        }},
    )
    world = PostgresWorldModel.__new__(PostgresWorldModel)
    world._pool = None
    world.conn = object()
    with pytest.raises(RuntimeError, match="tenant backfill"):
        world._preflight_rls_or_die()


def test_preflight_passes_when_no_null_rows(monkeypatch):
    monkeypatch.setattr(postgres, "_rls_explicitly_set", lambda: False)
    monkeypatch.setattr(
        "maverick.world_model_backends.pg_rls.preflight",
        lambda conn: {"role": "app", "ready": True, "tables": {
            "goals": {"null_tenant_rows": 0, "owned_by_current_role": True},
        }},
    )
    world = PostgresWorldModel.__new__(PostgresWorldModel)
    world._pool = None
    world.conn = object()
    world._preflight_rls_or_die()  # no raise


def test_preflight_skipped_when_explicitly_opted_in(monkeypatch):
    # Explicit MAVERICK_PG_RLS=1 keeps the old fail-closed path: no boot refusal
    # even with NULL rows present (operator knowingly opted in).
    monkeypatch.setattr(postgres, "_rls_explicitly_set", lambda: True)
    called = {"preflight": False}

    def _should_not_run(conn):  # pragma: no cover -- asserted not called
        called["preflight"] = True
        return {"tables": {}}

    monkeypatch.setattr(
        "maverick.world_model_backends.pg_rls.preflight", _should_not_run)
    world = PostgresWorldModel.__new__(PostgresWorldModel)
    world._pool = None
    world.conn = object()
    world._preflight_rls_or_die()
    assert called["preflight"] is False
