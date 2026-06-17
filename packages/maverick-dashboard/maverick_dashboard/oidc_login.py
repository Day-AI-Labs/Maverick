"""Built-in OIDC authorization-code browser-login flow for the dashboard.

This is the self-contained alternative to the reverse-proxy SSO path
(:mod:`maverick.proxy_auth`): a deployment that can't run an auth proxy in front
of the dashboard gets browser SSO directly, by having the dashboard itself drive
the OAuth2 / OpenID-Connect authorization-code flow.

It is **off by default and fail-closed**: every route here first checks
:func:`maverick.oidc.login_enabled` and returns 404 when the flow isn't fully
configured, so an unconfigured deployment behaves exactly as before (the bearer
gate and the reverse-proxy path are untouched). Configuration lives in
``[auth.oidc]`` (``client_id``/``client_secret``/``redirect_uri``/
``session_secret`` + issuer-or-endpoints); see :func:`maverick.oidc.login_enabled`.

Security mechanics (these are the whole point — see the security checklist in
the PR):

- **CSRF on the callback** via an opaque ``state`` minted at ``/auth/login``,
  stashed in a short-TTL signed transaction cookie, and required to match the
  ``state`` query param on ``/auth/callback`` before any token exchange.
- **PKCE (S256)**: a ``code_verifier`` is generated at login, its S256
  ``code_challenge`` is sent on the authorization request, and the verifier is
  sent on the token exchange — so an intercepted ``code`` can't be redeemed.
- **One-time login transactions**: the callback consumes each signed
  transaction ID server-side before token exchange, preventing replay of a
  captured transaction cookie.
- **Async HTTPS-only token exchange**: the token endpoint must be ``https://`` or we
  refuse to POST the client secret to it, and the network call uses
  ``httpx.AsyncClient`` so failed IdP calls do not block the event loop.
- **ID-token verification reuses** :func:`maverick.oidc.verify_oidc_token` — we
  do not re-implement JWT verification.
- **Open-redirect defence**: ``return_to`` is only honored if it is a safe local
  path; anything external / protocol-relative / with a backslash or control
  char falls back to ``/``.
- **No secrets in logs**: failures log a generic reason only — never the token,
  the authorization code, the client secret, or the session value.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import secrets
import time
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from maverick.oidc import (
    OIDCError,
    VerifiedPrincipal,
    load_oidc_config,
    login_enabled,
    resolve_endpoints,
    verify_oidc_token,
)
from maverick.web_session import sign_session, verify_session

log = logging.getLogger(__name__)

router = APIRouter(tags=["auth"])

# Cookie names.
TX_COOKIE = "mvk_oidc_tx"          # short-lived login transaction (state+PKCE)
SESSION_COOKIE = "mvk_session"     # the authenticated browser session

# Lifetimes (seconds).
_TX_TTL = 600                      # 10 min to complete the round-trip
_SESSION_TTL = 12 * 3600          # 12 h authenticated session

# Best-effort, per-process replay guard for transaction cookies. The signed
# cookie remains the source of transaction data, but the opaque tx id must be
# consumed exactly once before any token exchange is attempted.
_CONSUMED_TX_IDS: dict[str, int] = {}
_CONSUMED_TX_LOCK = asyncio.Lock()

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", "testclient"})


def _now() -> int:
    return int(time.time())


def _is_loopback_request(request: Request) -> bool:
    """True when the request's peer is loopback/in-process.

    Used only to decide the cookie ``Secure`` flag: on a real (non-loopback)
    deployment cookies are marked ``Secure`` so they're never sent over plain
    HTTP; loopback dev over http would otherwise never receive them back.
    """
    host = request.client.host if request.client else ""
    return host in _LOOPBACK_HOSTS


def _is_safe_return_to(value: str | None) -> bool:
    """Whether ``value`` is a safe *local* path to redirect a browser to.

    Blocks the open-redirect class: must start with a single ``/`` (a local
    absolute path), must NOT start with ``//`` (protocol-relative -> off-site),
    must contain no backslash (``/\\evil.com`` is treated as ``//`` by some
    browsers) and no control characters (CR/LF/NUL header-splitting tricks).
    """
    if not isinstance(value, str) or not value:
        return False
    if not value.startswith("/"):
        return False
    if value.startswith("//"):
        return False
    if "\\" in value:
        return False
    return all(ord(c) >= 0x20 and c != "\x7f" for c in value)


def _safe_return_to(value: str | None) -> str:
    """Sanitize ``return_to`` to a safe local path, defaulting to ``/``."""
    return value if _is_safe_return_to(value) else "/"


def _code_challenge_s256(verifier: str) -> str:
    """The S256 PKCE code_challenge for ``verifier`` (b64url, no padding)."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


