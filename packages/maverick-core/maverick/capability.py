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

from .safety.tool_risk import risk_rank, tool_risk


@dataclass(frozen=True)
class Capability:
    """A principal's scoped, attenuable grant over the tool surface.

    - ``allow_tools``: empty set means *all* tools (matches the ACL's
      "empty allow-list == all" convention); a non-empty set is a whitelist.
    - ``deny_tools``: always subtractive; deny wins over allow.
    - ``max_risk``: optional ceiling ("low"/"medium"/"high"); ``None`` == no cap.
    - ``expires_at``: optional epoch-seconds expiry; ``None`` == never.
    """

    principal: str
    allow_tools: frozenset[str] = frozenset()
    deny_tools: frozenset[str] = frozenset()
    max_risk: str | None = None
    expires_at: float | None = None

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
        if self.allow_tools and tool_name not in self.allow_tools:
            return False
        if (
            self.max_risk is not None
            and risk_rank(tool_risk(tool_name)) > risk_rank(self.max_risk)
        ):
            return False
        return True

    def attenuate(
        self,
        *,
        principal: str | None = None,
        allow: set[str] | frozenset[str] | None = None,
        deny: set[str] | frozenset[str] | None = None,
        max_risk: str | None = None,
    ) -> Capability:
        """Return a strictly-narrower grant. It can never broaden:

        - ``allow`` intersects (a whitelist only shrinks; if this grant
          allows all, the child may be *restricted* to ``allow``).
        - ``deny`` unions (the deny-set only grows).
        - ``max_risk`` can only tighten (min by rank).
        - ``expires_at`` is inherited (a child never outlives its parent).

        By construction, every tool the result ``permits`` is also permitted
        by ``self`` — children cannot escalate.
        """
        if allow is None:
            new_allow = self.allow_tools
        else:
            req = frozenset(allow)
            new_allow = req if not self.allow_tools else (self.allow_tools & req)
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
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")


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
    return Capability(
        principal=principal,
        allow_tools=frozenset(allowed),
        deny_tools=frozenset(denied),
        max_risk=max_risk,
    )


__all__ = [
    "Capability",
    "sign_capability",
    "verify_capability",
    "capability_enforced",
    "capability_from_config",
]
