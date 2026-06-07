"""Relational database tool — SQL via SQLAlchemy (any driver).

One connector for PostgreSQL, MySQL/MariaDB, SQL Server, CockroachDB, Oracle,
etc. through a SQLAlchemy connection URL. Read statements run directly; non-read
SQL (INSERT/UPDATE/DELETE/DDL) requires confirm=true.

Auth: ``DATABASE_URL`` (a SQLAlchemy URL), e.g.
  postgresql+psycopg://user:pass@host:5432/db
  mysql+pymysql://user:pass@host/db
  mssql+pyodbc://user:pass@host/db?driver=ODBC+Driver+18+for+SQL+Server
  cockroachdb://user@host:26257/db
The matching driver (psycopg / pymysql / pyodbc / ...) must be installed.

ops:
  - query(sql, url, limit, confirm)
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from . import Tool, as_bool

log = logging.getLogger(__name__)

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "op": {"type": "string", "enum": ["query"]},
        "sql": {"type": "string"},
        "url": {"type": "string", "description": "SQLAlchemy URL (else DATABASE_URL)."},
        "limit": {"type": "integer", "description": "max rows shown (default 50)."},
        "confirm": {"type": "boolean", "description": "required for non-read SQL."},
    },
    "required": ["op", "sql"],
}

_READ_PREFIXES = ("select", "with", "show", "describe", "desc", "explain",
                  "pragma", "values")


def _op_query(sql: str, url: str, limit: int, confirm: bool) -> str:
    if not sql:
        return "ERROR: query requires sql"
    if not sql.strip().lstrip("(").lower().startswith(_READ_PREFIXES) and not confirm:
        return "DRY RUN: non-read SQL (INSERT/UPDATE/DELETE/DDL). Re-run with confirm=true."
    url = (url or os.environ.get("DATABASE_URL", "")).strip()
    if not url:
        return "ERROR: database requires a SQLAlchemy URL via the url arg or DATABASE_URL."
    try:
        from sqlalchemy import create_engine, text
    except ImportError:
        return ("ERROR: sqlalchemy not installed. Run: pip install sqlalchemy plus the "
                "driver (psycopg / pymysql / pyodbc / ...).")
    try:
        engine = create_engine(url)
        with engine.connect() as conn:
            result = conn.execute(text(sql))
            if result.returns_rows:
                cols = list(result.keys())
                rows = result.fetchmany(max(1, limit))
                out = [f"columns: {cols}", f"{len(rows)} row(s):"]
                out += ["  " + json.dumps(list(r), default=str)[:300] for r in rows]
                return "\n".join(out)
            conn.commit()
            return f"ok: {result.rowcount} row(s) affected"
    except Exception as e:  # noqa: BLE001
        return f"ERROR: database query failed: {type(e).__name__}: {e}"


def _run(args: dict[str, Any]) -> str:
    op = args.get("op")
    if not op:
        return "ERROR: op is required"
    try:
        if op == "query":
            return _op_query((args.get("sql") or "").strip(),
                             (args.get("url") or "").strip(),
                             int(args.get("limit") or 50),
                             as_bool(args.get("confirm")))
    except Exception as e:  # noqa: BLE001
        return f"ERROR: database request failed: {type(e).__name__}: {e}"
    return f"ERROR: unknown op {op!r}"


def database_tool() -> Tool:
    return Tool(
        name="database",
        description=(
            "Relational DB SQL via SQLAlchemy (PostgreSQL, MySQL/MariaDB, SQL "
            "Server, CockroachDB, Oracle, ...). op: query (read runs; "
            "INSERT/UPDATE/DELETE/DDL need confirm=true). Auth: DATABASE_URL "
            "(SQLAlchemy URL) or the url arg; the matching driver must be installed."
        ),
        input_schema=_SCHEMA,
        fn=_run,
    )
