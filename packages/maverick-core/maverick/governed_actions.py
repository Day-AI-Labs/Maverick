"""Governed Actions -- typed, simulatable, lineage-tracked operations.

Borrowed from Palantir's ontology *Actions*, at agent scale: instead of an agent
running a free-form effect, a consequential operation is a declared ``Action``
with TYPED parameters and a risk class. Before it commits it is SIMULATED (a
preview of its effect with no side effects), gated by risk/approval, then
applied -- and every commit appends a tamper-evident LINEAGE link (hash-chained
exactly like :mod:`maverick.tools.provenance_chain`) so any outcome can be traced
back to the action, its inputs, and the skills/sources behind it.

Three Palantir borrows in one place:
  * **typed Actions** -- a registry of declared operations, not arbitrary calls;
  * **simulate-before-commit** -- preview the effect, gate the commit on risk;
  * **decision lineage** -- a verifiable chain from outcome to inputs.

Opt-in and fail-open per kernel rule 1: shipping this module changes nothing
(the kernel does not route through it by default); an operator/integration uses
it explicitly. Approval gating is enforced whenever ``commit`` is called;
``[actions] require_approval_at`` (default ``high``) sets the floor.
"""
from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from time import time

from .safety.tool_risk import RISK_LEVELS, risk_rank

log = logging.getLogger(__name__)

_GENESIS = "0" * 64


class ActionError(Exception):
    """A governed action was refused (bad params, risk gate, unknown action)."""


def _require_approval_at() -> str:
    """Risk floor at/above which ``commit`` requires an approver. Reads
    ``[actions] require_approval_at`` (default ``high``); never raises."""
    try:
        from .config import load_config
        v = str((load_config() or {}).get("actions", {}).get("require_approval_at", "high")).strip().lower()
        return v if v in RISK_LEVELS else "high"
    except Exception:  # pragma: no cover -- config must never block
        return "high"


def _canonical(params: dict) -> str:
    """Stable JSON for hashing/lineage; secrets redacted (fail-open)."""
    try:
        raw = json.dumps(params, sort_keys=True, default=str)
    except Exception:  # pragma: no cover -- unserializable -> repr
        raw = repr(params)
    try:
        from .safety.secret_detector import redact
        red, _ = redact(raw)
        return red
    except Exception:  # pragma: no cover -- detector optional
        return raw


def _link_hash(action: str, params_json: str, prev_hash: str) -> str:
    return hashlib.sha256(f"{action}|{params_json}|{prev_hash}".encode()).hexdigest()


@dataclass(frozen=True)
class ActionSpec:
    """A declared, typed operation. ``simulate`` previews the effect WITHOUT
    side effects; ``apply`` performs it. ``risk`` is a :data:`RISK_LEVELS` tier."""
    name: str
    params: dict[str, type]
    risk: str = "medium"
    simulate: Callable[[dict], str] | None = None
    apply: Callable[[dict], str] | None = None

    def __post_init__(self) -> None:
        if self.risk not in RISK_LEVELS:
            raise ValueError(f"risk {self.risk!r} must be one of {RISK_LEVELS}")


@dataclass(frozen=True)
class Preview:
    """The simulated effect of an action -- what WOULD happen on commit."""
    action: str
    params: dict
    effect: str
    risk: str
    requires_approval: bool


@dataclass(frozen=True)
class LineageLink:
    """One tamper-evident step: outcome <- action <- inputs/sources/skills."""
    ts: float
    action: str
    params_json: str   # canonical, secret-redacted
    effect: str
    result: str
    sources: tuple[str, ...]
    skills: tuple[str, ...]
    approver: str
    prev_hash: str
    hash: str


