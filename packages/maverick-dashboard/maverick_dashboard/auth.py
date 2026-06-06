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
    }
)


def _bearer_token(request: Request) -> str:
    """Extract the raw JWT from an ``Authorization: Bearer <jwt>`` header."""
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return ""


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
    """
    if not oidc_enabled():
        return None
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
