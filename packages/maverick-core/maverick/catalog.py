"""Federated content catalog for skills, plugins, MCP servers, personas.

A catalog is a JSON index hosted anywhere (GitHub Pages on an
``awesome-maverick-*`` repo is the zero-ops v1 host). Each index lists
installable entries with a content hash so the client can verify the
bytes it fetches match what the curator indexed.

Schema (one ``index.json`` per kind, served at
``<base>/<kind>/index.json``)::

    {
      "schema_version": 1,
      "kind": "skills",
      "entries": [
        {
          "name": "summarize-url",
          "version": "1.0.0",
          "summary": "Fetch a URL and summarise it.",
          "source": "gh:cdayAI/awesome-maverick-skills:summarize-url/SKILL.md",
          "sha256": "<hex digest of the fetched content>",
          "author": "cdayAI",
          "verified": true,
          "install_count": 0
        }
      ]
    }

Trust model: the index is curated (a PR against the awesome-list adds
an entry). On install the client fetches the entry's ``source`` and
verifies the SHA-256 matches the index. Because the content is both
curated AND hash-pinned, catalog installs don't require the
``MAVERICK_ALLOW_SKILL_INSTALL`` opt-in that free-text URL installs do.

The pinned SHA-256 is only integrity-in-transit: the index and the
content are served from the SAME unauthenticated host, so an attacker
controlling that host supplies both the bytes AND their hash. The
``verified`` field below is likewise SELF-ASSERTED by the index and is
NOT a trust signal. Real authenticity comes from the Ed25519
skill-signature path in ``skills`` (``trusted_pubkeys`` /
``require_signed_catalog``): a catalog install resolves to a skill whose
signature verifies against a trusted publisher, and the genuine verified
status is reported on the installed ``Skill.verified`` -- not on this
entry's ``verified`` bool.

Self-hosting: point ``[catalogs] indexes`` at your own base URL(s).
Multiple indexes merge; earlier indexes win on name collision.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

VALID_KINDS = ("skills", "plugins", "mcp", "personas")
SCHEMA_VERSION = 1
FETCH_TIMEOUT = 15.0
_CACHE_TTL = 6 * 3600  # 6 hours
_CACHE_DIR = Path.home() / ".maverick" / "cache" / "catalog"

# Default index host. Until maverick.dev is registered this points at
# the awesome-list raw content on GitHub (zero-ops Pages host). The
# client tolerates an unreachable index by returning an empty list, so
# a fresh install simply shows "no catalog entries" rather than erroring.
DEFAULT_INDEXES = (
    "https://raw.githubusercontent.com/cdayAI/awesome-maverick/main/catalog",
)


class CatalogError(Exception):
    """Raised on hash mismatch or malformed index entry."""


@dataclass(frozen=True)
class CatalogEntry:
    name: str
    version: str
    kind: str
    summary: str
    source: str
    sha256: str
    author: str = ""
    # Self-asserted by the index, NOT a trust signal (the index host is
    # unauthenticated). Real verification is reported on the installed
    # Skill.verified after Ed25519 signature checking. Kept for schema
    # compatibility / display only.
    verified: bool = False
    install_count: int = 0

    @classmethod
    def from_dict(cls, kind: str, d: dict) -> CatalogEntry:
        if not d.get("name") or not d.get("source"):
            raise CatalogError(f"catalog entry missing name/source: {d!r}")
        return cls(
            name=str(d["name"]),
            version=str(d.get("version", "0.0.0")),
            kind=kind,
            summary=str(d.get("summary", "")),
            source=str(d["source"]),
            sha256=str(d.get("sha256", "")),
            author=str(d.get("author", "")),
            verified=bool(d.get("verified", False)),
            install_count=int(d.get("install_count", 0) or 0),
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name, "version": self.version, "kind": self.kind,
            "summary": self.summary, "source": self.source, "sha256": self.sha256,
            "author": self.author, "verified": self.verified,
            "install_count": self.install_count,
        }


def _configured_indexes() -> list[str]:
    """Index base URLs from ``[catalogs] indexes`` in config, else default."""
    try:
        from .config import load_config
        cfg = (load_config() or {}).get("catalogs") or {}
        indexes = cfg.get("indexes")
        if isinstance(indexes, list) and indexes:
            return [str(i).rstrip("/") for i in indexes]
    except Exception as e:
        log.debug("catalog: config read failed: %s", e)
    return [i.rstrip("/") for i in DEFAULT_INDEXES]


def _cache_path(url: str) -> Path:
    h = hashlib.sha256(url.encode()).hexdigest()[:16]
    return _CACHE_DIR / f"{h}.json"


def _fetch_index_raw(url: str) -> dict | None:
    """Fetch + parse one index JSON, with a 6h on-disk cache.

    Returns None (not raise) on any network/parse failure so an
    unreachable catalog degrades to "no entries" rather than breaking
    the dashboard.
    """
    cache = _cache_path(url)
    if cache.exists():
        try:
            age = time.time() - cache.stat().st_mtime
            if age < _CACHE_TTL:
                return json.loads(cache.read_text())
        except (OSError, ValueError):
            pass
    if not url.startswith("https://"):
        log.warning("catalog: refusing non-https index url %s", url)
        return None
    # Shared SSRF guard: a configured index URL must not resolve to a
    # private/loopback/link-local/metadata address.
    from .tools.http_fetch import guarded_urlopen
    try:
        with guarded_urlopen(url, timeout=FETCH_TIMEOUT) as resp:
            if resp.status != 200:
                return None
            data = json.loads(resp.read(2_000_000).decode("utf-8"))
    except Exception as e:
        log.info("catalog: fetch %s failed: %s", url, e)
        # Serve stale cache if we have it.
        if cache.exists():
            try:
                return json.loads(cache.read_text())
            except (OSError, ValueError):
                return None
        return None
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(data))
    except OSError:
        pass
    return data


def load_catalog(kind: str, *, indexes: list[str] | None = None) -> list[CatalogEntry]:
    """Return merged catalog entries for ``kind`` across all indexes.

    Earlier indexes win on name collision. Malformed entries are
    skipped with a log line, not raised — one bad entry shouldn't hide
    the whole catalog.
    """
    if kind not in VALID_KINDS:
        raise CatalogError(f"unknown kind {kind!r}; valid: {', '.join(VALID_KINDS)}")
    bases = indexes if indexes is not None else _configured_indexes()
    seen: dict[str, CatalogEntry] = {}
    for base in bases:
        url = f"{base.rstrip('/')}/{kind}/index.json"
        data = _fetch_index_raw(url)
        if not data:
            continue
        for raw in data.get("entries", []):
            try:
                entry = CatalogEntry.from_dict(kind, raw)
            except CatalogError as e:
                log.info("catalog: skipping bad entry in %s: %s", url, e)
                continue
            seen.setdefault(entry.name, entry)
    return sorted(seen.values(), key=lambda e: e.name)


def resolve(name: str, kind: str, *, indexes: list[str] | None = None) -> CatalogEntry | None:
    """Find a single entry by name, or None."""
    for entry in load_catalog(kind, indexes=indexes):
        if entry.name == name:
            return entry
    return None


def verify_sha256(content: str, expected: str) -> bool:
    """True iff the SHA-256 of ``content`` matches ``expected`` (hex).

    An empty expected hash returns False: a catalog entry MUST pin a
    hash to be installable without the free-text opt-in gate.
    """
    if not expected:
        return False
    actual = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return hmac.compare_digest(actual, expected.lower())


__all__ = [
    "CatalogEntry", "CatalogError", "VALID_KINDS", "DEFAULT_INDEXES",
    "load_catalog", "resolve", "verify_sha256",
]
