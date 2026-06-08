"""Relational database tool — SQL via SQLAlchemy (any driver).

One connector for PostgreSQL, MySQL/MariaDB, SQL Server, CockroachDB, Oracle,
etc. through a SQLAlchemy connection URL. Simple read statements run directly;
non-read or ambiguous SQL (INSERT/UPDATE/DELETE/DDL, CTE, EXPLAIN) requires
confirm=true.

Auth: ``DATABASE_URL`` (a SQLAlchemy URL), e.g.
  postgresql+psycopg://user:pass@host:5432/db  # pragma: allowlist secret
  mysql+pymysql://user:pass@host/db  # pragma: allowlist secret
  mssql+pyodbc://user:pass@host/db?driver=ODBC+Driver+18+for+SQL+Server  # pragma: allowlist secret
  cockroachdb://user@host:26257/db
The matching driver (psycopg / pymysql / pyodbc / ...) must be installed.

ops:
  - query(sql, url, limit, confirm)
"""
from __future__ import annotations

import fnmatch
import json
import logging
import os
import re
from typing import Any
from urllib.parse import urlsplit

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

_READ_KEYWORDS = {"select", "show", "describe", "desc", "pragma", "values"}
_TOKEN_RE = re.compile(r"[a-zA-Z_]+")


def _leading_keyword(sql: str) -> str:
    """Return the first SQL keyword after leading whitespace/comments/parentheses."""
    idx = 0
    length = len(sql)
    while idx < length:
        while idx < length and sql[idx].isspace():
            idx += 1
        if idx < length and sql[idx] == "(":
            idx += 1
            continue
        if sql.startswith("--", idx):
            newline = sql.find("\n", idx + 2)
            if newline == -1:
                return ""
            idx = newline + 1
            continue
        if sql.startswith("/*", idx):
            end = sql.find("*/", idx + 2)
            if end == -1:
                return ""
            idx = end + 2
            continue
        break
    match = _TOKEN_RE.match(sql, idx)
    return match.group(0).lower() if match else ""


def _is_read_sql(sql: str) -> bool:
    """Conservative read gate for statements that do not require confirm=true.

    CTE-prefixed and EXPLAIN-prefixed statements are intentionally not treated
    as read-only here: PostgreSQL, SQL Server, and MySQL-family databases can
    execute mutating statements behind those prefixes (for example
    ``WITH ... DELETE`` or ``EXPLAIN ANALYZE``).
    """
    return _leading_keyword(sql) in _READ_KEYWORDS


def _host_denial(url: str, allow_hosts: tuple[str, ...]) -> str | None:
    if not allow_hosts:
        return None
    try:
        host = urlsplit(url).hostname
    except ValueError:
        host = None
    if not host or any(fnmatch.fnmatch(host, pat) for pat in allow_hosts):
        return None
    return (
        f"⚠ DENIED by capability policy: database URL host {host!r} is not "
        "granted by allow_hosts. The tool was not executed."
    )


def _op_query(sql: str, url: str, limit: int, confirm: bool,
              allow_hosts: tuple[str, ...] = ()) -> str:
    if not sql:
        return "ERROR: query requires sql"
    if not _is_read_sql(sql) and not confirm:
        return "DRY RUN: non-read SQL (INSERT/UPDATE/DELETE/DDL). Re-run with confirm=true."
    url = (url or os.environ.get("DATABASE_URL", "")).strip()
    if not url:
        return "ERROR: database requires a SQLAlchemy URL via the url arg or DATABASE_URL."
    denial = _host_denial(url, allow_hosts)
    if denial:
        return denial
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
                             as_bool(args.get("confirm")),
                             tuple(args.get("_capability_allow_hosts") or ()))
    except Exception as e:  # noqa: BLE001
        return f"ERROR: database request failed: {type(e).__name__}: {e}"
    return f"ERROR: unknown op {op!r}"


def database_tool() -> Tool:
    return Tool(
        name="database",
        description=(
            "Relational DB SQL via SQLAlchemy (PostgreSQL, MySQL/MariaDB, SQL "
            "Server, CockroachDB, Oracle, ...). op: query (simple reads run; "
            "writes/DDL/CTE/EXPLAIN need confirm=true). Auth: DATABASE_URL "
            "(SQLAlchemy URL) or the url arg; the matching driver must be installed."
        ),
        input_schema=_SCHEMA,
        fn=_run,
    )
