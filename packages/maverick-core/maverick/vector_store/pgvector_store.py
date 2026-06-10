"""pgvector vector store adapter (roadmap: 2028 H1 ecosystem).

Mirrors the Chroma/Qdrant/Weaviate adapter API (``add`` / ``query`` /
``delete`` / ``count`` / ``reset``) over Postgres + the pgvector extension —
so a deployment already on the Postgres world-model backend keeps its vectors
in the same database instead of standing up a separate vector service.

This adapter does **not** embed: it takes an injected ``embedder`` callable
(``texts -> list[vector]``) and stores the vectors. ``maverick_knowledge``'s
``build_embedder`` is the natural source; pass it in, or any callable. The
collection is one row-set in a shared ``mvk_vectors`` table, cosine distance
(``<=>``) for search.

Connection from ``MAVERICK_PG_DSN`` (or ``[world_model] dsn``), reusing the
Postgres backend's resolver. ``psycopg`` is the ``[postgres]`` extra, imported
lazily so the package imports clean without it.
"""
from __future__ import annotations

import json
import logging
import os
import uuid as _uuid
from collections.abc import Callable

log = logging.getLogger(__name__)

_TABLE = "mvk_vectors"


def _resolve_dsn(dsn: str | None) -> str | None:
    if dsn:
        return dsn
    env = os.environ.get("MAVERICK_PG_DSN", "").strip()
    if env:
        return env
    try:
        from ..config import load_config
        return str((load_config() or {}).get("world_model", {}).get("dsn") or "").strip() or None
    except Exception:  # pragma: no cover -- config never blocks construction
        return None


class PgVectorStore:
    """Thin wrapper over psycopg + pgvector. ``embedder`` is required for
    add/query (it turns text into vectors); the store never embeds itself."""

    def __init__(
        self,
        collection: str = "maverick",
        *,
        dsn: str | None = None,
        embedder: Callable[[list[str]], list[list[float]]] | None = None,
        dim: int | None = None,
    ):
        try:
            import psycopg
        except ImportError as e:
            raise ImportError(
                "psycopg not installed. Run: pip install 'maverick-agent[postgres]'"
            ) from e

        resolved = _resolve_dsn(dsn)
        if not resolved:
            raise ValueError(
                "pgvector store needs a DSN (MAVERICK_PG_DSN or [world_model] dsn)")
        self._collection = collection
        self._embedder = embedder
        self._dim = dim
        self._conn = psycopg.connect(resolved, autocommit=True)
        self._ensure_schema()

    def _embed(self, texts: list[str]) -> list[list[float]]:
        if self._embedder is None:
            raise RuntimeError(
                "pgvector store has no embedder; pass embedder=... (e.g. "
                "maverick_knowledge.embed.build_embedder()) — the store does "
                "not embed text itself")
        vecs = list(self._embedder(texts))
        if vecs and self._dim is None:
            self._dim = len(vecs[0])
        for v in vecs:
            if self._dim is not None and len(v) != self._dim:
                raise ValueError(
                    f"embedding dim {len(v)} != expected {self._dim} "
                    "(inconsistent embedder output)")
        return vecs

    def _ensure_schema(self) -> None:
        with self._conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            # The vector column is created on first add() once the dim is known
            # (pgvector requires a fixed dimension). Until then store the table
            # shell so count()/reset() work on an empty collection.
            cur.execute(
                f"CREATE TABLE IF NOT EXISTS {_TABLE} ("
                "  id text PRIMARY KEY,"
                "  collection text NOT NULL,"
                "  document text,"
                "  metadata jsonb"
                ")")
            cur.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{_TABLE}_collection "
                f"ON {_TABLE} (collection)")

    def _ensure_vector_column(self, dim: int) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"ALTER TABLE {_TABLE} ADD COLUMN IF NOT EXISTS embedding vector(%s)"
                % int(dim))

    def add(self, documents: list[str], *, ids: list[str] | None = None,
            metadatas: list[dict] | None = None) -> None:
        if not documents:
            return
        if ids is None:
            ids = [str(_uuid.uuid4()) for _ in documents]
        if len(ids) != len(documents):
            raise ValueError(f"ids length {len(ids)} != documents length {len(documents)}")
        if metadatas is not None and len(metadatas) != len(documents):
            raise ValueError(
                f"metadatas length {len(metadatas)} != documents length {len(documents)}")
        vecs = self._embed(documents)
        self._ensure_vector_column(self._dim or len(vecs[0]))
        with self._conn.cursor() as cur:
            for i, doc in enumerate(documents):
                vec = "[" + ",".join(repr(float(x)) for x in vecs[i]) + "]"
                meta = json.dumps(metadatas[i]) if metadatas else None
                cur.execute(
                    f"INSERT INTO {_TABLE} (id, collection, document, metadata, embedding) "
                    "VALUES (%s, %s, %s, %s, %s) "
                    "ON CONFLICT (id) DO UPDATE SET document = EXCLUDED.document, "
                    "metadata = EXCLUDED.metadata, embedding = EXCLUDED.embedding",
                    (ids[i], self._collection, doc, meta, vec))

    def query(self, text: str, *, top_k: int = 5) -> list[dict]:
        if not text:
            return []
        vec = self._embed([text])[0]
        qvec = "[" + ",".join(repr(float(x)) for x in vec) + "]"
        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT id, document, metadata, embedding <=> %s AS distance "
                f"FROM {_TABLE} WHERE collection = %s "
                "ORDER BY embedding <=> %s LIMIT %s",
                (qvec, self._collection, qvec, max(1, min(top_k, 100))))
            rows = cur.fetchall()
        out = []
        for rid, doc, meta, dist in rows:
            out.append({"id": rid, "document": doc,
                        "distance": float(dist) if dist is not None else None,
                        "metadata": meta})
        return out

    def delete(self, ids: list[str]) -> None:
        if not ids:
            return
        with self._conn.cursor() as cur:
            cur.execute(
                f"DELETE FROM {_TABLE} WHERE collection = %s AND id = ANY(%s)",
                (self._collection, list(ids)))

    def count(self) -> int:
        with self._conn.cursor() as cur:
            cur.execute(f"SELECT count(*) FROM {_TABLE} WHERE collection = %s",
                        (self._collection,))
            return int(cur.fetchone()[0])

    def reset(self) -> None:
        with self._conn.cursor() as cur:
            cur.execute(f"DELETE FROM {_TABLE} WHERE collection = %s", (self._collection,))

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:  # pragma: no cover
            pass


__all__ = ["PgVectorStore"]
