"""Negative knowledge -- executable guardrails mined from causally-triaged failures.

The Cognitive Data Engine's fix-mining stage, and the council's runner-up moat:
governance that gets *smarter from every incident* instead of ossifying into
static, hand-written ACLs. A triaged :class:`~maverick.data_engine.FailureClass`
(an action that *provably* lowers outcomes) becomes a :class:`Guardrail`: a
learned, reversible rule that discourages that action -- and unlike a deny-list,
each guardrail carries the **causal effect that justifies it**, so it can be
explained, ranked, and *dropped* automatically when re-triage shows the harm is
gone. Negative knowledge that compounds.

The registry persists the learned guardrails; ``consult`` is the read side an
agent (or the rehearsal gate) checks before acting. Pure + OFF by default: mining
only runs on an opt-in triaged corpus, and ``consult`` on an empty registry
returns ``None`` (no behaviour change).
"""
from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Guardrail:
    """A learned, causally-justified rule that an action hurts outcomes."""

    action: str
    severity: float     # |causal effect| -- how much the action lowers outcome
    ci_high: float      # the effect's upper confidence bound (< 0 == confidently harmful)
    rule: str           # human-readable justification

    @property
    def justified(self) -> bool:
        """Confidently harmful -- the evidence clears the bar to act on it."""
        return self.ci_high < 0.0

    def to_dict(self) -> dict:
        return {"action": self.action, "severity": self.severity,
                "ci_high": self.ci_high, "rule": self.rule}


def mine(failure_classes) -> list[Guardrail]:
    """Turn triaged failure classes into guardrails, strongest harm first.

    Only **trustworthy, confidently-harmful** classes (``ci_high < 0``) become
    guardrails -- a merely-frequent or shaky failure never hardens into a rule.
    """
    rails: list[Guardrail] = []
    for fc in failure_classes:
        if not getattr(fc, "trustworthy", False) or fc.ci_high >= 0.0:
            continue
        sev = abs(fc.causal_effect)
        rails.append(Guardrail(
            action=fc.action, severity=sev, ci_high=fc.ci_high,
            rule=(f"avoid '{fc.action}': it causally lowers task outcome by "
                  f"~{sev:.2f} (95% CI upper bound {fc.ci_high:.2f} < 0)"),
        ))
    rails.sort(key=lambda g: g.severity, reverse=True)
    return rails


@dataclass
class GuardrailRegistry:
    """Append/replace store of learned guardrails (atomic, 0600), keyed by action."""

    path: Path | None = None
    _rails: dict = None  # type: ignore[assignment]
    _lock: threading.Lock = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self._lock is None:
            self._lock = threading.Lock()
        if self._rails is None:
            self._rails = {}
        if self.path is not None:
            self._load()

    def update(self, guardrails) -> None:
        """Replace the learned set with a freshly-mined one (re-triage drops the
        rules whose harm is gone -- guardrails don't accumulate forever)."""
        with self._lock:
            self._rails = {g.action: g for g in guardrails}
            self._save()

    def consult(self, action: str) -> Guardrail | None:
        """The guardrail flagging ``action``, or None. The read side for an agent
        / the rehearsal gate; None on an empty registry (no behaviour change)."""
        with self._lock:
            return self._rails.get(action)

    def all(self) -> list[Guardrail]:
        with self._lock:
            return sorted(self._rails.values(), key=lambda g: g.severity, reverse=True)

    def _load(self) -> None:
        try:
            raw = json.loads(Path(self.path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for d in (raw or []):
            try:
                g = Guardrail(action=str(d["action"]), severity=float(d["severity"]),
                              ci_high=float(d["ci_high"]), rule=str(d.get("rule", "")))
                self._rails[g.action] = g
            except (KeyError, TypeError, ValueError):
                continue

    def _save(self) -> None:
        if self.path is None:
            return
        try:
            p = Path(self.path)
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps([g.to_dict() for g in self._rails.values()],
                                      sort_keys=True), encoding="utf-8")
            os.replace(tmp, p)
            try:
                os.chmod(p, 0o600)
            except OSError:
                pass
        except Exception:  # pragma: no cover -- persistence is best-effort
            log.debug("guardrail registry save failed", exc_info=True)


_shared: dict = {}
_shared_lock = threading.Lock()


def shared() -> GuardrailRegistry:
    from .paths import data_dir

    path = data_dir("guardrails.json")
    with _shared_lock:
        reg = _shared.get(path)
        if reg is None:
            reg = GuardrailRegistry(path=path)
            _shared[path] = reg
        return reg


def reset_shared() -> None:
    with _shared_lock:
        _shared.clear()


__all__ = ["Guardrail", "mine", "GuardrailRegistry", "shared", "reset_shared"]
