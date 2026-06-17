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
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
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


def _canonical(params: dict, *, max_len: int = 4000) -> str:
    """Stable JSON for hashing/lineage; secrets redacted THEN size-capped
    (fail-open). The cap bounds the ledger and avoids persisting large tool
    inputs (e.g. full file contents) verbatim."""
    try:
        raw = json.dumps(params, sort_keys=True, default=str)
    except Exception:  # pragma: no cover -- unserializable -> repr
        raw = repr(params)
    try:
        from .safety.secret_detector import redact
        raw, _ = redact(raw)
    except Exception:  # pragma: no cover -- detector optional
        pass
    return raw if len(raw) <= max_len else raw[:max_len] + "...(truncated)"


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


def impact_of(identifier: str, *, kind: str = "any",
              store_dir: str | Path | None = None) -> list[dict]:
    """Impact analysis: every recorded consequential action that depended on a
    given skill or source. Use when a skill/source is revoked or found bad --
    "what did it touch?" -- the inverse of lineage. Scans all per-goal ledgers;
    ``kind`` is ``skill`` | ``source`` | ``any``. Read-only, fail-open."""
    out: list[dict] = []
    try:
        d = _lineage_dir(store_dir)
        if not d.exists():
            return out
        want_skill = kind in ("skill", "any")
        want_source = kind in ("source", "any")
        for f in sorted(d.glob("*.ndjson")):
            try:
                goal_id: object = int(f.stem)
            except ValueError:
                goal_id = f.stem
            for line in f.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                link = json.loads(line)
                skills = link.get("skills") or []
                sources = link.get("sources") or []
                via = ("skill" if (want_skill and identifier in skills)
                       else "source" if (want_source and identifier in sources)
                       else None)
                if via:
                    out.append({"goal_id": goal_id, "action": link.get("action"),
                                "ts": link.get("ts"), "via": via,
                                "hash": str(link.get("hash", ""))[:12]})
    except Exception:  # pragma: no cover -- impact analysis never raises
        return out
    return out


__all__ = ["ActionSpec", "Preview", "LineageLink", "GovernedActions", "ActionError",
           "enabled", "record_tool_lineage", "load_lineage", "verify_lineage_file",
           "impact_of"]


# --------------------------------------------------------------------------
# Run-path wiring: persistent, per-goal lineage of consequential tool calls.
# Off by default (kernel rule 1); fail-open (lineage never breaks a run).
# --------------------------------------------------------------------------
def enabled() -> bool:
    """Whether the run path records governed-action lineage. Off by default;
    ``[actions] enable`` / ``MAVERICK_GOVERNED_ACTIONS`` turns it on. Never raises."""
    env = os.environ.get("MAVERICK_GOVERNED_ACTIONS", "").strip().lower()
    if env in {"1", "true", "yes", "on"}:
        return True
    if env in {"0", "false", "no", "off"}:
        return False
    try:
        from .config import load_config
        return bool((load_config() or {}).get("actions", {}).get("enable", False))
    except Exception:  # pragma: no cover -- config must never block a run
        return False


def _lineage_dir(store_dir: str | Path | None = None) -> Path:
    """Where per-goal lineage lives. With an ACTIVE tenant it resolves under the
    tenant's data dir (one tenant's audit trail never mixes with another's),
    matching the other learned stores; single-tenant keeps the legacy path."""
    if store_dir is not None:
        return Path(store_dir).expanduser()
    try:
        from .paths import current_tenant, data_dir
        if current_tenant():
            return data_dir("lineage")
    except Exception:  # pragma: no cover -- isolation never blocks lineage
        pass
    return Path("~/.maverick/lineage").expanduser()


def record_tool_lineage(goal_id: int, action: str, params: object, *,
                        skills: tuple[str, ...] = (), sources: tuple[str, ...] = (),
                        actor: str = "", store_dir: str | Path | None = None) -> None:
    """Append a tamper-evident lineage link for a CONSEQUENTIAL tool call
    (risk >= medium) to ``<store>/<goal_id>.ndjson``. Fail-open: a low-risk tool
    is skipped and any error is swallowed -- lineage must never break a run."""
    try:
        from .safety.tool_risk import risk_rank, tool_risk
        if risk_rank(tool_risk(str(action))) < risk_rank("medium"):
            return  # only consequential actions are traced
        f = _lineage_dir(store_dir)
        f.mkdir(parents=True, exist_ok=True)
        f = f / f"{int(goal_id)}.ndjson"
        prev = _GENESIS
        if f.exists():
            for line in f.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    prev = json.loads(line).get("hash", prev)
        pj = _canonical(params if isinstance(params, dict) else {"input": params})
        rec = {"ts": time(), "actor": str(actor), "action": str(action),
               "params_json": pj, "skills": list(skills), "sources": list(sources),
               "prev_hash": prev, "hash": _link_hash(str(action), pj, prev)}
        with open(f, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
    except Exception:  # pragma: no cover -- lineage is best-effort, never fatal
        pass


def load_lineage(goal_id: int, store_dir: str | Path | None = None) -> list[dict]:
    """The persisted lineage links for one goal (oldest first)."""
    try:
        f = _lineage_dir(store_dir) / f"{int(goal_id)}.ndjson"
        if not f.exists():
            return []
        return [json.loads(ln) for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip()]
    except Exception:  # pragma: no cover
        return []


def verify_lineage_file(goal_id: int, store_dir: str | Path | None = None) -> str:
    """``VALID`` or ``BROKEN`` over a goal's persisted lineage chain -- the
    tamper-evidence for "what consequential actions did this run take?"."""
    links = load_lineage(goal_id, store_dir)
    expected = _GENESIS
    for i, link in enumerate(links):
        if link.get("prev_hash") != expected:
            return f"BROKEN: link {i} ({link.get('action')}) prev_hash mismatch"
        if link.get("hash") != _link_hash(str(link.get("action")), str(link.get("params_json")), expected):
            return f"BROKEN: link {i} ({link.get('action')}) content hash mismatch"
        expected = str(link.get("hash"))
    return f"VALID: {len(links)} link(s)" + (f", head {expected[:12]}..." if links else " (empty)")
