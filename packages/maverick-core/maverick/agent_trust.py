"""Agent Trust Plane — the single registry + decision point for talking to
*external* agents.

Maverick grew several independent cross-agent pathways, each with its own
enable flag, its own auth model, and its own "who's allowed" list:

  * federation (``[federation] peers``)        — shared-secret tokens;
  * A2A tasks (``[a2a]``)                       — a single bearer token;
  * fleet memory (``agents.ndjson`` roster)     — a registration list;
  * channel/marketplace federation             — Ed25519 pinned keys.

So the one question a company actually asks — *"which outside agents may our
agents talk to, and what may they do or see?"* — had no single answer; it was
smeared across five config surfaces in three incompatible identity models, the
weakest of which (a symmetric shared secret) sat on the most powerful path
(goal delegation).

This module is the rebuild: **one registry** (``[agent_trust] agents``) that
names every trusted external agent by its *pinned Ed25519 public key* (the same
asymmetric identity ``federation_envelope`` already uses), declares the
**direction** it may communicate, and bounds **what it may do** (a tool/risk
ceiling), **how much it may spend** (a budget ceiling), and **what company data
it may read** (data scopes). And **one decision point** —
:func:`decide_inbound` / :func:`decide_outbound` — that every transport
consults before a cross-agent interaction.

**Posture (default-deny at the boundary, open in-process).** The trust plane is
*engaged* exactly when :func:`agent_trust_enforced` is true — automatically
under enterprise mode (the "I handle sensitive data" switch, mirroring
:func:`maverick.capability.capability_enforced`), or explicitly via
``[agent_trust] enforce = true`` / ``MAVERICK_AGENT_TRUST=1``. When engaged, an
external agent absent from the registry is **denied** (zero-trust at the
company edge). When *not* engaged it is a strict no-op — every decision is
ALLOW with no ceiling — so kernel rule 1 (default-open, fail-open) and every
existing deployment behave byte-for-byte as before. In-process peer messaging
(``agent_bus``) is internal and never gated here.

Pure and offline (no I/O beyond reading config), so the decision logic is
exhaustively unit-testable; wiring it into each transport is a separate,
deliberate step.

Registry format (``~/.maverick/config.toml``)::

    [agent_trust]
    enforce = true                       # or rely on [enterprise] mode
    agents = [
      { id = "vega", pubkey = "<64-hex Ed25519>", direction = "both",
        allow_tools = ["read_file", "http_fetch"], max_risk = "medium",
        max_dollars = 2.0, max_wall_seconds = 600, data_scopes = ["support"] },
      { id = "copilot", pubkey = "<64-hex>", direction = "inbound",
        allow_tools = ["research"], max_risk = "low" },
    ]
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

# An agent id becomes an audit field and a federation principal segment, so the
# charset matches federation_envelope's origin rules: no "/", no whitespace.
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
# Raw Ed25519 public key, hex-encoded: exactly 32 bytes (matches
# federation_envelope._PUBKEY_RE).
_PUBKEY_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_RISK_LEVELS = ("low", "medium", "high")
_DIRECTIONS = frozenset({"inbound", "outbound", "both"})
_MAX_AGENTS = 256

_TRUE_WORDS = {"1", "true", "yes", "on"}


class AgentTrustError(ValueError):
    """A registry entry or request the trust plane refuses to deal with."""


def valid_agent_id(agent_id: object) -> bool:
    return isinstance(agent_id, str) and bool(_ID_RE.fullmatch(agent_id))


def _truthy(value: object) -> bool:
    return str(value).strip().lower() in _TRUE_WORDS


def _risk(value: object) -> str | None:
    return value if isinstance(value, str) and value in _RISK_LEVELS else None


def _positive_float(value: object) -> float | None:
    """Coerce a config value to a positive float, or None (no ceiling)."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def _names(value: object) -> frozenset[str]:
    if isinstance(value, str):
        value = [value]
    if isinstance(value, (list, tuple, set)):
        return frozenset(str(v).strip() for v in value if str(v).strip())
    return frozenset()


