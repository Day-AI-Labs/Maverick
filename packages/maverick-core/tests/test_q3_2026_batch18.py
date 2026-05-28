"""Q3 2026 batch 18.

  - sql_query tool: read-only-by-default SQLite querying, write rejection
    (keyword guard + engine mode=ro), opt-in writes, params, row caps.
    Tested against a real stdlib sqlite3 db (no mocks).
"""
from __future__ import annotations

import sqlite3

from maverick.tools.sql_query import sql_query


def _mkdb(tmp_path):
    db = tmp_path / "t.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE users(id INTEGER PRIMARY KEY, name TEXT)")
    c.executemany("INSERT INTO users VALUES(?, ?)", [(1, "alice"), (2, "bob"), (3, "carol")])
    c.commit()
    c.close()
    return db


def test_select_returns_rows(tmp_path):
    db = _mkdb(tmp_path)
    out = sql_query().fn({"database": str(db), "query": "SELECT name FROM users ORDER BY id"})
    assert "alice" in out and "bob" in out and "carol" in out
    assert "(3 row(s))" in out


def test_readonly_rejects_write_by_keyword(tmp_path):
    db = _mkdb(tmp_path)
    out = sql_query().fn({"database": str(db), "query": "DELETE FROM users"})
    assert out.startswith("ERROR") and "read-only" in out.lower()
    # data untouched
    c = sqlite3.connect(db)
    assert c.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 3
    c.close()


def test_readonly_engine_blocks_write(tmp_path):
    """Even a write whose first keyword isn't flagged is blocked by mode=ro."""
    db = _mkdb(tmp_path)
    # leading comment slips past the keyword guard; the engine still refuses.
    out = sql_query().fn({
        "database": str(db),
        "query": "/* sneaky */ UPDATE users SET name='x'",
    })
    assert out.startswith("ERROR") and "sqlite" in out.lower()
    c = sqlite3.connect(db)
    assert c.execute("SELECT COUNT(*) FROM users WHERE name='x'").fetchone()[0] == 0
    c.close()


def test_write_allowed_when_read_only_false(tmp_path):
    db = _mkdb(tmp_path)
    out = sql_query().fn({
        "database": str(db),
        "query": "DELETE FROM users WHERE id = 1",
        "read_only": False,
    })
    assert "affected" in out.lower()
    c = sqlite3.connect(db)
    assert c.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 2
    c.close()


def test_params_binding(tmp_path):
    db = _mkdb(tmp_path)
    out = sql_query().fn({
        "database": str(db),
        "query": "SELECT name FROM users WHERE name = ?",
        "params": ["bob"],
    })
    assert "bob" in out and "alice" not in out and "(1 row(s))" in out


def test_max_rows_truncation(tmp_path):
    db = _mkdb(tmp_path)
    out = sql_query().fn({"database": str(db), "query": "SELECT * FROM users", "max_rows": 1})
    assert "truncated at 1" in out


def test_missing_database(tmp_path):
    out = sql_query().fn({"database": str(tmp_path / "nope.db"), "query": "SELECT 1"})
    assert "not found" in out.lower()


def test_bad_sql_returns_error(tmp_path):
    db = _mkdb(tmp_path)
    out = sql_query().fn({"database": str(db), "query": "SELECT * FROM does_not_exist"})
    assert out.startswith("ERROR")


def test_multi_statement_rejected(tmp_path):
    db = _mkdb(tmp_path)
    out = sql_query().fn({
        "database": str(db),
        "query": "SELECT 1; SELECT 2",
        "read_only": False,
    })
    assert out.startswith("ERROR")  # sqlite execute runs one statement only


def test_requires_database_and_query():
    assert "database is required" in sql_query().fn({"query": "SELECT 1"}).lower()
    assert "query is required" in sql_query().fn({"database": "x.db"}).lower()


def test_registered_by_default():
    from maverick.tools import base_registry

    class _FakeSandbox:
        pass

    class _FakeWorld:
        pass

    reg = base_registry(world=_FakeWorld(), sandbox=_FakeSandbox())
    assert "sql_query" in {t.name for t in reg.all()}


def test_schema_requires_database_and_query():
    schema = sql_query().input_schema
    assert schema["required"] == ["database", "query"]
