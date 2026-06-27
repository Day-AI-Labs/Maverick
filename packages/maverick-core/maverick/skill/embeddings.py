"""Embedding-based skill retrieval (optional, falls back to lexical).

Uses fastembed (ONNX) when installed; cached embeddings live in
``~/.maverick/skill_embeddings.json`` keyed by name + mtime.

Falls back gracefully to ``skills._relevant_skills_lexical`` when
fastembed isn't installed or any error occurs at retrieval time.
"""
from __future__ import annotations

import json
import logging
import math
import threading
from dataclasses import dataclass

from ..paths import data_dir

log = logging.getLogger(__name__)

CACHE_PATH = data_dir("skill_embeddings.json")
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


def _cache_path():
    """Resolve the cache path at CALL time so it follows the ACTIVE tenant.

    ``CACHE_PATH`` is computed once at import and snapshots whichever tenant was
    active then; in a long-lived multi-tenant process (the dashboard) every
    later load/save would hit that frozen path, so tenant B reads/writes tenant
    A's vector cache -- and since the cache is keyed by skill *name* and learned
    skills are tenant-scoped, a same-named skill could be served another
    tenant's vector. The sibling ``stats._resolve`` already re-reads the tenant
    per call for exactly this reason; mirror it. The module-attr stays the
    fallback so the single-tenant layout and tests monkeypatching ``CACHE_PATH``
    keep working.
    """
    try:
        from ..paths import current_tenant
        if current_tenant():
            return data_dir("skill_embeddings.json")
    except Exception:  # pragma: no cover -- isolation never blocks resolution
        pass
    return CACHE_PATH

_model = None  # lazy singleton
_model_lock = threading.Lock()  # guard the (expensive) lazy ONNX model load


def _have_fastembed() -> bool:
    try:
        import fastembed  # noqa: F401
        return True
    except ImportError:
        return False


def _get_model():
    global _model
    if _model is not None:
        return _model
    # Double-checked lock: without it, concurrent first calls (FastAPI
    # threadpool) each construct a TextEmbedding -- an expensive ONNX model
    # load -- and clobber _model.
    with _model_lock:
        if _model is not None:
            return _model
        try:
            from fastembed import TextEmbedding
        except ImportError:
            return None
        try:
            _model = TextEmbedding(model_name=MODEL_NAME)
            return _model
        except Exception as e:  # pragma: no cover
            log.error("failed to load embedding model: %s", e)
            return None


def embed(texts: list[str]) -> list[list[float]] | None:
    model = _get_model()
    if model is None or not texts:
        return None
    try:
        return [list(map(float, v)) for v in model.embed(texts)]
    except Exception as e:  # pragma: no cover
        log.error("embedding call failed: %s", e)
        return None


@dataclass
class CachedEmbedding:
    name: str
    text: str
    mtime: float
    vector: list[float]


def _load_cache() -> dict[str, CachedEmbedding]:
    path = _cache_path()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    out: dict[str, CachedEmbedding] = {}
    for name, entry in raw.items():
        if not isinstance(entry, dict):
            continue
        if not all(k in entry for k in ("text", "mtime", "vector")):
            continue
        out[name] = CachedEmbedding(
            name=name,
            text=entry["text"],
            mtime=float(entry["mtime"]),
            vector=entry["vector"],
        )
    return out


def _save_cache(cache: dict[str, CachedEmbedding]) -> None:
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = {
        name: {"text": e.text, "mtime": e.mtime, "vector": e.vector}
        for name, e in cache.items()
    }
    # Atomic write (temp + os.replace) so a crash mid-write or a concurrent
    # writer can't leave a truncated/corrupt cache -- the same pattern the
    # sibling skill.stats module uses.
    from ..file_lock import atomic_write_text
    atomic_write_text(path, json.dumps(raw))


def _skill_to_embed_text(skill) -> str:
    triggers = " | ".join(skill.triggers) if skill.triggers else ""
    first_line = (skill.body or "").splitlines()[0] if skill.body else ""
    return f"{skill.name}: {triggers}\n{first_line}".strip()


def build_or_update_cache(skills: list) -> dict[str, CachedEmbedding]:
    cache = _load_cache()
    to_embed: list[tuple[str, str, float]] = []
    for s in skills:
        try:
            mtime = s.path.stat().st_mtime
        except (OSError, AttributeError):
            mtime = 0.0
        cached = cache.get(s.name)
        if cached and cached.mtime >= mtime:
            continue
        to_embed.append((s.name, _skill_to_embed_text(s), mtime))

    if not to_embed:
        return cache

    vectors = embed([t[1] for t in to_embed])
    if vectors is None:
        return cache

    for (name, text, mtime), vec in zip(to_embed, vectors, strict=False):
        cache[name] = CachedEmbedding(name=name, text=text, mtime=mtime, vector=vec)

    valid_names = {s.name for s in skills}
    cache = {k: v for k, v in cache.items() if k in valid_names}

    _save_cache(cache)
    return cache


def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def relevant_skills_embed(
    goal: str, all_skills: list, max_n: int = 3, threshold: float = 0.35,
) -> list | None:
    if not _have_fastembed():
        return None
    if not all_skills:
        return []

    cache = build_or_update_cache(all_skills)
    if not cache:
        return None

    goal_vecs = embed([goal])
    if not goal_vecs:
        return None
    goal_vec = goal_vecs[0]

    by_name = {s.name: s for s in all_skills}
    # Fold each skill's past-run track record into the ranking BEFORE the
    # top-N cut (see skills._decay_weights / skill_stats), so a skill that
    # rides along with failures yields rank. Threshold still gates on raw
    # relevance — decay only re-orders skills that already cleared it, never
    # pulls in an irrelevant one. Neutral 1.0 when stats are unavailable.
    from ..skills import _decay_weights
    weights = _decay_weights(list(by_name))
    scored: list[tuple[float, object]] = []
    for name, entry in cache.items():
        if name not in by_name:
            continue
        score = _cosine(goal_vec, entry.vector)
        if score >= threshold:
            scored.append((score * weights.get(name, 1.0), by_name[name]))
    # Deterministic tie-break by name, like the BM25 path (skill_search.py): a
    # bare score sort leaves equal-scored skills in cache-insertion order, which
    # shifts across cache rebuilds and can flip which skills land inside max_n.
    scored.sort(key=lambda x: (-x[0], x[1].name))
    return [s for _, s in scored[:max_n]]
