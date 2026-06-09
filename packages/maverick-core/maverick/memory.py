"""Salience-weighted agent memory with provenance — anti-forgetting recall.

SOTA (agentic memory taxonomy, arXiv 2602.19320; Titans/nested-memory): the
bottleneck for long-horizon agents is *which* memories survive and whether they
carry provenance. Maverick's world model stores facts/episodes but recall is
flat. This adds a working-memory layer that (1) tags every item with provenance
(source agent, timestamp, confidence), (2) ranks recall by relevance × salience
so important items resist eviction, and (3) decays salience over time and on
eviction so stale items fade instead of being forgotten abruptly.

Pure in-memory + dependency-free, so it's trivially testable and can back a
``SwarmContext.memory`` slot. Off by default (a context only gets one when the
operator wires it); this module is the primitive, not a global.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(s: str) -> set[str]:
    return set(_TOKEN_RE.findall((s or "").lower()))


@dataclass
class MemoryItem:
    content: str
    source: str = ""           # provenance: which agent/tool wrote it
    confidence: float = 1.0    # provenance: how trusted the writer was
    ts: float = field(default_factory=time.time)
    salience: float = 1.0      # decays over time / on eviction pressure
    hits: int = 0              # times recalled (reinforces salience)

    def age_seconds(self, now: float | None = None) -> float:
        return (time.time() if now is None else now) - self.ts


@dataclass
class MemoryStore:
    """A bounded, salience-ranked memory with provenance.

    ``capacity`` caps the store; when full, the lowest-salience item is evicted
    (not the oldest — an important old fact outlives a trivial recent one).
    ``half_life`` (seconds) controls time decay applied at recall time.
    """
    capacity: int = 200
    half_life: float = 3600.0
    items: list[MemoryItem] = field(default_factory=list)

    def add(
        self, content: str, *, source: str = "", confidence: float = 1.0,
        salience: float = 1.0,
    ) -> MemoryItem | None:
        if not content or not content.strip():
            return None
        item = MemoryItem(
            content=content.strip(), source=source,
            confidence=max(0.0, min(1.0, confidence)), salience=max(0.0, salience),
        )
        self.items.append(item)
        self._evict_if_needed()
        return item

    def _effective_salience(self, item: MemoryItem, now: float) -> float:
        """Salience decayed by age (half-life) and reinforced by hits + writer trust."""
        if self.half_life <= 0:
            decay = 1.0
        else:
            decay = 0.5 ** (item.age_seconds(now) / self.half_life)
        return item.salience * decay * (1.0 + 0.1 * item.hits) * (0.5 + 0.5 * item.confidence)

    def _evict_if_needed(self) -> None:
        if len(self.items) <= self.capacity:
            return
        now = time.time()
        # Drop the lowest effective-salience item(s) until under capacity.
        self.items.sort(key=lambda it: self._effective_salience(it, now))
        overflow = len(self.items) - self.capacity
        del self.items[:overflow]

    def recall(self, query: str, *, k: int = 5, now: float | None = None) -> list[MemoryItem]:
        """Return up to ``k`` items ranked by relevance × effective salience.

        Recalled items get a salience/hit bump so frequently-useful memories
        resist eviction (the anti-forgetting property).
        """
        now = time.time() if now is None else now
        want = _tokens(query)
        scored: list[tuple[float, MemoryItem]] = []
        for it in self.items:
            rel = self._relevance(want, _tokens(it.content))
            if rel <= 0:
                continue
            scored.append((rel * self._effective_salience(it, now), it))
        scored.sort(key=lambda x: -x[0])
        out = [it for _, it in scored[:max(1, k)]]
        for it in out:
            it.hits += 1
            it.salience = min(10.0, it.salience + 0.25)
        return out

    @staticmethod
    def _relevance(a: set[str], b: set[str]) -> float:
        if not a or not b:
            return 0.0
        return len(a & b) / len(a | b)


__all__ = ["MemoryItem", "MemoryStore"]
