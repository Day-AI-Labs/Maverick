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
