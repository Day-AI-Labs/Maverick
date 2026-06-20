"""Oversight control plane: the policy decision point for agent actions.

The keystone of Maverick's enterprise governance (see
``docs/enterprise/architecture.md``, Layer A). Every consequential agent action
is evaluated here against the principal's capability and org policy, yielding a
single decision:

  - ``ALLOW``          -- proceed
  - ``DENY``           -- block (least-privilege or hard policy)
  - ``REQUIRE_HUMAN``  -- pause for human sign-off (the EU AI Act Art 14
                          human-oversight gate)

Decisions are strictest-wins (``DENY`` > ``REQUIRE_HUMAN`` > ``ALLOW``) and carry
a machine-readable ``rule`` + human ``reason`` so the choice lands in the audit
record (Art 12).

Default-open and opt-in: with no ``[governance]`` policy configured, ``evaluate``
allows anything the capability already permits, so a non-enterprise deployment
behaves exactly as before. Enterprise deployments set ``[governance]`` directly
or via a compliance-regime pack, which compiles down to the same :class:`Policy`.

This module is pure (no I/O, no network, no agent-loop coupling) so the decision
logic is exhaustively unit-testable; wiring it into the kernel's tool path and
recording verdicts to the audit chain are separate, deliberate steps.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum

from .safety.tool_risk import risk_rank, tool_risk

log = logging.getLogger(__name__)

_RISK_LEVELS = ("low", "medium", "high")

# Floors operators reach for that aren't in the 3-level scale. "critical" /
# "severe" / "max" all name the most-dangerous tier, which here is "high".
_RISK_ALIASES = {
    "critical": "high",
    "severe": "high",
    "max": "high",
    "maximum": "high",
}

# Explicit "no floor" sentinels so an operator can intentionally clear a floor
# without it being read as a typo and clamped.
_RISK_DISABLE = {"none", "off", "disabled", "never"}


class Decision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_HUMAN = "require_human"


@dataclass(frozen=True)
class Verdict:
    """The outcome of a policy evaluation.

    ``rule`` names the policy clause that fired (``capability`` / ``deny_actions``
    / ``deny_min_risk`` / ``deny_above`` / ``require_human_actions`` /
    ``require_human_min_risk`` / ``require_human_above`` / ``default``) so an
    auditor can see *why*, not just *what*.
    """

    decision: Decision
    reason: str
    rule: str

    @property
    def allowed(self) -> bool:
        return self.decision is Decision.ALLOW

    @property
    def needs_human(self) -> bool:
        return self.decision is Decision.REQUIRE_HUMAN


def _risk_level(value: object) -> str | None:
    """Strict parse of a risk level: a known level or ``None``.

    Used for the caller-supplied ``risk=`` override in :func:`evaluate`, where an
    unrecognized value deliberately falls through to the tool classifier
    (``_risk_level(risk) or tool_risk(action)``). For a *configured floor* use
    :func:`_risk_floor`, which must never silently disable the gate.
    """
    return value if isinstance(value, str) and value in _RISK_LEVELS else None


def _risk_floor(value: object) -> str | None:
    """Normalize a configured risk *floor* to a known level, or ``None`` if unset.

    A floor (``deny_min_risk`` / ``require_human_min_risk``) only fires when it
    resolves to a real level: ``policy.deny_min_risk and ...``. So a *present but
    unrecognized* value that resolves to ``None`` silently disables the gate --
    fail-OPEN. ``deny_min_risk = "critical"`` (a natural, stricter-sounding
    choice) used to drop the deny floor entirely.

    Resolution, fail-closed on misconfiguration:
      - absent / empty / explicit disable sentinel ("none"/"off"/...) -> ``None``
      - a known level (case/space-insensitive) -> that level
      - a known alias ("critical"/"severe"/"max") -> "high" (the top tier)
      - anything else -> clamp to "high" with a warning, never silently disable
    """
    if value is None:
        return None
    if not isinstance(value, str):
        log.warning("governance: ignoring non-string risk floor %r", value)
        return None
    norm = value.strip().lower()
    if not norm or norm in _RISK_DISABLE:
        return None
    if norm in _RISK_LEVELS:
        return norm
    if norm in _RISK_ALIASES:
        return _RISK_ALIASES[norm]
    log.warning(
        "governance: unrecognized risk floor %r; clamping to 'high' (the "
        "strictest available level) rather than disabling the gate", value,
    )
    return "high"


def _amount_table(value: object) -> dict[str, float]:
    """Coerce a config value into an ``action -> threshold`` map.

    Accepts a TOML table ``{action = amount}`` (a ``"*"`` key is the catch-all),
    or a bare number which becomes the catch-all ``{"*": amount}``. Non-numeric
    entries are dropped.
    """
    out: dict[str, float] = {}
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return {"*": float(value)}
    if isinstance(value, dict):
        for k, v in value.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                out[str(k)] = float(v)
    return out


@dataclass(frozen=True)
class Policy:
    """Org-level action policy, layered on top of per-principal capabilities.

    - ``deny_actions`` / ``require_human_actions``: exact action (tool) names.
    - ``deny_min_risk`` / ``require_human_min_risk``: a risk *floor* -- any action
      whose classified risk is at or above it gets the verdict. ``None`` == no
      floor. (Risk order: low < medium < high.)
    - ``deny_above`` / ``require_human_above``: dollar-amount thresholds per action
      (a ``"*"`` key applies to every action). When a call carries an ``amount``
      above the threshold it gets the verdict — the finance delegation-of-authority
      tier ("< $5k auto, $5k–50k human, > $50k denied"). Thresholds are in one
      reporting currency; the caller normalises ``amount`` into it.
    """

    deny_actions: frozenset[str] = frozenset()
    require_human_actions: frozenset[str] = frozenset()
    deny_min_risk: str | None = None
    require_human_min_risk: str | None = None
    deny_above: dict[str, float] = field(default_factory=dict)
    require_human_above: dict[str, float] = field(default_factory=dict)
    require_fresh_human_approval: bool = False

    def is_empty(self) -> bool:
        return not (
            self.deny_actions
            or self.require_human_actions
            or self.deny_min_risk
            or self.require_human_min_risk
            or self.deny_above
            or self.require_human_above
        )

    @classmethod
    def from_config(cls) -> Policy:
        """Build the policy from the ``[governance]`` config table (opt-in)."""
        try:
            from .config import load_config
            cfg = (load_config() or {}).get("governance") or {}
        except Exception:
            cfg = {}

        def _names(key: str) -> frozenset[str]:
            v = cfg.get(key)
            if isinstance(v, (list, tuple, set)):
                return frozenset(str(x) for x in v if str(x))
            return frozenset()

        base = cls(
            deny_actions=_names("deny_actions"),
            require_human_actions=_names("require_human_actions"),
            deny_min_risk=_risk_floor(cfg.get("deny_min_risk")),
            require_human_min_risk=_risk_floor(cfg.get("require_human_min_risk")),
            deny_above=_amount_table(cfg.get("deny_above")),
            require_human_above=_amount_table(cfg.get("require_human_above")),
            require_fresh_human_approval=bool(cfg.get("require_fresh_human_approval")),
        )
        # Compliance mode profiles (e.g. [compliance] profiles = ["hipaa"]) tighten
        # the live policy strictest-wins. No profiles configured -> base unchanged,
        # so default behavior is byte-for-byte identical. Lazy import avoids a
        # governance <-> compliance_profiles import cycle.
        try:
            from . import compliance_profiles
            profiles = compliance_profiles.configured_profiles()
        except Exception:  # pragma: no cover -- config never blocks policy build
            profiles = []
        if not profiles:
            return base
        from dataclasses import replace

        from .finance.regimes import union_policies
        merged = union_policies([base, compliance_profiles.compile_policy(profiles)])
        # union_policies doesn't carry the fresh-approval flag; preserve it.
        return replace(merged, require_fresh_human_approval=base.require_fresh_human_approval)


def _threshold_for(table: dict[str, float], action: str) -> float | None:
    """The amount threshold for ``action`` (exact key, else the ``"*"`` default)."""
    if action in table:
        return table[action]
    return table.get("*")


def _money(amount: float | None, currency: str) -> str:
    if amount is None:
        return ""
    cur = f" {currency}" if currency else ""
    return f"{amount:g}{cur}"


def evaluate(
    action: str,
    *,
    risk: str | None = None,
    capability=None,
    policy: Policy | None = None,
    amount: float | None = None,
    currency: str = "",
) -> Verdict:
    """Decide ALLOW / DENY / REQUIRE_HUMAN for ``action`` (a tool name).

    Strictest-wins evaluation order:
      1. capability (least privilege) -- a forbidden action is denied outright;
      2. org hard-deny (``deny_actions`` / ``deny_min_risk`` / ``deny_above``);
      3. human-oversight gate (``require_human_actions`` / ``require_human_min_risk``
         / ``require_human_above``);
      4. otherwise allow.

    ``risk`` overrides the classifier (``safety.tool_risk``) when given. ``amount``
    (in ``currency``) is the transaction value, checked against the policy's
    dollar-threshold tiers — the finance delegation-of-authority gate. ``policy``
    defaults to :meth:`Policy.from_config`; ``capability`` is an optional
    :class:`maverick.capability.Capability`.
    """
    if policy is None:
        policy = Policy.from_config()
    eff_risk = _risk_level(risk) or tool_risk(action)

    # 1. Least privilege: the capability is the ceiling; deny below it wins.
    if capability is not None and not capability.permits(action):
        return Verdict(Decision.DENY, f"capability does not permit {action!r}",
                       "capability")

    # 2. Org hard-deny.
    if action in policy.deny_actions:
        return Verdict(Decision.DENY, f"{action!r} is denied by org policy",
                       "deny_actions")
    if policy.deny_min_risk and risk_rank(eff_risk) >= risk_rank(policy.deny_min_risk):
        return Verdict(Decision.DENY,
                       f"{eff_risk}-risk {action!r} denied by org policy",
                       "deny_min_risk")
    deny_thresh = _threshold_for(policy.deny_above, action)
    if amount is not None and deny_thresh is not None and amount > deny_thresh:
        return Verdict(Decision.DENY,
                       f"{action!r} amount {_money(amount, currency)} exceeds the "
                       f"deny ceiling {_money(deny_thresh, currency)}", "deny_above")

    # 3. Human-oversight gate (EU AI Act Art 14).
    if action in policy.require_human_actions:
        return Verdict(Decision.REQUIRE_HUMAN,
                       f"{action!r} requires human approval", "require_human_actions")
    if (policy.require_human_min_risk
            and risk_rank(eff_risk) >= risk_rank(policy.require_human_min_risk)):
        return Verdict(Decision.REQUIRE_HUMAN,
                       f"{eff_risk}-risk {action!r} requires human approval",
                       "require_human_min_risk")
    hitl_thresh = _threshold_for(policy.require_human_above, action)
    if amount is not None and hitl_thresh is not None and amount > hitl_thresh:
        return Verdict(Decision.REQUIRE_HUMAN,
                       f"{action!r} amount {_money(amount, currency)} exceeds the "
                       f"approval threshold {_money(hitl_thresh, currency)}, "
                       "requires human approval", "require_human_above")

    # 4. Default-allow.
    return Verdict(Decision.ALLOW, "permitted", "default")


__all__ = ["Decision", "Verdict", "Policy", "evaluate"]
