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
    # A DB at v1 still needs the tenant migrations (v10 columns, v11 uniques),
    # approval-claims (v13), goal-domain (v14), projects (v15), artifacts (v16),
    # share/signoff/origin (v17), temporal fact_history (v18), rate_events (v19).
    pending = pg.pending_migrations(1)
    assert [v for v, _ in pending] == [10, 11, 13, 14, 15, 16, 17, 18, 19]
    # A DB at v10 still needs the remaining upgrades.
    assert [v for v, _ in pg.pending_migrations(10)] == [11, 13, 14, 15, 16, 17, 18, 19]
    # A DB at v11 still needs the rest of the ladder.
    assert [v for v, _ in pg.pending_migrations(11)] == [13, 14, 15, 16, 17, 18, 19]
    # A DB at v13 still needs goal-domain + projects + artifacts + share/etc.
    assert [v for v, _ in pg.pending_migrations(13)] == [14, 15, 16, 17, 18, 19]
    # A DB at v14 still needs projects + artifacts + share/signoff/origin.
    assert [v for v, _ in pg.pending_migrations(14)] == [15, 16, 17, 18, 19]
    # A DB at v15 still needs artifacts + share/signoff/origin + fact_history.
    assert [v for v, _ in pg.pending_migrations(15)] == [16, 17, 18, 19]
    # A DB at v16 still needs the share/signoff/origin + fact_history migrations.
    assert [v for v, _ in pg.pending_migrations(16)] == [17, 18, 19]
    # A DB at v17 still needs fact_history + rate_events.
    assert [v for v, _ in pg.pending_migrations(17)] == [18, 19]
    # A DB at v18 still needs the rate_events migration.
    assert [v for v, _ in pg.pending_migrations(18)] == [19]


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


def test_approval_claims_migration_adds_collaboration_columns():
    stmts = dict(pg.MIGRATIONS)[13]
    joined = "\n".join(stmts)
    assert "ALTER TABLE approvals ADD COLUMN IF NOT EXISTS claimed_by TEXT" in joined
    assert "ALTER TABLE approvals ADD COLUMN IF NOT EXISTS claimed_at DOUBLE PRECISION" in joined
    assert "ALTER TABLE approvals ADD COLUMN IF NOT EXISTS decided_by TEXT" in joined


def test_schema_version_is_latest_migration():
    assert pg._PG_SCHEMA_VERSION == 19
    assert max(v for v, _ in pg.MIGRATIONS) == pg._PG_SCHEMA_VERSION


def test_rate_events_migration_adds_table():
    joined = "\n".join(dict(pg.MIGRATIONS)[19])
    assert "CREATE TABLE IF NOT EXISTS rate_events" in joined
    assert "idx_pg_rate_events_key_ts" in joined


def test_artifacts_migration_adds_table():
    assert "CREATE TABLE IF NOT EXISTS artifacts" in "\n".join(dict(pg.MIGRATIONS)[16])


def test_share_signoff_origin_migration_adds_tables():
    joined = "\n".join(dict(pg.MIGRATIONS)[17])
    assert "CREATE TABLE IF NOT EXISTS share_links" in joined
    assert "CREATE TABLE IF NOT EXISTS signoffs" in joined
    assert "CREATE TABLE IF NOT EXISTS goal_origins" in joined


def test_goal_domain_migration_adds_domain_column():
    stmts = dict(pg.MIGRATIONS)[14]
    assert "ALTER TABLE goals ADD COLUMN IF NOT EXISTS domain TEXT" in "\n".join(stmts)


def test_projects_migration_adds_table_and_goal_fk():
    joined = "\n".join(dict(pg.MIGRATIONS)[15])
    assert "CREATE TABLE IF NOT EXISTS projects" in joined
    assert "ALTER TABLE goals ADD COLUMN IF NOT EXISTS project_id INTEGER" in joined


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