@dataclass(frozen=True)
class TrustedAgent:
    """One ``[agent_trust] agents`` entry — a single external agent's identity,
    reach, and limits. Frozen so a parsed registry can't be mutated under a
    decision.

    - ``pubkey`` is the *pinned* Ed25519 public key (hex); it is the agent's
      canonical identity for asymmetric verification. ``""`` means no pinned
      key (identity must then come from a transport's own auth, e.g. the
      federation shared token — discouraged but allowed for migration).
    - ``direction`` bounds who may start the conversation: ``inbound`` (the
      agent may call us), ``outbound`` (we may call it), or ``both``.
    - ``allow_tools`` / ``deny_tools`` / ``max_risk`` form the tool ceiling the
      agent runs under, expressed as a :class:`~maverick.capability.Capability`.
    - ``max_dollars`` / ``max_wall_seconds`` bound a delegated run's spend.
    - ``data_scopes`` are the memory domains/departments the agent may read
      (consumed by fleet-memory recall); empty == no governed-memory access.
    """

    id: str
    pubkey: str = ""
    direction: str = "both"
    allow_tools: frozenset[str] = frozenset()
    deny_tools: frozenset[str] = frozenset()
    max_risk: str | None = None
    max_dollars: float | None = None
    max_wall_seconds: float | None = None
    data_scopes: frozenset[str] = frozenset()

    def permits_inbound(self) -> bool:
        return self.direction in ("inbound", "both")

    def permits_outbound(self) -> bool:
        return self.direction in ("outbound", "both")

    def permits_scope(self, scope: str | None) -> bool:
        """True iff the agent may read memory tagged ``scope``.

        Empty ``data_scopes`` means *no* governed-memory access (fail-closed:
        an operator opts an external agent into a domain explicitly). A ``None``
        / unscoped query is always allowed — it carries no department to gate.
        """
        if not scope:
            return True
        return scope in self.data_scopes

    def capability(self, principal: str | None = None):
        """The tool ceiling this agent runs under, as a ``Capability``.

        Built lazily so the kernel imports without pulling in the capability
        module until a decision actually needs it.
        """
        from .capability import Capability
        return Capability(
            principal=principal or f"agent:{self.id}",
            allow_tools=self.allow_tools,
            deny_tools=self.deny_tools,
            max_risk=self.max_risk,
        )


@dataclass(frozen=True)
class TrustDecision:
    """The outcome of a trust-plane check.

    ``rule`` names the clause that fired (``disabled`` / ``not_in_registry`` /
    ``direction`` / ``capability`` / ``allow``) so the choice lands in the audit
    record with a reason, not just an allow/deny bit. ``capability`` is the tool
    ceiling the caller should narrow the run against — ``None`` when the plane
    is disengaged (no-op) so callers stay byte-for-byte identical to today.
    """

    allowed: bool
    reason: str
    rule: str
    agent: TrustedAgent | None = None
    capability: Any = None  # Capability | None

    @property
    def denied(self) -> bool:
        return not self.allowed


# -- config ----------------------------------------------------------------

def agent_trust_enforced() -> bool:
    """Is the trust plane engaged (default-deny for external agents)?

    On when ``MAVERICK_AGENT_TRUST`` is truthy, ``[agent_trust] enforce =
    true``, or enterprise mode is active (sensitive-data deployments get the
    zero-trust boundary automatically). Off by default — disengaged means every
    decision is a no-op ALLOW, preserving kernel rule 1. Mirrors
    :func:`maverick.capability.capability_enforced`.
    """
    env = os.environ.get("MAVERICK_AGENT_TRUST")
    if env is not None and env.strip() != "":
        return _truthy(env)
    try:
        from .enterprise import enterprise_enabled
        if enterprise_enabled():
            return True
    except Exception:  # pragma: no cover - enterprise read never blocks
        pass
    try:
        from .config import load_config
        cfg = (load_config() or {}).get("agent_trust") or {}
        return _truthy(cfg.get("enforce"))
    except Exception:
        return False


def _agent_from_entry(entry: dict) -> TrustedAgent | None:
    """Parse one registry entry, or ``None`` if it's malformed (fail-closed: a
    bad entry simply never matches, it does not broaden trust)."""
    agent_id = str(entry.get("id") or entry.get("origin") or "").strip()
    if not valid_agent_id(agent_id):
        log.warning("[agent_trust] skipping entry with bad id %r", agent_id)
        return None
    pubkey = str(entry.get("pubkey") or "").strip().lower()
    if pubkey and not _PUBKEY_RE.fullmatch(pubkey):
        log.warning("[agent_trust] agent %r: ignoring malformed pubkey", agent_id)
        pubkey = ""
    direction = str(entry.get("direction") or "both").strip().lower()
    if direction not in _DIRECTIONS:
        log.warning("[agent_trust] agent %r: bad direction %r; using 'both'",
                    agent_id, direction)
        direction = "both"
    return TrustedAgent(
        id=agent_id,
        pubkey=pubkey,
        direction=direction,
        allow_tools=_names(entry.get("allow_tools")),
        deny_tools=_names(entry.get("deny_tools")),
        max_risk=_risk(entry.get("max_risk")),
        max_dollars=_positive_float(entry.get("max_dollars")),
        max_wall_seconds=_positive_float(entry.get("max_wall_seconds")),
        data_scopes=_names(entry.get("data_scopes")),
    )


