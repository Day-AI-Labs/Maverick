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
    """Backend-safe active-tenant namespace, or None for single-tenant use.

    The namespace is intentionally collision-resistant: a readable sanitized
    prefix is only a hint, and a SHA-256 suffix covers the raw tenant id. This
    keeps external vector-store collection names tenant-isolated even when
    tenant ids differ only by punctuation or after truncation.
    """
    try:
        from .paths import current_tenant
        t = current_tenant()
    except Exception:  # pragma: no cover -- tenancy never blocks a run
        return None
    if not t:
        return None
    import hashlib
    import re

    raw = str(t)
    safe = re.sub(r"[^0-9A-Za-z]", "_", raw).strip("_") or "tenant"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"{safe[:32]}_{digest}"


def _sealed_recall() -> bool:
    """True when the vector store must hold **sealed** documents -- i.e. at-rest
    encryption is on.

    The backends embed the document they store, so a sealed document can't be
    embedded by the backend. In sealed mode we therefore embed the *plaintext*
    client-side (the local all-MiniLM model, same one pgvector/skills use) and
    hand the backend a precomputed vector + the sealed document, and we use a
    separate collection (``_s`` suffix) so sealed vectors never mix with legacy
    plaintext-embedded ones. Off -> behaviour is byte-for-byte unchanged.
    """
    try:
        from .crypto_at_rest import at_rest_enabled
        return bool(at_rest_enabled())
    except Exception:  # pragma: no cover -- config never blocks a run
        return False


def _embed_texts(texts: list[str]) -> list[list[float]] | None:
    """Local embedding via the shared skill embedder (fastembed all-MiniLM), or
    None when no local embedder is available."""
    from .skill import embeddings as skill_embeddings
    return skill_embeddings.embed(texts)


_sealed_warned: set[str] = set()


def _warn_sealed_backend_unsupported(backend: str) -> None:
    """Warn once per backend that sealed semantic recall isn't wired for it."""
    if backend in _sealed_warned:
        return
    _sealed_warned.add(backend)
    log.warning(
        "semantic recall is disabled for the %r vector backend under at-rest "
        "encryption (sealing its stored documents is not implemented yet); "
        "falling back to lexical recall over the sealed world DB. Use the "
        "'chroma' or 'pgvector' backend for sealed semantic recall.", backend,
    )


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

    Under at-rest encryption (:func:`_sealed_recall`) the collection gets a
    ``_s`` suffix so the sealed, client-embedded vectors live apart from any
    legacy plaintext-embedded data.
    """
    backend = backend or backend_name()
    if backend is None:
        return None
    sealed = _sealed_recall()
    # Sealing the stored document requires a client-side precomputed embedding
    # (the backend can't embed sealed text). That path is implemented for the
    # backends whose vector space matches the local embedder -- chroma and
    # pgvector (both all-MiniLM-L6-v2). For qdrant/weaviate it is not wired yet,
    # so rather than leak plaintext to them we disable the semantic path under
    # at-rest and fall back to lexical recall over the sealed world DB.
    if sealed and backend in ("qdrant", "weaviate"):
        _warn_sealed_backend_unsupported(backend)
        return None
    ns = _tenant_ns()
    sfx = "_s" if sealed else ""
    try:
        if backend == "chroma":
            from .vector_store import ChromaStore
            return ChromaStore(collection=(f"t_{ns}__goals" if ns else "goals") + sfx)
        if backend == "qdrant":
            from .vector_store import QdrantStore
            return QdrantStore(collection=(f"t_{ns}__goals" if ns else "goals") + sfx)
        if backend == "weaviate":
            from .vector_store import WeaviateStore
            # Weaviate class names must start with an uppercase letter.
            return WeaviateStore(collection=(f"T_{ns}__Goals" if ns else "Goals") + sfx)
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

            return PgVectorStore(collection="goals" + sfx, embedder=_embed)
    except Exception as e:  # pragma: no cover -- optional dep / backend down
        log.debug("semantic recall backend %s unavailable: %s", backend, e)
    return None


def _goal_text(goal) -> str:
    return f"{getattr(goal, 'title', '') or ''}\n\n{getattr(goal, 'description', '') or ''}".strip()


def index_goal(goal, *, store: Any | None = None) -> bool:
    """Upsert one goal into the vector store. Returns True if indexed.

    No-op (returns False) when no backend is configured/available. Metadata is
    limited to non-sensitive routing keys (``goal_id``/``status``); the sensitive
    ``title``/``result`` are NOT duplicated here -- callers hydrate them from the
    sealed world DB by ``goal_id``.

    The document is the goal's title+description. Under at-rest encryption it is
    **sealed** before storage (embedded client-side from the plaintext first, so
    similarity search is preserved); with at-rest off it is stored plaintext as
    before. If at-rest is on but no local embedder is available, indexing is
    skipped (returns False) rather than shipping plaintext to the store -- the
    caller falls back to lexical recall over the sealed world DB. Never raises.
    """
    store = store if store is not None else build_store()
    if store is None:
        return False
    text = _goal_text(goal)
    if not text:
        return False
    doc_id = f"goal:{getattr(goal, 'id', '')}"
    # Routing only -- no sensitive content (see search() callers).
    metas = [{
        "goal_id": getattr(goal, "id", None),
        "status": getattr(goal, "status", None),
    }]
    try:
        try:
            store.delete([doc_id])
        except Exception:  # pragma: no cover -- delete of absent id may raise
            pass
        if _sealed_recall():
            vecs = _embed_texts([text])
            if vecs is None:
                # at-rest on, no local embedder: don't leak plaintext to the
                # store and don't ship a sealed doc with a useless backend-side
                # embedding -- skip so the caller falls back to lexical recall.
                return False
            from .crypto_at_rest import seal_to_str
            store.add([seal_to_str(text)], ids=[doc_id], metadatas=metas,
                      embeddings=vecs)
        else:
            store.add([text], ids=[doc_id], metadatas=metas)
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
        # Over-fetch so we can drop the current goal then trim to k. Under at-rest
        # the stored documents are sealed, so the query is embedded client-side
        # (same model the index used) and searched by vector; otherwise the
        # backend embeds the query text as before.
        if _sealed_recall():
            qv = _embed_texts([query])
            if qv is None:
                return None  # no local embedder -> fall back to lexical recall
            hits = store.query(top_k=k + 1, embedding=qv[0])
        else:
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
