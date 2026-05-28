"""LLM response cache (SQLite-backed, content-addressed).

Cache LLM completions by a stable hash of (provider, model, system,
messages, tools, max_tokens, thinking_budget). On a cache hit the
LLM call is skipped entirely — useful in two cases:

  - tests / dev: identical prompts shouldn't burn budget
  - production: idempotent re-runs (re-execute the same goal) reuse
    prior intermediate completions

Tradeoffs:
  - Cache misses cost nothing extra (just one SQLite lookup).
  - The cache is opt-in: ``MAVERICK_LLM_CACHE=1`` or programmatic
    enable. The agent kernel doesn't read from cache automatically;
    callers wire it via ``cached_complete()``.

Storage: ``~/.maverick/llm_cache.db`` SQLite WAL. TTL evicts on read
(no background thread).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Optional

log = logging.getLogger(__name__)


DEFAULT_DB = Path.home() / ".maverick" / "llm_cache.db"
DEFAULT_TTL_S = 7 * 24 * 3600  # 7 days


_SCHEMA = """
CREATE TABLE IF NOT EXISTS responses (
  key         TEXT PRIMARY KEY,
  provider    TEXT NOT NULL,
  model       TEXT NOT NULL,
  text        TEXT NOT NULL,
  thinking    TEXT NOT NULL DEFAULT '',
  stop_reason TEXT NOT NULL DEFAULT '',
  created_at  REAL NOT NULL,
  hit_count   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_responses_created ON responses(created_at);
"""


@dataclass
class CachedResponse:
    key: str
    text: str
    thinking: str
    stop_reason: str
    provider: str
    model: str
    created_at: float
    hit_count: int


def _enabled_via_env() -> bool:
    return os.environ.get("MAVERICK_LLM_CACHE", "").strip().lower() in {
        "1", "true", "yes", "on",
    }


def _stable_dump(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, default=str, ensure_ascii=False)


def cache_key(
    *,
    provider: str,
    model: str,
    system: str,
    messages: list[dict] | None,
    tools: list[dict] | None,
    max_tokens: int,
    thinking_budget: Optional[int] = None,
) -> str:
    """Stable SHA-256 of the inputs that uniquely identify a completion."""
    payload = {
        "provider": provider,
        "model": model,
        "system": system,
        "messages": messages or [],
        "tools": tools or [],
        "max_tokens": int(max_tokens),
        "thinking_budget": thinking_budget,
    }
    return hashlib.sha256(_stable_dump(payload).encode("utf-8")).hexdigest()


class LLMCache:
    """Thread-safe SQLite cache. Multiple instances over the same DB are safe."""

    def __init__(
        self,
        db_path: Optional[Path] = None,
        *,
        ttl_seconds: float = DEFAULT_TTL_S,
    ) -> None:
        self.db_path = Path(db_path or DEFAULT_DB).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.ttl_seconds = float(ttl_seconds)
        self._lock = threading.Lock()
        self._ensure_schema()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        c = sqlite3.connect(str(self.db_path), isolation_level=None)
        try:
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA busy_timeout=5000")
            c.row_factory = sqlite3.Row
            yield c
        finally:
            c.close()

    def _ensure_schema(self) -> None:
        with self._conn() as c:
            c.executescript(_SCHEMA)

    def lookup(self, key: str, *, now: Optional[float] = None) -> Optional[CachedResponse]:
        n = now if now is not None else time.time()
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT * FROM responses WHERE key=?", (key,),
            ).fetchone()
            if row is None:
                return None
            age = n - float(row["created_at"])
            if self.ttl_seconds and age > self.ttl_seconds:
                c.execute("DELETE FROM responses WHERE key=?", (key,))
                return None
            c.execute(
                "UPDATE responses SET hit_count=hit_count+1 WHERE key=?",
                (key,),
            )
        return CachedResponse(
            key=key,
            text=str(row["text"]),
            thinking=str(row["thinking"] or ""),
            stop_reason=str(row["stop_reason"] or ""),
            provider=str(row["provider"]),
            model=str(row["model"]),
            created_at=float(row["created_at"]),
            hit_count=int(row["hit_count"]) + 1,
        )

    def store(
        self,
        key: str,
        *,
        provider: str,
        model: str,
        text: str,
        thinking: str = "",
        stop_reason: str = "",
    ) -> None:
        now = time.time()
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO responses "
                "(key, provider, model, text, thinking, stop_reason, "
                " created_at, hit_count) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
                (key, provider, model, text, thinking, stop_reason, now),
            )

    def purge_expired(self, *, now: Optional[float] = None) -> int:
        if not self.ttl_seconds:
            return 0
        n = now if now is not None else time.time()
        cutoff = n - self.ttl_seconds
        with self._lock, self._conn() as c:
            cur = c.execute(
                "DELETE FROM responses WHERE created_at < ?", (cutoff,),
            )
            return cur.rowcount

    def stats(self) -> dict:
        with self._conn() as c:
            row = c.execute(
                "SELECT COUNT(*) AS n, SUM(hit_count) AS hits, "
                "MIN(created_at) AS oldest FROM responses",
            ).fetchone()
        return {
            "entries": int(row["n"] or 0),
            "hits":    int(row["hits"] or 0),
            "oldest":  float(row["oldest"] or 0.0),
        }

    def clear(self) -> None:
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM responses")


_singleton_lock = threading.Lock()
_singleton: Optional[LLMCache] = None


def get(db_path: Optional[Path] = None) -> LLMCache:
    """Lazy global singleton.

    Call with an explicit ``db_path`` only the first time to override
    the default. Subsequent calls return the original instance.
    """
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = LLMCache(db_path=db_path)
    return _singleton


def enabled() -> bool:
    return _enabled_via_env()


__all__ = [
    "LLMCache", "CachedResponse", "cache_key", "get",
    "enabled", "DEFAULT_DB", "DEFAULT_TTL_S",
]
