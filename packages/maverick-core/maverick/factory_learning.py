"""A self-improving agent factory: learn from what the packs we make get wrong.

The factory drafts packs (intake, demonstration) and provisioning reveals where
those drafts fall short -- a tool the pack declared but didn't exist, a skill
its workflow needed but wasn't installed, an envelope a human had to widen at
approval. Today that signal dies in a log. This module closes the loop back
onto *generation quality*:

    record provisioning/approval outcomes  (attributed to suite + signal)
        --> mine recurring shortfalls into proposer CORRECTIONS
        --> promote each through the self_improvement gate  (the ``prompt`` rung)
        --> augment the generator's system prompt with the promoted guidance

So the NEXT finance pack the factory writes already knows that finance packs
typically need ``web_search``, because the last several needed it and the gate
agreed the pattern is real.

Posture (kernel rule 1): OFF by default and a no-op while off. Recording writes
no state, mining reads nothing, and ``augment_system_prompt`` returns the base
prompt UNCHANGED unless ``[self_improvement] enable`` (or
``MAVERICK_FACTORY_LEARNING``) is set -- a default deployment's generator is
byte-identical to before. Promotion reuses ``SelfImprovementController`` so a
correction only takes effect if it beats its baseline with enough support and
the verifier isn't drifting; nothing here widens any pack's envelope (a
correction is guidance text, never a tool grant). Outcome text is
secret-redacted before it is persisted.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import env_flag
from .paths import data_dir

log = logging.getLogger(__name__)

OUTCOMES_PATH = data_dir("factory_outcomes.ndjson")
PROMOTED_PATH = data_dir("factory_corrections.ndjson")

# Signals we attribute to a generated pack's *making*, not its running.
SIGNAL_TOOL_MISSING = "tool_declared_but_missing"   # provisioning had to synthesize it
SIGNAL_SKILL_GAP = "workflow_skill_gap"             # provisioning installed a catalog skill
SIGNAL_ENVELOPE_WIDENED = "envelope_widened"        # a human widened the clamp at approval
_VALID_SIGNALS = frozenset({SIGNAL_TOOL_MISSING, SIGNAL_SKILL_GAP, SIGNAL_ENVELOPE_WIDENED})

_lock = threading.Lock()
# A correction targeting the whole roster (no suite prefix) uses this scope.
_GLOBAL_SCOPE = "*"
_MAX_GUIDANCE_ITEMS = 8
# Bound the outcomes ledger the way trajectory_store bounds its capture: oldest
# rows roll off so a long-lived deployment can't grow it without limit (and the
# whole-file re-read in mining/promotion stays cheap). The promoted ledger is
# self-bounding (deduped on read, one entry per distinct correction).
_MAX_OUTCOME_ROWS = 50_000
# Rotate (read + rewrite, keeping the newest rows) once the file exceeds this many
# bytes. Sized comfortably above the worst-case row (pack + 200-char detail + json
# overhead ~= 320 B) * the row cap, so the expensive rewrite runs rarely and the
# ledger settles just above the cap rather than oscillating on every append.
_ROTATE_BYTES = _MAX_OUTCOME_ROWS * 320


def enabled() -> bool:
    """Whether the factory-learning loop is active. OFF by default, fail-open.

    Rides on the self-improvement master switch (the gate it promotes through),
    with a dedicated ``[self_improvement] factory_learning`` sub-toggle (default
    on) so an operator can keep the generator static while other rungs learn.
    ``MAVERICK_FACTORY_LEARNING`` overrides both.
    """
    v = env_flag("MAVERICK_FACTORY_LEARNING")
    if v is not None:
        return v
    try:
        from .self_improvement import enabled as si_enabled
        if not si_enabled():
            return False
        from .config import get_self_improvement
        return bool(get_self_improvement().get("factory_learning", True))
    except Exception:  # pragma: no cover -- never block a run
        return False


def _redact(text: str) -> str:
    try:
        from .safety.secret_detector import redact
        return redact(str(text or ""))[0]
    except Exception:  # pragma: no cover
        return str(text or "")


# --------------------------------------------------------------------------
# outcome ledger
# --------------------------------------------------------------------------
@dataclass
class FactoryOutcome:
    ts: float
    pack: str
    suite: str          # business suite, or "" for legacy/generic packs
    signal: str
    detail: str = ""    # the tool / skill / risk involved

    def to_dict(self) -> dict:
        return {"ts": self.ts, "pack": self.pack, "suite": self.suite,
                "signal": self.signal, "detail": self.detail}


def record_outcome(
    pack: str, signal: str, *, detail: str = "", suite: str | None = None,
    path: Path | None = None,
) -> bool:
    """Append one factory outcome. No-op (returns False) while disabled or for
    an unknown signal. Never raises -- a ledger write must not break onboarding.
    """
    if not enabled() or signal not in _VALID_SIGNALS:
        return False
    path = path or OUTCOMES_PATH
    if suite is None:
        try:
            from .domain import suite_for
            suite = suite_for(pack) or ""
        except Exception:  # pragma: no cover
            suite = ""
    entry = FactoryOutcome(ts=time.time(), pack=pack, suite=suite,
                           signal=signal, detail=_redact(detail)[:200])
    with _lock:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Create with 0600 atomically (os.open honors the mode on CREATE), so
            # the file is never briefly world/group-readable between open + chmod.
            fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600)
            with open(fd, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry.to_dict()) + "\n")
            _maybe_rotate(path)
            return True
        except OSError as e:
            log.warning("factory_learning: outcome write failed: %s", e)
            return False


def _maybe_rotate(path: Path) -> None:
    """Keep only the newest ``_MAX_OUTCOME_ROWS`` rows. Called under ``_lock``.

    Triggered by the file's actual SIZE, not a process-local counter: in the CLI
    a fresh process records only a few rows, so a counter would never trip and
    the cap would be a no-op. A cheap ``stat`` on each append, with the expensive
    read+rewrite only once the file is clearly oversized, bounds the ledger
    regardless of how many short-lived processes write it.
    """
    try:
        if path.stat().st_size < _ROTATE_BYTES:
            return
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
        if len(lines) <= _MAX_OUTCOME_ROWS:
            return
        tmp = path.with_suffix(path.suffix + ".tmp")
        fd = os.open(tmp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
        with open(fd, "w", encoding="utf-8") as f:
            f.write("".join(lines[-_MAX_OUTCOME_ROWS:]))
        os.replace(tmp, path)
    except OSError:  # pragma: no cover -- rotation is best-effort
        pass


def load_outcomes(*, path: Path | None = None) -> list[FactoryOutcome]:
    path = path or OUTCOMES_PATH
    if not path.exists():
        return []
    out: list[FactoryOutcome] = []
    try:
        with open(path, encoding="utf-8") as f:
            for raw in f:
                try:
                    d = json.loads(raw)
                    if not isinstance(d, dict):  # a bare int/str/array/null line
                        continue
                    out.append(FactoryOutcome(
                        ts=float(d.get("ts") or 0.0), pack=str(d.get("pack") or ""),
                        suite=str(d.get("suite") or ""), signal=str(d.get("signal") or ""),
                        detail=str(d.get("detail") or ""),
                    ))
                except (json.JSONDecodeError, TypeError, ValueError):
                    continue
    except OSError:
        return []
    return out


def record_provisioning(profile, plan, result) -> int:
    """Attribute a pack's provisioning gaps to its making. Best-effort.

    Called after ``provision.apply_plan``: a synthesized tool means the pack
    declared a tool that didn't exist (the generator should have known better
    or the tool belongs in the catalog); an installed skill means its workflow
    needed know-how the draft lacked. Returns the number of outcomes recorded
    (0 while disabled).
    """
    if not enabled():
        return 0
    pack = getattr(profile, "name", "") or ""
    n = 0
    # The making-time signal is "the pack DECLARED a tool that didn't exist",
    # keyed by the declared name (``gap.need``). Record it from the plan's
    # tool-gaps -- which captures every such tool whether or not synthesis later
    # succeeded -- and NOT also from ``result.generated`` (the post-synthesis
    # SANITIZED name): recording both would double-count and, worse, fragment
    # mining across two different spellings of the same tool.
    seen_tools: set[str] = set()
    for gap in getattr(plan, "tool_gaps", []) or []:
        if getattr(gap, "resolution", "") == "generate_tool" and gap.need not in seen_tools:
            seen_tools.add(gap.need)
            n += bool(record_outcome(pack, SIGNAL_TOOL_MISSING, detail=gap.need))
    for skill_name in getattr(result, "acquired", []) or []:
        n += bool(record_outcome(pack, SIGNAL_SKILL_GAP, detail=skill_name))
    return n


# --------------------------------------------------------------------------
# mining: recurring outcomes -> proposer corrections
# --------------------------------------------------------------------------
@dataclass
class ProposerCorrection:
    """A guidance hint to fold into the generator's system prompt."""

    scope: str          # suite key, or "*" for the whole roster
    signal: str
    detail: str
    support: int        # how many distinct packs exhibited it
    guidance: str       # the sentence appended to the proposer prompt

    def key(self) -> str:
        return f"{self.scope}|{self.signal}|{self.detail}"


