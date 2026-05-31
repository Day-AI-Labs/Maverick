"""Long-context compactor.

When a multi-turn message history exceeds a token budget, drop or
collapse the least-relevant older turns and keep the freshest +
most-similar-to-current turns. Cheap (no model call) and reversible
(the dropped turns are returned alongside so callers can persist
them to the world model for audit).

Strategy:
  1. Always preserve the system context AND the last K user turns
     (the active conversation tail).
  2. From the remaining (older) turns, score each by Jaccard token
     overlap with the most recent user message — the simplest
     decent relevance proxy that has zero deps.
  3. Keep top-N relevant older turns up to the token budget; drop
     the rest. Insert a one-line ``[N turns compacted]`` marker so
     the model sees a continuity hint.

We approximate token count as ``len(text) // 4`` (well-correlated
with tiktoken for typical prose; off by ~20% for code) so we don't
have to drag tiktoken or sentencepiece into the kernel.

Embedding-based ranking (cosine via :mod:`fastembed`) is opt-in and
slower; turn it on with ``use_embeddings=True`` when the embeddings
extra is installed.
"""
from __future__ import annotations

import logging
import os
import re
from collections.abc import Iterable
from dataclasses import dataclass

log = logging.getLogger(__name__)

_TRUE = {"1", "true", "yes", "on"}


def enabled() -> bool:
    """Whether conversation-history compaction is active.

    Off by default — the orchestrator includes the last 10 turns verbatim.
    Turn it on with ``MAVERICK_COMPACT_HISTORY=1`` or ``[context] compact =
    true`` to instead include a larger window compacted to a token budget,
    keeping the most relevant older turns (better long-conversation recall).
    """
    if (os.environ.get("MAVERICK_COMPACT_HISTORY") or "").strip().lower() in _TRUE:
        return True
    try:
        from .config import load_config
        return bool(load_config().get("context", {}).get("compact", False))
    except Exception:  # pragma: no cover -- config never blocks a run
        return False


def _positive_int_config(key: str, env: str, default: int) -> int:
    raw: object = os.environ.get(env)
    if raw is None:
        try:
            from .config import load_config
            raw = load_config().get("context", {}).get(key, default)
        except Exception:  # pragma: no cover
            raw = default
    try:
        n = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return n if n >= 1 else default


def target_tokens(default: int = 1500) -> int:
    """Token budget to compact history toward (``[context] history_tokens``)."""
    return _positive_int_config("history_tokens", "MAVERICK_HISTORY_TOKENS", default)


def window(default: int = 50) -> int:
    """How many recent turns to consider before compaction
    (``[context] history_window``)."""
    return _positive_int_config("history_window", "MAVERICK_HISTORY_WINDOW", default)


_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+")


def _approx_tokens(text: str) -> int:
    if not text:
        return 0
    # 4 chars/token is the rule-of-thumb baseline; round up.
    return (len(text) + 3) // 4


def _message_text(msg: dict) -> str:
    """Flatten an Anthropic-style message to a single string."""
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                t = block.get("text") or block.get("content") or ""
                if isinstance(t, str):
                    parts.append(t)
                elif isinstance(t, list):
                    for inner in t:
                        if isinstance(inner, dict):
                            parts.append(str(inner.get("text") or ""))
            elif isinstance(block, str):
                parts.append(block)
        return " ".join(parts)
    return ""


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_PATTERN.findall(text)}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    if union == 0:
        return 0.0
    return inter / union


@dataclass
class CompactResult:
    messages: list[dict]
    dropped: list[dict]
    tokens_before: int
    tokens_after: int
    kept_marker: str | None


def estimate_tokens(messages: Iterable[dict]) -> int:
    return sum(_approx_tokens(_message_text(m)) for m in messages)


