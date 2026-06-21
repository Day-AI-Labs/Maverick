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

import contextlib
import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # import only for type-checkers/IDEs; never at runtime
    from .capability import Capability

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

# Serializes the managed-registry load-modify-save. _save_managed is already
# atomic (no torn read), but the mutators are lock-free RMW: a set_revoked
# racing a put_agent/rotate would otherwise be clobbered -- a revoked external
# agent silently stays trusted. In-process threading.Lock + cross-process flock.
_MANAGED_LOCK = threading.Lock()


def _managed_locked():
    from contextlib import ExitStack

    from .file_lock import cross_process_lock
    stack = ExitStack()
    stack.enter_context(_MANAGED_LOCK)
    stack.enter_context(cross_process_lock(managed_path()))
    return stack


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


_INVALID = object()  # sentinel: a present-but-malformed security field


def _lifecycle_bound(entry: dict, key: str) -> object:
    """Parse a credential lifecycle bound (``not_before`` / ``expires_at``).

    Returns the positive epoch float, ``None`` when the field is ABSENT (no
    bound — legitimate), or the ``_INVALID`` sentinel when it is PRESENT but
    malformed. The caller drops the whole entry on ``_INVALID``: unlike a
    budget ceiling, a typo'd or zero/negative expiry must NOT silently coerce
    to "never expires" / "always valid" — that would make a misconfigured
    credential immortal (fail-open on a security field). Fail closed instead.
    """
    if key not in entry or entry.get(key) is None:
        return None
    parsed = _positive_float(entry.get(key))
    return parsed if parsed is not None else _INVALID


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
    # Per-caller bearers for the single-shared-bearer surfaces (A2A / gRPC goal
    # API / MCP), which carry no per-caller identity in-protocol. A request
    # presenting one resolves to principal "agent:<id>" and is governed by THIS
    # entry. Distinct per surface so a token leaked on one surface can't
    # authenticate another. "" = this agent has no bearer for that surface.
    a2a_token: str = ""
    grpc_token: str = ""
    mcp_token: str = ""
    # Key lifecycle (all default to "always valid" so existing configs are
    # byte-for-byte unchanged): a revoked or out-of-window entry is denied by
    # decide_inbound/decide_outbound/verify_identity. `not_before`/`expires_at`
    # are epoch seconds; supporting an overlap window (old key valid until
    # expires_at, new key not_before) is the zero-downtime rotation primitive.
    not_before: float | None = None
    expires_at: float | None = None
    revoked: bool = False

    def permits_inbound(self) -> bool:
        return self.direction in ("inbound", "both")

    def permits_outbound(self) -> bool:
        return self.direction in ("outbound", "both")

    def is_active(self, now: float | None = None) -> tuple[bool, str]:
        """``(active, rule)``. An expired/revoked/not-yet-valid entry is dead.

        ``rule`` is one of ``active`` / ``revoked`` / ``not_yet_valid`` /
        ``expired`` so a denial names *why* the credential is no longer good.
        """
        if self.revoked:
            return False, "revoked"
        t = time.time() if now is None else now
        if self.not_before is not None and t < self.not_before:
            return False, "not_yet_valid"
        if self.expires_at is not None and t >= self.expires_at:
            return False, "expired"
        return True, "active"

    def permits_scope(self, scope: str | None) -> bool:
        """True iff the agent may read memory tagged ``scope``.

        Empty ``data_scopes`` means *no* governed-memory access (fail-closed:
        an operator opts an external agent into a domain explicitly). A ``None``
        / unscoped query is always allowed — it carries no department to gate.
        """
        if not scope:
            return True
        return scope in self.data_scopes

    def capability(self, principal: str | None = None) -> Capability:
        """The tool ceiling this agent runs under, as a ``Capability``.

        Built lazily so the kernel imports without pulling in the capability
        module until a decision actually needs it. The entry's ``expires_at``
        propagates onto the grant so the handed-out capability expires with the
        registry entry (a grant must never outlive the trust that minted it).
        """
        from .capability import Capability
        return Capability(
            principal=principal or f"agent:{self.id}",
            allow_tools=self.allow_tools,
            deny_tools=self.deny_tools,
            max_risk=self.max_risk,
            expires_at=self.expires_at,
        )


