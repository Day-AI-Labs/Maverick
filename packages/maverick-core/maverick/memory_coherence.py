"""Fleet Memory Coherence Engine — deterministic adjudication for a shared
belief store written by many agents.

Maverick's ``facts`` table is a shared belief store: native agents *and* external
fleet agents (Agentforce, Copilot, custom runtimes) can assert ``key -> value``
beliefs into it. The base write path (:meth:`maverick.world_model.WorldModel.upsert_fact`)
is **last-writer-wins** (``ON CONFLICT(key) DO UPDATE SET value = excluded.value``):
whoever writes a key *last* wins, even an ``EXTERNAL``/untrusted source overwriting
an operator's ``FIRST_PARTY`` truth. With one agent that is fine; with a *fleet*
it is incoherent — the store converges on whoever wrote last, not on what is true.

This module is the consistency protocol on top. On a conflicting write it does not
stomp the incumbent; it **adjudicates** a winner with a deterministic total order
(no LLM, reproducible, so it cannot be steered by prompt injection):

  1. **trust** — higher :class:`~maverick.memory_guard.TrustTier` wins (an
     EXTERNAL agent can never overwrite a LEARNED/FIRST_PARTY belief);
  2. **corroboration** — at equal trust, the value more independent sources have
     asserted wins (trust-weighted voting);
  3. **reliability** — at equal corroboration, the source with the better track
     record wins (a per-source score the engine *learns* from past adjudications);
  4. **recency** — last-writer-wins survives only as the final tiebreak.

The loser is retained as dissent (auditable), the source's reliability is updated
from the outcome, and one :data:`~maverick.audit.events.EventKind.MEMORY_COHERENCE`
row is written so "who asserted what, and which rule decided" is provable.

OFF by default (``[memory_coherence] enable`` / ``MAVERICK_MEMORY_COHERENCE=1``).
When off, :func:`enabled` is False and the write path is byte-for-byte the legacy
last-writer-wins (kernel rule 1: fail-open, default-open). The pure
:func:`adjudicate` is dependency-free and exhaustively unit-testable; :func:`resolve`
is the stateful wrapper (loads/persists reliability, writes the audit row) and is
fail-open — any internal error degrades to "accept the write" (legacy behavior),
never a crash on the memory write path.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from enum import Enum

from .memory_guard import TrustTier

log = logging.getLogger(__name__)

_TRUE = {"1", "true", "yes", "on"}


class CoherenceState(str, Enum):
    """The coherence state a belief key lands in after an adjudication.

    - ``STABLE`` — one value, or the challenger cleanly agreed/upgraded it.
    - ``CONTESTED`` — a non-trivial belief (>= TOOL trust) was overruled or
      dissented; the loser is retained so the disagreement is inspectable.
    - ``QUARANTINED`` — a low-trust (EXTERNAL) contradiction was rejected and
      never became current (the poisoning-resistant outcome).
    """
    STABLE = "stable"
    CONTESTED = "contested"
    QUARANTINED = "quarantined"


@dataclass(frozen=True)
class Belief:
    """One asserted ``key -> value`` belief and the metadata that decides a tie.

    ``corroborations`` is how many *distinct* sources have asserted this value
    (>=1). ``trust`` is a :class:`~maverick.memory_guard.TrustTier` int.
    """
    value: str
    source: str = ""
    trust: int = int(TrustTier.FIRST_PARTY)
    updated_at: float = 0.0
    corroborations: int = 1


@dataclass(frozen=True)
class Adjudication:
    """The outcome of adjudicating a write.

    - ``accept`` — should the challenger's write proceed? (False = retain the
      incumbent, the caller must not overwrite.)
    - ``final`` — the belief to store as current when ``accept`` (already
      trust-/provenance-merged; e.g. a corroboration keeps the *higher* trust).
    - ``changed`` — did the stored *value* change (vs. a provenance-only refresh)?
    - ``state`` / ``rule`` — coherence state and the clause that decided.
    - ``reliability_deltas`` — ``{source: "won"|"lost"}`` for the caller/engine to
      fold into the per-source track record.
    """
    accept: bool
    final: Belief
    changed: bool
    state: CoherenceState
    rule: str
    reason: str = ""
    loser: Belief | None = None
    reliability_deltas: dict[str, str] = field(default_factory=dict)


# -- config ----------------------------------------------------------------

def enabled() -> bool:
    """Whether the coherence engine governs the fact-write path. OFF by default.

    Turn on with ``MAVERICK_MEMORY_COHERENCE=1`` or ``[memory_coherence] enable
    = true``. When off, the caller keeps legacy last-writer-wins behavior."""
    env = os.environ.get("MAVERICK_MEMORY_COHERENCE")
    if env is not None and env.strip() != "":
        return env.strip().lower() in _TRUE
    try:
        from .config import get_memory_coherence
        return bool(get_memory_coherence()["enable"])
    except Exception:  # pragma: no cover -- config never blocks a write
        return False


# -- the pure decision -----------------------------------------------------

def _score(belief: Belief, reliability: Mapping[str, float]) -> tuple[int, int, float, float]:
    """The deterministic comparison key for a belief (higher wins).

    ``(trust, corroborations, source-reliability, recency)`` — compared
    lexicographically, so trust dominates, then corroboration, then the source's
    track record, then recency as the final tiebreak.
    """
    return (
        int(belief.trust),
        int(belief.corroborations),
        float(reliability.get(belief.source, 0.0)),
        float(belief.updated_at),
    )


def _deciding_rule(a: tuple, b: tuple) -> str:
    """Name the first component that differs between two score tuples."""
    names = ("trust", "corroboration", "reliability", "recency")
    for name, x, y in zip(names, a, b):
        if x != y:
            return name
    return "tie"


def adjudicate(
    incumbent: Belief | None,
    challenger: Belief,
    *,
    reliability: Mapping[str, float] | None = None,
) -> Adjudication:
    """Decide a conflicting write deterministically (pure; no I/O).

    ``incumbent`` is the value currently stored for the key (None = first write).
    Ties always favor the incumbent (stability), so the result is reproducible.
    """
    rel = reliability or {}

    # First write: nothing to contest.
    if incumbent is None:
        return Adjudication(
            accept=True, final=challenger, changed=True,
            state=CoherenceState.STABLE, rule="first-write",
            reason="no incumbent",
            reliability_deltas={challenger.source: "won"} if challenger.source else {},
        )

    # Same value re-asserted: corroboration. Keep the HIGHER trust (a lower-trust
    # source agreeing must never *lower* the stored trust), bump the corroboration
    # count when the source is new, refresh recency. Value is unchanged.
    if incumbent.value == challenger.value:
        new_source_is_distinct = bool(challenger.source) and challenger.source != incumbent.source
        merged = replace(
            incumbent,
            trust=max(incumbent.trust, challenger.trust),
            source=challenger.source if challenger.trust > incumbent.trust else incumbent.source,
            updated_at=max(incumbent.updated_at, challenger.updated_at),
            corroborations=incumbent.corroborations + (1 if new_source_is_distinct else 0),
        )
        return Adjudication(
            accept=True, final=merged, changed=False,
            state=CoherenceState.STABLE, rule="corroborate",
            reason="challenger agreed with the current value",
            reliability_deltas={challenger.source: "won"} if challenger.source else {},
        )

    # Genuine contradiction: score both and let the total order decide.
    inc_score = _score(incumbent, rel)
    chg_score = _score(challenger, rel)
    rule = _deciding_rule(chg_score, inc_score)

    if chg_score > inc_score:
        # Challenger wins. A non-trivial overruled incumbent (>= TOOL) is CONTESTED
        # (retain the dissent); overruling raw EXTERNAL memory is a clean upgrade.
        state = (CoherenceState.CONTESTED
                 if incumbent.trust >= int(TrustTier.TOOL) else CoherenceState.STABLE)
        deltas: dict[str, str] = {}
        if challenger.source:
            deltas[challenger.source] = "won"
        if incumbent.source and incumbent.source != challenger.source:
            deltas[incumbent.source] = "lost"
        return Adjudication(
            accept=True, final=challenger, changed=True, state=state, rule=rule,
            reason=f"challenger outranked incumbent on {rule}",
            loser=incumbent, reliability_deltas=deltas,
        )

    # Incumbent wins (ties favor it). The challenger is rejected. A rejected
    # EXTERNAL contradiction is QUARANTINED (poisoning-resistant); a rejected
    # higher-trust dissent is merely CONTESTED (recorded, not promoted).
    state = (CoherenceState.QUARANTINED
             if challenger.trust <= int(TrustTier.EXTERNAL) else CoherenceState.CONTESTED)
    deltas = {}
    if incumbent.source:
        deltas[incumbent.source] = "won"
    if challenger.source and challenger.source != incumbent.source:
        deltas[challenger.source] = "lost"
    return Adjudication(
        accept=False, final=incumbent, changed=False, state=state, rule=rule,
        reason=f"incumbent held on {rule}", loser=challenger,
        reliability_deltas=deltas,
    )


# -- reliability store (per-source track record) ---------------------------

def _store_path():
    from .paths import data_dir
    return data_dir("coherence") / "reliability.json"


def load_reliability() -> dict[str, dict[str, int]]:
    """``{source: {"won": int, "lost": int}}`` — empty/unreadable -> ``{}``."""
    try:
        p = _store_path()
        if not p.exists():
            return {}
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # pragma: no cover -- a corrupt store must not break writes
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, dict[str, int]] = {}
    for src, rec in data.items():
        if isinstance(rec, dict):
            out[str(src)] = {"won": int(rec.get("won", 0) or 0),
                             "lost": int(rec.get("lost", 0) or 0)}
    return out


def reliability_scores(store: Mapping[str, dict[str, int]] | None = None) -> dict[str, float]:
    """Collapse the won/lost store into ``{source: score}`` where score = won -
    lost (a source consistently overruled trends negative)."""
    s = load_reliability() if store is None else store
    return {src: float(rec.get("won", 0) - rec.get("lost", 0)) for src, rec in s.items()}


def _save_reliability(store: dict[str, dict[str, int]]) -> None:
    p = _store_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".reliability.", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(store, f, sort_keys=True)
        os.chmod(tmp, 0o600)
        os.replace(tmp, p)
    except Exception:  # pragma: no cover
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _apply_deltas(deltas: Mapping[str, str]) -> None:
    """Fold a single adjudication's ``{source: won|lost}`` into the store."""
    if not deltas:
        return
    store = load_reliability()
    for src, outcome in deltas.items():
        if not src:
            continue
        rec = store.setdefault(src, {"won": 0, "lost": 0})
        if outcome == "won":
            rec["won"] += 1
        elif outcome == "lost":
            rec["lost"] += 1
    _save_reliability(store)


