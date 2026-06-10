"""Web archive tool — snapshot a URL locally so research stays reproducible
(roadmap: 2027 H2 ecosystem).

A research agent's citations rot: the live page gets edited, paywalled or
deleted, and a conclusion built on it can no longer be audited. This tool
freezes what was actually read: the fetched bytes land under
``data_dir("web_archive")/<id>/content.html`` next to a ``meta.json``
(url, final_url, fetched_at, status, content_type, sha256, note), where
``<id>`` is ``sha256(url|YYYY-MM-DD)[:16]`` — re-archiving the same URL the
same day refreshes one snapshot instead of piling up duplicates, while a new
day gets a new id (that date-versioning is the point of the tool).

SSRF stance: the URL (and EVERY redirect hop) is fetched through
``maverick.tools._ssrf.safe_client`` — the same resolve-once, validate-all,
pin-the-IP discipline ``http_fetch`` uses, so private/loopback/link-local/
metadata addresses are refused and DNS rebinding has no second resolution to
race. ``safe_client`` deliberately never follows redirects itself (an
unvalidated 3xx target would escape the pin), so redirects are followed
*manually* here, re-validating and re-pinning each hop, up to
:data:`MAX_REDIRECTS`. Bodies are streamed with a hard
:data:`MAX_BYTES` (5 MiB) cap — an over-cap response is rejected, not
truncated, because a silently partial archive is worse than none. A non-2xx
response IS archived (status recorded in meta): "the page 404'd that day" is
itself a reproducible research result.

ops:
  - save(url[, note])   — fetch + store; returns the archive id + path.
  - list([url_filter])  — table of snapshots (id, date, status, url).
  - get(id)             — meta + the first 4 KiB of text.

No confirm gate: saving a local snapshot is the tool's whole (idempotent
per url+day, workspace-local) purpose — there is no remote mutation to
protect. ``parallel_safe`` stays False because save writes to disk.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from . import Tool

log = logging.getLogger(__name__)

MAX_BYTES = 5 * 1024 * 1024  # 5 MiB body cap; over-cap is rejected outright
MAX_REDIRECTS = 5
_REDIRECT_CODES = {301, 302, 303, 307, 308}
_ID_RE = re.compile(r"^[0-9a-f]{16}$")
_UA = "Mozilla/5.0 (compatible; Maverick/1.0; web_archive)"

_WA_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "op": {"type": "string", "enum": ["save", "list", "get"]},
        "url": {"type": "string", "description": "http(s) URL to archive (save)."},
        "note": {"type": "string", "description": "Why this was archived (save)."},
        "url_filter": {"type": "string",
                       "description": "Substring filter on the archived URL (list)."},
        "id": {"type": "string", "description": "16-hex archive id (get)."},
    },
    "required": ["op"],
}


def _default_root() -> Path:
    from ..paths import data_dir
    return data_dir("web_archive")


def archive_id(url: str, date: str) -> str:
    """Deterministic snapshot id: sha256 of url + fetch date, 16 hex chars."""
    return hashlib.sha256(f"{url}|{date}".encode()).hexdigest()[:16]


def _fetch(url: str) -> dict:
    """GET ``url`` with per-hop SSRF validation + the 5 MiB streaming cap.

    Returns ``{status, content_type, body, final_url}``. Raises
    ``ValueError`` on a bad scheme / missing host / over-cap body / redirect
    loop, and ``_ssrf.BlockedHost`` on a non-public host (any hop).
    """
    from ._ssrf import safe_client

    current = url
    for _hop in range(MAX_REDIRECTS + 1):
        parsed = urlparse(current)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(f"only http/https supported; got scheme {parsed.scheme!r}")
        if not parsed.hostname:
            raise ValueError(f"missing host in URL {current!r}")
        location: str | None = None
        with safe_client(current, timeout=30.0) as client:
            with client.stream("GET", current, headers={"User-Agent": _UA}) as resp:
                status = resp.status_code
                if status in _REDIRECT_CODES and resp.headers.get("location"):
                    location = urljoin(current, resp.headers.get("location"))
                else:
                    buf = bytearray()
                    for chunk in resp.iter_bytes():
                        buf += chunk
                        if len(buf) > MAX_BYTES:
                            raise ValueError(
                                f"response exceeds the {MAX_BYTES // (1024 * 1024)} MiB "
                                "archive cap; refusing to store a partial snapshot")
                    return {
                        "status": status,
                        "content_type": (resp.headers.get("content-type") or "").strip(),
                        "body": bytes(buf),
                        "final_url": current,
                    }
        current = location  # next hop is re-validated + re-pinned above
    raise ValueError(f"too many redirects (> {MAX_REDIRECTS}) for {url!r}")


def _op_save(args: dict, root: Path) -> str:
    import httpx

    from ._ssrf import BlockedHost

    url = (args.get("url") or "").strip()
    if not url:
        return "ERROR: save requires url"
    note = str(args.get("note") or "")

    # Enterprise mode: archiving still means egress to an arbitrary host, so
    # it is held to the same boundary as http_fetch. No-op by default.
    from ..enterprise import enterprise_egress_denial
    deny = enterprise_egress_denial(url, tool="web_archive")
    if deny:
        return f"ERROR: {deny}"

    try:
        fetched = _fetch(url)
    except BlockedHost as e:
        return f"ERROR: refusing to fetch {url!r}: {e}"
    except ValueError as e:
        return f"ERROR: {e}"
    except httpx.HTTPError as e:
        return f"ERROR: fetch failed: {type(e).__name__}: {e}"

    fetched_at = datetime.now(timezone.utc)
    aid = archive_id(url, fetched_at.date().isoformat())
    adir = root / aid
    adir.mkdir(parents=True, exist_ok=True)
    body = fetched["body"]
    (adir / "content.html").write_bytes(body)
    meta = {
        "id": aid,
        "url": url,
        "final_url": fetched["final_url"],
        "fetched_at": fetched_at.isoformat(),
        "status": fetched["status"],
        "content_type": fetched["content_type"],
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
        "note": note,
    }
    (adir / "meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    status_note = ("" if 200 <= fetched["status"] < 300
                   else f"  (note: HTTP {fetched['status']} recorded)")
    return (
        f"archived {aid} -> {adir}{status_note}\n"
        f"  {len(body)} bytes, sha256 {meta['sha256'][:16]}…, "
        f"final url {fetched['final_url']}"
    )


def _op_list(args: dict, root: Path) -> str:
    flt = (args.get("url_filter") or "").strip().lower()
    rows: list[tuple[str, str, Any, str]] = []
    if root.is_dir():
        for meta_path in sorted(root.glob("*/meta.json")):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue  # a damaged snapshot must not hide the rest
            url = str(meta.get("url") or "")
            if flt and flt not in url.lower():
                continue
            rows.append((
                str(meta.get("fetched_at") or ""),
                str(meta.get("id") or meta_path.parent.name),
                meta.get("status", "?"),
                url,
            ))
    if not rows:
        return ("no archived snapshots match that filter" if flt
                else "no archived snapshots")
    rows.sort(reverse=True)  # newest first
    return "\n".join(
        f"  {aid}  {fetched_at[:19]}  [{status}]  {url[:80]}"
        for fetched_at, aid, status, url in rows
    )


def _op_get(args: dict, root: Path) -> str:
    aid = (args.get("id") or "").strip().lower()
    # Strict id shape doubles as the path-traversal guard: the id becomes a
    # directory name, so anything but 16 hex chars is refused.
    if not _ID_RE.fullmatch(aid):
        return "ERROR: get requires a 16-hex-char archive id (see save/list output)"
    adir = root / aid
    meta_path = adir / "meta.json"
    if not meta_path.is_file():
        return f"archive {aid} not found"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return f"ERROR: archive {aid} meta unreadable: {e}"
    try:
        head = (adir / "content.html").read_bytes()[:4096]
    except OSError:
        head = b""
    text = head.decode("utf-8", errors="replace")
    lines = [f"{meta.get('id', aid)}  {meta.get('url', '?')}"]
    for key in ("final_url", "fetched_at", "status", "content_type",
                "sha256", "size_bytes", "note"):
        if meta.get(key) not in (None, ""):
            lines.append(f"  {key + ':':<14}{meta[key]}")
    return "\n".join(lines) + f"\n\n{text}"


def web_archive(root: str | Path | None = None) -> Tool:
    """Factory. ``root`` overrides the snapshot directory (tests / embedders);
    by default it resolves ``data_dir("web_archive")`` lazily PER CALL so the
    active tenant / a repointed home applies to every save."""

    def _run(args: dict[str, Any]) -> str:
        op = args.get("op")
        if not op:
            return "ERROR: op is required"
        base = Path(root) if root is not None else _default_root()
        if op == "save":
            try:
                import httpx  # noqa: F401
            except ImportError:
                return "ERROR: httpx not installed. Run: pip install 'maverick-agent[session]'"
        try:
            return {
                "save": _op_save,
                "list": _op_list,
                "get":  _op_get,
            }.get(op, lambda a, r: f"ERROR: unknown op {op!r}")(args, base)
        except Exception as e:
            return f"ERROR: web_archive failed: {type(e).__name__}: {e}"

    return Tool(
        name="web_archive",
        description=(
            "Archive a URL's content locally so research stays reproducible "
            "after the live page changes. ops: save (url + optional note; "
            "follows redirects with per-hop SSRF checks, 5 MiB cap, non-2xx "
            "status archived too), list (optional url_filter substring), get "
            "(archive id -> meta + first 4 KiB of text). Snapshots live under "
            "the data dir; one snapshot per url per day."
        ),
        input_schema=_WA_SCHEMA,
        fn=_run,
        parallel_safe=False,  # save writes the data dir
    )


__all__ = ["web_archive", "archive_id", "MAX_BYTES", "MAX_REDIRECTS"]