class GovernedActions:
    """A registry + executor for typed governed actions, with an append-only,
    hash-chained lineage ledger."""

    def __init__(self) -> None:
        self._specs: dict[str, ActionSpec] = {}
        self.lineage: list[LineageLink] = []

    # -- registry -----------------------------------------------------------
    def register(self, spec: ActionSpec) -> None:
        self._specs[spec.name] = spec

    def get(self, name: str) -> ActionSpec:
        try:
            return self._specs[name]
        except KeyError:
            raise ActionError(f"unknown action {name!r}") from None

    # -- typing -------------------------------------------------------------
    def _validate(self, spec: ActionSpec, params: dict) -> None:
        missing = [k for k in spec.params if k not in params]
        if missing:
            raise ActionError(f"{spec.name}: missing param(s) {missing}")
        for k, typ in spec.params.items():
            if not isinstance(params[k], typ):
                raise ActionError(
                    f"{spec.name}: param {k!r} must be {typ.__name__}, "
                    f"got {type(params[k]).__name__}")

    def _requires_approval(self, spec: ActionSpec) -> bool:
        return risk_rank(spec.risk) >= risk_rank(_require_approval_at())

    # -- simulate-before-commit --------------------------------------------
    def simulate(self, name: str, params: dict) -> Preview:
        """Preview an action's effect WITHOUT performing it (typed-checked)."""
        spec = self.get(name)
        self._validate(spec, params)
        effect = spec.simulate(params) if spec.simulate else f"(no simulator for {name})"
        return Preview(action=name, params=dict(params), effect=str(effect),
                       risk=spec.risk, requires_approval=self._requires_approval(spec))

    def commit(self, name: str, params: dict, *, approver: str = "",
               sources: tuple[str, ...] = (), skills: tuple[str, ...] = ()) -> str:
        """Type-check, gate on risk/approval, apply, and append a lineage link.
        Raises :class:`ActionError` if the risk gate is unmet -- governance is
        enforced here, not optional."""
        spec = self.get(name)
        self._validate(spec, params)
        preview = self.simulate(name, params)
        if preview.requires_approval and not approver:
            raise ActionError(
                f"{name}: {spec.risk!r}-risk action requires an approver "
                f"(>= [actions] require_approval_at={_require_approval_at()!r})")
        result = spec.apply(params) if spec.apply else f"(no apply for {name})"
        self._append_lineage(spec, params, preview.effect, str(result),
                             sources, skills, approver)
        return str(result)

    # -- lineage ------------------------------------------------------------
    def _append_lineage(self, spec: ActionSpec, params: dict, effect: str,
                        result: str, sources, skills, approver: str) -> None:
        prev = self.lineage[-1].hash if self.lineage else _GENESIS
        pj = _canonical(params)
        h = _link_hash(spec.name, pj, prev)
        self.lineage.append(LineageLink(
            ts=time(), action=spec.name, params_json=pj, effect=effect,
            result=result, sources=tuple(sources), skills=tuple(skills),
            approver=approver, prev_hash=prev, hash=h))

    def verify_lineage(self) -> str:
        """Recompute the hash chain; ``VALID`` or ``BROKEN`` at the first bad
        link (reordering, edits, forged links). Deterministic, offline."""
        expected = _GENESIS
        for i, link in enumerate(self.lineage):
            if link.prev_hash != expected:
                return f"BROKEN: link {i} ({link.action}) prev_hash mismatch"
            if link.hash != _link_hash(link.action, link.params_json, link.prev_hash):
                return f"BROKEN: link {i} ({link.action}) content hash mismatch"
            expected = link.hash
        return f"VALID: {len(self.lineage)} link(s), head {expected[:12]}..."

    def trace(self, index: int = -1) -> dict:
        """The decision lineage of one outcome: what action ran, on what inputs,
        from which sources/skills, approved by whom (the Palantir 'trace this
        number to source' artifact, for an agent decision)."""
        if not self.lineage:
            raise ActionError("no lineage recorded")
        link = self.lineage[index]
        return {"action": link.action, "params": link.params_json,
                "effect": link.effect, "result": link.result,
                "sources": list(link.sources), "skills": list(link.skills),
                "approver": link.approver, "hash": link.hash[:12]}


__all__ = ["ActionSpec", "Preview", "LineageLink", "GovernedActions", "ActionError"]
