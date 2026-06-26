"""Guided opt-in for Postgres RLS: ownership/legacy-row preflight + NULL backfill.

These exercise the pure SQL-orchestration logic against a fake connection (no
live Postgres), the way test_postgres_rls_unit.py tests policy SQL -- so they run
everywhere, including CI without a DSN.
"""
from __future__ import annotations

import pytest
from maverick.world_model_backends import pg_rls
from maverick.world_model_backends.postgres import _TENANT_TABLES


class _FakeCursor:
    def __init__(self, conn: _FakeConn) -> None:
        self.conn = conn
        self._result: tuple | None = None
        self.rowcount = 0

    def execute(self, sql: str, params: tuple | None = None) -> None:
        self.conn.calls.append((sql, params))
        s = sql.strip().lower()
        if "current_user" in s:
            self._result = (self.conn.role,)
        elif "to_regclass" in s:
            tbl = params[0]
            self._result = (tbl if self.conn.tables.get(tbl, {}).get("exists") else None,)
        elif "pg_get_userbyid" in s:
            self._result = (self.conn.tables[params[0]]["owner"],)
        elif s.startswith("select count(*)"):
            tbl = sql.split("FROM ")[1].split()[0]
            self._result = (self.conn.tables[tbl]["nulls"],)
        elif s.startswith("update"):
            tbl = sql.split("UPDATE ")[1].split()[0]
            self.rowcount = self.conn.tables[tbl]["nulls"]
            self.conn.updated[tbl] = params[0]
        else:  # pragma: no cover - defensive
            self._result = None

    def fetchone(self) -> tuple | None:
        return self._result


class _FakeConn:
    def __init__(self, role: str, tables: dict[str, dict]) -> None:
        self.role = role
        self.tables = tables
        self.calls: list = []
        self.updated: dict[str, str] = {}
        self.committed = False

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)

    def commit(self) -> None:
        self.committed = True

    def close(self) -> None:
        pass


def _tables(role="app", *, nulls=0, exists=True, owner=None):
    owner = owner if owner is not None else role
    return {t: {"exists": exists, "owner": owner, "nulls": nulls}
            for t in _TENANT_TABLES}


# --- resolve_dsn precedence -------------------------------------------------

def test_resolve_dsn_prefers_arg_then_env_then_config(monkeypatch):
    monkeypatch.setenv("MAVERICK_PG_DSN", "env-dsn")
    assert pg_rls.resolve_dsn("arg-dsn") == "arg-dsn"
    assert pg_rls.resolve_dsn() == "env-dsn"
    monkeypatch.delenv("MAVERICK_PG_DSN", raising=False)
    monkeypatch.setattr("maverick.config.load_config",
                        lambda *a, **k: {"world_model": {"dsn": "cfg-dsn"}})
    assert pg_rls.resolve_dsn() == "cfg-dsn"


def test_resolve_dsn_empty_when_unconfigured(monkeypatch):
    monkeypatch.delenv("MAVERICK_PG_DSN", raising=False)
    monkeypatch.setattr("maverick.config.load_config", lambda *a, **k: {})
    assert pg_rls.resolve_dsn() == ""


# --- preflight --------------------------------------------------------------

def test_preflight_ready_when_owned_and_no_legacy_rows():
    conn = _FakeConn("app", _tables("app", nulls=0))
    rep = pg_rls.preflight(conn)
    assert rep["role"] == "app"
    assert rep["ready"] is True
    assert all(i["owned_by_current_role"] and i["null_tenant_rows"] == 0
               for i in rep["tables"].values())


def test_preflight_not_ready_with_legacy_null_rows():
    conn = _FakeConn("app", _tables("app", nulls=7))
    rep = pg_rls.preflight(conn)
    assert rep["ready"] is False
    assert all(i["null_tenant_rows"] == 7 for i in rep["tables"].values())


def test_preflight_not_ready_when_role_does_not_own_table():
    conn = _FakeConn("app", _tables("app", nulls=0, owner="postgres"))
    rep = pg_rls.preflight(conn)
    assert rep["ready"] is False
    assert all(i["owned_by_current_role"] is False for i in rep["tables"].values())


def test_preflight_flags_missing_table_without_raising():
    conn = _FakeConn("app", _tables("app", exists=False))
    rep = pg_rls.preflight(conn)
    assert rep["ready"] is False
    assert all(i.get("missing") for i in rep["tables"].values())


# --- backfill ---------------------------------------------------------------

def test_backfill_assigns_null_rows_and_commits():
    conn = _FakeConn("app", _tables("app", nulls=3))
    report = pg_rls.backfill(conn, "acme")
    assert report == dict.fromkeys(_TENANT_TABLES, 3)
    assert conn.committed is True
    assert conn.updated == dict.fromkeys(_TENANT_TABLES, "acme")


def test_backfill_dry_run_counts_without_writing():
    conn = _FakeConn("app", _tables("app", nulls=4))
    report = pg_rls.backfill(conn, "acme", dry_run=True)
    assert report == dict.fromkeys(_TENANT_TABLES, 4)
    assert conn.committed is False
    assert conn.updated == {}


def test_backfill_skips_missing_table():
    conn = _FakeConn("app", _tables("app", nulls=2, exists=False))
    report = pg_rls.backfill(conn, "acme")
    assert report == dict.fromkeys(_TENANT_TABLES, 0)
    assert conn.updated == {}


def test_backfill_rejects_empty_tenant():
    conn = _FakeConn("app", _tables("app", nulls=1))
    with pytest.raises(ValueError, match="non-empty tenant"):
        pg_rls.backfill(conn, "   ")
    assert conn.committed is False
