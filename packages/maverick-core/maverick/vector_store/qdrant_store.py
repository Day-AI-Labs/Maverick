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

from ..paths import data_dir

log = logging.getLogger(__name__)


DEFAULT_PATH = data_dir("qdrant")


def _active_tenant() -> str | None:
    """Tenant scope for vector ids, or ``None`` for legacy single-tenant use."""
    try:
        from ..paths import current_tenant
        return current_tenant()
    except Exception:  # pragma: no cover -- tenancy never blocks vector ops
        return None


def _stored_id(doc_id: str, tenant_id: str | None) -> str:
    """Namespace an id by tenant so one tenant can't read/delete another's
    vectors -- the same scheme the pgvector adapter uses for its row ids."""
    if tenant_id is None:
        return doc_id
    return f"tenant:{tenant_id}:{doc_id}"


class QdrantStore:
    """Thin wrapper over qdrant-client.

    Lazy import: qdrant-client + fastembed are heavy. We don't pay the
    cost unless a store is instantiated.
    """

    def __init__(
        self,
        collection: str = "maverick",
        path: Path | None = None,
        url: str | None = None,
        api_key: str | None = None,
        embedding_model: str | None = None,
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
        ids: list[str] | None = None,
        metadatas: list[dict] | None = None,
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
        # Fail fast with a clear message rather than a backend-internal
        # error deep in the upsert when the parallel arrays don't line up.
        if len(ids) != len(documents):
            raise ValueError(
                f"ids length {len(ids)} != documents length {len(documents)}"
            )
        if metadatas is not None and len(metadatas) != len(documents):
            raise ValueError(
                f"metadatas length {len(metadatas)} != documents length {len(documents)}"
            )
        tenant_id = _active_tenant()
        kwargs: dict = {
            "collection_name": self._collection,
            "documents": documents,
            "ids": [_stored_id(i, tenant_id) for i in ids],
        }
        if metadatas:
            kwargs["metadata"] = metadatas
        self._client.add(**kwargs)

    def query(self, text: str, *, top_k: int = 5) -> list[dict]:
        """Top-k similarity search. Returns list of
        {id, document, score, distance, metadata}.

        Results come back highest-similarity-first from Qdrant. ``score``
        is the raw similarity from the collection's metric; ``distance``
        is ``1 - score`` for "lower = closer" parity with the Chroma
        adapter. NOTE: ``1 - score`` only orders correctly for the
        default cosine (0..1) metric; for a DOT/EUCLID collection, sort
        by raw ``score`` (already similarity-ordered by the backend)
        rather than ``distance``.
        """
        if not text:
            return []
        tenant_id = _active_tenant()
        want = max(1, min(top_k, 100))
        prefix = f"tenant:{tenant_id}:" if tenant_id is not None else None
        # The similarity search spans the whole collection, but writes are
        # namespaced by `_stored_id` (the same isolation boundary delete() uses).
        # Without scoping the read, query() returned OTHER tenants' vectors.
        # Over-fetch and drop hits outside this tenant's prefix; strip the prefix
        # so the caller gets back its original doc id. (Best-effort top_k: a tenant
        # whose vectors are sparse among many may get < top_k -- a server-side
        # payload filter would be exact, but this matches the id-namespacing design.)
        fetch = want if prefix is None else min(100, want * 10)
        results = self._client.query(
            collection_name=self._collection,
            query_text=text,
            limit=fetch,
        )
        out: list[dict] = []
        for r in results:
            rid = str(getattr(r, "id", ""))
            if prefix is not None:
                if not rid.startswith(prefix):
                    continue
                rid = rid[len(prefix):]
            score = getattr(r, "score", None)
            score_f = float(score) if isinstance(score, (int, float)) else None
            distance = (1.0 - score_f) if score_f is not None else None
            out.append({
                "id": rid,
                "document": getattr(r, "document", "") or "",
                "score": score_f,
                "distance": distance,
                "metadata": getattr(r, "metadata", None) or None,
            })
            if len(out) >= want:
                break
        return out

    def delete(self, ids: list[str]) -> None:
        if not ids:
            return
        from qdrant_client.models import PointIdsList
        tenant_id = _active_tenant()
        self._client.delete(
            collection_name=self._collection,
            points_selector=PointIdsList(
                points=[_stored_id(i, tenant_id) for i in ids]),
        )

    def count(self) -> int:
        try:
            res = self._client.count(collection_name=self._collection, exact=True)
            return int(getattr(res, "count", 0))
        except Exception as e:
            # Log so a backend outage isn't silently reported as an empty store.
            log.warning("qdrant: count failed (%s); reporting 0", e)
            return 0

    def reset(self) -> None:
        """Drop and recreate the collection. Tests use this; runtime
        users should prefer ``delete(ids)``.

        Recreate after the drop so a ``query`` before the next ``add`` doesn't
        hit a missing collection. ``client.add`` auto-creates with the
        fastembed vector params, so recreate with the same params; if the
        client can't supply them (older versions / no model loaded) we leave
        the next ``add`` to lazily recreate."""
        try:
            self._client.delete_collection(self._collection)
        except Exception:
            pass
        try:
            self._client.create_collection(
                collection_name=self._collection,
                vectors_config=self._client.get_fastembed_vector_params(),
            )
        except Exception:  # pragma: no cover -- next add() recreates lazily
            pass


__all__ = ["QdrantStore", "DEFAULT_PATH"]
