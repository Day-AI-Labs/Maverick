"""Postgres backend: versioned-migration planner + tenant read-scoping.

These exercise the *pure* logic (no live Postgres, no psycopg) so the upgrade
ladder and the tenant predicate are covered even when no DB service is present.
The full round-trip lives in test_postgres_world.py (skipped without a DSN).
"""
from __future__ import annotations

import maverick.world_model_backends.postgres as pg


def test_pending_from_fresh_db_applies_everything():
    pending = pg.pending_migrations(0)
    versions = [v for v, _ in pending]
    assert versions == sorted(versions)  # ascending
    assert versions[0] == 1  # base schema first
    assert pg._PG_SCHEMA_VERSION in versions  # tenant migration included


def test_pending_skips_already_applied():
    # A DB already at the latest version has nothing to do.
    assert pg.pending_migrations(pg._PG_SCHEMA_VERSION) == []
    # A DB at v1 still needs both tenant migrations (v10 columns, v11 uniques).
    pending = pg.pending_migrations(1)
    assert [v for v, _ in pending] == [10, 11]
    # A DB at v10 still needs the tenant-unique migration.
    assert [v for v, _ in pg.pending_migrations(10)] == [11]


def test_pending_is_ordered_with_custom_ladder():
    ladder = [(3, ["c"]), (1, ["a"]), (2, ["b"])]
    assert pg.pending_migrations(0, ladder) == [(1, ["a"]), (2, ["b"]), (3, ["c"])]
    assert pg.pending_migrations(1, ladder) == [(2, ["b"]), (3, ["c"])]


def test_tenant_migration_adds_column_and_index_for_root_tables():
    stmts = dict(pg.MIGRATIONS)[10]
    joined = "\n".join(stmts)
    for table in pg._TENANT_TABLES:
        assert f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS tenant_id TEXT" in joined
        assert f"idx_pg_{table}_tenant" in joined


def test_tenant_unique_migration_makes_constraints_tenant_aware():
    stmts = dict(pg.MIGRATIONS)[11]
    joined = "\n".join(stmts)
    # The global UNIQUEs are dropped and replaced with COALESCE(tenant_id,'')
    # expression indexes so single-tenant (NULL) dedup is preserved.
    assert "DROP CONSTRAINT IF EXISTS facts_key_key" in joined
    assert "uq_pg_facts_tenant_key" in joined
    assert "uq_pg_conversations_tenant_chan_user" in joined
    assert "uq_pg_processed_tenant_chan_ext" in joined
    assert joined.count("COALESCE(tenant_id, '')") == 3  # one per unique table


def test_schema_version_is_latest_migration():
    assert pg._PG_SCHEMA_VERSION == 11
    assert pg._PG_SCHEMA_VERSION == max(v for v, _ in pg.MIGRATIONS)


def test_tenant_scope_noop_without_active_tenant(monkeypatch):
    monkeypatch.setattr(pg, "_active_tenant", lambda: None)
    frag, params = pg._tenant_scope()
    assert frag == ""
    assert params == []


def test_tenant_scope_filters_to_active_tenant_null_tolerant(monkeypatch):
    monkeypatch.setattr(pg, "_active_tenant", lambda: "acme")
    monkeypatch.setattr(pg, "_strict_tenant_isolation", lambda: False)
    frag, params = pg._tenant_scope()
    assert frag == "(tenant_id = %s OR tenant_id IS NULL)"
    assert params == ["acme"]


def test_strict_tenant_isolation_excludes_legacy_null(monkeypatch):
    monkeypatch.setattr(pg, "_active_tenant", lambda: "acme")
    monkeypatch.setattr(pg, "_strict_tenant_isolation", lambda: True)
    frag, params = pg._tenant_scope()
    # Strict mode: only the tenant's own rows, no NULL-legacy tolerance.
    assert frag == "tenant_id = %s"
    assert params == ["acme"]


def test_strict_isolation_reads_env(monkeypatch):
    monkeypatch.delenv("MAVERICK_STRICT_TENANT_ISOLATION", raising=False)
    assert pg._strict_tenant_isolation() is False
    monkeypatch.setenv("MAVERICK_STRICT_TENANT_ISOLATION", "1")
    assert pg._strict_tenant_isolation() is True
    monkeypatch.setenv("MAVERICK_STRICT_TENANT_ISOLATION", "off")
    assert pg._strict_tenant_isolation() is False


def test_tenant_scope_custom_column(monkeypatch):
    monkeypatch.setattr(pg, "_active_tenant", lambda: "acme")
    frag, _ = pg._tenant_scope("goals.tenant_id")
    assert frag == "(goals.tenant_id = %s OR goals.tenant_id IS NULL)"
