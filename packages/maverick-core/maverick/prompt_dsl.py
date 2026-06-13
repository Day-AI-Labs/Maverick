"""Cache-aware prompt assembly DSL (roadmap: 2028 H1 performance).

Prompt caching (Anthropic ephemeral cache_control, OpenAI automatic prefix
caching) only pays off when the **stable** parts of a prompt sit *before* the
**volatile** parts and stay byte-identical across calls — a single volatile
token early in the prompt busts the cache for everything after it. Hand-built
prompt strings make that easy to get wrong (a timestamp in the system block, a
per-request id spliced into the middle).

This is a tiny builder that makes cache structure explicit and gets the
ordering right by construction:

* ``PromptBuilder`` collects **segments**, each tagged ``STABLE`` (cacheable —
  system role, tool catalog, few-shot exemplars) or ``VOLATILE`` (per-request —
  the user's turn, a timestamp, a nonce).
* ``assemble()`` emits the segments **stable-first, in stable insertion order**,
  then the volatile tail, and marks the **cache breakpoint** at the end of the
  stable prefix — so a provider adapter knows exactly where to put
  ``cache_control``. Stable order is preserved (cache keys on exact prefix
  bytes), volatile order is preserved after it.
* ``cache_fingerprint()`` hashes only the stable prefix, so a caller can tell
  whether two assemblies share a cacheable prefix (and warn when a "stable"
  segment is accidentally varying).

Pure and deterministic; no provider import. A provider adapter consumes
``AssembledPrompt`` (it already owns the cache_control wire format).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum


class Stability(Enum):
    STABLE = "stable"        # cacheable: identical across requests
    VOLATILE = "volatile"    # per-request: never cache before it


@dataclass(frozen=True)
class Segment:
    text: str
    stability: Stability
    role: str = "system"     # advisory grouping (system / tool / user / ...)
    name: str = ""


@dataclass(frozen=True)
class AssembledPrompt:
    """The cache-ordered result.

    ``segments`` are stable-first then volatile; ``breakpoint_index`` is the
    index of the LAST stable segment (``-1`` when there is no stable prefix),
    i.e. a provider sets ``cache_control`` on ``segments[breakpoint_index]``.
    ``stable_text`` / ``volatile_text`` are the joined halves for convenience.
    """

    segments: list[Segment]
    breakpoint_index: int
    stable_text: str
    volatile_text: str

    @property
    def has_cacheable_prefix(self) -> bool:
        return self.breakpoint_index >= 0


class PromptBuilder:
    """Collect tagged segments; assemble cache-optimally."""

    def __init__(self, *, joiner: str = "\n\n"):
        self._segments: list[Segment] = []
        self._joiner = joiner

    def stable(self, text: str, *, role: str = "system", name: str = "") -> PromptBuilder:
        return self.add(text, Stability.STABLE, role=role, name=name)

    def volatile(self, text: str, *, role: str = "user", name: str = "") -> PromptBuilder:
        return self.add(text, Stability.VOLATILE, role=role, name=name)

    def add(self, text: str, stability: Stability, *, role: str = "system",
            name: str = "") -> PromptBuilder:
        if text:
            self._segments.append(Segment(text=text, stability=stability,
                                          role=role, name=name))
        return self

    def assemble(self) -> AssembledPrompt:
        """Order stable-first (insertion order preserved within each half) and
        mark the cache breakpoint at the end of the stable prefix."""
        stable = [s for s in self._segments if s.stability is Stability.STABLE]
        volatile = [s for s in self._segments if s.stability is Stability.VOLATILE]
        ordered = stable + volatile
        breakpoint_index = len(stable) - 1  # -1 when no stable segment
        return AssembledPrompt(
            segments=ordered,
            breakpoint_index=breakpoint_index,
            stable_text=self._joiner.join(s.text for s in stable),
            volatile_text=self._joiner.join(s.text for s in volatile),
        )

    def cache_fingerprint(self) -> str:
        """SHA-256 (hex, 16) of the stable prefix only — equal iff two builders
        share a cacheable prefix."""
        stable_text = self._joiner.join(
            s.text for s in self._segments if s.stability is Stability.STABLE)
        return hashlib.sha256(stable_text.encode("utf-8")).hexdigest()[:16]


def lint_segments(segments: list[Segment]) -> list[str]:
    """Flag cache anti-patterns in a segment list (problems; ``[]`` == OK).

    * a STABLE segment that contains an obvious per-request token (a long digit
      run / 'timestamp'/'nonce' marker) — it will silently bust the cache;
    * a VOLATILE segment placed (by a caller that bypassed ``assemble``) before
      a STABLE one — ordering that defeats caching.
    """
    import re
    problems: list[str] = []
    seen_volatile = False
    _SUSPECT = re.compile(r"\b(timestamp|nonce|request[_-]?id|\d{10,})\b", re.IGNORECASE)
    for i, s in enumerate(segments):
        if s.stability is Stability.VOLATILE:
            seen_volatile = True
        elif seen_volatile:
            problems.append(
                f"segment {i} ({s.name or s.role!r}) is STABLE but follows a "
                "VOLATILE one — assemble() reorders, but a hand-built prompt "
                "here would not cache")
        if s.stability is Stability.STABLE and _SUSPECT.search(s.text):
            problems.append(
                f"segment {i} ({s.name or s.role!r}) is tagged STABLE but looks "
                "per-request (timestamp/nonce/long-id) — it will bust the cache")
    return problems


__all__ = ["Stability", "Segment", "AssembledPrompt", "PromptBuilder",
           "lint_segments"]
