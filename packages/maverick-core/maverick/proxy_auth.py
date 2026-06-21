"""Reverse-proxy SSO: trust a forwarded identity header from a trusted upstream.

The standard, low-risk way to put browser SSO in front of an internal service:
a proxy (oauth2-proxy, your IdP's, an ALB OAuth listener, ...) authenticates the
user and forwards their identity in a request header (e.g. ``X-Forwarded-User``).
Maverick maps that value to a ``user:<id>`` principal that drops straight into
the capability/role + tenant model -- no hand-rolled OAuth flow to own.

SECURITY: a forwarded header is trivially spoofable by a *direct* client, so it
is honored ONLY when the request's network peer is a trusted upstream
(``trusted_proxies``; default: loopback, since the proxy usually runs on the
same host as the dashboard). The operator MUST also (a) make the proxy the only
ingress to the dashboard and (b) configure the proxy to strip any
client-supplied copy of the header. Default-off; opt-in via ``[auth.proxy]
enabled`` / ``MAVERICK_PROXY_AUTH``.
"""
from __future__ import annotations

import os

_DEFAULT_HEADER = "X-Forwarded-User"
# The proxy normally shares the host, so loopback is the safe default peer.
_LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost"})
_TRUE = {"1", "true", "yes", "on"}


def _section() -> dict:
    try:
        from .config import load_config
        return ((load_config() or {}).get("auth") or {}).get("proxy") or {}
    except Exception:
        return {}


def proxy_auth_enabled() -> bool:
    """Opt-in, off by default: ``MAVERICK_PROXY_AUTH`` or ``[auth.proxy] enabled``."""
    env = os.environ.get("MAVERICK_PROXY_AUTH", "").strip().lower()
    if env:
        return env in _TRUE
    val = _section().get("enabled")
    if isinstance(val, str):
        return val.strip().lower() in _TRUE
    return bool(val)


def proxy_header_name() -> str:
    """The forwarded-identity header to read (default ``X-Forwarded-User``)."""
    name = (
        os.environ.get("MAVERICK_PROXY_AUTH_HEADER")
        or str(_section().get("header") or "")
    ).strip()
    return name or _DEFAULT_HEADER


def _trust_loopback_fallback() -> bool:
    """Whether to trust loopback peers when ``trusted_proxies`` is unset.

    The same-host proxy is the documented default, so loopback stays trusted in
    the standard single-host deployment. But trusting loopback by IP alone can't
    tell the real proxy from ANY other co-located loopback process -- a sidecar,
    another container in the pod's network namespace, or an SSRF pivot to
    127.0.0.1 -- each of which could then spoof ``X-Forwarded-User: admin``.
    So enterprise mode requires an explicit ``trusted_proxies`` pin and does NOT
    fall back to loopback; operators can also force the fallback off with
    ``[auth.proxy] trust_loopback = false``.
    """
    val = _section().get("trust_loopback")
    if val is not None:
        return val.strip().lower() in _TRUE if isinstance(val, str) else bool(val)
    try:
        from .enterprise import enterprise_enabled
        if enterprise_enabled():
            return False
    except Exception:  # pragma: no cover -- never weaken posture on a lookup error
        pass
    return True


def proxy_trusts(client_host: str | None) -> bool:
    """True iff a request from ``client_host`` may carry the identity header.

    A configured ``[auth.proxy] trusted_proxies = ["10.0.0.5", ...]`` is the
    secure form (the exact proxy peer is pinned). With no pin, loopback is
    trusted only when the loopback fallback is allowed (see
    :func:`_trust_loopback_fallback` -- on by default, OFF under enterprise mode
    or ``trust_loopback = false``). An empty/unknown peer is never trusted.
    """
    if not client_host:
        return False
    trusted = _section().get("trusted_proxies")
    if isinstance(trusted, (list, tuple)) and trusted:
        return client_host in {str(t).strip() for t in trusted}
    return _trust_loopback_fallback() and client_host in _LOOPBACK


def principal_from_proxy(value: str):
    """Map a forwarded identity value to a :class:`maverick.oidc.VerifiedPrincipal`.

    ``principal`` is ``user:<value>`` so it matches the OIDC/``[role_assignments]``
    conventions; ``claims`` records that this identity came via the proxy (not a
    signed ID token) so downstream code can tell them apart.
    """
    from .oidc import VerifiedPrincipal
    return VerifiedPrincipal(
        sub=value, issuer="proxy", audience="", claims={"via": "proxy"},
    )


__all__ = [
    "proxy_auth_enabled",
    "proxy_header_name",
    "proxy_trusts",
    "principal_from_proxy",
]
