"""Session replay exporter.

Bundle a goal's audit-log events into a self-contained HTML file
the user (or a reviewer) can open in any browser to see what the
agent did, step by step, with timestamps + tool args/results.

This is the audit equivalent of a flight recorder — useful for:

  - Customer support ("what did the agent do at 14:32?")
  - Post-mortems (a deterministic, signed, offline-viewable trace)
  - Trust building (the user can SEE every decision)

Pure-Python, no external deps. Reads the daily NDJSON audit logs
(``~/.maverick/audit/YYYY-MM-DD.ndjson``), filters to the supplied
goal_id, and emits a single inline-CSS HTML page.
"""
from __future__ import annotations

import html
import json
import logging
from collections.abc import Iterable, Iterator
from pathlib import Path

from .safety.pii_detector import redact as _pii_redact
from .secrets import scrub


def _sanitize(text: str) -> str:
    """Strip secrets AND PII before the bundle leaves the machine.

    The export is shared with support/reviewers, so secret-scrubbing alone
    was insufficient -- emails, SSNs, phone numbers, and credit-card numbers
    in tool args/results/prompts were written verbatim. Both replace matches
    with ``[REDACTED:<kind>]`` (no quotes/newlines), so the result stays
    valid JSON.
    """
    return _pii_redact(scrub(text))[0]

log = logging.getLogger(__name__)


_AUDIT_DIR = Path.home() / ".maverick" / "audit"


_HTML_HEAD_TMPL = (
    '<!doctype html>\n'
    '<html lang="en">\n'
    '<head>\n'
    '<meta charset="utf-8" />\n'
    '<title>Maverick replay — goal __GOAL__</title>\n'
    '<style>\n'
    '  body { background: #0d1117; color: #e6edf3; '
    'font: 13px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace; '
    'margin: 0; padding: 2rem; }\n'
    '  h1 { margin: 0 0 1rem; font-size: 1rem; color: #8b949e; '
    'text-transform: uppercase; letter-spacing: .08em; }\n'
    '  .ev { background: #161b22; border: 1px solid #30363d; '
    'border-radius: 6px; padding: .75rem 1rem; margin: .5rem 0; }\n'
    '  .ev .meta { color: #8b949e; font-size: 11px; }\n'
    '  .ev pre { margin: .25rem 0 0; white-space: pre-wrap; '
    'word-break: break-word; }\n'
    '  .badge { display: inline-block; padding: .1rem .5rem; '
    'border-radius: 4px; font-size: 11px; '
    'background: rgba(46,160,67,.2); color: #2ea043; margin-right: .5rem; }\n'
    '  .badge.error  { background: rgba(248,81,73,.2); color: #f85149; }\n'
    '  .badge.system { background: rgba(110,118,129,.2); color: #8b949e; }\n'
    '</style>\n'
    '</head>\n'
    '<body>\n'
    '<h1>goal __GOAL__ — __N__ event(s)</h1>\n'
)


def _render_head(goal_id: int, n: int) -> str:
    return (
        _HTML_HEAD_TMPL
        .replace("__GOAL__", str(goal_id))
        .replace("__N__", str(n))
    )

_HTML_TAIL = "\n</body></html>\n"


def _iter_audit_files() -> Iterator[Path]:
    if not _AUDIT_DIR.exists():
        return
    yield from sorted(_AUDIT_DIR.glob("*.ndjson"))


def _iter_events_for_goal(goal_id: int, files: Iterable[Path] | None = None) -> Iterator[dict]:
    files = files if files is not None else _iter_audit_files()
    for path in files:
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    gid = ev.get("goal_id")
                    if gid is None:
                        continue
                    # A non-numeric goal_id (tampering, a future non-int
                    # id, an unrelated row) must skip the row, not abort
                    # the whole export with a ValueError.
                    try:
                        if int(gid) != int(goal_id):
                            continue
                    except (TypeError, ValueError):
                        continue
                    yield ev
        except OSError:
            continue


def _kind_class(kind: str) -> str:
    k = (kind or "").lower()
    if "error" in k or "fail" in k or "halt" in k:
        return "error"
    if "system" in k or "config" in k:
        return "system"
    return ""


def _render_event(ev: dict) -> str:
    kind = str(ev.get("kind") or ev.get("event") or "?")
    ts = ev.get("ts") or ev.get("created_at") or ""
    body = {k: v for k, v in ev.items() if k not in ("kind", "event", "ts",
                                                       "goal_id", "hash",
                                                       "prev_hash", "sig",
                                                       "key_id")}
    # Strip secrets AND PII: audit bodies carry tool args/results/prompts
    # that may contain API keys, bearer tokens, .env values, or user PII
    # (emails, SSNs, cards). The export is a file the user shares with
    # support/reviewers, so it must not leak any of them.
    body_text = _sanitize(json.dumps(body, indent=2, default=str))
    return (
        f'<div class="ev">'
        f'<div class="meta">'
        f'<span class="badge {_kind_class(kind)}">{html.escape(kind)}</span>'
        f'<span>{html.escape(str(ts))}</span></div>'
        f'<pre>{html.escape(body_text)}</pre>'
        f'</div>'
    )


def export_html(goal_id: int, out_path: Path) -> int:
    """Write a self-contained HTML replay file. Returns event count."""
    events = list(_iter_events_for_goal(goal_id))
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(_render_head(goal_id, len(events)))
        if not events:
            f.write('<p style="color:#8b949e">No events recorded for this goal.</p>')
        for ev in events:
            f.write(_render_event(ev))
            f.write("\n")
        f.write(_HTML_TAIL)
    _restrict_perms(out_path)
    return len(events)


def export_json(goal_id: int, out_path: Path) -> int:
    """Write a JSON dump of all matching events. Returns event count."""
    events = list(_iter_events_for_goal(goal_id))
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Strip secrets AND PII from the serialized bundle. Both redactors
    # replace values with [REDACTED:kind] (no quotes/newlines), so the
    # result stays valid JSON.
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(_sanitize(json.dumps(
            {"goal_id": goal_id, "events": events}, indent=2, default=str,
        )))
    _restrict_perms(out_path)
    return len(events)


def _restrict_perms(path: Path) -> None:
    """Lock an exported bundle to the owner (0o600).

    Replay bundles carry the run's prompts/results -- even after scrub() they
    can hold private (non-secret) content. The default umask often leaves them
    world-readable on a shared host; this closes that local-disclosure path.
    """
    try:
        import os
        os.chmod(path, 0o600)
    except OSError:
        pass


__all__ = ["export_html", "export_json"]
