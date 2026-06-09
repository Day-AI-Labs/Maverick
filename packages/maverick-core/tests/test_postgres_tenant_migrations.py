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


def test_tenant_scope_filters_strictly_to_active_tenant(monkeypatch):
    monkeypatch.setattr(pg, "_active_tenant", lambda: "acme")
    frag, params = pg._tenant_scope()
    assert frag == "tenant_id = %s"
    assert "IS NULL" not in frag
    assert params == ["acme"]


def test_tenant_scope_custom_column(monkeypatch):
    monkeypatch.setattr(pg, "_active_tenant", lambda: "acme")
    frag, _ = pg._tenant_scope("goals.tenant_id")
    assert frag == "goals.tenant_id = %s"


class _RecordingCursor:
    rowcount = 0

    def __init__(self):
        self.statements: list[tuple[str, tuple]] = []

    def execute(self, sql, params=()):
        self.statements.append((sql, tuple(params or ())))

    def fetchone(self):
        return None

    def fetchall(self):
        return []


class _RecordingTx:
    def __init__(self, cur: _RecordingCursor):
        self.cur = cur

    def __enter__(self):
        return self.cur

    def __exit__(self, *exc):
        return False


def _recording_world() -> tuple[pg.PostgresWorldModel, _RecordingCursor]:
    cur = _RecordingCursor()
    world = pg.PostgresWorldModel.__new__(pg.PostgresWorldModel)
    world._tx = lambda: _RecordingTx(cur)  # type: ignore[method-assign]
    return world, cur


def _sql_for(method_name: str, *args, tenant: str = "acme", **kwargs) -> str:
    world, cur = _recording_world()
    old = pg._active_tenant
    try:
        pg._active_tenant = lambda: tenant  # type: ignore[assignment]
        getattr(world, method_name)(*args, **kwargs)
    finally:
        pg._active_tenant = old  # type: ignore[assignment]
    return "\n".join(sql for sql, _ in cur.statements)


def test_goal_helper_reads_are_tenant_scoped():
    for method_name, args in (
        ("most_recent_goal", ()),
        ("active_goal", ()),
        ("inflight_goal", ()),
        ("candidate_goals", (True,)),
        ("subgoals", (123,)),
    ):
        sql = _sql_for(method_name, *args)
        assert "tenant_id = %s" in sql
        assert "IS NULL" not in sql


def test_tenant_root_mutations_are_tenant_scoped():
    assert "tenant_id = %s" in _sql_for("set_goal_status", 1, "done")
    assert "tenant_id = %s" in _sql_for("reclaim_orphan_goals")
    assert "tenant_id = %s" in _sql_for("decide_approval", 10, "approved")


def test_delete_facts_matching_includes_tenant_scope(monkeypatch):
    world, cur = _recording_world()
    monkeypatch.setattr(pg, "_active_tenant", lambda: "acme")
    monkeypatch.setattr(world, "facts_matching", lambda token: {"user:alice:secret": "v"})

    assert world.delete_facts_matching("alice") == ["user:alice:secret"]
    sql = "\n".join(stmt for stmt, _ in cur.statements)
    assert "DELETE FROM facts" in sql
    assert "tenant_id = %s" in sql
    assert "IS NULL" not in sql
