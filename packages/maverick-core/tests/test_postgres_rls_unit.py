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