async def _consume_tx_once(tx_id: str, expires_at: int) -> bool:
    """Atomically mark an OIDC login transaction as consumed.

    Transaction cookies are self-contained so they can survive redirects without
    external session middleware, but callbacks must not be replayable. This
    per-process guard records the opaque transaction id before the token
    exchange; repeated callbacks with the same cookie are rejected before making
    an outbound IdP request. Expired entries are pruned opportunistically.
    """
    if not tx_id:
        return False

    now = _now()
    async with _CONSUMED_TX_LOCK:
        expired = [key for key, exp in _CONSUMED_TX_IDS.items() if exp <= now]
        for key in expired:
            _CONSUMED_TX_IDS.pop(key, None)

        if tx_id in _CONSUMED_TX_IDS:
            return False

        _CONSUMED_TX_IDS[tx_id] = max(expires_at, now + 1)
        return True


async def _exchange_code_for_tokens(
    token_endpoint: str, *, cfg, code: str, code_verifier: str
) -> dict:
    """Exchange an authorization code without blocking the event loop."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        token_resp = await client.post(
            token_endpoint,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": cfg.redirect_uri,
                "client_id": cfg.client_id,
                "code_verifier": code_verifier,
            },
            auth=(cfg.client_id, cfg.client_secret),
        )
    token_resp.raise_for_status()
    token_data = token_resp.json()
    return token_data if isinstance(token_data, dict) else {}


def _set_cookie(response, name: str, value: str, *, max_age: int, secure: bool) -> None:
    """Set a hardened cookie: httponly + samesite=lax (+ secure when not loopback).

    ``samesite=lax`` lets the cookie ride the top-level GET redirect back from
    the IdP (the callback) while still blocking it on cross-site subrequests;
    ``httponly`` keeps it out of ``document.cookie`` (XSS can't read it).
    """
    response.set_cookie(
        name,
        value,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
    )


def _clear_cookie(response, name: str) -> None:
    response.delete_cookie(name, path="/")


def _principal_from_request_session(request: Request):
    """Return a :class:`VerifiedPrincipal` for a valid ``mvk_session`` cookie.

    Shared with the auth dependency so the session-cookie identity is established
    in exactly one place. Returns ``None`` when login is disabled, the cookie is
    absent, or the cookie fails verification (tampered/expired/wrong-secret).
    """
    if not login_enabled():
        return None
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        return None
    cfg = load_oidc_config()
    if not cfg.session_secret:
        return None
    payload = verify_session(raw, cfg.session_secret)
    if not payload:
        return None
    sub = payload.get("sub")
    if not isinstance(sub, str) or not sub:
        return None
    return VerifiedPrincipal(
        sub=sub, issuer="oidc-session", audience="", claims={"via": "session"},
    )


@router.get("/auth/login")
async def auth_login(request: Request):
    """Begin the authorization-code flow: redirect the browser to the IdP.

    Mints ``state`` + a PKCE ``code_verifier``, stashes them (plus a sanitized
    ``return_to``) in a short-TTL signed transaction cookie, and 302s to the
    authorization endpoint with the S256 ``code_challenge``.
    """
    if not login_enabled():
        raise HTTPException(status_code=404)

    cfg = load_oidc_config()
    try:
        endpoints = resolve_endpoints(cfg)
    except OIDCError as exc:
        # Don't leak discovery internals; the operator misconfigured the IdP.
        log.warning("OIDC login: could not resolve authorization endpoint")
        raise HTTPException(status_code=500, detail="OIDC login is misconfigured") from exc

    state = secrets.token_urlsafe(32)
    code_verifier = secrets.token_urlsafe(64)
    code_challenge = _code_challenge_s256(code_verifier)
    return_to = _safe_return_to(request.query_params.get("return_to"))

    tx_payload = {
        "state": state,
        "cv": code_verifier,
        "return_to": return_to,
        "jti": secrets.token_urlsafe(16),
        "exp": _now() + _TX_TTL,
    }
    tx_cookie = sign_session(tx_payload, cfg.session_secret)

    params = {
        "response_type": "code",
        "client_id": cfg.client_id,
        "redirect_uri": cfg.redirect_uri,
        "scope": "openid",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    auth_url = endpoints["authorization_endpoint"] + "?" + urlencode(params)

    response = RedirectResponse(auth_url, status_code=302)
    _set_cookie(
        response, TX_COOKIE, tx_cookie,
        max_age=_TX_TTL, secure=not _is_loopback_request(request),
    )
    return response


def _fail():
    """Build a failure response that also clears both auth cookies.

    Used on every callback error path so a half-finished/forged login leaves no
    stale transaction or session cookie behind. We surface the failure as a
    redirect to ``/auth/error`` rather than a raw 4xx so the user lands on a
    page, not a JSON blob (the CSRF/state-mismatch case is the documented
    exception — it returns a 400 inline).
    """
    response = RedirectResponse("/auth/error", status_code=303)
    _clear_cookie(response, TX_COOKIE)
    _clear_cookie(response, SESSION_COOKIE)
    return response


@router.get("/auth/callback")
async def auth_callback(request: Request):
    """Handle the IdP redirect: verify state, exchange the code, set the session.

    Order of checks (fail-closed at each step, clearing cookies on failure):
      1. tx cookie present + valid;
      2. ``state`` query param == tx-cookie state (CSRF) — else 400, NO token
         exchange;
      3. token endpoint is https; exchange the ``code`` with the PKCE verifier;
      4. verify the returned ``id_token`` via
         :func:`maverick.oidc.verify_oidc_token`;
      5. set the signed session cookie and redirect to the (sanitized)
         ``return_to``.
    """
    if not login_enabled():
        raise HTTPException(status_code=404)

    cfg = load_oidc_config()

    # (1) transaction cookie
    raw_tx = request.cookies.get(TX_COOKIE)
    tx = verify_session(raw_tx, cfg.session_secret) if raw_tx else None
    if not tx:
        log.warning("OIDC callback: missing/invalid transaction cookie")
        return _fail()

    # (2) CSRF: state must match. Reject BEFORE any network/token exchange.
    query_state = request.query_params.get("state") or ""
    tx_state = tx.get("state") or ""
    if not query_state or not secrets.compare_digest(query_state.encode(), tx_state.encode()):
        # CSRF: reject with 400 and clear cookies BEFORE any token exchange.
        log.warning("OIDC callback: state mismatch (possible CSRF)")
        return _csrf_reject()

    code = request.query_params.get("code") or ""
    if not code:
        log.warning("OIDC callback: no authorization code present")
        return _fail()

    # (3) resolve + https-check the token endpoint, then exchange the code.
    try:
        endpoints = resolve_endpoints(cfg)
    except OIDCError:
        log.warning("OIDC callback: could not resolve token endpoint")
        return _fail()
    token_endpoint = endpoints["token_endpoint"]
    if not token_endpoint.lower().startswith("https://"):
        log.warning("OIDC callback: refusing non-https token endpoint")
        return _fail()

    tx_id = str(tx.get("jti") or "")
    tx_exp = int(tx.get("exp") or 0)
    if not await _consume_tx_once(tx_id, tx_exp):
        log.warning("OIDC callback: replayed or malformed transaction cookie")
        return _fail()

    code_verifier = tx.get("cv") or ""
    try:
        token_data = await _exchange_code_for_tokens(
            token_endpoint, cfg=cfg, code=code, code_verifier=code_verifier
        )
    except Exception:
        # Never log the exception payload: it can echo the code/secret back.
        log.warning("OIDC callback: token exchange failed")
        return _fail()

    id_token = ""
    if isinstance(token_data, dict):
        id_token = str(token_data.get("id_token") or "")
    if not id_token:
        log.warning("OIDC callback: token response had no id_token")
        return _fail()

    # (4) verify the ID token — reuse the kernel verifier (no re-implementation).
    try:
        principal = verify_oidc_token(id_token)
    except OIDCError:
        log.warning("OIDC callback: id_token verification failed")
        return _fail()

    # (5) success: set the signed session cookie, clear the tx cookie, redirect.
    return_to = _safe_return_to(tx.get("return_to"))
    session_payload = {"sub": principal.sub, "exp": _now() + _SESSION_TTL}
    session_cookie = sign_session(session_payload, cfg.session_secret)

    response = RedirectResponse(return_to, status_code=303)
    _set_cookie(
        response, SESSION_COOKIE, session_cookie,
        max_age=_SESSION_TTL, secure=not _is_loopback_request(request),
    )
    _clear_cookie(response, TX_COOKIE)
    return response


def _csrf_reject():
    """Return a 400 that also clears both auth cookies (state mismatch / CSRF)."""
    out = PlainTextResponse("invalid state", status_code=400)
    _clear_cookie(out, TX_COOKIE)
    _clear_cookie(out, SESSION_COOKIE)
    return out


@router.get("/auth/logout")
async def auth_logout(request: Request):
    """Clear the session cookie and return to ``/``."""
    if not login_enabled():
        raise HTTPException(status_code=404)
    response = RedirectResponse("/", status_code=303)
    _clear_cookie(response, SESSION_COOKIE)
    return response


@router.get("/auth/error")
async def auth_error(request: Request):
    """Generic login-failure landing page (no detail that aids an attacker)."""
    if not login_enabled():
        raise HTTPException(status_code=404)
    return PlainTextResponse("login failed", status_code=401)


__all__ = [
    "router",
    "TX_COOKIE",
    "SESSION_COOKIE",
    "_principal_from_request_session",
    "_consume_tx_once",
    "_exchange_code_for_tokens",
]
