"""Proposer disagreement signals → adaptive test-time compute.

Karpathy SOTA-review item: ``max_depth=3, max_fanout=8`` static is
"the single most embarrassing line in the repo". Replace with:

    fanout = clip(1, 32, ceil(alpha * entropy(proposer_distribution)))
    depth  = early_stop_on(verifier_confidence > tau OR
                           delta_reward < epsilon for 2 steps)

This module gives the spawn machinery two helpers:

* ``adaptive_fanout(answers, requested, *, alpha=...)`` returns the
  number of sibling proposers to actually run, scaled by the
  disagreement entropy across a small "preview" sampling.
* ``answers_disagree(answers, threshold=...)`` flips True when the
  proposals don't cluster -- the orchestrator should pay more compute
  here.

Entropy estimation is intentionally cheap: we compute a normalized
hash-cluster entropy over the first ~256 chars of each answer. Real
production would use an embedding model; that's a v0.3 follow-up.
"""
from __future__ import annotations

import math
import os
import re
from collections import Counter

# Tunables (env-driven).
ALPHA = float(os.environ.get("MAVERICK_FANOUT_ALPHA", "4.0"))
FANOUT_MIN = int(os.environ.get("MAVERICK_FANOUT_MIN", "1"))
FANOUT_MAX = int(os.environ.get("MAVERICK_FANOUT_MAX", "32"))
DISAGREEMENT_THRESHOLD = float(os.environ.get("MAVERICK_DISAGREEMENT_THRESHOLD", "0.5"))


_NORM_RE = re.compile(r"\s+")


def _normalize(text: str, prefix_len: int = 256) -> str:
    """Strip whitespace + truncate so trivial formatting differences
    don't read as 'disagreement'."""
    return _NORM_RE.sub(" ", text.strip())[:prefix_len].lower()


def answer_entropy(answers: list[str]) -> float:
    """Normalized Shannon entropy across answer clusters in [0, 1].

    0 = all answers identical; 1 = every answer unique.
    """
    if len(answers) <= 1:
        return 0.0
    buckets = Counter(_normalize(a) for a in answers)
    n = sum(buckets.values())
    if n == 0:
        return 0.0
    # H = -sum(p log p)
    h = -sum((c / n) * math.log(c / n) for c in buckets.values())
    # Normalize by max entropy log(n) (when all unique).
    h_max = math.log(n)
    return h / h_max if h_max > 0 else 0.0


def adaptive_fanout(
    answers: list[str],
    requested: int,
    *,
    alpha: float = ALPHA,
    minimum: int = FANOUT_MIN,
    maximum: int = FANOUT_MAX,
) -> int:
    """Compute the actual fan-out to run.

    With no prior samples (cold start), runs at least 2 proposers so
    we have a disagreement signal next time. With prior samples, scale
    fanout up when entropy is high, down when answers agree.

    `requested` is the LLM-asked fan-out; we may run more or fewer.
    """
    if not answers:
        # Cold start: at least 2, capped at the caller's request.
        return max(minimum, min(2, max(requested, 2), maximum))
    ent = answer_entropy(answers)
    target = math.ceil(alpha * ent * max(requested, 1))
    # Ensure we never run fewer than the proposer asked for IF it
    # asked for a single answer (the simple case). When the proposer
    # asked for many, we trust entropy to scale us.
    if requested <= 1:
        return max(minimum, min(maximum, max(target, 1)))
    return max(minimum, min(maximum, target))


def answers_disagree(
    answers: list[str],
    *,
    threshold: float = DISAGREEMENT_THRESHOLD,
) -> bool:
    """Convenience predicate: do the answers disagree enough to merit
    spending more compute? Used as the trajectory-donation selection
    signal too (the cases where the swarm learned something the solo
    agent couldn't are the cases worth feeding back)."""
    return answer_entropy(answers) >= threshold
