"""Vector stores.

:class:`SqliteVectorStore` is a dependency-free brute-force cosine index -- fine
for the per-business corpora the factory produces; pgvector is an opt-in backend
for scale (``build_store`` selects it when configured).
"""
from __future__ import annotations

import json
import math
import sqlite3
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


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
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
        self._db = sqlite3.connect(str(path))
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS chunks ("
            "collection TEXT, id TEXT, text TEXT, vec TEXT, meta TEXT, "
            "PRIMARY KEY (collection, id))"
        )
        self._db.commit()

    def add(self, collection, items) -> None:
        self._db.executemany(
            "INSERT OR REPLACE INTO chunks VALUES (?,?,?,?,?)",
            [
                (collection, cid, text, json.dumps(vec), json.dumps(meta))
                for cid, text, vec, meta in items
            ],
        )
        self._db.commit()

    def search(self, collection, vector, k: int = 5) -> list[Match]:
        rows = self._db.execute(
            "SELECT text, vec, meta FROM chunks WHERE collection = ?", (collection,)
        ).fetchall()
        scored = [
            Match(_cosine(vector, json.loads(vec)), text, json.loads(meta))
            for text, vec, meta in rows
        ]
        scored.sort(key=lambda m: m.score, reverse=True)
        return scored[: max(1, k)]

    def count(self, collection: str) -> int:
        (n,) = self._db.execute(
            "SELECT COUNT(*) FROM chunks WHERE collection = ?", (collection,)
        ).fetchone()
        return n


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
