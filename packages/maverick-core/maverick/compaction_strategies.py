"""Opt-in compaction strategy selection (roadmap: compaction v3/v5/v7/v8).

The always-on path is :func:`maverick.compaction.compact_messages`. This
module layers the roadmap strategies on top of it, selected the same way
``context_compactor`` selects its behavior: an env var override, then the
``[context]`` config section, fail-open to the default.

    [context]
    compaction_strategy = "learned"     # v3: LLM summarizer + outcome ledger
    # or "multimodal"                   # v5: media blocks -> compact text stubs
    # or "streaming"                    # v7: incremental running summary
    # or "graph"                        # v8: entity-relation graph digest

Env override: ``MAVERICK_COMPACTION_STRATEGY``. Unset / unrecognised values
mean "no strategy" and :func:`compact_with_strategy` returns exactly what
``compact_messages`` returns — byte-identical default behavior. A strategy
that raises falls back to that same default (fail-open: compaction is an
optimization, never a correctness dependency).
"""
from __future__ import annotations

import logging
import os

from .compaction import KEEP_RECENT_TURNS, MAX_TOOL_OUTPUT_BYTES, compact_messages

log = logging.getLogger(__name__)

STRATEGIES = ("learned", "multimodal", "streaming", "graph")


def configured_strategy() -> str:
    """The configured strategy name, or ``""`` for the default path.

    ``MAVERICK_COMPACTION_STRATEGY`` beats ``[context] compaction_strategy``;
    anything not in :data:`STRATEGIES` (including typos) selects the default
    so a bad config value can never change compaction behavior.
    """
    env = (os.environ.get("MAVERICK_COMPACTION_STRATEGY") or "").strip().lower()
    if env in STRATEGIES:
        return env
    try:
        from .config import load_config
        raw = load_config().get("context", {}).get("compaction_strategy", "")
    except Exception:  # pragma: no cover -- config never blocks a run
        return ""
    name = str(raw or "").strip().lower()
    return name if name in STRATEGIES else ""


def compact_with_strategy(
    messages: list[dict],
    *,
    llm=None,
    conversation_id: str | None = None,
    keep_recent: int = KEEP_RECENT_TURNS,
    max_tool_bytes: int = MAX_TOOL_OUTPUT_BYTES,
    strategy: str | None = None,
    budget=None,
    scope: str | None = None,
) -> list[dict]:
    """Compact ``messages`` with the configured (or given) strategy.

    With no strategy configured this is exactly ``compact_messages(...)``.
    ``llm`` is the injected seam used by the learned / multimodal / streaming /
    graph strategies when present; every strategy degrades deterministically
    without it. ``conversation_id`` keys the streaming strategy's persisted
    cursor. Any strategy error falls back to the default path.
    """
    name = configured_strategy() if strategy is None else strategy
    if name not in STRATEGIES:
        return compact_messages(
            messages, keep_recent=keep_recent, max_tool_bytes=max_tool_bytes,
        )
    try:
        if name == "learned":
            from .compaction_learned import LearnedSummarizer
            return LearnedSummarizer(llm=llm, budget=budget, scope=scope).compact(
                messages, keep_recent=keep_recent)
        if name == "multimodal":
            from .compaction_multimodal import compact_media
            # Stub heavy media blocks, then apply the standard shrink pass.
            return compact_messages(
                compact_media(
                    messages, keep_recent=keep_recent, llm=llm, budget=budget),
                keep_recent=keep_recent, max_tool_bytes=max_tool_bytes,
            )
        if name == "streaming":
            from .compaction_streaming import compact_streaming
            return compact_streaming(
                messages, conversation_id=conversation_id,
                keep_recent=keep_recent, llm=llm, budget=budget,
            )
        from .compaction_graph import compact_graph
        return compact_graph(
            messages, keep_recent=keep_recent, llm=llm, budget=budget)
    except Exception as e:
        log.warning("compaction strategy %r failed (%s); using default path", name, e)
        return compact_messages(
            messages, keep_recent=keep_recent, max_tool_bytes=max_tool_bytes,
        )


__all__ = ["STRATEGIES", "configured_strategy", "compact_with_strategy"]
