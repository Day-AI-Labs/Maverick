"""OIDC bearer-auth gate for the dashboard HTTP surface.

Wires the kernel's OIDC verifier (``maverick.oidc``) into FastAPI as an
ENFORCED auth dependency. Default-OFF: with OIDC disabled (the default),
:func:`require_principal` returns ``None`` and every route behaves exactly as
before -- no token is required, no 401s. When OIDC is enabled, each gated
request must carry a valid ``Authorization: Bearer <jwt>`` ID token.

Importing this module never hard-requires PyJWT: ``maverick.oidc`` lazy-imports
PyJWT only inside :func:`verify_oidc_token`, which runs only when OIDC is
enabled and a token is actually verified.

Fail-closed only when enabled (missing/invalid token -> 401); fail-OPEN (allow)
only when disabled.
"""
from __future__ import annotations

from fastapi import HTTPException, Request
from maverick.oidc import (
    OIDCError,
    VerifiedPrincipal,
    oidc_enabled,
    verify_oidc_token,
)
from maverick.proxy_auth import (
    principal_from_proxy,
    proxy_auth_enabled,
    proxy_header_name,
    proxy_trusts,
)

# Probe/discovery endpoints that must answer without a bearer even when OIDC is
# on (load balancers and k8s liveness/readiness probes, plus the OpenAPI docs,
# can't present an ID token). Mirrors the dashboard's existing bearer-auth
# exemptions in ``app._AUTH_EXEMPT`` -- the HMAC-signed webhooks are NOT listed
# here because they carry their own credential and are gated separately.
_OIDC_EXEMPT_PATHS = frozenset(
    {
        "/healthz",
        "/livez",
        "/readyz",
        "/openapi.json",
        "/docs",
        "/redoc",
        "/docs/oauth2-redirect",
        "/.well-known/agent-card.json",
        "/.well-known/agent.json",
        # Built-in browser-login endpoints must answer without an existing
        # session/bearer -- they ARE the way a browser gets one. They self-gate
        # on login_enabled() (404 when the login flow is off).
        "/auth/login",
        "/auth/callback",
        "/auth/logout",
        "/auth/error",
    }
)


def _bearer_token(request: Request) -> str:
    """Extract the raw JWT from an ``Authorization: Bearer <jwt>`` header."""
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return ""


def _proxy_principal(request: Request) -> VerifiedPrincipal | None:
    """Reverse-proxy SSO: a principal from a forwarded identity header.

    Honored ONLY when proxy auth is enabled AND the request's network peer is a
    trusted upstream (anti-spoofing -- see :mod:`maverick.proxy_auth`). Returns
    ``None`` (fall through to OIDC/loopback) when not applicable.
    """
    if not proxy_auth_enabled():
        return None
    client_host = request.client.host if request.client else ""
    if not proxy_trusts(client_host):
        return None
    value = (request.headers.get(proxy_header_name(), "") or "").strip()
    if not value:
        return None
    return principal_from_proxy(value)


def _session_principal(request: Request) -> VerifiedPrincipal | None:
    """Built-in browser-login identity: a valid ``mvk_session`` cookie.

    Returns a principal only when the login flow is configured AND the cookie
    verifies (correct HMAC + unexpired). Absent/invalid -> ``None`` so the
    caller falls through to the OIDC bearer path unchanged. Imported lazily so
    the dashboard (and the existing bearer/proxy paths) don't take a hard
    dependency on the login module just to import this gate.
    """
    try:
        from .oidc_login import _principal_from_request_session
    except Exception:  # pragma: no cover - defensive; module should import
        return None
    return _principal_from_request_session(request)


def execution_user_id_from_request(request: Request) -> str | None:
    """Return the Maverick ``user_id`` for the authenticated HTTP principal.

    ``run_goal`` derives authorization principals as ``user:<user_id>``. The
    verified dashboard principal stores the raw subject on ``sub`` and exposes
    the full role-assignment key as ``principal``; pass only the subject so
    downstream checks evaluate the same ``user:<id>`` identity instead of
    falling back to ``user:local``.
    """
    principal = getattr(getattr(request, "state", None), "principal", None)
    sub = str(getattr(principal, "sub", "") or "").strip()
    if sub:
        return sub
    principal_name = str(getattr(principal, "principal", "") or "").strip()
    if principal_name.startswith("user:") and len(principal_name) > len("user:"):
        return principal_name[len("user:"):]
    return None


def require_principal(request: Request) -> VerifiedPrincipal | None:
    """FastAPI dependency enforcing OIDC bearer auth when OIDC is enabled.

    - OIDC disabled (default): returns ``None`` and allows the request. Behaviour
      is unchanged -- no auth header is read or required.
    - OIDC enabled: reads the ``Authorization: Bearer`` header, verifies it via
      :func:`maverick.oidc.verify_oidc_token`, stashes the principal on
      ``request.state.principal``, and returns it. A missing or invalid token
      raises ``HTTPException(401)`` (fail-closed).

    Health/liveness/discovery paths (see ``_OIDC_EXEMPT_PATHS``) stay open so
    probes and the OpenAPI docs keep working with OIDC on.

    Reverse-proxy SSO (``[auth.proxy]``) takes precedence: when enabled and the
    request comes from a trusted upstream, a forwarded identity header
    establishes the principal even with OIDC bearer off.

    Built-in browser login: when the login flow is configured, a valid
    ``mvk_session`` cookie (set by ``/auth/callback``) is accepted as the
    identity, sitting between the reverse-proxy header and the OIDC bearer.
    Invalid/absent -> falls through to the bearer path unchanged.
    """
    pp = _proxy_principal(request)
    if pp is not None:
        request.state.principal = pp
        return pp

    if not oidc_enabled():
        return None

    # Session-cookie identity (browser login). Only active when login is
    # configured; otherwise this returns None and nothing changes.
    sp = _session_principal(request)
    if sp is not None:
        request.state.principal = sp
        return sp

    if request.url.path in _OIDC_EXEMPT_PATHS:
        return None
    # HMAC-signed webhooks (GitHub/Telegram/Linear/Jira/...) can't present an
    # OIDC ID token -- the external sender authenticates with a shared-secret
    # signature, verified by the webhook handler itself. Requiring an OIDC
    # bearer here would 401 every inbound webhook when OIDC is on, breaking
    # event delivery. They're gated by their signature, not OIDC (mirrors the
    # webhook entries in app._AUTH_EXEMPT).
    if request.url.path.startswith("/webhook/"):
        return None

    token = _bearer_token(request)
    if not token:
        raise HTTPException(
            status_code=401,
            detail="OIDC bearer token required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        principal = verify_oidc_token(token)
    except OIDCError:
        # Opaque 401: never leak which check failed (expiry vs. signature vs.
        # audience) to an unauthenticated caller.
        raise HTTPException(
            status_code=401,
            detail="invalid OIDC token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    request.state.principal = principal
    return principal
