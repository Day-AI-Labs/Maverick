"""Signed, attenuating capabilities for agents — the P0 identity layer.

A :class:`Capability` is a scoped grant (which tools, up to what risk) bound
to a *principal*. Unlike the static config ACL (:mod:`maverick.safety.tool_acl`),
a capability can only be **attenuated** (narrowed) as it propagates to child
agents, so a sub-agent can never exceed what its parent was granted — least
privilege by construction, which is the "agent exceeded its permissions"
failure mode the 2026 enterprise surveys flag as the #1 risk.

Grants can be Ed25519-signed so they are independently verifiable and
auditable, reusing the audit-signing key primitives (no new crypto).

Default-open and opt-in: when no capability is set on the context/agent,
enforcement is a no-op and behaviour is unchanged. Turn it on with
``[capabilities] enforce = true`` or ``MAVERICK_ENFORCE_CAPABILITIES=1``.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from fnmatch import fnmatch

from .safety.tool_risk import RISK_LEVELS, risk_rank, tool_risk

# The coordination control-plane: the tools that let a specialist participate in
# the workforce -- discover peers, spawn specialists, fan out a swarm, and
# message/delegate across the agent bus. These are how "individual agents
# communicate to complete things", so a capability PERMITS them by default even
# when a narrow allowlist or a low risk-ceiling would otherwise block them
# (several are classified high-risk because they fan out budget). An operator can
# still revoke coordination for a specific principal by listing a tool in
# ``deny_tools`` -- deny always wins. The fan-out stays bounded by max_depth, the
# budget, and each spawned child's own (attenuated) envelope.
COORDINATION_TOOLS: frozenset[str] = frozenset({
    "spawn_specialist", "spawn_swarm", "spawn_subagent", "list_specialists",
    "send_to_agent", "recv_from_agent", "delegate_to_agent", "ask_user",
})


@dataclass(frozen=True)
class Capability:
    """A principal's scoped, attenuable grant over the tool surface.

    - ``allow_tools``: empty set means *all* tools (matches the ACL's
      "empty allow-list == all" convention); a non-empty set is a whitelist.
    - ``deny_tools``: always subtractive; deny wins over allow.
    - ``max_risk``: optional ceiling ("low"/"medium"/"high"); ``None`` == no cap.
    - ``expires_at``: optional epoch-seconds expiry; ``None`` == never.
    - ``allow_paths``: fnmatch-style filesystem path globs the principal may
      touch; empty set means *all* paths (same "empty == all" convention).
    - ``allow_hosts``: fnmatch-style network host globs the principal may reach;
      empty set means *all* hosts.
    """

    principal: str
    allow_tools: frozenset[str] = frozenset()
    deny_tools: frozenset[str] = frozenset()
    max_risk: str | None = None
    expires_at: float | None = None
    allow_paths: frozenset[str] = frozenset()
    allow_hosts: frozenset[str] = frozenset()
    ancestors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        # Fail closed at the trust boundary: an unknown max_risk string -- e.g.
        # an operator who writes "none"/"readonly" in a role/domain TOML
        # intending the *tightest* ceiling -- must not silently rank as "medium"
        # (risk_rank's default for unknown levels) and thereby PERMIT medium-risk
        # tools (the default class for any unclassified/MCP-adjacent tool).
        # Coerce any unrecognized ceiling to the most restrictive level.
        if self.max_risk is not None and self.max_risk not in RISK_LEVELS:
            object.__setattr__(self, "max_risk", RISK_LEVELS[0])

    def revocation_principals(self) -> tuple[str, ...]:
        """Principals whose revocation invalidates this grant.

        A child grant is re-bound to the child principal, but revoking any
        ancestor must still kill the descendant grant immediately. Check the
        current principal first, then walk back toward the root.
        """
        return (self.principal, *reversed(self.ancestors))

    def is_expired(self, now: float | None = None) -> bool:
        if self.expires_at is None:
            return False
        return (time.time() if now is None else now) >= self.expires_at

    def permits(self, tool_name: str, *, now: float | None = None) -> bool:
        """True iff this grant allows ``tool_name`` (deny > allow > risk)."""
        if self.is_expired(now):
            return False
        if tool_name in self.deny_tools:
            return False
        # Coordination floor: the workforce control-plane is permitted unless the
        # operator explicitly denied it above -- a narrow allowlist or a low risk
        # ceiling must not isolate an agent from spawning/messaging its peers.
        if tool_name in COORDINATION_TOOLS:
            return True
        if self.allow_tools == frozenset({_DENY_ALL}):
            return False
        if self.allow_tools and tool_name not in self.allow_tools:
            return False
        if (
            self.max_risk is not None
            and risk_rank(tool_risk(tool_name)) > risk_rank(self.max_risk)
        ):
            return False
        return True

    def permits_path(self, path: str) -> bool:
        """True iff ``path`` matches some ``allow_paths`` glob (empty == all)."""
        if not self.allow_paths:
            return True
        return any(fnmatch(path, pat) for pat in self.allow_paths)

    def permits_host(self, host: str) -> bool:
        """True iff ``host`` matches some ``allow_hosts`` glob (empty == all)."""
        if not self.allow_hosts:
            return True
        return any(fnmatch(host, pat) for pat in self.allow_hosts)

    def intersect(self, other: Capability, *, principal: str | None = None) -> Capability:
        """Return the least-authority intersection of two grants.

        Empty allow/tool/path/host sets mean "all", so intersection must preserve
        that convention without letting a restricted peer grant broaden an
        ambient grant (or vice versa). Denies union, risk ceilings tighten, and
        the earliest expiry wins.
        """
        if self.max_risk is None:
            max_risk = other.max_risk
        elif other.max_risk is None:
            max_risk = self.max_risk
        else:
            max_risk = min(self.max_risk, other.max_risk, key=risk_rank)
        expiries = [e for e in (self.expires_at, other.expires_at) if e is not None]
        return Capability(
            principal=principal or self.principal,
            allow_tools=_narrow_tools(
                self.allow_tools, other.allow_tools or None
            ),
            deny_tools=self.deny_tools | other.deny_tools,
            max_risk=max_risk,
            expires_at=min(expiries) if expiries else None,
            allow_paths=_narrow_globs(
                self.allow_paths, other.allow_paths or None
            ),
            allow_hosts=_narrow_globs(
                self.allow_hosts, other.allow_hosts or None
            ),
            ancestors=_intersected_ancestors(self, other, principal),
        )

    def attenuate(
        self,
        *,
        principal: str | None = None,
        allow: set[str] | frozenset[str] | None = None,
        deny: set[str] | frozenset[str] | None = None,
        max_risk: str | None = None,
        allow_paths: set[str] | frozenset[str] | None = None,
        allow_hosts: set[str] | frozenset[str] | None = None,
    ) -> Capability:
        """Return a strictly-narrower grant. It can never broaden:

        - ``allow`` intersects (a whitelist only shrinks; if this grant
          allows all, the child may be *restricted* to ``allow``).
        - ``deny`` unions (the deny-set only grows).
        - ``max_risk`` can only tighten (min by rank).
        - ``allow_paths`` / ``allow_hosts`` intersect (an all-permissive scope
          may be *restricted* by the child; an already-restricted scope only
          shrinks, and can never gain a path/host the parent lacked).
        - ``expires_at`` is inherited (a child never outlives its parent).

        By construction, every tool/path/host the result permits is also
        permitted by ``self`` — children cannot escalate.
        """
        new_allow = _narrow_tools(self.allow_tools, allow)
        new_deny = self.deny_tools | (frozenset(deny) if deny else frozenset())
        new_max = self.max_risk
        if max_risk is not None:
            new_max = (
                max_risk if self.max_risk is None
                else min(self.max_risk, max_risk, key=risk_rank)
            )
        return Capability(
            principal=principal or self.principal,
            allow_tools=new_allow,
            deny_tools=new_deny,
            max_risk=new_max,
            expires_at=self.expires_at,
            allow_paths=_narrow_globs(self.allow_paths, allow_paths),
            allow_hosts=_narrow_globs(self.allow_hosts, allow_hosts),
            ancestors=_attenuated_ancestors(self, principal),
        )

    def signing_bytes(self) -> bytes:
        """Canonical, stable serialization for signing/verification."""
        payload = {
            "principal": self.principal,
            "allow_tools": sorted(self.allow_tools),
            "deny_tools": sorted(self.deny_tools),
            "max_risk": self.max_risk,
            "expires_at": self.expires_at,
            "allow_paths": sorted(self.allow_paths),
            "allow_hosts": sorted(self.allow_hosts),
        }
        if self.ancestors:
            payload["ancestors"] = list(self.ancestors)
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")


# A tool name/glob that can never match any real tool/path/host, used to
# represent an empty (permits-nothing) allow-list without colliding with the
# "empty set == all" convention -- NUL is illegal in the configured names.
_DENY_ALL = "\x00"


def _attenuated_ancestors(cap: Capability, principal: str | None) -> tuple[str, ...]:
    """Return lineage for a grant re-bound from ``cap`` to ``principal``.

    Rebinding a capability creates a descendant principal; recording the parent
    chain lets revocation of any ancestor propagate at the authorization
    boundary without needing every process to share an in-memory edge graph.
    """
    return _lineage_for(cap, principal)


def _intersected_ancestors(
    left: Capability, right: Capability, principal: str | None,
) -> tuple[str, ...]:
    """Merge both input lineages for an intersected grant.

    Verified handoffs are intersected with an agent's ambient grant at the tool
    boundary. The result must stay revocable through either side's ancestors
    (for example, the sender that delegated the handoff and the recipient's
    spawn parent).
    """
    target = principal or left.principal
    return _merge_lineages(_lineage_for(left, target), _lineage_for(right, target))


def _lineage_for(cap: Capability, principal: str | None) -> tuple[str, ...]:
    lineage = cap.ancestors
    if principal is not None and principal != cap.principal:
        lineage = (*lineage, cap.principal)
    return _merge_lineages(lineage)


def _merge_lineages(*lineages: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    merged: list[str] = []
    for lineage in lineages:
        for pr in lineage:
            if pr and pr not in seen:
                seen.add(pr)
                merged.append(pr)
    return tuple(merged)


def _narrow_tools(
    current: frozenset[str],
    requested: set[str] | frozenset[str] | None,
) -> frozenset[str]:
    """Intersect two tool allow-lists without failing open on disjoint sets."""
    if requested is None:
        return current
    req = frozenset(requested)
    if not current:
        return req
    if not req:
        return current
    narrowed = current & req
    return narrowed or frozenset({_DENY_ALL})


def _narrow_globs(
    current: frozenset[str],
    requested: set[str] | frozenset[str] | None,
) -> frozenset[str]:
    """Intersect two allow-globs sets, preserving the narrow-only invariant.

    Mirrors the ``allow_tools`` intersection (empty == all): an all-permissive
    parent may be restricted to ``requested``; an already-restricted parent
    only shrinks. When both sides are restricted but their patterns are
    disjoint, the result must permit *nothing* -- collapsing to the empty set
    there would wrongly mean "all", so we emit an unmatchable sentinel instead.
    """
    if requested is None:
        return current
    req = frozenset(requested)
    if not current:
        return req
    if not req:
        return current
    narrowed = current & req
    return narrowed or frozenset({_DENY_ALL})


def _have_crypto() -> bool:
    try:
        from cryptography.hazmat.primitives.asymmetric import ed25519  # noqa: F401
        return True
    except ImportError:
        return False


def sign_capability(cap: Capability, private_key_hex: str) -> str:
    """Ed25519-sign a grant; returns a hex signature. Requires ``cryptography``."""
    from cryptography.hazmat.primitives.asymmetric import ed25519
    priv = ed25519.Ed25519PrivateKey.from_private_bytes(bytes.fromhex(private_key_hex))
    return priv.sign(cap.signing_bytes()).hex()


def verify_capability(cap: Capability, sig_hex: str, public_key_hex: str) -> bool:
    """Verify a grant's Ed25519 signature, reusing the audit-signing verifier.

    Returns False (never raises) on a bad signature, and False when
    ``cryptography`` is absent — callers that *require* verification must
    check :func:`_have_crypto` first.
    """
    if not _have_crypto():
        return False
    from .audit.signing import verify_ed25519
    return verify_ed25519(public_key_hex, sig_hex, cap.signing_bytes())


def capability_enforced() -> bool:
    """Opt-in, off by default. ``MAVERICK_ENFORCE_CAPABILITIES=1`` or
    ``[capabilities] enforce = true`` turns on per-agent capability
    enforcement + attenuating propagation to children."""
    if os.environ.get("MAVERICK_ENFORCE_CAPABILITIES", "").strip().lower() in {
        "1", "true", "yes", "on",
    }:
        return True
    # Enterprise mode forces capability enforcement on (least privilege is
    # mandatory when an agent handles sensitive data).
    try:
        from .enterprise import enterprise_enabled
        if enterprise_enabled():
            return True
    except Exception:
        pass
    try:
        from .config import load_config
        cfg = (load_config() or {}).get("capabilities") or {}
        return bool(cfg.get("enforce"))
    except Exception:
        return False


def capability_from_config(
    principal: str,
    *,
    channel: str | None = None,
    user_id: str | None = None,
) -> Capability:
    """Build the root grant from the existing ``[security]`` ACL config.

    Reuses the deployment's allow/deny/max-risk (the same knobs
    :mod:`maverick.safety.tool_acl` reads), so capabilities need no new policy
    surface — but now the grant propagates to children with attenuation. With
    no ACL configured this is an all-permissive grant bound to ``principal``
    (still gives identity + least-privilege-on-spawn).
    """
    try:
        from .safety.tool_acl import resolve_lists, resolve_max_risk
        allowed, denied = resolve_lists(channel=channel, user_id=user_id)
        max_risk = resolve_max_risk(channel=channel, user_id=user_id)
    except Exception:
        # Fail CLOSED, not open. An EMPTY allow_tools means "all tools", so the
        # old fallback (set(), set(), None) was an all-permissive root grant on a
        # resolver error -- the inverse of tool_acl's _FAIL_CLOSED posture.
        # _DENY_ALL makes permits() refuse every tool; "low" is the tightest
        # risk ceiling. Dead-defensive today (resolve_lists/resolve_max_risk
        # swallow their own config errors and already return fail-closed), but a
        # latent trap for any future refactor that lets those resolvers raise.
        allowed, denied, max_risk = {_DENY_ALL}, set(), "low"
    base = Capability(
        principal=principal,
        allow_tools=frozenset(allowed),
        deny_tools=frozenset(denied),
        max_risk=max_risk,
    )
    # RBAC: if this principal is assigned a role, narrow the deployment-ACL
    # ceiling by that role's scope. It routes through attenuate(), so a role can
    # only ever restrict -- never escalate past [security]. Opt-in: with no
    # [role_assignments]/[roles] config the base grant is returned unchanged.
    role = role_for_principal(principal)
    if role:
        base = _apply_role(base, role)
    return base


class UnknownRoleError(ValueError):
    """Raised when an explicitly requested RBAC role is not configured."""


def capability_for_role(role: str, *, principal: str = "agent") -> Capability:
    """The capability for ``principal`` scoped to the named RBAC ``role``.

    Starts from the deployment-ACL grant (:func:`capability_from_config`) and
    narrows it by the ``[roles.<role>]`` scope -- the same attenuation
    :func:`capability_from_config` applies for an *assigned* role, but keyed on
    an explicit role rather than ``[role_assignments]``. This is how a fleet
    agent runs least-privileged under its declared role. Unknown or empty
    explicit roles are rejected so governed fleet runs cannot fail open to the
    deployment-wide base grant.
    """
    role_name = role.strip() if isinstance(role, str) else role
    if not role_exists(role_name):
        raise UnknownRoleError(f"undefined RBAC role: {role!r}")
    base = capability_from_config(principal)
    return _apply_role(base, role_name)


def _roles_config() -> dict:
    """The ``[roles]`` table (role name -> scope dict), or empty."""
    try:
        from .config import load_config
        return (load_config() or {}).get("roles") or {}
    except Exception:
        return {}


def configured_roles() -> frozenset[str]:
    """The configured RBAC role names that fleet agents may declare."""
    roles = _roles_config()
    return frozenset(
        name for name, scope in roles.items()
        if isinstance(name, str) and isinstance(scope, dict)
    )


def role_exists(role_name: str) -> bool:
    """True when ``role_name`` names a configured ``[roles.<role_name>]`` table."""
    if not isinstance(role_name, str) or not role_name.strip():
        return False
    return isinstance(_roles_config().get(role_name.strip()), dict)


def role_for_principal(principal: str) -> str | None:
    """The RBAC role assigned to ``principal``, or ``None``.

    Reads ``[role_assignments]`` (``"<principal>" = "<role>"``) and falls back to
    a ``default`` assignment when set. RBAC is opt-in: with no
    ``[role_assignments]`` config this returns ``None`` and the grant is
    unchanged.
    """
    try:
        from .config import load_config
        assigns = (load_config() or {}).get("role_assignments") or {}
    except Exception:
        return None
    role = assigns.get(principal) or assigns.get("default")
    return role if isinstance(role, str) and role else None


def _apply_role(base: Capability, role_name: str) -> Capability:
    """Narrow ``base`` by the named role's ``[roles.<role_name>]`` scope.

    Routes through :meth:`Capability.attenuate`, so a role can only ever
    *restrict* the deployment ACL ceiling -- a misconfigured role that lists
    broader tools/paths/hosts than ``[security]`` still cannot escalate a
    principal past it. An unknown/empty role leaves ``base`` unchanged.

    Scope keys mirror the :class:`Capability` fields: ``allow_tools``,
    ``deny_tools``, ``max_risk``, ``allow_paths``, ``allow_hosts``.
    """
    scope = _roles_config().get(role_name)
    if not isinstance(scope, dict):
        return base

    def _set(key: str) -> set[str] | None:
        v = scope.get(key)
        return set(v) if isinstance(v, (list, tuple, set)) and v else None

    risk = scope.get("max_risk")
    return base.attenuate(
        allow=_set("allow_tools"),
        deny=_set("deny_tools"),
        max_risk=risk if isinstance(risk, str) else None,
        allow_paths=_set("allow_paths"),
        allow_hosts=_set("allow_hosts"),
    )


__all__ = [
    "Capability",
    "sign_capability",
    "verify_capability",
    "capability_enforced",
    "capability_from_config",
    "capability_for_role",
    "configured_roles",
    "role_exists",
    "role_for_principal",
    "UnknownRoleError",
]