def _guidance_for(signal: str, detail: str, scope: str) -> str:
    where = "packs" if scope == _GLOBAL_SCOPE else f"{scope} packs"
    if signal == SIGNAL_TOOL_MISSING:
        return (f"{where} commonly need the {detail!r} tool but recent drafts "
                f"omitted it or named a tool that doesn't exist -- include a real, "
                f"catalog tool for this need.")
    if signal == SIGNAL_SKILL_GAP:
        return (f"{where} typically need the {detail!r} skill -- reflect that "
                f"capability in the workflow.")
    if signal == SIGNAL_ENVELOPE_WIDENED:
        return (f"{where} were repeatedly approved only after widening the "
                f"{detail!r} envelope -- size the envelope for this need up front.")
    return ""  # pragma: no cover -- unknown signal never mined


def mine_corrections(
    outcomes: list[FactoryOutcome] | None = None, *, min_support: int = 3,
) -> list[ProposerCorrection]:
    """Aggregate recurring outcomes into corrections meeting ``min_support``.

    Support counts DISTINCT packs (one pack that hit the same gap five times is
    one data point, not five), grouped by (suite-scope, signal, detail). Pure
    and deterministic -- the same ledger always mines the same corrections,
    ordered by support then key for a stable promotion sequence.
    """
    outcomes = load_outcomes() if outcomes is None else outcomes
    packs: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for o in outcomes:
        if o.signal not in _VALID_SIGNALS or not o.detail:
            continue
        scope = o.suite or _GLOBAL_SCOPE
        packs[(scope, o.signal, o.detail)].add(o.pack)
    corrections: list[ProposerCorrection] = []
    for (scope, signal, detail), pset in packs.items():
        if len(pset) < max(1, min_support):
            continue
        corrections.append(ProposerCorrection(
            scope=scope, signal=signal, detail=detail, support=len(pset),
            guidance=_guidance_for(signal, detail, scope),
        ))
    corrections.sort(key=lambda c: (-c.support, c.key()))
    return corrections


