"""Compaction plug-in API (roadmap: 2028 H2 performance — "compaction v9").

Context compaction is currently one built-in algorithm (:func:`maverick.
compaction.compact_messages`). This is the extension point that lets a
deployment or plugin register its **own** compaction strategy — a graph-
structured one, a domain-specific summarizer, a learned model — and select it
by name, without forking the kernel.

A strategy is any object with a ``name`` and a ``compact(messages, **kw) ->
list[dict]``. The built-in heuristic registers itself as ``"heuristic"`` (the
default), so unchanged deployments behave exactly as before; ``compact_with``
dispatches to the configured strategy (``[context] compaction_strategy`` / env
``MAVERICK_COMPACTION_STRATEGY``) and **fails safe** to the built-in when the
named strategy is unknown, so a typo degrades to working compaction rather than
to none.
"""
from __future__ import annotations

import os
from typing import Protocol, runtime_checkable


@runtime_checkable
class CompactionStrategy(Protocol):
    name: str

    def compact(self, messages: list[dict], **kwargs) -> list[dict]: ...


class _HeuristicStrategy:
    """The shipping built-in: tool-result digest + recent-turn passthrough."""

    name = "heuristic"

    def compact(self, messages: list[dict], **kwargs) -> list[dict]:
        from .compaction import compact_messages
        allowed = {k: kwargs[k] for k in ("keep_recent", "max_tool_bytes")
                   if k in kwargs}
        return compact_messages(messages, **allowed)


_REGISTRY: dict[str, CompactionStrategy] = {}
_DEFAULT = "heuristic"


def register(strategy: CompactionStrategy, *, replace: bool = False) -> None:
    """Register a compaction strategy under ``strategy.name``."""
    name = getattr(strategy, "name", None)
    if not isinstance(name, str) or not name:
        raise ValueError("strategy must have a non-empty string 'name'")
    if not callable(getattr(strategy, "compact", None)):
        raise ValueError(f"strategy {name!r} must have a callable compact()")
    if name in _REGISTRY and not replace:
        raise ValueError(f"compaction strategy {name!r} already registered")
    _REGISTRY[name] = strategy


def get(name: str) -> CompactionStrategy | None:
    return _REGISTRY.get(name)


def available() -> list[str]:
    return sorted(_REGISTRY)


def _configured_name() -> str:
    env = os.environ.get("MAVERICK_COMPACTION_STRATEGY", "").strip()
    if env:
        return env
    try:
        from .config import load_config
        name = str(((load_config() or {}).get("context") or {})
                   .get("compaction_strategy", "")).strip()
        return name or _DEFAULT
    except Exception:  # pragma: no cover -- config never blocks compaction
        return _DEFAULT


def compact_with(messages: list[dict], *, strategy: str | None = None,
                 **kwargs) -> list[dict]:
    """Compact ``messages`` with the named/configured strategy.

    Fails safe to the built-in ``heuristic`` when the requested strategy is not
    registered — a misconfiguration degrades to working compaction, never none.
    """
    name = strategy or _configured_name()
    strat = _REGISTRY.get(name) or _REGISTRY[_DEFAULT]
    return strat.compact(messages, **kwargs)


class _StrategyAdapter:
    """Adapt one of the v3/v5/v7/v8 strategies (compaction_strategies) to the
    plug-in ``CompactionStrategy`` protocol, so both selection paths share one
    registry. The heavy modules import lazily on first compact()."""

    def __init__(self, name: str):
        self.name = name

    def compact(self, messages: list[dict], **kwargs) -> list[dict]:
        from .compaction_strategies import compact_with_strategy
        allowed = {k: kwargs[k] for k in
                   ("llm", "conversation_id", "keep_recent", "max_tool_bytes",
                    "budget", "scope")
                   if k in kwargs}
        return compact_with_strategy(messages, strategy=self.name, **allowed)


# Register the built-in as the default at import, plus the named strategies
# from compaction_strategies so `[context] compaction_strategy` selects any of
# them through this one dispatcher (still fail-safe to heuristic on a typo).
register(_HeuristicStrategy())
for _name in ("learned", "multimodal", "streaming", "graph"):
    register(_StrategyAdapter(_name))


__all__ = ["CompactionStrategy", "register", "get", "available", "compact_with"]