def load_registry(cfg: dict | None = None) -> dict[str, TrustedAgent]:
    """Parse ``[agent_trust] agents`` into ``{id: TrustedAgent}``.

    Forgiving like ``federation.load_peers``: junk entries are skipped with a
    warning, duplicates keep the first occurrence, and nothing here ever raises
    — an unreadable config yields an empty registry (which, when the plane is
    engaged, denies every external agent: the fail-closed direction).
    """
    if cfg is None:
        try:
            from .config import load_config
            cfg = load_config() or {}
        except Exception:
            log.warning("agent_trust: config unreadable; registry is empty")
            return {}
    raw = (cfg.get("agent_trust") or {}).get("agents")
    if not isinstance(raw, list):
        if raw is not None:
            log.warning("[agent_trust] agents must be a list; ignoring")
        return {}
    out: dict[str, TrustedAgent] = {}
    for item in raw[:_MAX_AGENTS]:
        if not isinstance(item, dict):
            log.warning("[agent_trust] skipping non-table entry %r", item)
            continue
        agent = _agent_from_entry(item)
        if agent is not None and agent.id not in out:
            out[agent.id] = agent
    return out


def lookup(agent_id: str, *, registry: dict[str, TrustedAgent] | None = None) -> TrustedAgent | None:
    reg = load_registry() if registry is None else registry
    return reg.get(agent_id)


# -- decision point --------------------------------------------------------

def _resolve(enforced: bool | None) -> bool:
    return agent_trust_enforced() if enforced is None else enforced


def decide_inbound(
    agent_id: str,
    *,
    requested_tools: Any = (),
    max_risk: str | None = None,
    registry: dict[str, TrustedAgent] | None = None,
    enforced: bool | None = None,
) -> TrustDecision:
    """Decide whether external agent ``agent_id`` may act *on us*.

    Returns a :class:`TrustDecision`. When the plane is disengaged the decision
    is a no-op ALLOW with ``capability=None`` (callers change nothing). When
    engaged: an agent absent from the registry is DENIED; an agent whose
    ``direction`` forbids inbound is DENIED; an agent whose ceiling does not
    permit a *requested* (required) tool is DENIED; otherwise ALLOWED, and the
    decision carries the agent's :class:`Capability` ceiling for the caller to
    narrow the run against.
    """
    if not _resolve(enforced):
        return TrustDecision(True, "agent trust plane disengaged", "disabled")
    agent = lookup(agent_id, registry=registry)
    if agent is None:
        return TrustDecision(
            False, f"external agent {agent_id!r} is not in the trust registry",
            "not_in_registry")
    if not agent.permits_inbound():
        return TrustDecision(
            False, f"agent {agent_id!r} is not permitted inbound "
                   f"(direction={agent.direction!r})", "direction", agent)
    cap = agent.capability()
    requested = _names(requested_tools)
    if max_risk and _risk(max_risk) is None:
        # An unrecognized risk word is treated as the safe default rather than
        # silently lifting the ceiling.
        max_risk = None
    denied = sorted(t for t in requested if not cap.permits(t))
    if denied:
        return TrustDecision(
            False, f"agent {agent_id!r} may not use required tools: {denied}",
            "capability", agent, cap)
    if max_risk and agent.max_risk and _rank(max_risk) > _rank(agent.max_risk):
        return TrustDecision(
            False, f"agent {agent_id!r} requested risk {max_risk!r} above its "
                   f"ceiling {agent.max_risk!r}", "capability", agent, cap)
    return TrustDecision(True, "permitted", "allow", agent, cap)