# --------------------------------------------------------------------------
# promotion: gate a correction through the self_improvement controller
# --------------------------------------------------------------------------
def _default_scorer(correction: ProposerCorrection, total_packs: int) -> tuple[float, float, int]:
    """Evidence for a correction as (baseline_score, candidate_score, samples).

    Higher score = better generation. Baseline is the current *avoidance rate*
    of this gap across packs in scope (so a prevalent gap has a LOW baseline);
    candidate is 1.0 (the correction's intent: stop producing this gap). The
    improvement the gate weighs is therefore the gap's prevalence, and
    ``samples`` is the distinct-pack support -- a rare gap won't clear the
    rung's ``min_samples`` and a barely-present one won't beat the margin.
    """
    base = max(0.0, 1.0 - (correction.support / max(1, total_packs)))
    return base, 1.0, correction.support


def promoted_corrections(*, path: Path | None = None) -> list[ProposerCorrection]:
    """Corrections that have passed the gate (most recent wins per key)."""
    path = path or PROMOTED_PATH
    if not path.exists():
        return []
    by_key: dict[str, ProposerCorrection] = {}
    try:
        with open(path, encoding="utf-8") as f:
            for raw in f:
                try:
                    d = json.loads(raw)
                    if not isinstance(d, dict):  # a bare int/str/array/null line
                        continue
                    c = ProposerCorrection(
                        scope=str(d.get("scope") or _GLOBAL_SCOPE),
                        signal=str(d.get("signal") or ""), detail=str(d.get("detail") or ""),
                        support=int(d.get("support") or 0), guidance=str(d.get("guidance") or ""),
                    )
                    by_key[c.key()] = c
                except (json.JSONDecodeError, TypeError, ValueError):
                    continue
    except OSError:
        return []
    return list(by_key.values())