def compact(
    messages: list[dict],
    *,
    target_tokens: int,
    preserve_tail: int = 4,
    use_embeddings: bool = False,
    embed_model: str | None = None,
) -> CompactResult:
    """Return a compacted message list under ``target_tokens``.

    Args:
        messages: full message history (in order; oldest first).
        target_tokens: approximate token cap to compact toward.
        preserve_tail: number of most-recent messages to keep
            verbatim (the active conversation).
        use_embeddings: if True, rank older turns by cosine to the
            most recent user message via :mod:`fastembed`. Requires
            the [embeddings] extra. Falls back to Jaccard on
            ImportError.
        embed_model: override the default embedding model.

    The returned :class:`CompactResult` carries the compacted list,
    the dropped messages (for audit), pre- and post- token counts,
    and a continuity marker that was inserted (if any).
    """
    if not messages:
        return CompactResult(
            messages=[], dropped=[], tokens_before=0,
            tokens_after=0, kept_marker=None,
        )
    before = estimate_tokens(messages)
    if before <= target_tokens:
        return CompactResult(
            messages=list(messages), dropped=[],
            tokens_before=before, tokens_after=before, kept_marker=None,
        )

    tail = messages[-preserve_tail:] if preserve_tail > 0 else []
    head = messages[: -preserve_tail] if preserve_tail > 0 else list(messages)
    if not head:
        return CompactResult(
            messages=list(messages), dropped=[],
            tokens_before=before, tokens_after=before, kept_marker=None,
        )

    most_recent_user = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            most_recent_user = _message_text(m)
            break

    scored: list[tuple[float, int, dict]] = []
    if use_embeddings:
        try:
            scored = _score_by_embedding(head, most_recent_user, embed_model)
        except ImportError:
            scored = _score_by_jaccard(head, most_recent_user)
    else:
        scored = _score_by_jaccard(head, most_recent_user)

    scored.sort(reverse=True)
    tail_tokens = estimate_tokens(tail)
    budget_remaining = max(target_tokens - tail_tokens, 0)

    kept_by_idx: dict[int, dict] = {}
    used = 0
    for score, idx, msg in scored:
        cost = _approx_tokens(_message_text(msg))
        if used + cost > budget_remaining:
            continue
        kept_by_idx[idx] = msg
        used += cost

    dropped = [m for i, m in enumerate(head) if i not in kept_by_idx]
    if not dropped:
        return CompactResult(
            messages=list(messages), dropped=[],
            tokens_before=before, tokens_after=before, kept_marker=None,
        )

    kept_head = [kept_by_idx[i] for i in sorted(kept_by_idx)]
    marker_msg = {
        "role": "user",
        "content": f"[{len(dropped)} earlier turn(s) compacted to save context]",
    }
    new_messages = kept_head + [marker_msg] + list(tail)
    return CompactResult(
        messages=new_messages,
        dropped=dropped,
        tokens_before=before,
        tokens_after=estimate_tokens(new_messages),
        kept_marker=marker_msg["content"],
    )


def _score_by_jaccard(head: list[dict], query: str) -> list[tuple[float, int, dict]]:
    q = _tokens(query)
    out: list[tuple[float, int, dict]] = []
    for i, m in enumerate(head):
        out.append((_jaccard(_tokens(_message_text(m)), q), i, m))
    return out


def _score_by_embedding(
    head: list[dict], query: str, model_name: str | None,
) -> list[tuple[float, int, dict]]:
    """Embedding-based ranking. Raises ImportError if fastembed missing."""
    from fastembed import TextEmbedding
    name = model_name or "BAAI/bge-small-en-v1.5"
    m = TextEmbedding(model_name=name)
    qv = next(iter(m.embed([query])), None)
    if qv is None:
        return _score_by_jaccard(head, query)

    def _cos(a, b) -> float:
        import math
        ax = list(a)
        bx = list(b)
        if not ax or not bx or len(ax) != len(bx):
            return 0.0
        dot = sum(x * y for x, y in zip(ax, bx))
        na = math.sqrt(sum(x * x for x in ax))
        nb = math.sqrt(sum(y * y for y in bx))
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)

    texts = [_message_text(msg) for msg in head]
    out: list[tuple[float, int, dict]] = []
    for i, (vec, msg) in enumerate(zip(m.embed(texts), head)):
        out.append((_cos(qv, vec), i, msg))
    return out


__all__ = ["compact", "CompactResult", "estimate_tokens"]
