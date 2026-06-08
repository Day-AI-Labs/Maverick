"""Relational `database` tool (SQLAlchemy). Driver/network-free paths."""
from __future__ import annotations


def test_database_registers(tmp_path):
    from maverick.sandbox.local import LocalBackend
    from maverick.tools import base_registry

    class _W:
        def open_questions(self, gid):
            return []

    names = {t.name for t in base_registry(_W(), LocalBackend(workdir=tmp_path)).all()}
    assert "database" in names


def test_requires_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from maverick.tools.database_tool import database_tool
    out = database_tool().fn({"op": "query", "sql": "select 1"})
    assert "ERROR" in out and "DATABASE_URL" in out


def test_write_needs_confirm(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost/db")
    from maverick.tools.database_tool import database_tool
    out = database_tool().fn({"op": "query", "sql": "DELETE FROM t WHERE 1=1"})
    assert "DRY RUN" in out


def test_read_returns_error_gracefully_without_server(monkeypatch):
    # No reachable DB / maybe no driver: must return an ERROR string, not raise.
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@127.0.0.1:1/db")
    from maverick.tools.database_tool import database_tool
    out = database_tool().fn({"op": "query", "sql": "SELECT 1"})
    assert out.startswith("ERROR")


def test_cte_prefixed_write_needs_confirm(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost/db")
    from maverick.tools.database_tool import database_tool

    out = database_tool().fn({
        "op": "query",
        "sql": "WITH victims AS (SELECT id FROM users) DELETE FROM users USING victims",
    })

    assert "DRY RUN" in out


def test_explain_prefixed_sql_needs_confirm(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost/db")
    from maverick.tools.database_tool import database_tool

    out = database_tool().fn({"op": "query", "sql": "EXPLAIN ANALYZE DELETE FROM users"})

    assert "DRY RUN" in out


def test_comment_prefixed_write_needs_confirm(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost/db")
    from maverick.tools.database_tool import database_tool

    for sql in (
        "/* select */ DELETE FROM users",
        "-- SELECT\nDROP TABLE users",
        "  (/* select */ UPDATE users SET admin = true)",
    ):
        out = database_tool().fn({"op": "query", "sql": sql})
        assert "DRY RUN" in out


def test_comment_prefixed_read_is_allowed(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from maverick.tools.database_tool import database_tool

    out = database_tool().fn({"op": "query", "sql": "/* allowed */ -- still allowed\nSELECT 1"})

    assert "DATABASE_URL" in out


def test_database_url_host_scope_applies_to_env_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@evil.com/db")
    from maverick.tools.database_tool import database_tool

    out = database_tool().fn({
        "op": "query",
        "sql": "SELECT 1",
        "_capability_allow_hosts": ("*.example.com",),
    })

    assert "DENIED by capability" in out
    assert "evil.com" in out