def decide_outbound(
    agent_id: str,
    *,
    registry: dict[str, TrustedAgent] | None = None,
    enforced: bool | None = None,
) -> TrustDecision:
    """Decide whether *we* may initiate contact with external agent ``agent_id``.

    The egress half: a company controls which outside agents its agents may
    *dial*. Disengaged -> no-op ALLOW. Engaged -> an unknown agent, or one whose
    ``direction`` forbids outbound, is DENIED before any connection is opened.
    """
    if not _resolve(enforced):
        return TrustDecision(True, "agent trust plane disengaged", "disabled")
    agent = lookup(agent_id, registry=registry)
    if agent is None:
        return TrustDecision(
            False, f"external agent {agent_id!r} is not in the trust registry",
            "not_in_registry")
    if not agent.permits_outbound():
        return TrustDecision(
            False, f"agent {agent_id!r} is not permitted outbound "
                   f"(direction={agent.direction!r})", "direction", agent)
    return TrustDecision(True, "permitted", "allow", agent, agent.capability())


def _rank(risk: str) -> int:
    try:
        return _RISK_LEVELS.index(risk)
    except ValueError:
        return -1


def clamp_budget(
    agent: TrustedAgent | None,
    *,
    max_dollars: float | None = None,
    max_wall_seconds: float | None = None,
) -> tuple[float | None, float | None]:
    """Clamp a requested run budget DOWN to the agent's ceiling (never up).

    ``None`` on either side means "no ceiling from that side"; the result is the
    tighter of the two. Used so a delegated run can request *less* than its
    ceiling but never more.
    """
    def _min(req: float | None, cap: float | None) -> float | None:
        vals = [v for v in (req, cap) if v is not None]
        return min(vals) if vals else None

    if agent is None:
        return max_dollars, max_wall_seconds
    return (
        _min(max_dollars, agent.max_dollars),
        _min(max_wall_seconds, agent.max_wall_seconds),
    )


# -- identity --------------------------------------------------------------

def verify_identity(
    agent_id: str,
    envelope: object,
    *,
    expected_schema: str,
    registry: dict[str, TrustedAgent] | None = None,
) -> tuple[bool, str]:
    """Verify a signed envelope against ``agent_id``'s *pinned* public key.

    Reuses :func:`maverick.federation_envelope.verify_envelope` — the same
    Ed25519 / pinned-key, fail-closed primitive the channel and marketplace
    paths use — so every external surface shares one asymmetric identity model
    instead of inventing its own. Fails closed: an unknown agent, an agent with
    no pinned key, a schema/signature mismatch, or absent ``cryptography`` all
    return ``(False, reason)`` and never raise.
    """
    agent = lookup(agent_id, registry=registry)
    if agent is None:
        return False, f"agent {agent_id!r} is not in the trust registry"
    if not agent.pubkey:
        return False, f"agent {agent_id!r} has no pinned public key"
    from .federation_envelope import verify_envelope
    return verify_envelope(
        envelope,
        expected_schema=expected_schema,
        peers={agent.id: {"origin": agent.id, "pubkey": agent.pubkey}},
    )


# -- audit + status --------------------------------------------------------

def record_denied(
    agent_id: str,
    decision: TrustDecision,
    *,
    direction: str,
    correlation_id: str = "",
) -> None:
    """Record a trust-plane denial to the audit chain (fail-safe).

    A denial is a security-relevant event, so it lands in the Operating Record
    alongside capability/governance denials. Never raises — an audit-path
    failure must not change the deny outcome.
    """
    try:
        from .audit import record
        from .audit.events import EventKind
        record(
            EventKind.AGENT_TRUST_DENIED, agent="agent_trust",
            peer=agent_id, direction=direction, rule=decision.rule,
            reason=decision.reason, correlation_id=correlation_id,
        )
    except Exception as e:  # pragma: no cover - audit is best-effort here
        log.warning("agent_trust: audit record failed: %s", e)


def status() -> dict[str, Any]:
    """A summary for ``maverick doctor`` / dashboards: engaged flag + roster."""
    reg = load_registry()
    return {
        "enforced": agent_trust_enforced(),
        "count": len(reg),
        "agents": [
            {
                "id": a.id,
                "direction": a.direction,
                "pinned_key": bool(a.pubkey),
                "max_risk": a.max_risk,
                "data_scopes": sorted(a.data_scopes),
            }
            for a in reg.values()
        ],
    }


__all__ = [
    "AgentTrustError",
    "TrustedAgent",
    "TrustDecision",
    "agent_trust_enforced",
    "load_registry",
    "lookup",
    "decide_inbound",
    "decide_outbound",
    "clamp_budget",
    "verify_identity",
    "record_denied",
    "status",
    "valid_agent_id",
]
