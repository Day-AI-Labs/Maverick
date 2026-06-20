"""Vector stores.

:class:`SqliteVectorStore` is a dependency-free brute-force cosine index -- fine
for the per-business corpora the factory produces; pgvector is an opt-in backend
for scale (``build_store`` selects it when configured).
"""
from __future__ import annotations

import json
import math
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass
class Match:
    score: float
    text: str
    meta: dict[str, Any]


class VectorStore(Protocol):
    def add(
        self, collection: str, items: list[tuple[str, str, list[float], dict]]
    ) -> None: ...

    def search(
        self, collection: str, vector: list[float], k: int = 5
    ) -> list[Match]: ...

    def delete_collection(self, collection: str) -> None: ...


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class SqliteVectorStore:
    """Brute-force cosine over vectors stored as JSON in SQLite.

    One row per chunk, scoped by ``collection`` (the domain's knowledge source),
    so retrieval is filtered per domain -- knowledge respects the compartment
    bulkheads. ``:memory:`` (the default) is used by tests.
    """

    def __init__(self, path: str | Path = ":memory:"):
        # Create the parent dir for a file-backed store (e.g. a tenant's
        # ~/.maverick/tenants/<t>/knowledge.db) -- sqlite3.connect won't, and
        # would raise on a missing directory. ":memory:" needs no dir.
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        # KnowledgeBase shares one store across threads (ingestion runs under
        # asyncio.to_thread / a worker pool), so allow cross-thread use and
        # serialize access with a lock -- a single sqlite connection is not safe
        # for concurrent use.
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = threading.Lock()
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS chunks ("
            "collection TEXT, id TEXT, text TEXT, vec TEXT, meta TEXT, "
            "PRIMARY KEY (collection, id))"
        )
        self._db.commit()

    def add(self, collection, items) -> None:
        with self._lock:
            self._db.executemany(
                "INSERT OR REPLACE INTO chunks VALUES (?,?,?,?,?)",
                [
                    (collection, cid, text, json.dumps(vec), json.dumps(meta))
                    for cid, text, vec, meta in items
                ],
            )
            self._db.commit()

    def search(self, collection, vector, k: int = 5) -> list[Match]:
        if k <= 0:
            return []
        with self._lock:
            rows = self._db.execute(
                "SELECT text, vec, meta FROM chunks WHERE collection = ?", (collection,)
            ).fetchall()
        scored: list[Match] = []
        for text, vec, meta in rows:
            stored = json.loads(vec)
            # A query embedded with a different model/dim than the corpus would
            # silently score 0.0 against every chunk and return arbitrary
            # results. Surface that misconfiguration instead of guessing.
            if len(stored) != len(vector):
                raise ValueError(
                    f"knowledge: query vector dim {len(vector)} != stored dim "
                    f"{len(stored)} for collection {collection!r}; the corpus was "
                    "embedded with a different embedder/model than this query"
                )
            scored.append(Match(_cosine(vector, stored), text, json.loads(meta)))
        scored.sort(key=lambda m: m.score, reverse=True)
        return scored[:k]

    def delete_collection(self, collection: str) -> None:
        """Remove all chunks for one collection."""
        with self._lock:
            self._db.execute("DELETE FROM chunks WHERE collection = ?", (collection,))
            self._db.commit()

    def count(self, collection: str) -> int:
        with self._lock:
            (n,) = self._db.execute(
                "SELECT COUNT(*) FROM chunks WHERE collection = ?", (collection,)
            ).fetchone()
        return n

    def close(self) -> None:
        """Close the underlying SQLite connection (idempotent)."""
        db = getattr(self, "_db", None)
        if db is not None:
            db.close()
            self._db = None

    def __enter__(self) -> SqliteVectorStore:
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def build_store(cfg: dict | None = None):
    """Select a vector store from config. Defaults to embedded SQLite; pgvector
    (``[knowledge] store = "pgvector"``) is the opt-in scale backend."""
    cfg = cfg or {}
    backend = str(cfg.get("store", "sqlite")).lower()
    if backend == "pgvector":
        raise NotImplementedError(
            "pgvector store is not bundled yet; use the default sqlite store "
            "([knowledge] store = 'sqlite')."
        )
    return SqliteVectorStore(cfg.get("path") or ":memory:")
