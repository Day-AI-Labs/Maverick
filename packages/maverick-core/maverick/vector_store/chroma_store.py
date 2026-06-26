"""Chroma vector store adapter.

Lightweight embedding-backed memory using Chroma. Reads from
~/.maverick/vector_store/ by default; configurable via
``MAVERICK_CHROMA_PATH``.

Optional dep behind ``[chroma]`` extra.

This is the FIRST vector-store adapter; future Qdrant / Weaviate
plugins follow this shape.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from ..paths import data_dir

log = logging.getLogger(__name__)


DEFAULT_PATH = data_dir("vector_store")


class ChromaStore:
    """Thin wrapper over chromadb's PersistentClient.

    Methods mirror the planned vector-store SDK: ``add(docs)``,
    ``query(text, top_k)``, ``delete(ids)``, ``count()``.

    Lazy import: chromadb is heavy (numpy + onnxruntime). We don't
    pay the cost unless the user actually instantiates a store.
    """

    def __init__(
        self,
        collection: str = "maverick",
        path: Path | None = None,
        embedding_function: Any = None,
    ):
        try:
            import chromadb  # noqa: F401
        except ImportError as e:
            raise ImportError(
                "chromadb not installed. Run: pip install 'maverick-agent[chroma]'"
            ) from e
        from chromadb import PersistentClient

        store_path = Path(
            path
            or os.environ.get("MAVERICK_CHROMA_PATH", str(DEFAULT_PATH))
        )
        store_path.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(store_path, 0o700)
        except OSError:
            pass

        self._client = PersistentClient(path=str(store_path))
        # Remember the embedding function so reset() recreates the collection in
        # the SAME embedding space. Recreating without it would silently fall
        # back to Chroma's default embedder, so post-reset vectors live in a
        # different space and never match the originals.
        self._embedding_function = embedding_function
        self._collection = self._client.get_or_create_collection(
            name=collection,
            embedding_function=embedding_function,
        )
        self._collection_name = collection

    def add(
        self,
        documents: list[str],
        *,
        ids: list[str] | None = None,
        metadatas: list[dict] | None = None,
        embeddings: list[list[float]] | None = None,
    ) -> None:
        """Index a batch of documents. ids auto-generated if not provided.

        When ``embeddings`` is given (precomputed client-side), Chroma stores
        them as-is and does NOT run its own embedding function -- so the caller
        can store a *sealed* document while the vector was computed from the
        plaintext (at-rest mode)."""
        if not documents:
            return
        import uuid as _uuid
        if ids is None:
            ids = [str(_uuid.uuid4()) for _ in documents]
        # Fail fast on mismatched parallel arrays instead of a confusing
        # backend-internal error.
        if len(ids) != len(documents):
            raise ValueError(
                f"ids length {len(ids)} != documents length {len(documents)}"
            )
        if metadatas is not None and len(metadatas) != len(documents):
            raise ValueError(
                f"metadatas length {len(metadatas)} != documents length {len(documents)}"
            )
        if embeddings is not None and len(embeddings) != len(documents):
            raise ValueError(
                f"embeddings length {len(embeddings)} != documents length {len(documents)}"
            )
        kwargs: dict[str, Any] = {"documents": documents, "ids": ids}
        if metadatas:
            kwargs["metadatas"] = metadatas
        if embeddings is not None:
            kwargs["embeddings"] = embeddings
        self._collection.add(**kwargs)

    def query(self, text: str | None = None, *, top_k: int = 5,
              embedding: list[float] | None = None) -> list[dict]:
        """Top-k similarity search. Returns list of {id, document, distance, metadata}.

        Pass ``embedding`` (a precomputed query vector) to search by vector
        rather than by ``text`` -- used in at-rest mode where stored documents
        are sealed and the query is embedded client-side."""
        if embedding is not None:
            result = self._collection.query(
                query_embeddings=[embedding],
                n_results=max(1, min(top_k, 100)),
            )
        elif text:
            result = self._collection.query(
                query_texts=[text],
                n_results=max(1, min(top_k, 100)),
            )
        else:
            return []
        out: list[dict] = []
        ids = (result.get("ids") or [[]])[0]
        docs = (result.get("documents") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        for i, doc_id in enumerate(ids):
            out.append({
                "id": doc_id,
                "document": docs[i] if i < len(docs) else "",
                "distance": distances[i] if i < len(distances) else None,
                "metadata": metadatas[i] if i < len(metadatas) else None,
            })
        return out

    def delete(self, ids: list[str]) -> None:
        if not ids:
            return
        self._collection.delete(ids=ids)

    def count(self) -> int:
        return self._collection.count()

    def reset(self) -> None:
        """Drop and recreate the collection. Tests use this; runtime
        users should prefer ``delete(ids)``."""
        try:
            self._client.delete_collection(self._collection_name)
        except Exception:
            pass
        self._collection = self._client.get_or_create_collection(
            name=self._collection_name,
            embedding_function=self._embedding_function,
        )


__all__ = ["ChromaStore", "DEFAULT_PATH"]
