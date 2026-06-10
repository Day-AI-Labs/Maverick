"""Weaviate vector store adapter.

Mirrors the ChromaStore / QdrantStore interface (``add`` / ``query`` /
``delete`` / ``count`` / ``reset``) over a Weaviate collection, so cross-run
semantic memory can target a Weaviate cluster without touching call sites.

Optional dep behind the ``[weaviate]`` extra. Connection is env-driven:
``MAVERICK_WEAVIATE_URL`` (+ ``MAVERICK_WEAVIATE_API_KEY``) for a remote
cluster, otherwise a local embedded/`connect_to_local` instance. The
``weaviate-client`` v4 module is imported lazily so the package imports clean
without the extra.

Embeddings: like Qdrant's fastembed path, this assumes the collection is
configured with a server-side vectorizer (``near_text`` does the embedding).
Pass an explicit ``vector`` via ``add``/``query`` to bring your own.
"""
from __future__ import annotations

import logging
import os
import uuid as _uuid
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 8080


def _stable_uuid(doc_id: str) -> str:
    """Weaviate requires UUID object ids; map an arbitrary string id to a
    deterministic UUIDv5 so the same logical id always addresses the same
    object (idempotent upserts, addressable deletes)."""
    try:
        return str(_uuid.UUID(str(doc_id)))
    except (ValueError, AttributeError, TypeError):
        return str(_uuid.uuid5(_uuid.NAMESPACE_URL, f"maverick:{doc_id}"))


class WeaviateStore:
    """Thin wrapper over weaviate-client v4's collection API."""

    def __init__(
        self,
        collection: str = "Maverick",
        url: str | None = None,
        api_key: str | None = None,
    ):
        try:
            import weaviate  # noqa: F401
        except ImportError as e:
            raise ImportError(
                "weaviate-client not installed. Run: pip install 'maverick-agent[weaviate]'"
            ) from e
        import weaviate
        from weaviate.classes.init import Auth

        url = url or os.environ.get("MAVERICK_WEAVIATE_URL")
        api_key = api_key or os.environ.get("MAVERICK_WEAVIATE_API_KEY")

        if url:
            auth = Auth.api_key(api_key) if api_key else None
            self._client = weaviate.connect_to_weaviate_cloud(
                cluster_url=url, auth_credentials=auth
            )
        else:
            self._client = weaviate.connect_to_local(
                host=os.environ.get("MAVERICK_WEAVIATE_HOST", DEFAULT_HOST),
                port=int(os.environ.get("MAVERICK_WEAVIATE_PORT", DEFAULT_PORT)),
            )

        # v4: collections.exists / create / get.
        if not self._client.collections.exists(collection):
            self._client.collections.create(collection)
        self._collection_name = collection
        self._collection = self._client.collections.get(collection)

    def add(
        self,
        documents: list[str],
        *,
        ids: list[str] | None = None,
        metadatas: list[dict] | None = None,
    ) -> None:
        if not documents:
            return
        if ids is None:
            ids = [str(_uuid.uuid4()) for _ in documents]
        if len(ids) != len(documents):
            raise ValueError(f"ids length {len(ids)} != documents length {len(documents)}")
        if metadatas is not None and len(metadatas) != len(documents):
            raise ValueError(
                f"metadatas length {len(metadatas)} != documents length {len(documents)}"
            )
        for i, doc in enumerate(documents):
            props: dict[str, Any] = {"text": doc}
            if metadatas:
                props.update(metadatas[i])
            self._collection.data.insert(properties=props, uuid=_stable_uuid(ids[i]))

    def query(self, text: str, *, top_k: int = 5) -> list[dict]:
        """Top-k similarity search. Returns [{id, document, distance, metadata}]."""
        if not text:
            return []
        from weaviate.classes.query import MetadataQuery

        res = self._collection.query.near_text(
            query=text,
            limit=max(1, min(top_k, 100)),
            return_metadata=MetadataQuery(distance=True),
        )
        out: list[dict] = []
        for obj in res.objects:
            props = dict(obj.properties or {})
            document = props.pop("text", "")
            out.append({
                "id": str(obj.uuid),
                "document": document,
                "distance": getattr(obj.metadata, "distance", None),
                "metadata": props or None,
            })
        return out

    def delete(self, ids: list[str]) -> None:
        if not ids:
            return
        for doc_id in ids:
            self._collection.data.delete_by_id(_stable_uuid(doc_id))

    def count(self) -> int:
        agg = self._collection.aggregate.over_all(total_count=True)
        return int(getattr(agg, "total_count", 0) or 0)

    def reset(self) -> None:
        """Drop and recreate the collection. Tests use this; runtime users
        should prefer ``delete(ids)``."""
        try:
            self._client.collections.delete(self._collection_name)
        except Exception:
            pass
        self._client.collections.create(self._collection_name)
        self._collection = self._client.collections.get(self._collection_name)

    def close(self) -> None:
        """Release the client's gRPC/HTTP connections (v4 holds sockets open)."""
        try:
            self._client.close()
        except Exception:
            pass


__all__ = ["WeaviateStore", "DEFAULT_HOST", "DEFAULT_PORT"]
