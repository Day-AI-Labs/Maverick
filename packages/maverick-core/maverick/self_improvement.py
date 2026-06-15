"""Governed self-improvement: the promotion ladder that makes learning *safe*.

Maverick already *learns* in several places (skills, reflexions, dreams,
config evolution). What it lacks is a single governed gate that decides whether
a proposed self-change is allowed to take effect -- and that is the whole moat.
A frontier lab can train a better policy; what it will not ship into a bank is a
system that rewrites *itself* in production. The defensible asset is not the
learning, it is the **interlocks that make self-modification deployable**: a
change may take effect only if it (a) measurably beats its own baseline, (b)
never widens the capability envelope, (c) is approved by a human at the rungs
that touch tools/code/weights, (d) is reversible, and (e) is refused outright
while the verifier is mis-calibrated (so the system can't learn from its own
drift). Every promotion is signed into the audit chain.

This module is that controller. It does NOT train models -- the per-rung work
(RL on trajectories, tool synthesis, code self-mod, fine-tuning) is injected as
opaque candidate payloads. It owns the *governance spine* shared by every rung,
so each new self-improvement capability inherits the same provable safety
properties instead of re-litigating them.

Rungs, lowest -> highest risk: ``config`` -> ``prompt`` -> ``tool`` ->
``policy`` -> ``code`` -> ``weights``. Higher rungs require capability evidence
and human approval; the lowest may auto-promote once they beat their baseline.

Posture (kernel rule 1): OFF by default and a no-op while off -- nothing is ever
promoted unless ``[self_improvement] enable`` is set, so it can never change a
default deployment's behaviour. When ON, the gates fail **closed**: a promotion
is a privileged write, so a broken gate, missing evidence, or any error rejects
the change rather than letting it through. The engine being off is fail-open
(does nothing); the engine deciding is fail-closed (won't promote on doubt).
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Rungs ordered by blast radius. Index == risk rank.
RUNGS: tuple[str, ...] = ("config", "prompt", "tool", "policy", "code", "weights")


def _rung_rank(rung: str) -> int:
    try:
        return RUNGS.index(rung)
    except ValueError:
        # Unknown rung is treated as the most dangerous -- fail closed.
        return len(RUNGS)


# Per-rung gate policy. ``require_capability_evidence`` forces a non-escalation
# proof (a change that can't show it didn't widen authority is refused at and
# above ``tool``). ``require_human`` gates code/weights behind explicit sign-off.
_RUNG_POLICY: dict[str, dict[str, Any]] = {
    "config":  {"min_samples": 3,  "require_capability_evidence": False, "require_human": False},
    "prompt":  {"min_samples": 5,  "require_capability_evidence": False, "require_human": False},
    "tool":    {"min_samples": 5,  "require_capability_evidence": True,  "require_human": False},
    "policy":  {"min_samples": 8,  "require_capability_evidence": True,  "require_human": False},
    "code":    {"min_samples": 10, "require_capability_evidence": True,  "require_human": True},
    "weights": {"min_samples": 20, "require_capability_evidence": True,  "require_human": True},
}


def enabled() -> bool:
    """Whether the controller may promote anything. OFF by default, fail-open."""
    if os.environ.get("MAVERICK_SELF_IMPROVEMENT", "").strip().lower() in {
        "1", "true", "yes", "on",
    }:
        return True
    try:
        from .config import get_self_improvement
        return bool(get_self_improvement().get("enable", False))
    except Exception:  # pragma: no cover -- config never blocks a run
        return False


def _config() -> dict:
    try:
        from .config import get_self_improvement
        return get_self_improvement()
    except Exception:  # pragma: no cover
        return {"enable": False, "min_improvement": 0.0, "max_auto_rung": "policy"}


@dataclass
class Candidate:
    """A proposed self-change awaiting promotion.

    The controller is agnostic to *what* changed -- ``payload`` is opaque (a
    config diff, a new tool's source, a trained adapter ref). It judges only the
    evidence: did it beat baseline, did authority stay bounded, is it reversible.

    Capability non-escalation can be proven two ways: pass ``capability_widens``
    directly (the caller computed it with ``maverick.capability``), or pass
    ``capability_before``/``capability_after`` plus ``probe_tools`` and let the
    gate check that the change permits no tool the prior grant didn't.
    """

    rung: str
    summary: str
    baseline_score: float
    candidate_score: float
    samples: int = 0
    payload: Any = None
    capability_widens: bool | None = None
    capability_before: Any = None
    capability_after: Any = None
    probe_tools: tuple[str, ...] = ()
    approved: bool = False
    # Truthy iff the change can be undone (a snapshot id / revert handle). A
    # change that can't be rolled back is never promoted.
    rollback: Any = None
    provenance: dict = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])


@dataclass(frozen=True)
class GateResult:
    gate: str
    ok: bool
    reason: str = ""


@dataclass(frozen=True)
class Verdict:
    """Outcome of evaluating a candidate. ``promote`` is the AND of all gates."""

    candidate_id: str
    rung: str
    promote: bool
    gates: tuple[GateResult, ...]
    blocking_reason: str = ""

    @property
    def ok(self) -> bool:
        return self.promote


@dataclass(frozen=True)
class PromotionRecord:
    id: str
    rung: str
    summary: str
    baseline_score: float
    candidate_score: float
    promoted_at: float
    rolled_back: bool = False
    rolled_back_at: float | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id, "rung": self.rung, "summary": self.summary,
            "baseline_score": self.baseline_score,
            "candidate_score": self.candidate_score,
            "promoted_at": self.promoted_at,
            "rolled_back": self.rolled_back,
            "rolled_back_at": self.rolled_back_at,
        }


def _capability_widens(cand: Candidate) -> bool | None:
    """Did the change widen authority? True=widened, False=bounded, None=unknown.

    A declared verdict wins (caller used the real ``capability`` algebra). Else,
    if before/after grants and a tool probe set are supplied, the change widens
    iff it permits some probed tool the prior grant did not.
    """
    if cand.capability_widens is not None:
        return bool(cand.capability_widens)
    before, after = cand.capability_before, cand.capability_after
    if before is None or after is None or not cand.probe_tools:
        return None
    try:
        for tool in cand.probe_tools:
            if after.permits(tool) and not before.permits(tool):
                return True
        return False
    except Exception:  # pragma: no cover -- can't prove -> caller treats as unknown
        return None


def _default_frozen_fn() -> bool:
    try:
        from .calibration import learning_frozen
        return bool(learning_frozen())
    except Exception:  # pragma: no cover -- if we can't check, fail closed below
        raise


def _default_audit_fn(**payload: Any) -> None:
    try:
        from .audit import EventKind, record
        record(EventKind.LEARNING_UPDATE, agent="self_improvement", **payload)
    except Exception:  # pragma: no cover -- audit is best-effort, never blocks
        log.debug("self-improvement audit failed", exc_info=True)


@dataclass
class SelfImprovementController:
    """Decide, record, and reverse self-changes under the safety interlocks."""

    min_improvement: float = 0.0
    max_auto_rung: str = "policy"
    frozen_fn: Callable[[], bool] = _default_frozen_fn
    audit_fn: Callable[..., None] = _default_audit_fn
    ledger: PromotionLedger | None = None
    now: Callable[[], float] = time.time
    rung_policy: dict[str, dict[str, Any]] = field(
        default_factory=lambda: {k: dict(v) for k, v in _RUNG_POLICY.items()})

    # -- the gate pipeline (pure; no side effects) ------------------------

    def evaluate(self, cand: Candidate) -> Verdict:
        """Run every gate. Promotion requires ALL to pass; gates fail closed."""
        gates: list[GateResult] = []

        # 0. Known rung.
        policy = self.rung_policy.get(cand.rung)
        if policy is None:
            return self._reject(cand, [GateResult("rung", False, f"unknown rung {cand.rung!r}")])

        # 1. Calibration interlock: never learn while the verifier is drifting.
        try:
            frozen = self.frozen_fn()
        except Exception:
            frozen = True  # can't confirm the judge is honest -> fail closed
        gates.append(GateResult("calibration", not frozen,
                                "" if not frozen else "learning frozen: verifier mis-calibrated"))

        # 2. Evidence: must beat its own baseline by the margin, with enough samples.
        improvement = cand.candidate_score - cand.baseline_score
        enough = cand.samples >= int(policy["min_samples"])
        beats = improvement > self.min_improvement
        ev_ok = enough and beats
        ev_reason = ""
        if not enough:
            ev_reason = f"insufficient evidence: {cand.samples} < {policy['min_samples']} samples"
        elif not beats:
            ev_reason = (f"no improvement: +{improvement:.4f} <= margin "
                         f"{self.min_improvement:.4f}")
        gates.append(GateResult("evidence", ev_ok, ev_reason))

        # 3. Capability non-escalation -- the core safety property of the moat.
        widens = _capability_widens(cand)
        needs_cap = bool(policy["require_capability_evidence"])
        if widens is True:
            gates.append(GateResult("capability", False, "change widens the capability envelope"))
        elif widens is None and needs_cap:
            gates.append(GateResult("capability", False,
                                    "no capability-non-escalation proof for a tool/code/weights change"))
        else:
            gates.append(GateResult("capability", True, ""))

        # 4. Human approval -- required at code/weights, and for any rung above
        #    ``max_auto_rung`` (a deployment-wide ceiling on autonomous promotion).
        needs_human = bool(policy["require_human"]) or (
            _rung_rank(cand.rung) > _rung_rank(self.max_auto_rung))
        human_ok = (not needs_human) or bool(cand.approved)
        gates.append(GateResult("human_approval", human_ok,
                                "" if human_ok else f"{cand.rung} promotion requires human approval"))

        # 5. Reversibility: never promote a change you can't undo.
        rb_ok = bool(cand.rollback)
        gates.append(GateResult("rollback", rb_ok,
                                "" if rb_ok else "no rollback handle: change is not reversible"))

        failing = [g for g in gates if not g.ok]
        if failing:
            return Verdict(cand.id, cand.rung, False, tuple(gates), failing[0].reason)
        return Verdict(cand.id, cand.rung, True, tuple(gates))

    def _reject(self, cand: Candidate, gates: list[GateResult]) -> Verdict:
        return Verdict(cand.id, cand.rung, False, tuple(gates),
                       gates[0].reason if gates else "rejected")

    # -- privileged writes (promote / rollback) --------------------------

    def promote(self, cand: Candidate) -> Verdict:
        """Evaluate and, if every gate passes, record + sign the promotion.

        A no-op (never promotes) while the engine is disabled. The caller
        applies ``cand.payload`` only when the returned verdict ``ok`` is True.
        """
        if not enabled():
            return Verdict(cand.id, cand.rung, False,
                           (GateResult("enabled", False, "self-improvement disabled"),),
                           "self-improvement disabled")
        verdict = self.evaluate(cand)
        if not verdict.promote:
            self.audit_fn(content="self_improvement_rejected", decision="reject",
                          rung=cand.rung, candidate=cand.id, reason=verdict.blocking_reason)
            return verdict
        rec = PromotionRecord(
            id=cand.id, rung=cand.rung, summary=cand.summary,
            baseline_score=cand.baseline_score, candidate_score=cand.candidate_score,
            promoted_at=self.now(),
        )
        if self.ledger is not None:
            self.ledger.add(rec)
        self.audit_fn(content="self_improvement_promoted", decision="promote",
                      rung=cand.rung, candidate=cand.id,
                      improvement=round(cand.candidate_score - cand.baseline_score, 6))
        return verdict

    def rollback(self, record_id: str, *, undo: Callable[[], None] | None = None) -> bool:
        """Reverse a prior promotion: mark it rolled back, run ``undo``, audit."""
        if self.ledger is None:
            return False
        rec = self.ledger.get(record_id)
        if rec is None or rec.rolled_back:
            return False
        if undo is not None:
            try:
                undo()
            except Exception:
                log.warning("self-improvement rollback undo failed for %s", record_id, exc_info=True)
                return False
        self.ledger.mark_rolled_back(record_id, at=self.now())
        self.audit_fn(content="self_improvement_rolled_back", decision="rollback",
                      rung=rec.rung, candidate=record_id)
        return True


@dataclass
class PromotionLedger:
    """Append-only, atomically-persisted record of promotions (0600)."""

    path: Path | None = None
    max_records: int = 1000
    _records: dict[str, PromotionRecord] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        if self.path is not None:
            self._load()

    def add(self, rec: PromotionRecord) -> None:
        with self._lock:
            self._records[rec.id] = rec
            if len(self._records) > self.max_records:
                # Drop oldest by promoted_at.
                oldest = sorted(self._records.values(), key=lambda r: r.promoted_at)
                for r in oldest[: len(self._records) - self.max_records]:
                    self._records.pop(r.id, None)
            self._save()

    def get(self, record_id: str) -> PromotionRecord | None:
        with self._lock:
            return self._records.get(record_id)

    def mark_rolled_back(self, record_id: str, *, at: float) -> None:
        with self._lock:
            rec = self._records.get(record_id)
            if rec is None:
                return
            self._records[record_id] = PromotionRecord(
                **{**rec.to_dict(), "rolled_back": True, "rolled_back_at": at})
            self._save()

    def all(self) -> list[PromotionRecord]:
        with self._lock:
            return sorted(self._records.values(), key=lambda r: r.promoted_at, reverse=True)

    def _load(self) -> None:
        try:
            raw = json.loads(Path(self.path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for d in (raw or []):
            try:
                rec = PromotionRecord(
                    id=str(d["id"]), rung=str(d["rung"]), summary=str(d.get("summary", "")),
                    baseline_score=float(d.get("baseline_score", 0.0)),
                    candidate_score=float(d.get("candidate_score", 0.0)),
                    promoted_at=float(d.get("promoted_at", 0.0)),
                    rolled_back=bool(d.get("rolled_back", False)),
                    rolled_back_at=d.get("rolled_back_at"),
                )
                self._records[rec.id] = rec
            except (KeyError, TypeError, ValueError):
                continue

    def _save(self) -> None:
        if self.path is None:
            return
        try:
            p = Path(self.path)
            p.parent.mkdir(parents=True, exist_ok=True)
            data = [r.to_dict() for r in self._records.values()]
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
            os.replace(tmp, p)
            try:
                os.chmod(p, 0o600)
            except OSError:
                pass
        except Exception:  # pragma: no cover -- persistence is best-effort
            log.debug("promotion ledger save failed", exc_info=True)


_shared: dict[Path, SelfImprovementController] = {}
_shared_lock = threading.Lock()


def shared() -> SelfImprovementController:
    from .paths import data_dir

    path = data_dir("self_improvement.json")
    with _shared_lock:
        ctrl = _shared.get(path)
        if ctrl is None:
            cfg = _config()
            ctrl = SelfImprovementController(
                min_improvement=float(cfg.get("min_improvement", 0.0)),
                max_auto_rung=str(cfg.get("max_auto_rung", "policy")),
                ledger=PromotionLedger(path=path),
            )
            _shared[path] = ctrl
        return ctrl


def reset_shared() -> None:
    with _shared_lock:
        _shared.clear()


def consider(cand: Candidate, *, controller: SelfImprovementController | None = None) -> Verdict:
    """Opt-in entry point: judge a candidate self-change for promotion.

    Returns a non-promoting verdict (a safe no-op for the caller) when the
    engine is off or any gate fails. The caller applies the change only on
    ``verdict.ok``.
    """
    if not enabled():
        return Verdict(cand.id, cand.rung, False,
                       (GateResult("enabled", False, "self-improvement disabled"),),
                       "self-improvement disabled")
    try:
        return (controller or shared()).promote(cand)
    except Exception:  # pragma: no cover -- a privileged write must never crash a run
        log.warning("self-improvement promotion errored; refusing change", exc_info=True)
        return Verdict(cand.id, cand.rung, False,
                       (GateResult("error", False, "controller error"),), "controller error")


__all__ = [
    "RUNGS", "Candidate", "GateResult", "Verdict", "PromotionRecord",
    "SelfImprovementController", "PromotionLedger",
    "enabled", "shared", "reset_shared", "consider",
]
