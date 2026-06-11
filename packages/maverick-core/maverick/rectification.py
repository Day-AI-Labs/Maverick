"""Right-to-rectification (GDPR Art. 16) over the world model
(roadmap: 2027 H2 safety).

The GDPR surface so far covers access/portability (Art. 15/20,
``maverick.dsar``) and erasure (Art. 17, ``maverick erase`` +
``maverick.audit.erase``). Art. 16 is the missing third verb: a data subject
may demand that *inaccurate* personal data be **corrected**, not deleted — a
mistyped email address, a wrong name spelling — without nuking the
conversations and goals the data lives in.

Scope: the world model's user-content columns, taken from the real
``world_model.py`` schema — ``goals.title/description/result``,
``turns.content`` and ``facts.value``. That mirrors what the DSAR export
reads and the erase path scrubs; structured identity columns
(``conversations.user_id`` etc.) are the erase/tenancy surface's job, not a
free-text correction's.

Mechanics:

* :func:`find_occurrences` — case-insensitive substring scan returning
  ``{table, id, field, snippet}`` rows (snippet = ±40 chars of context).
  Reads go through the world's locked read helper and the at-rest decryption
  shim (``world_model._dec_field``): sealed columns can never be matched by
  SQL ``LIKE``, so matching happens in Python on plaintext — the same
  scan-then-decrypt shape ``WorldModel.search_goals`` uses. Importing those
  module-level helpers (rather than copying them) keeps rectify/erase/search
  agreeing on how sealed text is read and written back.
* :func:`rectify` — ``dry_run=True`` **by default**: mutation is opt-in, a
  report is free. With ``dry_run=False`` every matched cell is rewritten with
  a case-insensitive replace that preserves all surrounding text, inside ONE
  ``world._writing()`` transaction (the world model's own write-lock pattern)
  so a reader never observes a half-rectified subject. Row timestamps are
  deliberately untouched: rectification corrects content, it must not reorder
  history.
* Audit trail: a real run appends one line to a dedicated
  ``data_dir("rectifications.jsonl")`` (0600) rather than a
  ``goal_events`` row, for two reasons: rectification is *subject*-scoped,
  not goal-scoped (goal_events requires a goal_id), and the trail must
  outlive later goal deletion/erasure. The entry records a sha256 digest of
  the subject (the same convention ``audit.erase`` logs) and per-table
  counts — never the old value (that would re-leak what was just corrected)
  and never the new one. Trail writing is best-effort *after* commit:
  fail-open, a logging failure must not roll back a completed correction.

This module targets the SQLite ``WorldModel`` (what ``open_world`` returns by
default); pass any world exposing the same ``_read_all``/``_writing`` surface.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .world_model import _dec_field, _enc_field

log = logging.getLogger(__name__)

# (table -> user-content columns) from the world_model.py schema. Table and
# column names are interpolated into SQL below; they only ever come from this
# constant (validated by _select_tables), never from caller input.
TABLES: dict[str, tuple[str, ...]] = {
    "goals": ("title", "description", "result"),
    "turns": ("content",),
    "facts": ("value",),
}

SNIPPET_RADIUS = 40
TRAIL_FILENAME = "rectifications.jsonl"


def _subject_digest(subject: str) -> str:
    """Short non-reversible identifier for trail/log lines (matches the
    ``audit.erase`` convention of never logging the raw subject)."""
    return hashlib.sha256(subject.encode("utf-8")).hexdigest()[:16]


def _require_subject(subject: str) -> str:
    s = (subject or "").strip()
    if not s:
        raise ValueError("subject must be a non-empty string")
    return s


def _select_tables(tables) -> tuple[str, ...]:
    if tables is None:
        return tuple(TABLES)
    selected: list[str] = []
    for t in tables:
        if t not in TABLES:
            raise ValueError(
                f"unknown table {t!r} (expected a subset of {tuple(TABLES)})")
        selected.append(t)
    return tuple(dict.fromkeys(selected))


def find_occurrences(world, subject: str, *, limit: int = 1000) -> list[dict]:
    """Locate ``subject`` (case-insensitive) in the world's user-content fields.

    Returns up to ``limit`` rows of ``{"table", "id", "field", "snippet"}``,
    one per matched cell (a cell with several occurrences reports once, with
    the first occurrence's ±40-char snippet), in deterministic
    table-then-rowid order.
    """
    needle = _require_subject(subject).lower()
    cap = max(1, int(limit))
    out: list[dict] = []
    for table, columns in TABLES.items():
        cols = ", ".join(("id",) + columns)
        for row in world._read_all(f"SELECT {cols} FROM {table} ORDER BY id"):
            for column in columns:
                text = _dec_field(row[column])
                if not text:
                    continue
                idx = text.lower().find(needle)
                if idx < 0:
                    continue
                start = max(0, idx - SNIPPET_RADIUS)
                end = min(len(text), idx + len(needle) + SNIPPET_RADIUS)
                out.append({
                    "table": table,
                    "id": row["id"],
                    "field": column,
                    "snippet": text[start:end],
                })
                if len(out) >= cap:
                    return out
    return out


@dataclass(frozen=True)
class RectificationReport:
    """Outcome of :func:`rectify`.

    ``matches`` counts matched cells (table+row+field); ``by_table`` breaks
    that down per table. ``changed`` is the number of cells actually
    rewritten — always 0 on a dry run, equal to ``matches`` on a real run.
    """

    matches: int
    changed: int
    by_table: dict[str, int]
    dry_run: bool


def rectify(
    world,
    subject: str,
    replacement: str,
    *,
    tables=None,
    dry_run: bool = True,
) -> RectificationReport:
    """Replace every occurrence of ``subject`` with ``replacement``.

    Matching is case-insensitive; the replace preserves all surrounding text
    (only the matched spans change, every match in a cell is rewritten).
    ``dry_run=True`` (the default — mutation must be opted into) reports what
    *would* change without touching the database. ``tables`` optionally
    narrows the sweep to a subset of :data:`TABLES`.

    Raises ``ValueError`` for an empty/blank ``subject`` or ``replacement``
    (an empty replacement is erasure — that's ``maverick erase``'s job, with
    its own safeguards) and for an unknown table name.
    """
    subj = _require_subject(subject)
    if not (replacement or "").strip():
        raise ValueError(
            "replacement must be a non-empty string "
            "(to delete a subject's data use the erasure surface instead)")
    selected = _select_tables(tables)
    pattern = re.compile(re.escape(subj), re.IGNORECASE)

    matches = 0
    changed = 0
    by_table: dict[str, int] = {}
    # One _writing() scope == one transaction + the world's write lock, for
    # the dry run too: the report is then computed against a stable snapshot
    # and is exactly what a real run would change.
    with world._writing() as conn:
        for table in selected:
            columns = TABLES[table]
            cols = ", ".join(("id",) + columns)
            for row in conn.execute(f"SELECT {cols} FROM {table} ORDER BY id").fetchall():
                for column in columns:
                    text = _dec_field(row[column])
                    if not text:
                        continue
                    # Callable replacement: ``replacement`` is literal text,
                    # never re.sub group-reference syntax.
                    new_text, n = pattern.subn(lambda _m: replacement, text)
                    if n == 0:
                        continue
                    matches += 1
                    by_table[table] = by_table.get(table, 0) + 1
                    if not dry_run:
                        conn.execute(
                            f"UPDATE {table} SET {column} = ? WHERE id = ?",
                            (_enc_field(new_text), row["id"]),
                        )
                        changed += 1

    report = RectificationReport(
        matches=matches, changed=changed, by_table=by_table, dry_run=bool(dry_run),
    )
    if not dry_run and changed:
        _append_trail(subj, report)
        log.info("rectification applied: subject_hash=%s changed=%d by_table=%s",
                 _subject_digest(subj), changed, by_table)
    return report


def _trail_path() -> Path:
    from .paths import data_dir
    return data_dir(TRAIL_FILENAME)


def _append_trail(subject: str, report: RectificationReport) -> None:
    """Append one audit line for a *applied* rectification. Best-effort: the
    correction is already committed, so a trail failure warns, never raises.
    Carries the subject digest and counts only — no old or new values."""
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "action": "rectify",
        "subject_sha256_16": _subject_digest(subject),
        "matches": report.matches,
        "changed": report.changed,
        "by_table": dict(report.by_table),
    }
    try:
        path = _trail_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, default=str) + "\n")
    except OSError as e:
        log.warning("rectification: could not append audit trail: %s", e)


def render(report: RectificationReport) -> str:
    """CLI-style summary of a :class:`RectificationReport`."""
    mode = "DRY RUN (no rows changed)" if report.dry_run else "APPLIED"
    lines = [
        f"rectification: {mode} -- {report.matches} matching field(s), "
        f"{report.changed} rewritten",
    ]
    for table in sorted(report.by_table):
        lines.append(f"  {table}: {report.by_table[table]}")
    if not report.by_table:
        lines.append("  (no occurrences found)")
    if report.dry_run and report.matches:
        lines.append("  re-run with dry_run=False to apply")
    return "\n".join(lines)


__all__ = [
    "TABLES",
    "SNIPPET_RADIUS",
    "TRAIL_FILENAME",
    "RectificationReport",
    "find_occurrences",
    "rectify",
    "render",
]
