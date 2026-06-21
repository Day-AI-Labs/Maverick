"""Semantic cross-run recall over the vector_store adapters.

`recall_past_goals` (tools/recall.py) does a linear scan + on-demand
fastembed/jaccard re-rank: fine for small histories, but O(n) per query
and embeds every candidate every time. This module routes recall through a
persistent vector store (Chroma / Qdrant) when the operator configures one,
so similarity search is indexed and incremental — the "how well" companion
to the auto-recall wiring (the "when").

Design:
  * Fully opt-in. With no ``[memory] backend`` configured (the default),
    every entry point is a no-op and callers fall back to the existing
    lexical/embedding recall. The kernel never *requires* a vector store.
  * Fail-open. A missing optional dep (chromadb/qdrant-client), a backend
    error, or a malformed config degrades to "no semantic backend" — never
    an exception into the run.
  * Dependency-injectable. ``build_store`` is the single construction
    point; tests pass a fake store with the same ``add``/``query``
    interface, so the wiring is exercised without the heavy extras.

Document id convention: ``goal:<id>`` so re-indexing a goal upserts rather
than duplicates (delete-then-add).
"""
from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger(__name__)


def backend_name() -> str | None:
    """Configured vector-store backend, or None when semantic recall is off.

    Resolved from ``MAVERICK_VECTOR_STORE`` (env wins) or ``[memory]
    backend`` in config. Recognised: ``chroma``, ``qdrant``, ``weaviate``,
    ``pgvector``. Anything else (including unset / "none") disables the
    semantic path.
    """
    env = os.environ.get("MAVERICK_VECTOR_STORE")
    if env is not None:
        name = env.strip().lower()
    else:
        try:
            from .config import load_config
            name = str(load_config().get("memory", {}).get("backend", "")).strip().lower()
        except Exception:  # pragma: no cover -- config never blocks a run
            name = ""
    return name if name in ("chroma", "qdrant", "weaviate", "pgvector") else None


def _tenant_ns() -> str | None:
    """Sanitized active-tenant namespace, or None for single-tenant use."""
    try:
        from .paths import current_tenant
        t = current_tenant()
    except Exception:  # pragma: no cover -- tenancy never blocks a run
        return None
    if not t:
        return None
    import re
    return re.sub(r"[^0-9A-Za-z]", "_", str(t))[:48] or None


def build_store(backend: str | None = None) -> Any | None:
    """Construct the configured vector store, or None if unavailable.

    Never raises: a missing extra or a backend error returns None so the
    caller falls back to lexical/embedding recall.

    Multi-tenant isolation: the SHARED external backends (chroma/qdrant/weaviate)
    run similarity SEARCH across every row in a collection -- id-namespacing
    isolates get/delete-by-id but NOT search -- so one tenant's recall would
    surface another tenant's goals. Give each tenant its OWN collection (the
    standard vector-DB multi-tenancy pattern; a wrong name errors loudly rather
    than leaking). No-op single-tenant. pgvector already scopes by a tenant_id
    column, so it keeps the shared collection.
    """
    backend = backend or backend_name()
    if backend is None:
        return None
    ns = _tenant_ns()
    try:
        if backend == "chroma":
            from .vector_store import ChromaStore
            return ChromaStore(collection=f"t_{ns}__goals" if ns else "goals")
        if backend == "qdrant":
            from .vector_store import QdrantStore
            return QdrantStore(collection=f"t_{ns}__goals" if ns else "goals")
        if backend == "weaviate":
            from .vector_store import WeaviateStore
            # Weaviate class names must start with an uppercase letter.
            return WeaviateStore(collection=f"T_{ns}__Goals" if ns else "Goals")
        if backend == "pgvector":
            # pgvector does not embed; inject the local fastembed embedder
            # (the same one skills use). No embedder -> fail-open to lexical.
            from .skill import embeddings as skill_embeddings
            from .vector_store import PgVectorStore

            def _embed(texts):
                vecs = skill_embeddings.embed(list(texts))
                if vecs is None:
                    raise RuntimeError(
                        "pgvector recall needs a local embedder (install fastembed)")
                return vecs

            return PgVectorStore(collection="goals", embedder=_embed)
    except Exception as e:  # pragma: no cover -- optional dep / backend down
        log.debug("semantic recall backend %s unavailable: %s", backend, e)
    return None


def _goal_text(goal) -> str:
    return f"{getattr(goal, 'title', '') or ''}\n\n{getattr(goal, 'description', '') or ''}".strip()


def index_goal(goal, *, store: Any | None = None) -> bool:
    """Upsert one goal into the vector store. Returns True if indexed.

    No-op (returns False) when no backend is configured/available. Stores
    the goal's title+description as the document (it must be embedded as
    plaintext for similarity search) and id ``goal:<id>``. Metadata is limited
    to non-sensitive routing keys (``goal_id``/``status``): the sensitive
    ``title``/``result`` are NOT duplicated here -- callers hydrate them from the
    sealed world DB by ``goal_id`` -- so the external vector store holds no
    verbatim copy of them. Delete-then-add so re-indexing upserts. Never raises.
    """
    store = store if store is not None else build_store()
    if store is None:
        return False
    text = _goal_text(goal)
    if not text:
        return False
    doc_id = f"goal:{getattr(goal, 'id', '')}"
    try:
        try:
            store.delete([doc_id])
        except Exception:  # pragma: no cover -- delete of absent id may raise
            pass
        store.add(
            [text],
            ids=[doc_id],
            metadatas=[{
                # Routing only -- no sensitive content. title/result are read
                # back from the sealed world DB by goal_id (see search() callers),
                # so the vector store never holds a plaintext copy of them.
                "goal_id": getattr(goal, "id", None),
                "status": getattr(goal, "status", None),
            }],
        )
        return True
    except Exception as e:  # pragma: no cover -- backend write error
        log.debug("semantic index of goal failed: %s", e)
        return False


def search(
    query: str,
    *,
    k: int = 5,
    store: Any | None = None,
    exclude_goal_id: int | None = None,
) -> list[tuple[float, dict]] | None:
    """Semantic top-k over indexed goals.

    Returns a list of ``(score, metadata)`` where score is a similarity in
    [0, 1] (``1 - distance``, clamped) and metadata carries only routing keys
    (goal_id / status); hydrate title/result from the world DB by goal_id (the
    vector store keeps no plaintext copy). Returns ``None`` when no backend is
    configured/available, so
    the caller knows to fall back to lexical/embedding recall (an empty list
    means "backend present, no matches"). Never raises.
    """
    if not query:
        return None
    store = store if store is not None else build_store()
    if store is None:
        return None
    try:
        # Over-fetch so we can drop the current goal then trim to k.
        hits = store.query(query, top_k=k + 1)
    except Exception as e:  # pragma: no cover -- backend query error
        log.debug("semantic search failed: %s", e)
        return None
    out: list[tuple[float, dict]] = []
    for h in hits or []:
        meta = h.get("metadata") or {}
        gid = meta.get("goal_id")
        if exclude_goal_id is not None and gid == exclude_goal_id:
            continue
        dist = h.get("distance")
        # Chroma returns L2/cosine distance; map to a [0,1] similarity.
        if dist is None:
            score = 0.0
        else:
            try:
                score = max(0.0, min(1.0, 1.0 - float(dist)))
            except (TypeError, ValueError):
                score = 0.0
        out.append((score, meta))
        if len(out) >= k:
            break
    return out


__all__ = ["backend_name", "build_store", "index_goal", "search"]