# -- the stateful entry point ----------------------------------------------

def _digest(value: str) -> str:
    """Short content digest for the audit row (never log the raw value — it may
    be sealed/sensitive; the digest still pins which value won)."""
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()[:16]


def _audit(key: str, adj: Adjudication, incumbent: Belief, challenger: Belief) -> None:
    try:
        from .audit import EventKind, record
        record(
            EventKind.MEMORY_COHERENCE, agent="memory_coherence",
            action="adjudicate", key=key, rule=adj.rule, state=adj.state.value,
            accepted=adj.accept, changed=adj.changed,
            winner_source=adj.final.source, winner_trust=int(adj.final.trust),
            winner_digest=_digest(adj.final.value),
            challenger_source=challenger.source, challenger_trust=int(challenger.trust),
            challenger_digest=_digest(challenger.value),
            incumbent_source=incumbent.source, incumbent_trust=int(incumbent.trust),
        )
    except Exception:  # pragma: no cover -- audit never blocks a write
        log.debug("memory_coherence: audit failed", exc_info=True)


def resolve(key: str, incumbent: Belief | None, challenger: Belief) -> Adjudication:
    """Adjudicate, persist the reliability outcome, and audit. Fail-open.

    This is what the write path calls. On *any* internal error it returns an
    "accept the challenger" adjudication so the memory write degrades to legacy
    last-writer-wins rather than failing — a coherence bug must never lose a write
    or crash the agent (kernel rule 1)."""
    try:
        adj = adjudicate(incumbent, challenger, reliability=reliability_scores())
        _apply_deltas(adj.reliability_deltas)
        if incumbent is not None:
            _audit(key, adj, incumbent, challenger)
        return adj
    except Exception:  # pragma: no cover -- degrade to last-writer-wins
        log.warning("memory_coherence: resolve failed; accepting write (legacy)",
                    exc_info=True)
        return Adjudication(
            accept=True, final=challenger, changed=True,
            state=CoherenceState.STABLE, rule="error-fail-open",
            reason="coherence engine error; degraded to last-writer-wins",
        )


__all__ = [
    "CoherenceState", "Belief", "Adjudication", "enabled", "adjudicate",
    "resolve", "load_reliability", "reliability_scores",
]
