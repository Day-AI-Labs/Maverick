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

import os
from urllib.parse import urlparse

from fastapi import HTTPException, Request, WebSocket
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


# ---------------------------------------------------------------------------
# Owner-scoped multi-tenant authorization (stage 2)
#
# The verified principal is the unit of ownership. Goals/fleets created by a
# caller are stamped with that caller's ``user:<sub>`` string; every read/mutate
# of an owned resource checks the caller against the owner.
#
# Load-bearing invariant: when auth is OFF there is no principal, so
# ``caller_principal`` returns None and EVERY check below is a no-op. The
# dashboard then behaves exactly as it did before this layer existed
# (single-user mode -- one operator owns everything).
# ---------------------------------------------------------------------------


def caller_principal(request: Request) -> str | None:
    """The full ``"user:<sub>"`` identity of the caller, or None when auth is OFF.

    Mirrors ``request.state.principal`` set by :func:`require_principal`. None
    means no principal was established (OIDC/proxy/session all off) -- i.e.
    single-user mode -- and is the signal for every scoping check to disable
    itself and preserve legacy behaviour.
    """
    principal = getattr(getattr(request, "state", None), "principal", None)
    if principal is None:
        return None
    name = str(getattr(principal, "principal", "") or "").strip()
    return name or None


def is_dashboard_admin(principal: str) -> bool:
    """True iff ``principal`` is listed as a dashboard admin.

    Admins bypass owner scoping (they see and control every goal/fleet). The
    roster is the ``[dashboard] admins`` list in ``~/.maverick/config.toml``,
    with an optional ``MAVERICK_DASHBOARD_ADMINS`` (comma-separated) env
    override. Comparison is exact against the full ``"user:<sub>"`` form.
    """
    if not principal:
        return False
    admins: set[str] = set()
    env = (os.environ.get("MAVERICK_DASHBOARD_ADMINS") or "").strip()
    if env:
        admins = {a.strip() for a in env.split(",") if a.strip()}
    else:
        try:
            from maverick.config import load_config

            raw = (load_config().get("dashboard", {}) or {}).get("admins", []) or []
        except Exception:  # pragma: no cover - config read must never gate auth
            raw = []
        if isinstance(raw, str):
            raw = [raw]
        if isinstance(raw, (list, tuple)):
            admins = {str(a).strip() for a in raw if str(a).strip()}
    return principal in admins


def role_for_principal(principal: str | None) -> str | None:
    """The dashboard RBAC role for ``principal``.

    None when auth is off (no principal) -- the signal for every gate to
    disable itself (single-user mode). A config-pinned bootstrap admin
    (:func:`is_dashboard_admin`) is always ``"admin"`` and cannot be demoted via
    the store, so you can't lock yourself out. Otherwise the stored role, or the
    configured default (``operator``) for an authenticated user with no explicit
    assignment.
    """
    if principal is None:
        return None
    if is_dashboard_admin(principal):
        return "admin"
    from . import rbac
    return rbac.get_stored_role(principal) or rbac.default_role()


def caller_role(request: Request) -> str | None:
    """The RBAC role of the current caller (None when auth is off)."""
    return role_for_principal(caller_principal(request))


def has_permission(request: Request, permission: str) -> bool:
    """Whether the caller may perform ``permission`` ("admin"/"operate"/"view").

    Auth off -> True (legacy single-user; the local operator owns everything).
    Otherwise gated by the caller's role.
    """
    principal = caller_principal(request)
    if principal is None:
        return True
    from . import rbac
    return permission in rbac.permissions_for(role_for_principal(principal))


def require_permission(request: Request, permission: str) -> None:
    """Raise ``HTTPException(403)`` unless the caller's role grants ``permission``."""
    if not has_permission(request, permission):
        raise HTTPException(status_code=403, detail="insufficient role for this action")


def goal_owner_filter(request: Request) -> str | None:
    """The ``owner`` value to pass to ``WorldModel.list_goals``.

    Returns None (no owner filter -> all goals) when the caller is unauthenticated
    (auth off) or an admin; otherwise the caller's principal so the listing is
    scoped to the rows they own. ``owner=None`` is the historical default, so the
    auth-off path is unchanged.
    """
    principal = caller_principal(request)
    if principal is None or is_dashboard_admin(principal):
        return None
    return principal


def can_access_goal_principal(principal: str | None, goal) -> bool:
    """Whether ``principal`` may read/mutate ``goal``.

    ``None`` means auth is off and preserves the dashboard's historical
    single-user behavior. Authenticated non-admin callers may access only goals
    stamped with their exact owner principal.
    """
    if principal is None:
        return True
    if is_dashboard_admin(principal):
        return True
    return getattr(goal, "owner", "") == principal


def can_access_goal(request: Request, goal) -> bool:
    """Whether the caller may read/mutate ``goal``.

    Allowed iff auth is off (no principal), the caller is an admin, or the
    caller owns the goal. Legacy ``owner == ""`` goals (created before this
    layer, or by an external/webhook path) are therefore reachable only by the
    no-auth/admin paths, never by a different authenticated user.
    """
    return can_access_goal_principal(caller_principal(request), goal)