def _persist_promoted(correction: ProposerCorrection, *, path: Path | None = None) -> bool:
    """Append a promoted correction. Never raises (returns False on I/O error) so
    an unwritable data dir can't crash the promotion pass."""
    path = path or PROMOTED_PATH
    with _lock:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600)
            with open(fd, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "ts": time.time(), "scope": correction.scope, "signal": correction.signal,
                    "detail": correction.detail, "support": correction.support,
                    "guidance": correction.guidance,
                }) + "\n")
            return True
        except OSError as e:
            log.warning("factory_learning: promoted-correction write failed: %s", e)
            return False


def review_and_promote(
    *, min_support: int = 3, controller: Any = None, scorer=None,
    total_packs: int | None = None, promoted_path: Path | None = None,
) -> list[ProposerCorrection]:
    """Mine corrections and promote those the self_improvement gate accepts.

    Each mined correction becomes a ``prompt``-rung ``Candidate`` (guidance text
    widens no capability, so the rung needs no escalation proof and no human
    sign-off). The controller's evidence + calibration gates decide; a promoted
    correction is persisted so ``augment_system_prompt`` picks it up. Returns
    the list promoted this pass. No-op while disabled.
    """
    if not enabled():
        return []
    promoted_path = promoted_path or PROMOTED_PATH
    corrections = mine_corrections(min_support=min_support)
    if not corrections:
        return []
    try:
        from .self_improvement import Candidate
        if controller is None:
            from .self_improvement import SelfImprovementController
            controller = SelfImprovementController()
    except Exception as e:  # pragma: no cover -- can't build the gate -> fail closed
        log.debug("factory_learning: controller unavailable: %s", e)
        return []

    score = scorer or _default_scorer
    npacks = total_packs if total_packs is not None else _distinct_pack_count()
    promoted: list[ProposerCorrection] = []
    already = {c.key() for c in promoted_corrections(path=promoted_path)}
    for corr in corrections:
        if corr.key() in already:
            continue
        baseline, candidate, samples = score(corr, npacks)
        cand = Candidate(
            rung="prompt",
            summary=f"factory guidance [{corr.scope}/{corr.signal}]: {corr.detail}",
            baseline_score=baseline, candidate_score=candidate, samples=samples,
            capability_widens=False,  # guidance text never widens authority
            rollback=True,            # remove the line from the promoted store
            provenance={"kind": "factory_correction", "key": corr.key()},
        )
        try:
            verdict = controller.evaluate(cand)
        except Exception as e:  # pragma: no cover -- gate failure -> skip, fail closed
            log.debug("factory_learning: gate error for %s: %s", corr.key(), e)
            continue
        if getattr(verdict, "promote", False) and _persist_promoted(corr, path=promoted_path):
            promoted.append(corr)
    return promoted


def _distinct_pack_count(*, path: Path | None = None) -> int:
    return len({o.pack for o in load_outcomes(path=path)}) or 1


# --------------------------------------------------------------------------
# application: fold promoted guidance into a generator's system prompt
# --------------------------------------------------------------------------
def guidance_block(suite: str | None = None) -> str:
    """The promoted-guidance addendum for ``suite`` (and global), or "".

    Returns "" while disabled, so a caller can unconditionally append it.
    Scope-matched: a finance proposer sees finance + global corrections, never
    another suite's. Capped so a long history can't bloat the system prompt.
    """
    if not enabled():
        return ""
    scope = suite or ""
    items = [
        c for c in promoted_corrections()
        if c.scope == _GLOBAL_SCOPE or (scope and c.scope == scope)
    ]
    if not items:
        return ""
    items.sort(key=lambda c: -c.support)
    lines = [f"- {c.guidance}" for c in items[:_MAX_GUIDANCE_ITEMS] if c.guidance]
    if not lines:
        return ""
    return ("\nLearned from packs this factory has already produced (apply when "
            "relevant):\n" + "\n".join(lines))


def augment_system_prompt(base_system: str, *, suite: str | None = None) -> str:
    """Append promoted factory guidance to a proposer system prompt. Identity
    while disabled or when there's nothing promoted (default deployments are
    byte-identical)."""
    block = guidance_block(suite)
    return f"{base_system}\n{block}" if block else base_system


__all__ = [
    "FactoryOutcome", "ProposerCorrection",
    "SIGNAL_TOOL_MISSING", "SIGNAL_SKILL_GAP", "SIGNAL_ENVELOPE_WIDENED",
    "enabled", "record_outcome", "load_outcomes", "record_provisioning",
    "mine_corrections", "review_and_promote", "promoted_corrections",
    "guidance_block", "augment_system_prompt",
]
