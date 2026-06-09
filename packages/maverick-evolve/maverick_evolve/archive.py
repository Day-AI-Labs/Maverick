"""Stage 2: a diverse archive of high-performing agent configs.

Naive self-improvement converges to a local optimum and stalls (the "plateau
problem"). The published fix (Darwin Gödel Machine, quality-diversity methods)
is to keep an *archive* of diverse high performers and branch from across it,
not just from the single best. This is that archive, restricted to **config**
candidates (dicts) -- no code, so it's safe to keep and sample.
"""
from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, field


def _config_id(config: dict) -> str:
    blob = json.dumps(config, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


@dataclass
class Candidate:
    config: dict
    score: float = 0.0
    id: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = _config_id(self.config)


@dataclass
class Archive:
    """Bounded, score-ranked, diversity-aware archive of config candidates.

    ``capacity`` caps the archive; when full, eviction keeps the best performers
    AND a spread of diverse ones, so the population doesn't collapse onto one
    lineage (which is what causes plateaus).
    """
    capacity: int = 50
    candidates: list[Candidate] = field(default_factory=list)

    def add(self, candidate: Candidate) -> Candidate:
        """Insert (or update if a better score for the same config arrives)."""
        for existing in self.candidates:
            if existing.id == candidate.id:
                if candidate.score > existing.score:
                    existing.score = candidate.score
                return existing
        self.candidates.append(candidate)
        self._evict_if_needed()
        return candidate

    def best(self) -> Candidate | None:
        return max(self.candidates, key=lambda c: c.score) if self.candidates else None

    def sample(self, rng: random.Random | None = None) -> Candidate | None:
        """Sample a parent weighted by score (softmax-ish), so exploration
        favors good lineages without ignoring the diverse tail."""
        if not self.candidates:
            return None
        rng = rng or random
        lo = min(c.score for c in self.candidates)
        weights = [(c.score - lo) + 1e-3 for c in self.candidates]  # keep all reachable
        return rng.choices(self.candidates, weights=weights, k=1)[0]

    def diverse(self, k: int) -> list[Candidate]:
        """Return the best plus the most *config-distant* others (greedy QD).

        Picks the top scorer first, then repeatedly adds the candidate maximizing
        minimum distance to the already-chosen set -- a spread of high-performing
        but distinct configs to branch from.
        """
        if not self.candidates or k <= 0:
            return []
        chosen = [self.best()]
        pool = [c for c in self.candidates if c.id != chosen[0].id]
        while pool and len(chosen) < k:
            nxt = max(pool, key=lambda c: min(self.config_distance(c.config, s.config) for s in chosen))
            chosen.append(nxt)
            pool.remove(nxt)
        return chosen

    def _evict_if_needed(self) -> None:
        if len(self.candidates) <= self.capacity:
            return
        # Keep a diverse high-performing subset; drop the rest.
        keep = self.diverse(self.capacity)
        keep_ids = {c.id for c in keep}
        self.candidates = [c for c in self.candidates if c.id in keep_ids]

    @staticmethod
    def config_distance(a: dict, b: dict) -> float:
        """Normalized distance: fraction of keys whose values differ."""
        keys = set(a) | set(b)
        if not keys:
            return 0.0
        differing = sum(1 for k in keys if a.get(k) != b.get(k))
        return differing / len(keys)


__all__ = ["Candidate", "Archive"]