def assert_goal_access(request: Request, goal) -> None:
    """Raise ``HTTPException(404)`` if the caller may not touch ``goal``.

    404 (not 403) on denial so a cross-tenant probe can't distinguish "exists
    but forbidden" from "does not exist". Callers fetch the goal first (a real
    miss is its own 404) and then gate on this.
    """
    if not can_access_goal(request, goal):
        raise HTTPException(status_code=404, detail="no such goal")


def require_principal(
    request: Request = None,  # type: ignore[assignment]
    websocket: WebSocket = None,  # type: ignore[assignment,name-defined]
) -> VerifiedPrincipal | None:
    """FastAPI dependency enforcing OIDC bearer auth when OIDC is enabled.

    WebSocket routes: the app-level dependency also runs for WS connections,
    where FastAPI injects ``websocket`` instead of ``request``. WS endpoints
    do their own auth before ``accept`` (``websocket_authorized``), so this
    dependency lets the connection through to that gate when OIDC is off, and
    applies the same bearer check via the WS headers when it is on.

    - OIDC disabled (default): returns ``None`` and allows the request. Behaviour
      is unchanged -- no auth header is read or required.
    - OIDC enabled: reads the ``Authorization: Bearer`` header and verifies it
      via :func:`maverick.oidc.verify_oidc_token`. HTTP requests stash the
      principal on ``request.state.principal``; WebSocket routes receive the
      returned principal from dependency injection. A missing or invalid token
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
    if request is None:
        # WebSocket connection: no Request to stash state on. OIDC off ->
        # defer to the endpoint's own websocket_authorized gate; OIDC on ->
        # enforce the same bearer verification against the WS headers.
        if not oidc_enabled():
            return None
        if websocket is None:
            raise HTTPException(status_code=401, detail="OIDC bearer token required")
        auth = websocket.headers.get("authorization", "")
        ws_token = auth[7:] if auth.startswith("Bearer ") else ""
        if not ws_token:
            raise HTTPException(status_code=401, detail="OIDC bearer token required")
        try:
            return verify_oidc_token(ws_token)
        except OIDCError as exc:
            raise HTTPException(status_code=401, detail="invalid OIDC token") from exc

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

    if request.url.path in _OIDC_EXEMPT_PATHS or request.url.path == "/static/daybreak-logo.jpg":
        return None
    if request.url.path.startswith("/share/"):
        # Public read-only share links carry their own revocable token (verified
        # in the route, which 404s an invalid one); an external recipient has no
        # OIDC session, like the webhook paths below.
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
    except OIDCError as exc:
        # Opaque 401: never leak which check failed (expiry vs. signature vs.
        # audience) to an unauthenticated caller.
        raise HTTPException(
            status_code=401,
            detail="invalid OIDC token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    request.state.principal = principal
    return principal


def websocket_caller_principal(principal: VerifiedPrincipal | None) -> str | None:
    """Return the owner principal established for a WebSocket connection.

    The app-level dependency returns a ``VerifiedPrincipal`` for OIDC-authenticated
    WebSockets but has no ``Request.state`` to persist it on. WebSocket handlers
    pass that dependency result here so owner checks use the same
    ``user:<sub>`` string as HTTP routes. ``None`` preserves auth-off behavior.
    """
    if principal is None:
        return None
    name = str(getattr(principal, "principal", "") or "").strip()
    return name or None


def _websocket_same_origin(websocket) -> bool:
    """Require a browser WebSocket Origin matching the requested Host."""
    origin = websocket.headers.get("origin")
    host = websocket.headers.get("host")
    if not origin or not host:
        return False
    return urlparse(origin).netloc == host


def websocket_authorized(websocket) -> bool:
    """Auth gate for WebSocket endpoints (the HTTP middleware doesn't run
    for WS connections).

    Mirrors the bearer middleware's policy exactly:
      - token configured -> require ``Authorization: Bearer <token>``
        (constant-time compare). Browsers can't set WS headers; browser
        consumers use the loopback/no-token mode or a reverse proxy that
        injects the header.
      - no token -> same-origin loopback peers only, and never through a proxy
        (a forwarding header means the loopback peer is the proxy, not the
        user — fail closed, same as HTTP).
    """
    import hmac as _hmac
    import os as _os

    expected = _os.environ.get("MAVERICK_DASHBOARD_TOKEN")
    if expected:
        auth = websocket.headers.get("authorization", "")
        supplied = auth[7:] if auth.startswith("Bearer ") else ""
        return bool(supplied) and _hmac.compare_digest(expected.encode(), supplied.encode())
    from .app import _PROXY_FORWARD_HEADERS, _is_loopback_client
    host = websocket.client.host if websocket.client else ""
    proxied = any(websocket.headers.get(h) for h in _PROXY_FORWARD_HEADERS)
    return _is_loopback_client(host) and not proxied and _websocket_same_origin(websocket)
