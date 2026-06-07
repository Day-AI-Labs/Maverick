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

from .safety.tool_risk import risk_rank, tool_risk


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
        )

    def signing_bytes(self) -> bytes:
        """Canonical, stable serialization for signing/verification."""
        return json.dumps(
            {
                "principal": self.principal,
                "allow_tools": sorted(self.allow_tools),
                "deny_tools": sorted(self.deny_tools),
                "max_risk": self.max_risk,
                "expires_at": self.expires_at,
                "allow_paths": sorted(self.allow_paths),
                "allow_hosts": sorted(self.allow_hosts),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")


# A tool name/glob that can never match any real tool/path/host, used to
# represent an empty (permits-nothing) allow-list without colliding with the
# "empty set == all" convention -- NUL is illegal in the configured names.
_DENY_ALL = "\x00"


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
        allowed, denied, max_risk = set(), set(), None
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


def capability_for_role(role: str, *, principal: str = "agent") -> Capability:
    """The capability for ``principal`` scoped to the named RBAC ``role``.

    Starts from the deployment-ACL grant (:func:`capability_from_config`) and
    narrows it by the ``[roles.<role>]`` scope -- the same attenuation
    :func:`capability_from_config` applies for an *assigned* role, but keyed on
    an explicit role rather than ``[role_assignments]``. This is how a fleet
    agent runs least-privileged under its declared role. An unknown/empty role
    leaves the base grant unchanged.
    """
    base = capability_from_config(principal)
    return _apply_role(base, role) if role else base


def _roles_config() -> dict:
    """The ``[roles]`` table (role name -> scope dict), or empty."""
    try:
        from .config import load_config
        return (load_config() or {}).get("roles") or {}
    except Exception:
        return {}


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
    "role_for_principal",
]
