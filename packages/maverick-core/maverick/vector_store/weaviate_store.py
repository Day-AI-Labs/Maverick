"""Weaviate vector store adapter (roadmap: 2027 H1 ecosystem — "Weaviate vector store").

Embedding-backed memory using Weaviate. Mirrors the Chroma / Qdrant adapter API
(``add(docs)``, ``query(text, top_k)``, ``delete(ids)``, ``count()``) so callers
swap one for another with no code change.

Uses Weaviate's embedded mode by default (no separate server) and a remote
cluster when configured:
  - ``MAVERICK_WEAVIATE_URL``     -> remote server URL (overrides embedded)
  - ``MAVERICK_WEAVIATE_API_KEY`` -> remote API key

Vectorization is delegated to Weaviate's configured vectorizer module, so the
collection embeds text server-side — the same "no extra wiring" stance as the
Qdrant adapter's fastembed integration. Optional dep behind the ``[weaviate]``
extra.
"""
from __future__ import annotations

import logging
import os
import uuid as _uuid

log = logging.getLogger(__name__)


def _uuid_for(doc_id: str) -> str:
    """Weaviate object IDs must be UUIDs; map an arbitrary string id onto a
    stable UUID5 so re-adding the same id upserts rather than duplicates."""
    try:
        return str(_uuid.UUID(doc_id))
    except (ValueError, AttributeError, TypeError):
        return str(_uuid.uuid5(_uuid.NAMESPACE_URL, f"maverick:{doc_id}"))


class WeaviateStore:
    """Thin wrapper over weaviate-client v4. Lazy import: the client is heavy."""

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

        url = url or os.environ.get("MAVERICK_WEAVIATE_URL")
        api_key = api_key or os.environ.get("MAVERICK_WEAVIATE_API_KEY")

        if url:
            if api_key:
                from weaviate.classes.init import Auth
                self._client = weaviate.connect_to_weaviate_cloud(
                    cluster_url=url, auth_credentials=Auth.api_key(api_key))
            else:
                self._client = weaviate.connect_to_local(host=url)
        else:
            self._client = weaviate.connect_to_embedded()

        # Weaviate collection names are capitalized GraphQL classes.
        self._collection = collection[:1].upper() + collection[1:]
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        try:
            if not self._client.collections.exists(self._collection):
                self._client.collections.create(self._collection)
        except Exception as e:  # pragma: no cover -- backend-specific
            log.warning("weaviate: ensure collection failed: %s", e)

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
                f"metadatas length {len(metadatas)} != documents length {len(documents)}")
        coll = self._client.collections.get(self._collection)
        with coll.batch.dynamic() as batch:
            for i, doc in enumerate(documents):
                props = {"document": doc}
                if metadatas:
                    props.update(metadatas[i] or {})
                batch.add_object(properties=props, uuid=_uuid_for(ids[i]))

    def query(self, text: str, *, top_k: int = 5) -> list[dict]:
        if not text:
            return []
        coll = self._client.collections.get(self._collection)
        res = coll.query.near_text(query=text, limit=max(1, min(top_k, 100)))
        out: list[dict] = []
        for obj in getattr(res, "objects", []) or []:
            props = dict(getattr(obj, "properties", {}) or {})
            document = props.pop("document", "") or ""
            meta = getattr(obj, "metadata", None)
            distance = getattr(meta, "distance", None) if meta else None
            dist_f = float(distance) if isinstance(distance, (int, float)) else None
            score = (1.0 - dist_f) if dist_f is not None else None
            out.append({
                "id": str(getattr(obj, "uuid", "")),
                "document": document,
                "score": score,
                "distance": dist_f,
                "metadata": props or None,
            })
        return out

    def delete(self, ids: list[str]) -> None:
        if not ids:
            return
        coll = self._client.collections.get(self._collection)
        for doc_id in ids:
            try:
                coll.data.delete_by_id(_uuid_for(doc_id))
            except Exception as e:  # pragma: no cover -- backend-specific
                log.debug("weaviate: delete %s failed: %s", doc_id, e)

    def count(self) -> int:
        try:
            coll = self._client.collections.get(self._collection)
            res = coll.aggregate.over_all(total_count=True)
            return int(getattr(res, "total_count", 0) or 0)
        except Exception:
            return 0

    def reset(self) -> None:
        try:
            self._client.collections.delete(self._collection)
        except Exception:
            pass
        self._ensure_collection()


__all__ = ["WeaviateStore"]