@dataclass(frozen=True)
class TrustDecision:
    """The outcome of a trust-plane check.

    ``rule`` names the clause that fired (``disabled`` / ``not_in_registry`` /
    ``direction`` / ``capability`` / ``revoked`` / ``not_yet_valid`` /
    ``expired`` / ``data_scope`` / ``allow``) so the choice lands in the audit
    record with a reason, not just an allow/deny bit. ``capability`` is the tool
    ceiling the caller should narrow the run against — ``None`` when the plane
    is disengaged (no-op) so callers stay byte-for-byte identical to today.
    """

    allowed: bool
    reason: str
    rule: str
    agent: TrustedAgent | None = None
    capability: Capability | None = None

    @property
    def denied(self) -> bool:
        return not self.allowed


# -- config ----------------------------------------------------------------

def agent_trust_enforced(cfg: dict | None = None) -> bool:
    """Is the trust plane engaged (default-deny for external agents)?

    On when ``MAVERICK_AGENT_TRUST`` is truthy, ``[agent_trust] enforce =
    true``, or enterprise mode is active (sensitive-data deployments get the
    zero-trust boundary automatically). Off by default — disengaged means every
    decision is a no-op ALLOW, preserving kernel rule 1. Mirrors
    :func:`maverick.capability.capability_enforced`.

    Pass ``cfg`` (a pre-loaded config) to read engagement from the *same*
    config snapshot the registry is read from — :func:`load_trust_state` does
    this so one operation observes one consistent config view (no TOCTOU
    between the enforced flag and the registry).
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
        if cfg is None:
            from .config import load_config
            cfg = load_config() or {}
        return _truthy((cfg.get("agent_trust") or {}).get("enforce"))
    except Exception:
        return False


def load_trust_state() -> tuple[bool, dict[str, TrustedAgent]]:
    """Load ``(enforced, registry)`` from a SINGLE config read.

    Every cross-agent operation should take one snapshot of the trust state and
    thread it through :func:`decide_inbound` / :func:`decide_outbound` /
    :func:`clamp_budget` (which all accept ``registry=`` / ``enforced=``), so a
    config edit mid-request can't make one check see "engaged, old registry"
    and the next see "disengaged, new registry". Env/enterprise still win for
    the enforced flag (they're not part of the config table).
    """
    try:
        from .config import load_config
        cfg = load_config() or {}
    except Exception:
        cfg = {}
    return agent_trust_enforced(cfg), load_registry(cfg)


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
    not_before = _lifecycle_bound(entry, "not_before")
    expires_at = _lifecycle_bound(entry, "expires_at")
    if not_before is _INVALID or expires_at is _INVALID:
        # Fail closed: a present-but-malformed lifecycle bound drops the entry
        # (the agent is simply untrusted) rather than minting an immortal cred.
        log.warning("[agent_trust] agent %r: malformed not_before/expires_at; "
                    "dropping entry (fail-closed)", agent_id)
        return None
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
        a2a_token=str(entry.get("a2a_token") or ""),
        grpc_token=str(entry.get("grpc_token") or ""),
        mcp_token=str(entry.get("mcp_token") or ""),
        not_before=not_before,  # type: ignore[arg-type]  # float|None (not _INVALID)
        expires_at=expires_at,  # type: ignore[arg-type]
        revoked=bool(entry.get("revoked")),
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
    out: dict[str, TrustedAgent] = {}
    if isinstance(raw, list):
        for item in raw[:_MAX_AGENTS]:
            if not isinstance(item, dict):
                log.warning("[agent_trust] skipping non-table entry %r", item)
                continue
            agent = _agent_from_entry(item)
            if agent is not None and agent.id not in out:
                out[agent.id] = agent
    elif raw is not None:
        log.warning("[agent_trust] agents must be a list; ignoring")
    # Merge the CLI-managed registry overlay (agent_trust.json, client-scoped):
    # managed entries add to / override the hand-edited config ones, so
    # `maverick trust` add/rotate/revoke take effect without editing TOML.
    for item in _load_managed():
        agent = _agent_from_entry(item)
        if agent is None:
            continue
        if agent.id in out or len(out) < _MAX_AGENTS:
            out[agent.id] = agent
    return out


# -- CLI-managed registry overlay (JSON; client-scoped via the tenant floor) --

def managed_path():
    """Path to the CLI-managed registry overlay (``agent_trust.json``).

    Under the active client's data dir (the tenant floor), so the managed
    registry is automatically per-deployment/per-client.
    """
    from .paths import data_dir
    return data_dir("agent_trust.json")


def _load_managed() -> list[dict]:
    import json
    try:
        p = managed_path()
        if not p.exists():
            return []
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:  # pragma: no cover - a corrupt overlay must not crash reads
        log.warning("agent_trust: managed registry unreadable: %s", e)
        return []
    return [a for a in data if isinstance(a, dict)] if isinstance(data, list) else []


def _save_managed(entries: list[dict]) -> None:
    import json
    import os as _os
    import tempfile
    p = managed_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".agent_trust.", suffix=".json")
    try:
        with _os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(entries[:_MAX_AGENTS], f, indent=2, sort_keys=True)
        _os.chmod(tmp, 0o600)
        _os.replace(tmp, p)
    except Exception:
        with contextlib.suppress(OSError):
            _os.unlink(tmp)
        raise


def put_agent(entry: dict) -> TrustedAgent:
    """Add or replace a managed agent (by ``id``). Returns the parsed agent.

    Validates via :func:`_agent_from_entry`; raises :class:`AgentTrustError` on a
    malformed entry so the CLI surfaces a clear error instead of silently
    dropping it."""
    agent = _agent_from_entry(entry)
    if agent is None:
        raise AgentTrustError(f"invalid agent entry: {entry!r}")
    with _managed_locked():
        entries = [e for e in _load_managed() if str(e.get("id") or "") != agent.id]
        clean = {k: v for k, v in entry.items() if v not in (None, "", [], {})}
        clean["id"] = agent.id
        entries.append(clean)
        _save_managed(entries)
    return agent


def remove_agent(agent_id: str) -> bool:
    """Delete a managed agent by id. Returns True if one was removed."""
    with _managed_locked():
        entries = _load_managed()
        kept = [e for e in entries if str(e.get("id") or "") != agent_id]
        if len(kept) == len(entries):
            return False
        _save_managed(kept)
    return True


def set_revoked(agent_id: str, revoked: bool) -> bool:
    """Mark a managed agent revoked / unrevoked. Returns True if it existed."""
    with _managed_locked():
        entries = _load_managed()
        found = False
        for e in entries:
            if str(e.get("id") or "") == agent_id:
                e["revoked"] = bool(revoked)
                found = True
        if found:
            _save_managed(entries)
    return found


def local_pubkey() -> str | None:
    """This deployment's pinned Ed25519 public key (hex) for out-of-band
    distribution to peers, or ``None`` when ``cryptography`` is unavailable."""
    try:
        from .audit import signing as audit_signing
        if not audit_signing._have_crypto():
            return None
        _priv, pub, _key_id = audit_signing._load_or_create_keypair()
        return pub.hex()
    except Exception:  # pragma: no cover
        return None


def lookup(agent_id: str, *, registry: dict[str, TrustedAgent] | None = None) -> TrustedAgent | None:
    reg = load_registry() if registry is None else registry
    return reg.get(agent_id)


_TOKEN_ATTRS = {"a2a": "a2a_token", "grpc": "grpc_token", "mcp": "mcp_token"}


def agent_for_token(
    token: str, surface: str, *, registry: dict[str, TrustedAgent] | None = None,
) -> TrustedAgent | None:
    """Resolve a valid presented per-caller bearer for ``surface`` (a2a/grpc/mcp)
    to its registered agent, or ``None``.

    Constant-time compares against every entry's surface token (scanning all so
    timing doesn't reveal which matched); an empty token never matches. A token
    is an authentication credential, so it only resolves while the matching
    trust entry is active and inbound-permitted -- revoked, expired,
    not-yet-valid, or outbound-only entries therefore fail authentication for
    management methods as well as task execution. This is how a per-caller
    bearer maps to a specific :class:`TrustedAgent` so the registry can govern
    individual callers on a single-shared-bearer surface."""
    import hmac
    attr = _TOKEN_ATTRS.get(surface)
    presented = (token or "").encode()
    if attr is None or not presented:
        return None
    reg = load_registry() if registry is None else registry
    matched: TrustedAgent | None = None
    for agent in reg.values():
        configured = getattr(agent, attr, "")
        if configured and hmac.compare_digest(configured.encode(), presented):
            active, _ = agent.is_active()
            if active and agent.permits_inbound():
                matched = matched or agent
    return matched


def agent_for_a2a_token(
    token: str, *, registry: dict[str, TrustedAgent] | None = None,
) -> TrustedAgent | None:
    """Back-compat wrapper: resolve a per-caller A2A bearer (see
    :func:`agent_for_token`)."""
    return agent_for_token(token, "a2a", registry=registry)


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
    active, why = agent.is_active()
    if not active:
        return TrustDecision(
            False, f"agent {agent_id!r} credential is {why}", why, agent)
    if not agent.permits_inbound():
        return TrustDecision(
            False, f"agent {agent_id!r} is not permitted inbound "
                   f"(direction={agent.direction!r})", "direction", agent)
    cap = agent.capability()
    requested = _names(requested_tools)
    # Normalise case BEFORE validating: a request for "HIGH"/"Critical" must not
    # slip past the ceiling because it didn't match the lowercase risk set. An
    # unrecognised risk word is REFUSED (fail-closed), never waved through.
    if max_risk is not None:
        norm = str(max_risk).strip().lower()
        if norm and _risk(norm) is None:
            return TrustDecision(
                False, f"agent {agent_id!r} requested unrecognised risk "
                       f"{max_risk!r}", "capability", agent, cap)
        max_risk = norm or None
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
    active, why = agent.is_active()
    if not active:
        return TrustDecision(
            False, f"agent {agent_id!r} credential is {why}", why, agent)
    if not agent.permits_outbound():
        return TrustDecision(
            False, f"agent {agent_id!r} is not permitted outbound "
                   f"(direction={agent.direction!r})", "direction", agent)
    return TrustDecision(True, "permitted", "allow", agent, agent.capability())


def decide_memory_access(
    agent_id: str,
    domain: str | None,
    *,
    registry: dict[str, TrustedAgent] | None = None,
    enforced: bool | None = None,
) -> TrustDecision:
    """Decide whether external agent ``agent_id`` may read/write memory tagged
    ``domain`` — the gate shared by fleet-memory ingest AND recall.

    Disengaged -> no-op ALLOW. Engaged: the agent must be registered, active,
    inbound-permitted, and ``domain`` must be a NON-EMPTY scope the agent's
    ``data_scopes`` allows. An unscoped (``domain=None``) request is **denied**
    when engaged — an external agent cannot read across all departments by
    simply omitting the scope (the old ``permits_scope(None) -> True`` bypass).
    """
    if not _resolve(enforced):
        return TrustDecision(True, "agent trust plane disengaged", "disabled")
    agent = lookup(agent_id, registry=registry)
    if agent is None:
        return TrustDecision(
            False, f"external agent {agent_id!r} is not in the trust registry",
            "not_in_registry")
    active, why = agent.is_active()
    if not active:
        return TrustDecision(
            False, f"agent {agent_id!r} credential is {why}", why, agent)
    if not agent.permits_inbound():
        return TrustDecision(
            False, f"agent {agent_id!r} is not permitted inbound "
                   f"(direction={agent.direction!r})", "direction", agent)
    scope = (domain or "").strip()
    if not scope:
        return TrustDecision(
            False, f"agent {agent_id!r} must declare a data scope (one of "
                   f"{sorted(agent.data_scopes)}) — unscoped access is denied",
            "data_scope", agent)
    if not agent.permits_scope(scope):
        return TrustDecision(
            False, f"agent {agent_id!r} may not access data scope {scope!r}",
            "data_scope", agent)
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
    active, why = agent.is_active()
    if not active:
        return False, f"agent {agent_id!r} credential is {why}"
    if not agent.pubkey:
        return False, f"agent {agent_id!r} has no pinned public key"
    # Bind the claimed identity to the signed envelope explicitly. verify_envelope
    # keys peers on the envelope's own `origin`, so without this check an envelope
    # whose origin differs from agent_id would be rejected with a confusing "not
    # in peer trust list" (or, if a deployment's signing origin legitimately
    # differs from its registry id, a valid envelope would silently fail). Assert
    # the binding up front with a clear reason.
    if not isinstance(envelope, dict):
        return False, "envelope is not an object"
    origin = envelope.get("origin")
    if origin != agent_id:
        return False, (f"envelope origin {origin!r} does not match the claimed "
                       f"agent {agent_id!r}")
    from .federation_envelope import verify_envelope
    return verify_envelope(
        envelope,
        expected_schema=expected_schema,
        peers={agent.id: {"origin": agent.id, "pubkey": agent.pubkey}},
    )


# -- audit + status --------------------------------------------------------

def record_denied(
    agent_id: str,
    decision: TrustDecision | None = None,
    *,
    direction: str,
    correlation_id: str = "",
    rule: str | None = None,
    reason: str | None = None,
) -> None:
    """Record a trust-plane denial to the audit chain (fail-safe).

    Pass a :class:`TrustDecision` (the usual case) or ``rule=``/``reason=``
    directly — the latter lets a caller log a denial without fabricating a
    throwaway decision object. A denial is a security-relevant event, so it
    lands in the Operating Record alongside capability/governance denials.
    Never raises — an audit-path failure must not change the deny outcome.
    """
    if decision is not None:
        rule, reason = decision.rule, decision.reason
    try:
        from .audit import record
        from .audit.events import EventKind
        record(
            EventKind.AGENT_TRUST_DENIED, agent="agent_trust",
            peer=agent_id, direction=direction, rule=rule or "denied",
            reason=reason or "", correlation_id=correlation_id,
        )
    except Exception as e:  # pragma: no cover - audit is best-effort here
        log.warning("agent_trust: audit record failed: %s", e)


def status() -> dict[str, Any]:
    """A summary for ``maverick doctor`` / dashboards: engaged flag + roster."""
    enforced, reg = load_trust_state()
    return {
        "enforced": enforced,
        "count": len(reg),
        "agents": [
            {
                "id": a.id,
                "direction": a.direction,
                "pinned_key": bool(a.pubkey),
                "max_risk": a.max_risk,
                "data_scopes": sorted(a.data_scopes),
                "active": a.is_active()[0],
                "expires_at": a.expires_at,
            }
            for a in reg.values()
        ],
    }


__all__ = [
    "AgentTrustError",
    "TrustedAgent",
    "TrustDecision",
    "agent_trust_enforced",
    "load_trust_state",
    "load_registry",
    "managed_path",
    "put_agent",
    "remove_agent",
    "set_revoked",
    "local_pubkey",
    "lookup",
    "agent_for_token",
    "agent_for_a2a_token",
    "decide_inbound",
    "decide_outbound",
    "decide_memory_access",
    "clamp_budget",
    "verify_identity",
    "record_denied",
    "status",
    "valid_agent_id",
]
