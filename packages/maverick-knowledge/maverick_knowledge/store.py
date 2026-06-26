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


def _to_pgvector(vec: list[float]) -> str:
    """A pgvector text literal (``[1,2,3]``) -- passed with a ``::vector`` cast so
    the backend needs only ``psycopg`` + the Postgres ``vector`` extension, not
    the optional ``pgvector`` Python package."""
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"


class PgVectorStore:
    """pgvector-backed scale-out vector store -- the opt-in backend for corpora
    too large for the brute-force SQLite index.

    Same surface + collection-scoped compartments as :class:`SqliteVectorStore`,
    but cosine search runs in Postgres via the ``<=>`` operator (with an IVFFlat
    index), so retrieval doesn't scan every row in the process. Vectors are
    passed as text literals cast to ``::vector``; only ``psycopg`` and the
    Postgres ``vector`` extension are required (no numpy / pgvector-python).

    Connection-shared across threads like the SQLite store (ingestion runs on a
    threadpool); a single psycopg connection is NOT thread-safe, so every
    statement is serialized under a lock.
    """

    def __init__(self, dsn: str | None = None, *, dim: int = 1024,
                 table: str = "knowledge_chunks") -> None:
        try:
            import psycopg
        except ImportError as e:  # pragma: no cover -- exercised only without psycopg
            raise ImportError(
                "pgvector store needs psycopg. Run: "
                "pip install 'maverick-knowledge[pgvector]'"
            ) from e
        import os
        self._dsn = dsn or os.environ.get("MAVERICK_KNOWLEDGE_DSN") \
            or os.environ.get("MAVERICK_PG_DSN") or ""
        if not self._dsn:
            raise RuntimeError(
                "pgvector store requires MAVERICK_KNOWLEDGE_DSN / MAVERICK_PG_DSN "
                "or [knowledge] dsn in config.toml."
            )
        if dim <= 0:
            raise ValueError(f"pgvector store needs a positive dim, got {dim}")
        self._dim = int(dim)
        # Identifier is operator/config-derived, not agent input; still constrain
        # it to a safe charset so it can be interpolated into DDL without an
        # injection surface.
        if not table.replace("_", "").isalnum():
            raise ValueError(f"invalid table name {table!r}")
        self._table = table
        self._lock = threading.Lock()
        self._db = psycopg.connect(self._dsn, autocommit=True)
        try:
            self._db.execute("CREATE EXTENSION IF NOT EXISTS vector")
        except Exception as e:  # pragma: no cover -- perms vary by deployment
            raise RuntimeError(
                "pgvector store: could not enable the 'vector' extension "
                f"({e}). Install pgvector and grant CREATE on the database."
            ) from e
        self._db.execute(
            f"CREATE TABLE IF NOT EXISTS {self._table} ("
            "collection TEXT, id TEXT, text TEXT, "
            f"embedding vector({self._dim}), meta JSONB, "
            "PRIMARY KEY (collection, id))"
        )
        # Cosine IVFFlat index -- approximate but the point of the scale backend.
        self._db.execute(
            f"CREATE INDEX IF NOT EXISTS {self._table}_embedding_idx "
            f"ON {self._table} USING ivfflat (embedding vector_cosine_ops) "
            "WITH (lists = 100)"
        )

    def add(self, collection, items) -> None:
        if not items:
            return
        with self._lock, self._db.cursor() as cur:
            cur.executemany(
                f"INSERT INTO {self._table} (collection, id, text, embedding, meta) "
                "VALUES (%s, %s, %s, %s::vector, %s::jsonb) "
                "ON CONFLICT (collection, id) DO UPDATE SET "
                "text = EXCLUDED.text, embedding = EXCLUDED.embedding, "
                "meta = EXCLUDED.meta",
                [
                    (collection, cid, text, _to_pgvector(vec), json.dumps(meta))
                    for cid, text, vec, meta in items
                ],
            )

    def search(self, collection, vector, k: int = 5) -> list[Match]:
        if k <= 0:
            return []
        if len(vector) != self._dim:
            # Mirror the SQLite store: a query embedded at a different dim than
            # the corpus is a misconfiguration, not an empty result.
            raise ValueError(
                f"knowledge: query vector dim {len(vector)} != store dim "
                f"{self._dim}; the corpus was embedded with a different "
                "embedder/model than this query"
            )
        with self._lock, self._db.cursor() as cur:
            rows = cur.execute(
                f"SELECT text, meta, 1 - (embedding <=> %s::vector) AS score "
                f"FROM {self._table} WHERE collection = %s "
                "ORDER BY embedding <=> %s::vector LIMIT %s",
                (_to_pgvector(vector), collection, _to_pgvector(vector), int(k)),
            ).fetchall()
        # psycopg adapts JSONB to a dict already; tolerate a str just in case.
        return [
            Match(float(score), text,
                  meta if isinstance(meta, dict) else json.loads(meta or "{}"))
            for text, meta, score in rows
        ]

    def delete_collection(self, collection: str) -> None:
        with self._lock:
            self._db.execute(
                f"DELETE FROM {self._table} WHERE collection = %s", (collection,))

    def count(self, collection: str) -> int:
        with self._lock, self._db.cursor() as cur:
            (n,) = cur.execute(
                f"SELECT COUNT(*) FROM {self._table} WHERE collection = %s",
                (collection,),
            ).fetchone()
        return int(n)

    def close(self) -> None:
        """Close the underlying connection (idempotent)."""
        db = getattr(self, "_db", None)
        if db is not None:
            db.close()
            self._db = None

    def __enter__(self) -> PgVectorStore:
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def build_store(cfg: dict | None = None):
    """Select a vector store from config. Defaults to embedded SQLite; pgvector
    (``[knowledge] store = "pgvector"``) is the opt-in scale backend.

    pgvector reads its DSN from ``[knowledge] dsn`` /
    ``MAVERICK_KNOWLEDGE_DSN`` / ``MAVERICK_PG_DSN`` and its vector width from
    ``[knowledge] dim`` (default 1024 -- matches ``voyage-3``)."""
    cfg = cfg or {}
    backend = str(cfg.get("store", "sqlite")).lower()
    if backend == "pgvector":
        return PgVectorStore(
            dsn=cfg.get("dsn") or None,
            dim=int(cfg.get("dim", 1024)),
        )
    return SqliteVectorStore(cfg.get("path") or ":memory:")
