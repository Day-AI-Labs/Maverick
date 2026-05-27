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
from typing import Any, Optional

log = logging.getLogger(__name__)


DEFAULT_PATH = Path.home() / ".maverick" / "vector_store"


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
        path: Optional[Path] = None,
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
        self._collection = self._client.get_or_create_collection(
            name=collection,
            embedding_function=embedding_function,
        )
        self._collection_name = collection

    def add(
        self,
        documents: list[str],
        *,
        ids: Optional[list[str]] = None,
        metadatas: Optional[list[dict]] = None,
    ) -> None:
        """Index a batch of documents. ids auto-generated if not provided."""
        if not documents:
            return
        import uuid as _uuid
        if ids is None:
            ids = [str(_uuid.uuid4()) for _ in documents]
        kwargs: dict[str, Any] = {"documents": documents, "ids": ids}
        if metadatas:
            kwargs["metadatas"] = metadatas
        self._collection.add(**kwargs)

    def query(self, text: str, *, top_k: int = 5) -> list[dict]:
        """Top-k similarity search. Returns list of {id, document, distance, metadata}."""
        if not text:
            return []
        result = self._collection.query(
            query_texts=[text],
            n_results=max(1, min(top_k, 100)),
        )
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
        )


__all__ = ["ChromaStore", "DEFAULT_PATH"]
