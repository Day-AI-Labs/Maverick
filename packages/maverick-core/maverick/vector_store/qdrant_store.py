"""Qdrant vector store adapter.

Embedding-backed memory using Qdrant. Mirrors the Chroma adapter API
(``add(docs)``, ``query(text, top_k)``, ``delete(ids)``, ``count()``)
so callers can swap one for the other.

Defaults to local persistent mode under ``~/.maverick/qdrant/`` (chmod
700). Configurable:
  - ``MAVERICK_QDRANT_PATH`` -> local persistent path
  - ``MAVERICK_QDRANT_URL``  -> remote server URL (overrides path)
  - ``MAVERICK_QDRANT_API_KEY`` -> remote API key

Optional dep behind ``[qdrant]`` extra. qdrant-client >= 1.6 ships
fastembed integration; this adapter uses ``client.add``/``client.query``
so embeddings happen client-side without an extra wiring step.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


DEFAULT_PATH = Path.home() / ".maverick" / "qdrant"


class QdrantStore:
    """Thin wrapper over qdrant-client.

    Lazy import: qdrant-client + fastembed are heavy. We don't pay the
    cost unless a store is instantiated.
    """

    def __init__(
        self,
        collection: str = "maverick",
        path: Optional[Path] = None,
        url: Optional[str] = None,
        api_key: Optional[str] = None,
        embedding_model: Optional[str] = None,
    ):
        try:
            from qdrant_client import QdrantClient  # noqa: F401
        except ImportError as e:
            raise ImportError(
                "qdrant-client not installed. Run: pip install 'maverick-agent[qdrant]'"
            ) from e
        from qdrant_client import QdrantClient

        url = url or os.environ.get("MAVERICK_QDRANT_URL")
        api_key = api_key or os.environ.get("MAVERICK_QDRANT_API_KEY")

        if url:
            self._client = QdrantClient(url=url, api_key=api_key)
        else:
            store_path = Path(
                path or os.environ.get("MAVERICK_QDRANT_PATH", str(DEFAULT_PATH))
            )
            store_path.mkdir(parents=True, exist_ok=True)
            try:
                os.chmod(store_path, 0o700)
            except OSError:
                pass
            self._client = QdrantClient(path=str(store_path))

        if embedding_model:
            # Switch the built-in fastembed model. Default is
            # sentence-transformers/all-MiniLM-L6-v2 (384-dim).
            try:
                self._client.set_model(embedding_model)
            except Exception as e:  # pragma: no cover -- depends on backend
                log.warning("qdrant: set_model(%s) failed: %s", embedding_model, e)

        self._collection = collection

    def add(
        self,
        documents: list[str],
        *,
        ids: Optional[list[str]] = None,
        metadatas: Optional[list[dict]] = None,
    ) -> None:
        """Index a batch of documents. ids auto-generated if not provided.

        Requires fastembed for the default embedder. Errors propagate so
        the caller can surface a helpful install hint.
        """
        if not documents:
            return
        import uuid as _uuid
        if ids is None:
            ids = [str(_uuid.uuid4()) for _ in documents]
        kwargs: dict = {
            "collection_name": self._collection,
            "documents": documents,
            "ids": ids,
        }
        if metadatas:
            kwargs["metadata"] = metadatas
        self._client.add(**kwargs)

    def query(self, text: str, *, top_k: int = 5) -> list[dict]:
        """Top-k similarity search. Returns list of {id, document, distance, metadata}.

        ``distance`` is ``1 - score`` so callers comparing Chroma and
        Qdrant adapters see consistent "lower = closer" semantics.
        """
        if not text:
            return []
        results = self._client.query(
            collection_name=self._collection,
            query_text=text,
            limit=max(1, min(top_k, 100)),
        )
        out: list[dict] = []
        for r in results:
            score = getattr(r, "score", None)
            distance = (1.0 - score) if isinstance(score, (int, float)) else None
            out.append({
                "id": str(getattr(r, "id", "")),
                "document": getattr(r, "document", "") or "",
                "distance": distance,
                "metadata": getattr(r, "metadata", None) or None,
            })
        return out

    def delete(self, ids: list[str]) -> None:
        if not ids:
            return
        from qdrant_client.models import PointIdsList
        self._client.delete(
            collection_name=self._collection,
            points_selector=PointIdsList(points=list(ids)),
        )

    def count(self) -> int:
        try:
            res = self._client.count(collection_name=self._collection, exact=True)
            return int(getattr(res, "count", 0))
        except Exception:
            return 0

    def reset(self) -> None:
        """Drop and recreate the collection. Tests use this; runtime
        users should prefer ``delete(ids)``."""
        try:
            self._client.delete_collection(self._collection)
        except Exception:
            pass


__all__ = ["QdrantStore", "DEFAULT_PATH"]
