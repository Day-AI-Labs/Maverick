"""FastAPI dashboard for Maverick.

v0.1.6: BackgroundTask runner moved to maverick.runner; this file just
imports it. Eliminates the duplicate that lived in app.py + api.py +
mcp/server.py.
"""
from __future__ import annotations

import argparse
import asyncio
import hmac
import ipaddress
import json
import logging
import os
import re
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import BackgroundTasks, Depends, FastAPI, Form, HTTPException, Request, WebSocket
from fastapi.exceptions import RequestValidationError
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    StreamingResponse,
)
from fastapi.templating import Jinja2Templates
from maverick import a2a
from starlette.exceptions import HTTPException as StarletteHTTPException

from ._shared import _any_provider_key_set, _world
from ._shared import _world_cache as _world_cache  # re-export: tests clear app._world_cache
from .api import router as api_router
from .auth import (
    assert_goal_access,
    caller_principal,
    can_access_goal,
    execution_user_id_from_request,
    goal_owner_filter,
    require_principal,
)
from .oidc_login import router as oidc_login_router

log = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _format_datetime(ts) -> str:
    """Jinja filter: float epoch -> 'HH:MM:SS'."""
    import datetime as _dt
    try:
        return _dt.datetime.fromtimestamp(float(ts)).strftime("%H:%M:%S")
    except (TypeError, ValueError):
        return str(ts)


templates.env.filters["datetime"] = _format_datetime
# Make `theme` available unconditionally so templates rendered without
# a Request object (rare; legacy paths) still resolve `theme or 'dark'`.
templates.env.globals.setdefault("theme", "dark")
templates.env.globals.setdefault("font", "default")
templates.env.globals.setdefault("lang", "en")
templates.env.globals.setdefault("density", "comfortable")
templates.env.globals.setdefault("custom_theme_css", "")
templates.env.globals.setdefault("custom_theme_names", [])
templates.env.globals.setdefault("dir", "ltr")
from .i18n import t as _i18n_t  # noqa: E402
from .themes import custom_themes, theme_css  # noqa: E402

templates.env.globals.setdefault("t", lambda key: _i18n_t(key, "en"))

_VALID_THEMES = {"dark", "light", "solarized", "hicontrast"}
_VALID_FONTS = {"default", "dyslexic"}
_VALID_DENSITIES = {"comfortable", "compact"}


def _valid_theme_names() -> set[str]:
    """Built-in themes plus the operator's validated ``[dashboard] themes``."""
    return _VALID_THEMES | set(custom_themes())


def _resolve_theme(request: Request) -> str:
    """Pick the theme from ``?theme=`` query param, cookie, config, then dark."""
    valid = _valid_theme_names()
    q = (request.query_params.get("theme") or "").strip().lower()
    if q in valid:
        return q
    c = (request.cookies.get("mvk_theme") or "").strip().lower()
    if c in valid:
        return c
    try:
        from maverick.config import load_config
        cfg = (load_config() or {}).get("dashboard") or {}
        cfg_theme = (cfg.get("theme") or "").strip().lower()
        if cfg_theme in valid:
            return cfg_theme
    except Exception:
        pass
    return "dark"


def resolve_density(request: Request) -> str:
    """UI density: ``?density=`` → ``mvk_density`` cookie → ``[dashboard]
    density`` config → comfortable. Default-off: ``comfortable`` is the
    existing layout; ``compact`` opts in to the denser one."""
    q = (request.query_params.get("density") or "").strip().lower()
    if q in _VALID_DENSITIES:
        return q
    c = (request.cookies.get("mvk_density") or "").strip().lower()
    if c in _VALID_DENSITIES:
        return c
    try:
        from maverick.config import load_config
        cfg = (load_config() or {}).get("dashboard") or {}
        cfg_density = (cfg.get("density") or "").strip().lower()
        if cfg_density in _VALID_DENSITIES:
            return cfg_density
    except Exception:
        pass
    return "comfortable"


def _resolve_font(request: Request) -> str:
    """Font preference: ``?font=`` → cookie → default. Independent axis from
    the theme so high-contrast + dyslexia-friendly compose."""
    q = (request.query_params.get("font") or "").strip().lower()
    if q in _VALID_FONTS:
        return q
    c = (request.cookies.get("mvk_font") or "").strip().lower()
    if c in _VALID_FONTS:
        return c
    return "default"


# Context processor: every template gets the `theme` variable for the
# body class + the theme switcher links, the `font` accessibility axis,
# and the chrome-i18n helpers (`lang`, `t`).
def _theme_context(request: Request) -> dict:
    from .i18n import dir_for, resolve_lang
    from .i18n import t as _t
    lang = resolve_lang(request)
    custom = custom_themes()
    return {
        "theme": _resolve_theme(request),
        "font": _resolve_font(request),
        "density": resolve_density(request),
        "custom_theme_css": theme_css(custom),
        "custom_theme_names": sorted(custom),
        "lang": lang,
        "dir": dir_for(lang),
        "t": lambda key: _t(key, lang),
    }


# Register the per-request context processor with Starlette so every
# TemplateResponse picks up the resolved theme automatically.
templates.context_processors.append(_theme_context)


def _set_theme_cookie(response, theme: str) -> None:
    """Persist the theme choice as a cookie so it sticks across page loads."""
    if theme in _valid_theme_names():
        response.set_cookie(
            "mvk_theme", theme,
            max_age=30 * 24 * 3600,  # 30 days
            samesite="lax",
            httponly=False,  # the switcher links are visible to JS anyway
        )


app = FastAPI(
    title="Maverick Dashboard + REST API",
    description="Local browser UI plus REST API for programmatic access.",
    version="0.1.0",
    # OIDC bearer-auth gate, applied to every route. Default-OFF: when OIDC is
    # disabled (the default) `require_principal` returns None and changes
    # nothing -- no token is required and no route 401s. When OIDC is enabled it
    # enforces a valid `Authorization: Bearer` ID token on each request (health/
    # liveness/docs paths excepted; see maverick_dashboard.auth). This is an
    # auth layer ON TOP OF the existing MAVERICK_DASHBOARD_TOKEN middleware, not
    # a replacement for it.
    dependencies=[Depends(require_principal)],
)
app.include_router(api_router)
# Built-in OIDC browser-login routes (/auth/login, /auth/callback, /auth/logout).
# Each route self-gates on maverick.oidc.login_enabled() and 404s when the login
# flow isn't fully configured, so including the router unconditionally is inert
# off by default. See maverick_dashboard.oidc_login.
app.include_router(oidc_login_router)
a2a.mount(app)

_DOCS_CSP = (
    "default-src 'self'; "
    "img-src 'self' data: https:; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'none'; "
    "form-action 'self'; "
    "object-src 'none'"
)

_DEFAULT_CSP = (
    "default-src 'self'; "
    "img-src 'self' data:; "
    "style-src 'self' 'unsafe-inline'; "
    "script-src 'self' 'unsafe-inline'; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'none'; "
    "form-action 'self'; "
    "object-src 'none'"
)

# The plan-tree page pulls Cytoscape.js from jsdelivr (SRI-pinned in the
# template). Allow that one host on script-src for this page only; every
# other directive stays as locked-down as _DEFAULT_CSP. connect-src stays
# 'self' — the live poll only ever fetches our own /api/v1 endpoint.
_PLAN_TREE_CSP = (
    "default-src 'self'; "
    "img-src 'self' data:; "
    "style-src 'self' 'unsafe-inline'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'none'; "
    "form-action 'self'; "
    "object-src 'none'"
)

# /goals/{id}/plan — the only page that loads the Cytoscape CDN script.
_PLAN_TREE_PATH_RE = re.compile(r"^/goals/\d+/plan/?$")


@app.middleware("http")
async def persist_theme(request: Request, call_next):
    """If ?theme= / ?font= / ?density= / ?lang= is in the URL, set a cookie so it sticks."""
    response = await call_next(request)
    q = request.query_params.get("theme")
    if q and q.lower() in _valid_theme_names():
        _set_theme_cookie(response, q.lower())
    f = request.query_params.get("font")
    if f and f.lower() in _VALID_FONTS:
        response.set_cookie("mvk_font", f.lower(), max_age=30 * 24 * 3600,
                            samesite="lax", httponly=False)
    d = request.query_params.get("density")
    if d and d.lower() in _VALID_DENSITIES:
        response.set_cookie("mvk_density", d.lower(), max_age=30 * 24 * 3600,
                            samesite="lax", httponly=False)
    lang = request.query_params.get("lang")
    from .i18n import LANGS
    if lang and lang.lower() in LANGS:
        response.set_cookie("mvk_lang", lang.lower(), max_age=365 * 24 * 3600,
                            samesite="lax", httponly=False)
    return response


@app.on_event("startup")
async def _reclaim_orphans() -> None:
    """Mark goals stuck in active/pending as blocked after a crash.

    Without this, SIGKILL/OOM mid-run strands rows in 'active' forever
    and `active_goal()` returns a ghost. Council finding (Tier 0).
    """
    try:
        from maverick.world_model import DEFAULT_DB, WorldModel
        wm = WorldModel(DEFAULT_DB)
        n = wm.reclaim_orphan_goals()
        if n:
            log.warning("reclaimed %d orphan goal(s) from prior crash", n)
    except Exception:
        log.exception("orphan reclaim failed on startup")


@app.on_event("startup")
async def _install_queue_dispatcher() -> None:
    """If ``[queue] backend`` selects a task queue, install the QueueDispatcher
    so this (producer) process enqueues goals for the worker pool instead of
    running them in-process. No-op for the default in-process install."""
    try:
        from maverick.queue_dispatcher import install_from_config
        if install_from_config():
            log.info("queue dispatcher installed: goals run out-of-process")
    except Exception:
        log.exception("queue dispatcher install failed (running in-process)")

_AUTH_EXEMPT = {
    "/healthz", "/livez", "/readyz",
    "/openapi.json", "/docs", "/redoc", "/docs/oauth2-redirect",
    "/.well-known/agent-card.json", "/.well-known/agent.json",
    # /webhook/start authenticates with its own HMAC signature instead of
    # the dashboard bearer / same-origin checks (external senders have
    # neither), so it must bypass the centralized middleware.
    "/webhook/start",
    # Linear/Jira/GitHub issue webhooks authenticate the same way (their
    # own HMAC signature), so they bypass the bearer/same-origin checks too.
    "/webhook/linear",
    "/webhook/jira",
    "/webhook/github",
    "/webhook/gitlab",
    # Built-in OIDC browser-login endpoints: they bootstrap a session and carry
    # their own flow-level security (state/PKCE/signed cookies). They must be
    # reachable by a browser that has no dashboard token yet; each self-gates on
    # login_enabled() and 404s when the login flow is off.
    "/auth/login",
    "/auth/callback",
    "/auth/logout",
    "/auth/error",
}


# Inbound webhook bodies are intentionally small JSON payloads.  Enforce
# this before HMAC verification so unauthenticated callers cannot force the
# dashboard to buffer or hash arbitrarily large request bodies.
_MAX_WEBHOOK_BODY_BYTES = 256 * 1024


async def _read_limited_webhook_body(request: Request) -> bytes:
    """Read a webhook request body with a hard size cap.

    ``Content-Length`` lets us reject obviously oversized requests before
    reading any body bytes.  For chunked or otherwise lengthless requests,
    stream incrementally and abort as soon as the cap is exceeded instead of
    using ``request.body()``, which buffers the entire body before returning.
    """
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            declared = int(content_length)
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid Content-Length")
        if declared > _MAX_WEBHOOK_BODY_BYTES:
            raise HTTPException(status_code=413, detail="webhook body too large")

    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > _MAX_WEBHOOK_BODY_BYTES:
            raise HTTPException(status_code=413, detail="webhook body too large")
    return bytes(body)

# Safe methods skip the CSRF check (browsers send Origin/Referer
# inconsistently on GETs from address bars and bookmarks).
_CSRF_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _is_same_origin(request: Request) -> bool:
    """Allow only same-origin browser submissions for mutating form POSTs.

    Fails closed when no Origin or Referer is present on a mutating
    request. The previous fail-open branch ("Non-browser/API clients
    commonly omit both headers") was a soft-CSRF: any tab on the same
    machine could fire a no-cors fetch with both headers stripped and
    have it accepted. Real API clients send Authorization headers and
    are exempted by the bearer-auth middleware before they reach here.
    """
    if request.method in _CSRF_SAFE_METHODS:
        return True
    expected = request.url.netloc
    for header in ("origin", "referer"):
        value = request.headers.get(header)
        if not value:
            continue
        parsed = urlparse(value)
        if parsed.netloc == expected:
            return True
        return False
    return False


def _is_loopback_client(host: str) -> bool:
    """True for in-process/loopback callers (safe to serve without a token)."""
    if not host:
        return False
    # Starlette's in-process TestClient reports host="testclient"; a real
    # network peer can never present that (request.client.host is the
    # socket peer, set by the server, not user-controllable).
    if host in ("localhost", "testclient"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


# Standard headers a reverse proxy adds when forwarding a request.
_PROXY_FORWARD_HEADERS = ("x-forwarded-for", "x-forwarded-host", "x-real-ip", "forwarded")


def _is_proxied(request: Request) -> bool:
    """True if a reverse proxy forwarded this request.

    In no-token mode the dashboard trusts the loopback peer
    (``request.client.host``). A reverse proxy on the same host connects over
    loopback, so a deploy that fronts the app with a public proxy but forgets
    to set ``MAVERICK_DASHBOARD_TOKEN`` on the app process would serve the
    control surface unauthenticated to the internet — the loopback peer is the
    proxy, not the real remote client. Treat any standard forwarding header as
    proof a proxy is in front and fall through to the token requirement (fail
    closed). Reading these headers only ever makes auth STRICTER, so a forged
    header cannot grant access — at worst a direct caller locks itself out by
    sending one.
    """
    return any(request.headers.get(h) for h in _PROXY_FORWARD_HEADERS)


@app.middleware("http")
async def bearer_auth(request: Request, call_next):
    expected = os.environ.get("MAVERICK_DASHBOARD_TOKEN")
    if request.url.path in _AUTH_EXEMPT:
        return await call_next(request)
    if not expected:
        # No token configured: serve loopback only. An operator who binds
        # --host 0.0.0.0 without setting a token must NOT silently expose
        # run history, spend, and the control surface unauthenticated to
        # the network. Set MAVERICK_DASHBOARD_TOKEN to allow remote access.
        client_host = request.client.host if request.client else ""
        if _is_loopback_client(client_host) and not _is_proxied(request):
            # Loopback is served without a bearer, so a malicious page open in
            # the user's browser could otherwise drive mutating endpoints via an
            # ambient cross-site request (CSRF): cancel/resume goals, disable
            # safety tools, arm the killswitch, purge caches. Gate unsafe methods
            # behind the same-origin check centrally (the one /chat/send already
            # enforces per-route) so every current and future /api/v1 mutation is
            # covered. Token mode needs no such check — a cross-site page cannot
            # attach the Authorization header.
            # The bundled WebExtension is the one sanctioned cross-origin
            # caller: its Origin is chrome-extension://… and it is accepted
            # only behind the operator's explicit opt-in (see extension_cors).
            if not _is_same_origin(request) and _allowed_extension_origin(request) is None:
                return JSONResponse(
                    {"detail": "cross-site request blocked"},
                    status_code=403,
                )
            return await call_next(request)
        return JSONResponse(
            {"detail": "dashboard requires MAVERICK_DASHBOARD_TOKEN for non-loopback or proxied access"},
            status_code=401,
        )
    auth = request.headers.get("authorization", "")
    header_token = auth[7:] if auth.startswith("Bearer ") else ""
    # ``?token=`` query auth was removed: it leaks the bearer through
    # browser history, Referer headers on outbound link clicks, uvicorn
    # access logs, and any logging proxy in front. Require the
    # ``Authorization: Bearer`` header.
    if header_token and hmac.compare_digest(header_token, expected):
        return await call_next(request)
    return JSONResponse({"detail": "unauthorized"}, status_code=401)


def _wants_html(request: Request) -> bool:
    """True when the client prefers HTML (browser nav) over JSON (API)."""
    accept = (request.headers.get("accept") or "").lower()
    if request.url.path.startswith(("/api/", "/openapi", "/healthz", "/livez", "/readyz", "/metrics")):
        return False
    return "text/html" in accept or "*/*" in accept


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Branded HTML for browser 404s; JSON for API callers."""
    if exc.status_code == 404 and _wants_html(request):
        return templates.TemplateResponse(
            request, "404.html",
            {"path": request.url.path},
            status_code=404,
        )
    return JSONResponse(
        {"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """422 for browser nav becomes 400 with the branded error page."""
    if _wants_html(request):
        return templates.TemplateResponse(
            request, "500.html",
            {"path": request.url.path},
            status_code=400,
        )
    return JSONResponse({"detail": exc.errors()}, status_code=422)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Catch-all so we never serve the default white "Internal Server Error"."""
    log.exception("unhandled dashboard exception on %s", request.url.path)
    if _wants_html(request):
        return templates.TemplateResponse(
            request, "500.html",
            {"path": request.url.path},
            status_code=500,
        )
    return JSONResponse({"detail": "internal server error"}, status_code=500)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Apply baseline browser-security headers to every response.

    These are cheap, well-supported, and close a class of attacks
    (clickjacking, MIME sniffing, Referer leakage, cross-origin
    exfiltration) the dashboard had no defense against before.
    """
    response = await call_next(request)
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault(
        "Cross-Origin-Opener-Policy", "same-origin",
    )
    # Content-Security-Policy. The templates use first-party inline
    # <style>, <script>, and style="" attributes, so script/style-src
    # need 'unsafe-inline' for now (a nonce-based tightening is tracked
    # tech debt). The value still hardens the dashboard meaningfully:
    #   - default/connect/script/style 'self' → injected JS can't fetch()
    #     to an external exfil endpoint or pull a remote script
    #   - frame-ancestors 'none' → reinforces X-Frame-Options (clickjack)
    #   - form-action 'self' → an injected <form> can't POST off-origin
    #   - object-src 'none', base-uri 'none' → kill plugin + <base> tricks
    # This matters because the dashboard renders agent-produced text;
    # if any of it ever reaches an HTML sink, CSP is the backstop.
    path = request.url.path
    if path in {"/docs", "/redoc"}:
        csp = _DOCS_CSP
    elif _PLAN_TREE_PATH_RE.match(path):
        csp = _PLAN_TREE_CSP
    else:
        csp = _DEFAULT_CSP
    response.headers.setdefault("Content-Security-Policy", csp)
    return response


# ----- browser-extension CORS gate (extensions/browser) -----
# The bundled WebExtension is a cross-origin caller: its popup/service-worker
# fetches arrive with an Origin of chrome-extension://<id> (moz-extension://
# <uuid> on Firefox). Browsers need CORS approval for it to read responses,
# and the no-token CSRF gate in bearer_auth would otherwise 403 its POSTs.
# This allowance is OPT-IN and fail-closed: until the operator sets
# `[dashboard] allow_extension = true` (or MAVERICK_DASHBOARD_ALLOW_EXTENSION=1)
# no CORS header is ever emitted and extension origins stay blocked. It is
# scoped to extension origins only — a web origin (https://…) never matches,
# so the same-origin posture for ordinary sites is unchanged. A configured
# dashboard token still applies to every extension call (the extension sends
# the same Authorization: Bearer header as any API client).
_EXTENSION_ORIGIN_RE = re.compile(r"^(?:chrome|moz)-extension://[a-zA-Z0-9-]+$")


def _extension_cors_enabled() -> bool:
    """Operator opt-in for the bundled WebExtension. Fail-closed default."""
    if os.environ.get("MAVERICK_DASHBOARD_ALLOW_EXTENSION") == "1":
        return True
    try:
        from maverick.config import load_config
        return bool(((load_config() or {}).get("dashboard") or {}).get("allow_extension"))
    except Exception:
        return False


def _allowed_extension_origin(request: Request) -> str | None:
    """The request's Origin, iff it is an extension origin AND the gate is on."""
    origin = request.headers.get("origin") or ""
    if _EXTENSION_ORIGIN_RE.match(origin) and _extension_cors_enabled():
        return origin
    return None


@app.middleware("http")
async def extension_cors(request: Request, call_next):
    """CORS for the bundled WebExtension only (opt-in; see above).

    Registered after the other middlewares, so it is OUTERMOST: preflights
    are answered before bearer_auth (a preflight carries no Authorization
    header by design and grants nothing by itself), and the CORS header is
    added to every response for an allowed origin — including 401s, so the
    popup can read the error instead of a blocked-by-CORS blank.
    """
    origin = _allowed_extension_origin(request)
    if origin is None:
        return await call_next(request)
    if request.method == "OPTIONS" and request.headers.get("access-control-request-method"):
        return PlainTextResponse("", status_code=204, headers={
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Authorization, Content-Type",
            "Access-Control-Max-Age": "600",
            "Vary": "Origin",
        })
    response = await call_next(request)
    response.headers["Access-Control-Allow-Origin"] = origin
    vary = response.headers.get("Vary")
    if not vary:
        response.headers["Vary"] = "Origin"
    elif "origin" not in vary.lower():
        response.headers["Vary"] = f"{vary}, Origin"
    return response


# ----- goal-creation rate limit -----
# Council safety-seat (round 1): nothing throttled /chat/send or
# POST /api/v1/goals. A runaway loop or a flood of same-origin posts
# could spawn unbounded goals, each costing real money. This is an
# in-process sliding-window limiter (no new dependency) shared by all
# goal-creating routes. Caps are generous and configurable.
#
# Exposed-deployment hardening: the window used to be one process-wide
# deque shared across every caller AND the HMAC webhooks, so a single
# noisy client (or a webhook flood) 429'd everyone. Key the per-client
# window per principal/source (client IP, or a webhook source label) and
# keep a separate global ceiling so the process still can't be driven to
# spawn unbounded paid goals in aggregate.
_goal_times: dict[str, deque[float]] = {}
_goal_times_global: deque[float] = deque()
_goal_rl_lock = threading.Lock()


def _max_goals_per_min() -> int:
    try:
        return max(1, int(os.environ.get("MAVERICK_DASHBOARD_MAX_GOALS_PER_MIN", "30")))
    except ValueError:
        return 30


def _max_goals_global_per_min() -> int:
    # Process-wide ceiling across all clients; defaults to 10x the per-client
    # cap so one client can't starve others yet a distributed flood is still
    # bounded.
    try:
        return max(1, int(os.environ.get(
            "MAVERICK_DASHBOARD_MAX_GOALS_GLOBAL_PER_MIN",
            str(_max_goals_per_min() * 10),
        )))
    except ValueError:
        return _max_goals_per_min() * 10


def _rate_limit_key(request: Request | None, source: str | None = None) -> str:
    """Identify the principal/source for rate-limiting.

    Assumption (documented): we don't have per-request auth principals
    threaded through here, so we key on the client IP (the safe, IP-based
    option called out in the issue). HMAC webhooks pass an explicit
    ``source`` label since their callers share no useful client identity.
    """
    if source:
        return f"source:{source}"
    host = request.client.host if (request and request.client) else "unknown"
    return f"ip:{host}"


def check_goal_rate_limit(
    request: Request | None = None, *, source: str | None = None
) -> None:
    """Raise HTTPException(429) if the goal-creation rate exceeds a cap.

    Two 60-second sliding windows are enforced: a per-client window keyed
    by principal/source (so one noisy client can't 429 everyone) and a
    process-wide global ceiling (so a distributed flood still can't spawn
    unbounded paid goals).
    """
    key = _rate_limit_key(request, source)
    cap = _max_goals_per_min()
    global_cap = _max_goals_global_per_min()
    now = time.monotonic()
    cutoff = now - 60.0
    with _goal_rl_lock:
        # Global ceiling first.
        while _goal_times_global and _goal_times_global[0] < cutoff:
            _goal_times_global.popleft()
        if len(_goal_times_global) >= global_cap:
            retry = int(60 - (now - _goal_times_global[0])) + 1
            raise HTTPException(
                status_code=429,
                detail=f"goal rate limit reached ({global_cap}/min total). "
                       f"Try again in {retry}s.",
                headers={"Retry-After": str(max(1, retry))},
            )

        window = _goal_times.get(key)
        if window is None:
            window = _goal_times[key] = deque()
        while window and window[0] < cutoff:
            window.popleft()
        if len(window) >= cap:
            retry = int(60 - (now - window[0])) + 1
            raise HTTPException(
                status_code=429,
                detail=f"goal rate limit reached ({cap}/min). Try again in {retry}s.",
                headers={"Retry-After": str(max(1, retry))},
            )

        # Opportunistically drop empty per-client windows so a flood of
        # distinct IPs can't grow the dict without bound.
        for stale_key in [k for k, w in _goal_times.items() if not w and k != key]:
            del _goal_times[stale_key]

        window.append(now)
        _goal_times_global.append(now)


# ----- SSE stream concurrency cap -----
# Council security finding (exposed-deployment hardening): each open SSE
# stream spawns a 300s task polling SQLite every 0.5s. Thousands of
# EventSource opens exhaust file descriptors and the event loop. Cap the
# number of concurrent streams with a semaphore (no new dependency) and
# return 503 past the cap. Built lazily on the running loop so the limit
# binds to the event loop the streams actually run on.
def _max_sse_streams() -> int:
    try:
        return max(1, int(os.environ.get("MAVERICK_DASHBOARD_MAX_SSE", "64")))
    except ValueError:
        return 64


_sse_semaphore: asyncio.Semaphore | None = None


def _get_sse_semaphore() -> asyncio.Semaphore:
    global _sse_semaphore
    if _sse_semaphore is None:
        _sse_semaphore = asyncio.Semaphore(_max_sse_streams())
    return _sse_semaphore


def _load_skills():
    from maverick.skills import load_skills
    return load_skills()


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    w = _world()
    # Use SQL aggregation instead of pulling every goal into Python. Owner-scope
    # the rollup to the caller (auth-off/admin -> all; see goal_owner_filter).
    owner = goal_owner_filter(request)
    if owner is None:
        rows = w.conn.execute(
            "SELECT status, COUNT(*) FROM goals GROUP BY status"
        ).fetchall()
    else:
        rows = w.conn.execute(
            "SELECT status, COUNT(*) FROM goals WHERE owner = ? GROUP BY status",
            (owner,),
        ).fetchall()
    by_status = {r[0]: int(r[1]) for r in rows}
    counts = {
        "total":   sum(by_status.values()),
        "active":  by_status.get("active", 0),
        "done":    by_status.get("done", 0),
        "blocked": by_status.get("blocked", 0),
    }
    # Bounded recent slice instead of "load every goal ever, take last 20".
    recent = w.list_goals(owner=owner, limit=20, order="desc")
    facts = w.get_facts()
    skills = _load_skills()
    return templates.TemplateResponse(
        request, "index.html",
        {"counts": counts, "goals": recent,
         "facts": facts, "skills": skills[:10]},
    )


@app.get("/redact", response_class=HTMLResponse)
async def redact_page(request: Request) -> HTMLResponse:
    """Granular redaction UI (preview/select/scrub via /api/v1/redact/preview)."""
    return templates.TemplateResponse(request, "redact.html", {})


@app.get("/perf", response_class=HTMLResponse)
async def perf_page(request: Request) -> HTMLResponse:
    """Public perf dashboard: SLA + benchmark history (data via /api/v1/perf)."""
    return templates.TemplateResponse(request, "perf.html", {})


@app.get("/goals", response_class=HTMLResponse)
async def goals_page(request: Request) -> HTMLResponse:
    goals = _world().list_goals(owner=goal_owner_filter(request), limit=200, order="desc")
    return templates.TemplateResponse(request, "goals.html", {"goals": goals})


@app.get("/tenants", response_class=HTMLResponse)
async def tenants_page(request: Request) -> HTMLResponse:
    """Operator console: the provisioned-tenant roster (status / plan / quota).

    Cross-tenant control-plane data, so it is admin-only: a non-admin
    authenticated caller (``goal_owner_filter`` returns their principal) sees an
    access notice, not the roster. Fail-soft to an empty roster so a missing
    registry never 500s the console.
    """
    is_admin = goal_owner_filter(request) is None
    tenants = []
    if is_admin:
        try:
            from maverick.tenant_registry import list_tenants
            tenants = list_tenants()
        except Exception:  # pragma: no cover -- never 500 the console
            tenants = []
    return templates.TemplateResponse(
        request, "tenants.html", {"tenants": tenants, "is_admin": is_admin},
    )


def _tenant_overview_rows() -> list[dict]:
    """Per-tenant rollup for the multi-tenant view: goals by status (from the
    tenant's own world DB, when one exists), today's spend, suspended flag.

    Fail-soft per tenant: an unreadable world DB or spend ledger yields zero
    counts/spend, never a 500. A tenant whose world.db doesn't exist yet (no
    runs) reports empty counts rather than materializing the DB.
    """
    from maverick.tenant_registry import list_tenants, tenant_spend_today
    rows: list[dict] = []
    for t in list_tenants():
        counts: dict[str, int] = {}
        try:
            from maverick.workspace import Workspace
            db = Workspace(t.id).db_path
            if db.exists():
                from maverick.world_model import WorldModel
                wm = WorldModel(db)
                try:
                    counts = {
                        str(r[0]): int(r[1]) for r in wm.conn.execute(
                            "SELECT status, COUNT(*) FROM goals GROUP BY status"
                        )
                    }
                finally:
                    wm.close()
        except Exception:  # pragma: no cover -- one bad tenant DB never 500s
            counts = {}
        try:
            spend = float(tenant_spend_today(t.id))
        except Exception:  # pragma: no cover -- spend read never blocks the view
            spend = 0.0
        rows.append({
            "id": t.id,
            "display_name": t.display_name,
            "plan": t.plan,
            "status": t.status,
            "suspended": not t.active,
            "goals": counts,
            "total_goals": sum(counts.values()),
            "spend_today": round(spend, 4),
            "max_daily_dollars": t.max_daily_dollars,
        })
    return rows


@app.get("/tenants/overview", response_class=HTMLResponse)
async def tenants_overview_page(request: Request) -> HTMLResponse:
    """Multi-tenant view: per-tenant goal/spend rollup for the operator.

    Admin-only exactly like ``/tenants`` (cross-tenant control-plane data): a
    non-admin authenticated caller sees an access notice, not the rollup.
    Fail-soft to an empty roster so a missing registry never 500s the console.
    """
    is_admin = goal_owner_filter(request) is None
    rows: list[dict] = []
    if is_admin:
        try:
            rows = _tenant_overview_rows()
        except Exception:  # pragma: no cover -- never 500 the console
            rows = []
    return templates.TemplateResponse(
        request, "tenants_overview.html", {"rows": rows, "is_admin": is_admin},
    )


@app.get("/api/v1/tenants/overview")
async def tenants_overview_api(request: Request) -> JSONResponse:
    """JSON face of the multi-tenant view. Admin-only like ``/tenants``."""
    if goal_owner_filter(request) is not None:
        raise HTTPException(status_code=403, detail="admin access required")
    try:
        rows = _tenant_overview_rows()
    except Exception:  # pragma: no cover -- never 500 the console
        rows = []
    return JSONResponse({"tenants": rows})


@app.get("/skills", response_class=HTMLResponse)
async def skills_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "skills.html", {"skills": _load_skills()})


@app.get("/learned", response_class=HTMLResponse)
async def learned_page(request: Request) -> HTMLResponse:
    """Self-learning observability: the learned-capability ledger + the
    on-disk generated tools, with a remove action per generated tool (#427)."""
    from .api import _learned_snapshot
    return templates.TemplateResponse(
        request, "learned.html", _learned_snapshot(),
    )


@app.get("/facts", response_class=HTMLResponse)
async def facts_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "facts.html", {"facts": _world().get_facts()})


@app.get("/spend", response_class=HTMLResponse)
async def spend_page(request: Request) -> HTMLResponse:
    w = _world()
    return templates.TemplateResponse(
        request, "spend.html",
        {"episodes": w.list_episodes(limit=50), "total": w.total_spend()},
    )


@app.get("/providers", response_class=HTMLResponse)
async def providers_page(request: Request) -> HTMLResponse:
    from maverick.provider_health import get as _health
    return templates.TemplateResponse(
        request, "providers.html", {"rows": _health().snapshot()},
    )


# ----- Control surface pages (council pass) -----

_AUDIT_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def safe_audit_day(day: str | None) -> str | None:
    """Validate a ``?day=`` value as YYYY-MM-DD before it reaches the
    audit log's path builder.

    The audit log resolves ``day`` to ``audit_dir/{day}.ndjson``; an
    unvalidated value like ``../../../etc/foo`` would escape the audit
    directory. Anything that isn't a bare date is rejected to ``None``
    (today), neutralizing path traversal at the HTTP boundary.
    """
    if day and _AUDIT_DAY_RE.match(day):
        return day
    return None


@app.get("/audit", response_class=HTMLResponse)
async def audit_page(request: Request) -> HTMLResponse:
    """Tail of the local audit log."""
    from maverick.audit import default_audit_log
    try:
        n = max(1, min(int(request.query_params.get("n") or 200), 1000))
    except (TypeError, ValueError):
        n = 200
    day = safe_audit_day(request.query_params.get("day"))
    events = default_audit_log().tail(n, day=day)
    # Distinct kinds in this tail (for the filter dropdown), computed before
    # filtering so every available kind stays selectable; then optionally
    # narrow to one kind (e.g. shield_block, tool_call).
    kinds = sorted({str(e.get("kind")) for e in events if e.get("kind")})
    kind = (request.query_params.get("kind") or "").strip()
    if kind:
        events = [e for e in events if e.get("kind") == kind]
    return templates.TemplateResponse(
        request, "audit.html",
        {"events": events, "n": n, "day": day, "kind": kind, "kinds": kinds},
    )


@app.get("/compartments", response_class=HTMLResponse)
async def compartments_page(request: Request) -> HTMLResponse:
    """The agent factory's roster: each domain pack and the bulkhead it runs in.

    Reads the discoverable domain packs (built-in + onboarded) so an operator
    can see which sealed agents exist and the capability envelope each runs
    under -- the compartments a Rung-2 seal acts on."""
    try:
        from maverick.domain import available_domains
        domains = sorted(available_domains().values(), key=lambda d: d.name)
    except Exception:  # never 500 the page if the factory layer is unavailable
        domains = []
    return templates.TemplateResponse(request, "compartments.html", {"domains": domains})


_OVERSIGHT_KINDS = frozenset({
    "governance_denied", "shield_block", "capability_denied",
    "egress_blocked", "consent_result", "halt",
})


def _is_intervention(e: dict) -> bool:
    """True iff an audit event is a control-plane intervention.

    A ``consent_result`` only counts when it denied/timed out -- an approval is
    not an intervention.
    """
    kind = e.get("kind")
    if kind == "consent_result":
        return str(e.get("decision") or "").lower() in {"deny", "timeout"}
    return kind in _OVERSIGHT_KINDS


def _intervention_detail(e: dict) -> str:
    """A one-line, human summary of an intervention, by kind."""
    kind = e.get("kind")
    if kind == "shield_block":
        return f"{e.get('stage') or '?'}: {e.get('reason') or ''}".strip()
    if kind == "capability_denied":
        return f"tool={e.get('tool') or '?'} principal={e.get('principal') or '?'}"
    if kind == "egress_blocked":
        return f"provider={e.get('provider') or '?'}"
    if kind == "consent_result":
        return f"{e.get('decision') or '?'}: {e.get('action') or ''}".strip()
    if kind == "halt":
        return f"{e.get('source') or '?'}: {e.get('detail') or ''}".strip()
    # governance_denied (and any future kind): the reason, plus which policy
    # rule fired so the operator can see why it was held.
    detail = str(e.get("reason") or e.get("detail") or e.get("tool") or "")
    rule = e.get("rule")
    if kind == "governance_denied" and rule:
        detail = f"{detail} [{rule}]".strip()
    return detail


def _audit_event_visible_to_caller(
    e: dict,
    *,
    principal: str | None,
    owner_filter: str | None,
    world,
    goal_owner_cache: dict[int, str | None],
) -> bool:
    """Return whether an oversight audit row is visible to this dashboard user.

    ``owner_filter is None`` is the dashboard's established bypass for auth-off
    single-user mode and admins.  Authenticated non-admins only see events tied
    to one of their goals, or ownerless events whose explicit user principal is
    theirs.  Unknown/malformed ownership markers fail closed so the global audit
    log cannot leak cross-tenant guardrail metadata.
    """
    if owner_filter is None:
        return True
    if principal is None:
        return False

    raw_goal_id = e.get("goal_id")
    if raw_goal_id not in (None, ""):
        try:
            goal_id = int(raw_goal_id)
        except (TypeError, ValueError):
            return False
        if goal_id not in goal_owner_cache:
            try:
                goal = world.get_goal(goal_id)
                goal_owner_cache[goal_id] = getattr(goal, "owner", None) if goal else None
            except Exception:
                goal_owner_cache[goal_id] = None
        return goal_owner_cache[goal_id] == owner_filter

    return str(e.get("principal") or "") == principal


@app.get("/oversight", response_class=HTMLResponse)
async def oversight_page(request: Request) -> HTMLResponse:
    """Operator mission-control: every control-plane intervention in one pane.

    Unifies what each guardrail did to the fleet -- org-policy DENY /
    REQUIRE_HUMAN (governance, EU AI Act Art 14), shield blocks, capability
    denials, the enterprise egress lock, consent denials, and killswitch halts
    -- next to the live halt state, the pending human-approval queue, and the
    count of active agents. The per-guardrail pages (/safety, /approvals,
    /audit, /fleets) remain the deep dives; this is the at-a-glance roll-up.
    Fail-soft: an unreadable audit log yields empty panels, never a 500.
    """
    from collections import Counter, deque

    from maverick.audit import default_audit_log
    try:
        n = max(1, min(int(request.query_params.get("n") or 1000), 5000))
    except (TypeError, ValueError):
        n = 1000
    day = safe_audit_day(request.query_params.get("day"))
    since = safe_audit_day(request.query_params.get("since"))
    until = safe_audit_day(request.query_params.get("until"))
    ranged = bool(since or until)
    w = _world()
    owner_filter = goal_owner_filter(request)
    principal = caller_principal(request)
    goal_owner_cache: dict[int, str | None] = {}

    # Counts span the whole window; the trail keeps only the newest 150 (a
    # bounded deque), so a wide incident-review range stays cheap in memory.
    by_kind: Counter = Counter()
    recent: deque = deque(maxlen=150)
    total = 0
    if ranged:
        # Incident review: an inclusive [since, until] window across day-files,
        # reusing the export reader's lexical date filter (open-ended if one
        # bound is unset). Bound the file scan on a very wide window.
        from maverick.audit.export import iter_audit_events
        scanned = 0
        try:
            for e in iter_audit_events(since=since, until=until):
                scanned += 1
                if scanned > 200_000:
                    break
                if _is_intervention(e) and _audit_event_visible_to_caller(
                    e, principal=principal, owner_filter=owner_filter,
                    world=w, goal_owner_cache=goal_owner_cache,
                ):
                    by_kind[str(e.get("kind"))] += 1
                    total += 1
                    recent.append(e)
        except Exception:  # pragma: no cover - never 500 the console on a log error
            pass
    else:
        try:
            raw = default_audit_log().tail(n, day=day)
        except Exception:  # pragma: no cover - never 500 the console on a log error
            raw = []
        for e in raw:
            if _is_intervention(e) and _audit_event_visible_to_caller(
                e, principal=principal, owner_filter=owner_filter,
                world=w, goal_owner_cache=goal_owner_cache,
            ):
                by_kind[str(e.get("kind"))] += 1
                total += 1
                recent.append(e)

    rows = [
        {
            "ts": e.get("ts"),
            "kind": e.get("kind"),
            "agent": e.get("agent") or "-",
            "goal_id": e.get("goal_id"),
            "detail": _intervention_detail(e),
        }
        for e in reversed(recent)
    ]

    try:
        from maverick.killswitch import is_active
        halted = bool(is_active())
    except Exception:
        halted = False

    try:
        approvals = list(w.pending_approvals())
    except Exception:
        approvals = []
    sources = {a.id: _approval_source(a.provenance) for a in approvals}
    try:
        active = len(w.list_goals(status="active", owner=owner_filter))
    except Exception:
        active = 0

    return templates.TemplateResponse(
        request, "oversight.html",
        {
            "events": rows,
            "by_kind": dict(by_kind),
            "total": total,
            "ranged": ranged,
            "since": since,
            "until": until,
            "halted": halted,
            "approvals": approvals,
            "sources": sources,
            "pending": len(approvals),
            "active": active,
            "n": n,
            "day": day,
        },
    )


@app.get("/safety", response_class=HTMLResponse)
async def safety_page(request: Request) -> HTMLResponse:
    """Shield activity: what the safety layer blocked, by stage and reason."""
    from collections import Counter

    from maverick.audit import default_audit_log
    try:
        n = max(1, min(int(request.query_params.get("n") or 1000), 5000))
    except (TypeError, ValueError):
        n = 1000
    day = safe_audit_day(request.query_params.get("day"))
    blocks = [
        e for e in default_audit_log().tail(n, day=day)
        if e.get("kind") == "shield_block"
    ]
    by_stage = Counter((e.get("stage") or "unknown") for e in blocks)
    top_reasons = Counter((e.get("reason") or "unknown") for e in blocks).most_common(10)
    recent = list(reversed(blocks))[:100]
    return templates.TemplateResponse(
        request, "safety.html",
        {
            "total": len(blocks),
            "by_stage": dict(by_stage),
            "top_reasons": top_reasons,
            "events": recent,
            "n": n,
            "day": day,
        },
    )


def _compliance_view(framework: str) -> dict:
    """Build the control-coverage view for the /compliance page + export.

    Reuses ``maverick.compliance.compliance_report()`` (the same source the
    ``maverick compliance`` CLI maps to GDPR + EU AI Act + US frameworks) and
    applies the ``?framework=eu|us|all`` filter the CLI uses. Fail-soft: if the
    core import or the report raises, return an empty view so the page renders an
    empty state instead of 500ing. ``framework`` is normalised to one of
    ``eu``/``us``/``all`` (default ``all``).
    """
    framework = framework if framework in {"eu", "us", "all"} else "all"
    try:
        from maverick.compliance import COMPLIANCE_DISCLAIMER, compliance_report
        checks = compliance_report()
    except Exception:  # pragma: no cover - never 500 the console if core is absent
        return {"framework": framework, "groups": {}, "summary": {}, "disclaimer": ""}
    if framework != "all":
        checks = [c for c in checks if c.framework == framework]
    # Group by framework bucket ("eu"/"us") for labelled tables on the page.
    labels = {"eu": "EU AI Act / GDPR", "us": "NIST AI RMF + US state/sector law"}
    groups: dict[str, dict] = {}
    for c in checks:
        bucket = groups.setdefault(
            c.framework, {"label": labels.get(c.framework, c.framework), "rows": []}
        )
        bucket["rows"].append(c)
    summary = {
        "active": sum(1 for c in checks if c.status == "active"),
        "action_needed": sum(1 for c in checks if c.status == "action_needed"),
        "total": len(checks),
    }
    return {
        "framework": framework,
        "groups": groups,
        "summary": summary,
        "disclaimer": COMPLIANCE_DISCLAIMER,
    }


@app.get("/compliance", response_class=HTMLResponse)
async def compliance_page(request: Request) -> HTMLResponse:
    """Auditor-ready control-coverage report (GDPR + EU AI Act + US frameworks).

    Org/system-level posture (like /safety), grouped by framework. The
    ``?framework=eu|us|all`` query param mirrors ``maverick compliance``.
    Control coverage only -- not a legal attestation. Fail-soft to an empty
    state so a missing core install never 500s the console.
    """
    view = _compliance_view(request.query_params.get("framework") or "all")
    return templates.TemplateResponse(request, "compliance.html", view)


@app.get("/plugins", response_class=HTMLResponse)
async def plugins_page(request: Request) -> HTMLResponse:
    """Discovered + enabled plugins."""
    try:
        from maverick.plugins import _allowed_plugin_names, _entry_points
    except Exception:
        return templates.TemplateResponse(
            request, "plugins.html",
            {"groups": {}, "allowlist_active": False, "error": "plugin discovery failed"},
        )
    allow = _allowed_plugin_names()
    groups: dict[str, list[dict]] = {}
    for label, group in (
        ("tools",    "maverick.tools"),
        ("channels", "maverick.channels"),
        ("skills",   "maverick.skills"),
        ("personas", "maverick.personas"),
    ):
        items: list[dict] = []
        try:
            for ep in _entry_points(group):
                items.append({
                    "name": ep.name,
                    "module": getattr(ep, "value", str(ep)),
                    "enabled": allow is None or ep.name in allow,
                })
        except Exception:
            pass
        groups[label] = items
    return templates.TemplateResponse(
        request, "plugins.html",
        {"groups": groups, "allowlist_active": allow is not None, "error": None},
    )


@app.get("/mcp", response_class=HTMLResponse)
async def mcp_page(request: Request) -> HTMLResponse:
    """Configured MCP servers."""
    try:
        from maverick.config import load_config
        servers = (load_config() or {}).get("mcp_servers") or {}
    except Exception:
        servers = {}
    return templates.TemplateResponse(
        request, "mcp.html", {"servers": servers},
    )


@app.get("/tools", response_class=HTMLResponse)
async def tools_page(request: Request) -> HTMLResponse:
    """Tools the agent currently has registered (post-ACL, post-rate-limit)."""
    tools: list[dict] = []
    error = None
    try:
        from maverick.sandbox import build_sandbox
        from maverick.tools import base_registry
        from maverick.world_model import DEFAULT_DB, WorldModel
        wm = WorldModel(DEFAULT_DB)
        sb = build_sandbox()
        reg = base_registry(world=wm, sandbox=sb)
        tools = [{"name": t.name, "description": (t.description or "")[:240]}
                 for t in sorted(reg.all(), key=lambda x: x.name)]
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
    return templates.TemplateResponse(
        request, "tools.html", {"tools": tools, "error": error},
    )


def _permissions_snapshot() -> dict:
    """Aggregate everything the agent is currently allowed to do.

    Read-only view assembled from config + the live registry + the
    dashboard's runtime overrides. Powers the /permissions page and
    GET /api/v1/permissions.
    """
    snap: dict = {
        "tools": [], "capabilities": {}, "channels": [], "sandbox": {},
        "budget": {}, "network": "open", "plugins": [], "providers": [],
        "retention": {}, "overlay_denied": [], "error": None,
        "sandbox_warning": None,
    }
    try:
        from maverick.config import load_config
        cfg = load_config() or {}
    except Exception as e:
        snap["error"] = f"config read failed: {type(e).__name__}: {e}"
        cfg = {}

    snap["capabilities"] = cfg.get("capabilities") or {}
    snap["budget"] = cfg.get("budget") or {}
    snap["retention"] = cfg.get("retention") or {}
    snap["sandbox"] = cfg.get("sandbox") or {}
    # Security surface: the default 'local' sandbox runs model-driven shell on
    # the host with no filesystem/network isolation (secret env vars are
    # scrubbed, but it is not a container). Make the posture explicit on the
    # /permissions page + API instead of leaving it silent.
    _sb_backend = str(snap["sandbox"].get("backend") or "local").strip().lower()
    if _sb_backend == "local":
        snap["sandbox_warning"] = (
            "Sandbox backend is 'local': the agent's shell runs on this host "
            "with no filesystem/network isolation. Use the docker or podman "
            "backend for untrusted goals."
        )
    snap["providers"] = sorted((cfg.get("providers") or {}).keys())
    snap["channels"] = [
        {"name": n, "enabled": bool(c.get("enabled", True))}
        for n, c in (cfg.get("channels") or {}).items()
    ]
    sec = cfg.get("security") or {}
    snap["network"] = (sec.get("network_policy") or "open")

    try:
        from maverick.runtime_overrides import denied_tools as _overlay
        snap["overlay_denied"] = sorted(_overlay())
    except Exception:
        snap["overlay_denied"] = []

    # Live registry = the true set of tools after ACL + rate-limit +
    # overlay filtering. A tool present here is genuinely callable.
    try:
        from maverick.sandbox import build_sandbox
        from maverick.tools import base_registry
        from maverick.world_model import DEFAULT_DB, WorldModel
        wm = WorldModel(DEFAULT_DB)
        reg = base_registry(world=wm, sandbox=build_sandbox())
        enabled = {t.name for t in reg.all()}
    except Exception as e:
        snap["error"] = (snap["error"] or "") + f" registry: {type(e).__name__}: {e}"
        enabled = set()
    # Show enabled tools + the overlay-denied ones (so the user can re-enable).
    names = sorted(enabled | set(snap["overlay_denied"]))
    snap["tools"] = [
        {"name": n, "enabled": n in enabled} for n in names
    ]

    try:
        from maverick.plugins import installed_plugins
        snap["plugins"] = installed_plugins()
    except Exception:
        snap["plugins"] = {}
    return snap


@app.get("/permissions", response_class=HTMLResponse)
async def permissions_page(request: Request) -> HTMLResponse:
    """What Maverick can do — tools, capabilities, channels, data flow."""
    return templates.TemplateResponse(
        request, "permissions.html", {"perm": _permissions_snapshot()},
    )


# The audit kind a governance verdict records when it blocks or parks an
# action (see maverick.governance + the kernel tool path). Referenced as a
# literal so the dashboard reads the log even on a kernel build that predates
# the EventKind constant; resolved from the constant when it exists.
def _governance_event_kind() -> str:
    try:
        from maverick.audit import EventKind
        return getattr(EventKind, "GOVERNANCE_DENIED", "governance_denied")
    except Exception:  # pragma: no cover - audit module always importable
        return "governance_denied"


def _approval_source(provenance: str | None) -> str | None:
    """Label trusted governance/Art-14 approvals, else ``None``.

    Approval ``detail`` is free-form operator context and may include
    model-, user-, or remote-server-controlled text. Only the explicit
    trusted ``provenance`` field may drive source labels in the decision UI.
    """
    if provenance == "governance":
        return "governance · Art 14"
    return None

@app.get("/approvals", response_class=HTMLResponse)
async def approvals_page(request: Request) -> HTMLResponse:
    """Pending high-risk actions awaiting approve/deny.

    Populated when an agent runs with ``MAVERICK_CONSENT_MODE=dashboard``:
    ``safety.consent.require_consent`` parks each gated action here and
    polls for the decision this page writes back. Governance ``REQUIRE_HUMAN``
    holds (EU AI Act Art 14) arrive with trusted provenance metadata;
    ``_approval_source`` labels them so an operator can distinguish a policy
    hold from a plain consent one without trusting free-form detail text.
    """
    approvals = _world().pending_approvals()
    sources = {a.id: _approval_source(a.provenance) for a in approvals}
    return templates.TemplateResponse(
        request, "approvals.html",
        {"approvals": approvals, "sources": sources},
    )


def _recent_governance_holds(limit: int = 10) -> list[dict]:
    """The most recent governance oversight events for the operator console.

    Reuses the audit reader behind ``/audit`` (today's NDJSON tail), filtered to
    governance verdicts (``GOVERNANCE_DENIED``) and returned newest-first. These
    are the Art-14 / Art-12 record of every org-policy block + human-oversight
    hold. Fail-soft: a missing/unreadable log yields an empty panel, never a 500.
    """
    try:
        from maverick.audit import default_audit_log
        kind = _governance_event_kind()
        events = [
            e for e in default_audit_log().tail(500)
            if e.get("kind") == kind
        ]
    except Exception:  # pragma: no cover - never 500 the console on a log error
        return []
    return list(reversed(events))[:limit]


def _fleet_recent_runs(
    fleet_name: str, *, owner: str | None = None, limit: int = 12
) -> list[dict]:
    """A fleet's recent agent runs for the operator console (newest-first).

    Mirrors ``maverick fleet status``: reads the per-fleet run index
    (``maverick.fleet.load_runs``) and resolves each run's goal via the
    dashboard world to recover its ``status`` + ``title``. When ``owner`` is
    set, only goals owned by that principal are rendered, so a stale run index
    from a deleted same-name fleet cannot be attached to a new owner's roster.
    Returns at most ``limit`` rows of ``{agent, goal_id, title, status, ts}``.
    Fail-soft: a missing/garbled index or a vanished goal yields an
    empty/partial list, never a 500.
    """
    try:
        from maverick.fleet import load_runs
        runs = load_runs(fleet_name)
    except Exception:  # pragma: no cover - never 500 the console on a read error
        return []
    w = _world()
    rows: list[dict] = []
    # Newest-first, capped after owner filtering: the index is oldest-first.
    for r in reversed(runs):
        if len(rows) >= limit:
            break
        gid = r.get("goal_id")
        goal = None
        try:
            if isinstance(gid, int):
                goal = w.get_goal(gid)
        except Exception:  # pragma: no cover - a bad row must not break the page
            goal = None
        if owner is not None and (goal is None or getattr(goal, "owner", "") != owner):
            continue
        rows.append({
            "agent": r.get("agent") or "—",
            "goal_id": gid,
            "title": goal.title if goal else "",
            "status": goal.status if goal else "missing",
            "ts": r.get("ts"),
        })
    return rows


@app.get("/fleets", response_class=HTMLResponse)
async def fleets_page(request: Request) -> HTMLResponse:
    """Operator console: the per-employee agent fleets + their oversight.

    Layer C of the enterprise control plane (see
    ``docs/enterprise/architecture.md``): lists each fleet (owner + role-scoped
    roster) alongside the recent governance oversight trail and a link to the
    pending human-approval queue -- the EU AI Act Art 14 human-oversight surface.
    """
    try:
        from maverick.fleet import list_fleets
        fleets = list_fleets()
    except Exception:  # pragma: no cover - never 500 the console if the registry errors
        fleets = []
    # Owner-scope the roster to the caller (auth-off/admin -> all).
    owner = goal_owner_filter(request)
    if owner is not None:
        fleets = [f for f in fleets if f.owner == owner]
    # Per-fleet recent runs (newest-first), scoped to the fleets already shown.
    runs_by_fleet = {f.name: _fleet_recent_runs(f.name, owner=owner) for f in fleets}
    return templates.TemplateResponse(
        request, "fleets.html",
        {
            "fleets": fleets,
            "runs_by_fleet": runs_by_fleet,
            "holds": _recent_governance_holds(),
            "pending_count": len(_world().pending_approvals()),
        },
    )


@app.get("/cache", response_class=HTMLResponse)
async def cache_page(request: Request) -> HTMLResponse:
    """In-process cache stats + purge buttons."""
    from maverick.cache import stats
    return templates.TemplateResponse(
        request, "cache.html", {"stats": stats()},
    )


@app.get("/store", response_class=HTMLResponse)
async def store_page(request: Request) -> HTMLResponse:
    """Skill Store: browse + install catalog skills without a terminal."""
    from maverick.catalog import load_catalog
    try:
        entries = [e.to_dict() for e in load_catalog("skills")]
    except Exception:
        entries = []
    installed = {s.name for s in _load_skills()}
    return templates.TemplateResponse(
        request, "store.html", {"entries": entries, "installed": installed},
    )


def template_market_entries() -> list[dict]:
    """The goal-template catalog (user-installed + bundled), annotated with the
    operator's own star ratings from the marketplace ratings ledger.

    Powers the /templates page and GET /api/v1/templates. Offline + fail-soft:
    a template that no longer parses is skipped; a missing ratings ledger
    means everything shows unrated.
    """
    from maverick.marketplace_ratings import RatingsLedger, stars_bar
    from maverick.templates import list_templates, load_template
    try:
        ratings = RatingsLedger().all_ratings("templates")
    except Exception:  # pragma: no cover -- ratings never block the catalog
        ratings = {}
    entries: list[dict] = []
    for name in list_templates():
        try:
            tpl = load_template(name)
        except (OSError, ValueError, FileNotFoundError):
            continue
        mine = ratings.get(name) or {}
        stars = mine.get("stars")
        entries.append({
            "name": name,
            "title": tpl.title,
            "params": list(tpl.params),
            "body": tpl.body[:2000],
            "stars": stars,
            "rating_bar": stars_bar(float(stars), 0) if stars else "unrated",
        })
    return entries


@app.get("/templates", response_class=HTMLResponse)
async def templates_market_page(request: Request) -> HTMLResponse:
    """Visual goal-templates marketplace: browse the catalog with ratings and
    one-click "use template" (prefills the chat form via query params — the
    goal never auto-starts)."""
    return templates.TemplateResponse(
        request, "templates_market.html", {"entries": template_market_entries()},
    )


@app.get("/channels", response_class=HTMLResponse)
async def channels_page(request: Request) -> HTMLResponse:
    """Configured + enabled channels."""
    sensitive_markers = (
        "token", "secret", "password", "passwd", "api_key", "apikey", "auth",
        "credential", "cookie", "session",
    )

    def _display_channels(channels: dict) -> dict:
        out: dict = {}
        for name, cfg in (channels or {}).items():
            if not isinstance(cfg, dict):
                out[name] = {"enabled": bool(cfg)}
                continue
            safe_cfg: dict = {}
            for key, value in cfg.items():
                key_l = str(key).lower()
                if any(marker in key_l for marker in sensitive_markers):
                    safe_cfg[key] = "[redacted]"
                else:
                    safe_cfg[key] = value
            out[name] = safe_cfg
        return out

    try:
        from maverick.config import load_config
        channels = _display_channels((load_config() or {}).get("channels") or {})
    except Exception:
        channels = {}
    return templates.TemplateResponse(
        request, "channels.html", {"channels": channels},
    )


@app.get("/api/v1/providers")
async def providers_api() -> JSONResponse:
    from maverick.provider_health import get as _health
    return JSONResponse({"providers": _health().snapshot()})


@app.websocket("/ws/v1/runs/{goal_id}/events")
async def run_events_firehose(websocket: WebSocket, goal_id: int) -> None:
    """Run-events firehose: stream a goal's events over WebSocket as they land.

    Sends each event as one JSON message ``{id, agent, kind, content, ts}``;
    a final ``{kind: "status", content: <terminal>}`` message closes the
    stream when the goal finishes. Auth mirrors the HTTP policy (Authorization
    header in token mode; loopback-only otherwise), checked before accept.
    Resume with ``?since_id=``."""
    import asyncio as _asyncio

    from fastapi import WebSocketDisconnect

    from .auth import websocket_authorized
    if not websocket_authorized(websocket):
        await websocket.close(code=4401)
        return
    await websocket.accept()
    try:
        since = int(websocket.query_params.get("since_id", 0))
    except (TypeError, ValueError):
        since = 0
    w = _world()
    g = w.get_goal(goal_id)
    if g is None:
        await websocket.send_json({"error": "no such goal"})
        await websocket.close(code=4404)
        return
    terminal = {"done", "completed", "failed", "error", "cancelled"}
    try:
        last = since
        while True:
            for e in w.goal_events(goal_id, since_id=last, limit=500):
                last = e.id
                await websocket.send_json({
                    "id": e.id, "agent": e.agent, "kind": e.kind,
                    "content": e.content, "ts": e.ts,
                })
            g = w.get_goal(goal_id)
            if g is None or g.status in terminal:
                await websocket.send_json({
                    "id": last + 1, "agent": "system", "kind": "status",
                    "content": (g.status if g else "deleted"), "ts": time.time(),
                })
                break
            await _asyncio.sleep(0.5)
    except WebSocketDisconnect:
        return
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


@app.get("/api/v1/goals/{goal_id}/cost-preview")
async def goal_cost_preview(request: Request, goal_id: int, iterations: int = 1) -> JSONResponse:
    """Inline cost preview: project a pending goal's cost before running it.

    Treats the goal description as one step per non-empty line (or the whole
    text as one step), projects tokens/dollars via maverick.cost_projection,
    and reports the OK/TIGHT/OVER verdict against the configured default
    budget."""
    w = _world()
    g = w.get_goal(goal_id)
    if g is None:
        raise HTTPException(status_code=404, detail="no such goal")
    assert_goal_access(request, g)
    from maverick.budget import Budget
    from maverick.cost_projection import compare_against_budget, project_plan
    text = (g.description or g.title or "").strip()
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    steps = [{"text": ln} for ln in (lines or [text])]
    projection = project_plan(steps, iterations=max(1, min(int(iterations), 10)))
    budget_dollars = Budget().max_dollars
    verdict = compare_against_budget(projection, budget_dollars)
    return JSONResponse({
        "goal_id": goal_id,
        "steps": len(steps),
        "total_tokens": projection.total_tokens,
        "total_dollars": round(projection.total_dollars, 4),
        "budget_dollars": budget_dollars,
        "verdict": verdict.verdict,
        "recommendation": verdict.recommendation,
    })


@app.get("/api/v1/goals/{goal_id}/cost-breakdown")
async def goal_cost_breakdown(request: Request, goal_id: int) -> JSONResponse:
    """'Why this cost' drill-down: a run's spend split by agent role/outcome.

    Buckets the goal's episodes (cost, tokens, count) so the dollar figure on
    the dashboard decomposes into who spent it and on what."""
    w = _world()
    g = w.get_goal(goal_id)
    if g is None:
        raise HTTPException(status_code=404, detail="no such goal")
    assert_goal_access(request, g)
    buckets: dict[str, dict] = {}
    total = 0.0
    for ep in w.list_episodes(limit=10_000, goal_id=goal_id):
        key = str(getattr(ep, "outcome", "") or "episode")
        b = buckets.setdefault(key, {"episodes": 0, "dollars": 0.0,
                                     "in_tokens": 0, "out_tokens": 0})
        cost = float(getattr(ep, "cost_dollars", 0) or 0)
        b["episodes"] += 1
        b["dollars"] += cost
        b["in_tokens"] += int(getattr(ep, "input_tokens", 0) or 0)
        b["out_tokens"] += int(getattr(ep, "output_tokens", 0) or 0)
        total += cost
    rows = [{"bucket": k, **{kk: (round(vv, 4) if kk == "dollars" else vv)
                             for kk, vv in v.items()}}
            for k, v in sorted(buckets.items(), key=lambda kv: -kv[1]["dollars"])]
    return JSONResponse({"goal_id": goal_id, "total_dollars": round(total, 4),
                         "buckets": rows})


@app.get("/api/v1/cost/anomalies")
async def cost_anomalies(threshold_sigma: float = 3.0, limit: int = 500) -> JSONResponse:
    """Cost anomaly alerts: goals whose spend is a statistical outlier.

    Computes per-goal spend over the recent episode window and flags goals
    above mean + threshold_sigma * stdev (min 3 goals before anything can
    flag). The data behind a dashboard alert badge."""
    import statistics

    w = _world()
    limit = max(1, min(int(limit), 10_000))
    by_goal: dict[int, float] = {}
    for ep in w.list_episodes(limit=limit):
        gid = getattr(ep, "goal_id", None)
        if gid is None:
            continue
        by_goal[gid] = by_goal.get(gid, 0.0) + float(getattr(ep, "cost_dollars", 0) or 0)
    spends = [s for s in by_goal.values() if s > 0]
    if len(spends) < 3:
        return JSONResponse({"anomalies": [], "goals_considered": len(by_goal),
                             "note": "need >=3 priced goals to baseline"})
    mean = statistics.fmean(spends)
    stdev = statistics.pstdev(spends)
    cut = mean + max(0.5, float(threshold_sigma)) * stdev
    anomalies = [
        {"goal_id": gid, "dollars": round(s, 4),
         "x_mean": round(s / mean, 1) if mean else None}
        for gid, s in sorted(by_goal.items(), key=lambda kv: -kv[1])
        if s > cut and stdev > 0
    ]
    return JSONResponse({
        "anomalies": anomalies, "goals_considered": len(by_goal),
        "mean_dollars": round(mean, 4), "cutoff_dollars": round(cut, 4),
    })


@app.post("/api/v1/skills/validate")
async def skills_validate(request: Request) -> JSONResponse:
    """Skill validator service: lint a SKILL.md body without installing it.

    POST the raw SKILL.md text (text/plain or markdown); responds
    ``{ok, errors, warnings}`` from the same linter `maverick skill validate`
    runs locally — so a marketplace author can validate from CI or an editor
    against a self-hosted instance. Size-capped; nothing is persisted."""
    import tempfile as _tempfile
    from pathlib import Path as _Path

    from maverick.skills import validate_skill_file

    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="POST the SKILL.md body")
    if len(body) > 256 * 1024:
        raise HTTPException(status_code=413, detail="skill too large (max 256 KiB)")
    with _tempfile.TemporaryDirectory(prefix="mvk-skill-validate-") as td:
        p = _Path(td) / "SKILL.md"
        p.write_bytes(body)
        result = validate_skill_file(p)
    return JSONResponse({
        "ok": result.ok, "errors": result.errors, "warnings": result.warnings,
    })


@app.get("/api/v1/pins")
async def pins_list(request: Request) -> JSONResponse:
    """Pinned watch list for the calling principal (most-recently-pinned first)."""
    from maverick.ux_store import shared as _ux
    return JSONResponse({"pins": _ux().pins(caller_principal(request))})


@app.post("/api/v1/pins/{goal_id}")
async def pins_add(request: Request, goal_id: int) -> JSONResponse:
    g = _world().get_goal(goal_id)
    if g is None:
        raise HTTPException(status_code=404, detail="no such goal")
    assert_goal_access(request, g)
    from maverick.ux_store import shared as _ux
    return JSONResponse({"pins": _ux().pin(caller_principal(request), goal_id)})


@app.delete("/api/v1/pins/{goal_id}")
async def pins_remove(request: Request, goal_id: int) -> JSONResponse:
    from maverick.ux_store import shared as _ux
    return JSONResponse({"pins": _ux().unpin(caller_principal(request), goal_id)})


@app.get("/api/v1/views")
async def views_list(request: Request) -> JSONResponse:
    """Saved dashboard views (named filter/query-param sets) for the caller."""
    from maverick.ux_store import shared as _ux
    return JSONResponse({"views": _ux().views(caller_principal(request))})


@app.post("/api/v1/views/{name}")
async def views_save(request: Request, name: str) -> JSONResponse:
    from maverick.ux_store import shared as _ux
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="body must be a JSON object of params")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object of params")
    try:
        _ux().save_view(caller_principal(request), name, body)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return JSONResponse({"saved": name}, status_code=201)


@app.delete("/api/v1/views/{name}")
async def views_delete(request: Request, name: str) -> JSONResponse:
    from maverick.ux_store import shared as _ux
    if not _ux().delete_view(caller_principal(request), name):
        raise HTTPException(status_code=404, detail="no such view")
    return JSONResponse({"deleted": name})


@app.get("/api/v1/gallery")
async def gallery_list(request: Request) -> JSONResponse:
    """Run gallery: the deployment's featured runs, enriched with live goal
    state and links to the tutorial/explain exports."""
    from maverick.ux_store import shared as _ux
    w = _world()
    runs = []
    for entry in _ux().gallery():
        g = w.get_goal(entry["goal_id"])
        if g is None or not can_access_goal(request, g):
            continue
        runs.append({
            **entry,
            "title": (g.title or "")[:120],
            "status": g.status,
            "tutorial": f"/api/v1/goals/{entry['goal_id']}/tutorial.md",
            "explain": f"/api/v1/goals/{entry['goal_id']}/explain",
        })
    return JSONResponse({"gallery": runs})


@app.post("/api/v1/gallery/{goal_id}")
async def gallery_add(request: Request, goal_id: int) -> JSONResponse:
    g = _world().get_goal(goal_id)
    if g is None:
        raise HTTPException(status_code=404, detail="no such goal")
    assert_goal_access(request, g)
    try:
        body = await request.json()
    except ValueError:
        body = {}
    blurb = str((body or {}).get("blurb") or "")
    from maverick.ux_store import shared as _ux
    try:
        entry = _ux().gallery_add(goal_id, blurb=blurb,
                                  curator=caller_principal(request))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return JSONResponse(entry, status_code=201)


@app.delete("/api/v1/gallery/{goal_id}")
async def gallery_remove(request: Request, goal_id: int) -> JSONResponse:
    from maverick.ux_store import shared as _ux
    if not _ux().gallery_remove(goal_id):
        raise HTTPException(status_code=404, detail="not in the gallery")
    return JSONResponse({"removed": goal_id})


@app.get("/api/v1/goals/{goal_id}/annotations")
async def annotations_list(request: Request, goal_id: int) -> JSONResponse:
    """Trace annotations: human notes pinned to replay-trace steps (seq)."""
    g = _world().get_goal(goal_id)
    if g is None:
        raise HTTPException(status_code=404, detail="no such goal")
    assert_goal_access(request, g)
    from maverick.ux_store import shared as _ux
    return JSONResponse({"annotations": _ux().annotations(goal_id)})


@app.post("/api/v1/goals/{goal_id}/annotations")
async def annotations_add(request: Request, goal_id: int) -> JSONResponse:
    g = _world().get_goal(goal_id)
    if g is None:
        raise HTTPException(status_code=404, detail="no such goal")
    assert_goal_access(request, g)
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="body must be JSON {seq, note}")
    if not isinstance(body, dict) or "seq" not in body or not body.get("note"):
        raise HTTPException(status_code=400, detail="body must be JSON {seq, note}")
    from maverick.ux_store import shared as _ux
    try:
        entry = _ux().annotate(goal_id, int(body["seq"]), str(body["note"]),
                               author=caller_principal(request))
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return JSONResponse(entry, status_code=201)


@app.get("/api/v1/goals/{goal_id}/anomalies")
async def goal_anomalies(request: Request, goal_id: int, history: int = 50) -> JSONResponse:
    """Cross-run anomaly signals for one run vs the deployment baseline."""
    w = _world()
    g = w.get_goal(goal_id)
    if g is None:
        raise HTTPException(status_code=404, detail="no such goal")
    assert_goal_access(request, g)
    from maverick.cross_run_anomaly import MIN_BASELINE_RUNS, detect
    anomalies = detect(w, goal_id, history=max(5, min(int(history), 500)))
    return JSONResponse({
        "goal_id": goal_id,
        "anomalies": [{"kind": a.kind, "severity": a.severity, "detail": a.detail}
                      for a in anomalies],
        "note": (f"baseline needs >= {MIN_BASELINE_RUNS} terminal runs before "
                 "anything can flag"),
    })


@app.get("/api/v1/goals/{goal_id}/tutorial.md")
async def goal_tutorial(request: Request, goal_id: int) -> PlainTextResponse:
    """Run-as-tutorial export: the run rendered as step-by-step markdown."""
    w = _world()
    g = w.get_goal(goal_id)
    if g is None:
        raise HTTPException(status_code=404, detail="no such goal")
    assert_goal_access(request, g)
    from maverick.tutorial_export import tutorial_markdown
    events = w.goal_events(goal_id, limit=5000)
    md = tutorial_markdown(g, events)
    return PlainTextResponse(content=md, media_type="text/markdown; charset=utf-8")


@app.get("/api/v1/goals/{goal_id}/replay-storyboard")
async def goal_replay_storyboard(request: Request, goal_id: int) -> JSONResponse:
    """Replay-to-MP4 storyboard: the ordered captioned frames + durations and
    the exact ffmpeg command an operator runs to encode the video.

    The deterministic, offline half of replay-to-MP4 (the encode needs ffmpeg
    and is done out-of-band or via the CLI). Secret/PII-scrubbed."""
    w = _world()
    g = w.get_goal(goal_id)
    if g is None:
        raise HTTPException(status_code=404, detail="no such goal")
    assert_goal_access(request, g)
    from pathlib import Path as _Path

    from maverick.replay_video import ffmpeg_command, storyboard
    # Feed the world's goal events (the live trail) rather than the audit-log
    # files replay_video reads by default, so the storyboard reflects this run.
    events = [{"kind": e.kind, "ts": e.ts, "agent": e.agent, "content": e.content}
              for e in w.goal_events(goal_id, limit=5000)]
    frames = storyboard(goal_id, events=events)
    cmd = ffmpeg_command(_Path("frames.ffconcat"), _Path(f"replay-{goal_id}.mp4"))
    return JSONResponse({
        "goal_id": goal_id,
        "frames": [{"index": f.index, "kind": f.kind, "caption": f.caption,
                    "seconds": f.seconds} for f in frames],
        "total_seconds": round(sum(f.seconds for f in frames), 2),
        "ffmpeg_command": cmd,
    })


@app.get("/api/v1/goals/{goal_id}/explain")
async def goal_explain(request: Request, goal_id: int) -> JSONResponse:
    """Plain-language narrative of a run (deterministic, no LLM)."""
    w = _world()
    g = w.get_goal(goal_id)
    if g is None:
        raise HTTPException(status_code=404, detail="no such goal")
    assert_goal_access(request, g)
    from maverick.plain_language import explain
    events = w.goal_events(goal_id, limit=2000)
    return JSONResponse({"goal_id": goal_id, "explanation": explain(g, events)})


@app.get("/api/v1/runs/compare")
async def runs_compare(request: Request, ids: str) -> JSONResponse:
    """Multi-run dashboard: side-by-side summary of up to 8 runs."""
    try:
        goal_ids = [int(x) for x in ids.split(",") if x.strip()][:8]
    except ValueError:
        raise HTTPException(status_code=400, detail="ids must be comma-separated integers")
    if not goal_ids:
        raise HTTPException(status_code=400, detail="ids is required")
    w = _world()
    runs = []
    for gid in goal_ids:
        g = w.get_goal(gid)
        if g is None:
            raise HTTPException(status_code=404, detail=f"no such goal: {gid}")
        assert_goal_access(request, g)
        events = w.goal_events(gid, limit=10_000)
        errors = sum(1 for e in events if e.kind == "error")
        runs.append({
            "goal_id": gid,
            "title": (g.title or "")[:120],
            "status": g.status,
            "events": len(events),
            "errors": errors,
            "created_at": getattr(g, "created_at", None),
        })
    return JSONResponse({"runs": runs})


@app.get("/api/v1/cost/by-tag")
async def cost_by_tag_api(tag_field: str = "tag", limit: int = 500) -> JSONResponse:
    """Cost-attribution API: spend split by tag (team / project / cost-center).

    Buckets the priced episodes by their tag (episode field, else the goal's
    metadata/tags) via ``maverick.cost_by_tag`` and returns
    ``{buckets: [{tag, cost, in_tok, out_tok, runs}, ...]}`` sorted by spend. The JSON face of ``maverick status --cost``'s tag split,
    for chargeback exports and BI pulls. Behind the dashboard's normal auth."""
    from maverick.cost_by_tag import gather, split_by_tag

    limit = max(1, min(int(limit), 10_000))
    buckets = split_by_tag(gather(_world(), tag_field=tag_field, limit=limit))
    return JSONResponse({"tag_field": tag_field, "buckets": buckets})


@app.get("/api/v1/shield/calibration")
async def shield_calibration_api() -> JSONResponse:
    """Shield calibration data for the oversight console.

    Threshold sweep (recall / precision / fp-rate per block threshold) plus
    per-rule hit counts over the red-team corpus — the shipped one, or an
    operator's own via ``MAVERICK_REDTEAM_CORPUS``. Behind the dashboard's
    normal auth (not in the exempt list)."""
    import os as _os
    from pathlib import Path as _Path

    try:
        from maverick_shield.redteam import calibration_report, load_corpus
    except ImportError:
        raise HTTPException(status_code=501, detail="maverick-shield is not installed")
    corpus_env = _os.environ.get("MAVERICK_REDTEAM_CORPUS", "").strip()
    try:
        cases = load_corpus(_Path(corpus_env) if corpus_env else None)
    except (OSError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f"corpus error: {e}")
    return JSONResponse(calibration_report(cases))


@app.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request) -> HTMLResponse:
    recent = _world().list_goals(owner=goal_owner_filter(request), limit=10, order="desc")
    # "Use template" on /templates links here with ?title=&description= to
    # prefill the form (never auto-start; the user reviews, edits, submits).
    prefill_title = (request.query_params.get("title") or "")[:200]
    prefill_description = (request.query_params.get("description") or "")[:8000]
    return templates.TemplateResponse(
        request, "chat.html",
        {"recent": recent, "prefill_title": prefill_title,
         "prefill_description": prefill_description},
    )


@app.post("/chat/send")
async def chat_send(
    request: Request,
    bg: BackgroundTasks,
    title: str = Form(...),
    description: str = Form(""),
) -> RedirectResponse:
    if not _is_same_origin(request):
        raise HTTPException(status_code=403, detail="cross-site form post blocked")
    if not _any_provider_key_set():
        raise HTTPException(
            status_code=400,
            detail=(
                "No LLM provider key or endpoint configured. Run 'maverick "
                "init', export ANTHROPIC_API_KEY / OPENAI_API_KEY, or add a "
                "[providers.<name>] api_key/base_url to "
                "~/.maverick/config.toml before starting the dashboard."
            ),
        )
    check_goal_rate_limit(request)
    title = (title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="goal text is required")
    w = _world()
    # The optional "Add details" textarea gives the agent a real brief; fall
    # back to the title when empty (prior behavior was description == title).
    description = (description or "").strip()
    goal_id = w.create_goal(
        title[:200], (description or title)[:8000],
        owner=caller_principal(request) or "",
    )
    # Use the shared runner so this path gets the same concurrency cap,
    # budget defaults, and error handling as the REST API and MCP server.
    from maverick.runner import run_goal_in_thread
    user_id = execution_user_id_from_request(request)
    if user_id:
        bg.add_task(run_goal_in_thread, goal_id, channel="dashboard", user_id=user_id)
    else:
        bg.add_task(run_goal_in_thread, goal_id)
    return RedirectResponse(f"/chat/goal/{goal_id}", status_code=303)


@app.post("/webhook/start")
async def webhook_start(request: Request, bg: BackgroundTasks) -> JSONResponse:
    """Generic inbound webhook: create a goal from an HMAC-signed POST.

    Body is JSON ``{title, description?, budget?}``. The request must carry
    an ``X-Maverick-Signature: sha256=<hex>`` header computed over the
    timestamp + raw body with the configured ``[webhooks] secret`` (see
    ``maverick.webhooks``), plus an ``X-Maverick-Timestamp`` header. Returns
    ``{"goal_id": <int>}`` on success.

    Auth: this route is exempt from the dashboard bearer / same-origin
    middleware (see ``_AUTH_EXEMPT``); the HMAC signature is the only
    credential. We fail closed -- a missing/empty secret yields 401.

    Replay defence (Maverick-CONTROLLED format): the signature binds the
    ``X-Maverick-Timestamp``; a request whose timestamp is outside the
    configured freshness window (``[webhooks] max_age_seconds``) is rejected,
    so a captured signed request can't be replayed to re-spend budget.
    """
    from maverick.webhooks import inbound_secret, verify_signature

    secret = inbound_secret()
    if not secret:
        raise HTTPException(
            status_code=401,
            detail=(
                "inbound webhooks are not configured. Set a [webhooks] "
                "secret in ~/.maverick/config.toml or MAVERICK_WEBHOOK_SECRET."
            ),
        )
    signature = request.headers.get("X-Maverick-Signature") or ""
    timestamp = request.headers.get("X-Maverick-Timestamp") or ""
    if not signature or not timestamp:
        raise HTTPException(status_code=403, detail="bad webhook signature")
    body = await _read_limited_webhook_body(request)
    if not verify_signature(body, signature, secret, timestamp=timestamp):
        raise HTTPException(status_code=403, detail="bad webhook signature")

    if not _any_provider_key_set():
        raise HTTPException(
            status_code=400,
            detail=(
                "No LLM provider key or endpoint configured. Run 'maverick "
                "init', export ANTHROPIC_API_KEY / OPENAI_API_KEY, or add a "
                "[providers.<name>] api_key/base_url to "
                "~/.maverick/config.toml before starting the dashboard."
            ),
        )
    try:
        payload = json.loads(body or b"{}")
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="body must be valid JSON")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")

    title = str(payload.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="title is required")
    description = str(payload.get("description") or "")

    check_goal_rate_limit(request, source="webhook")
    w = _world()
    # HMAC webhooks carry no OIDC principal, so this resolves to "" (unowned):
    # reachable only by no-auth/admin callers, never another tenant.
    goal_id = w.create_goal(
        title[:200], description[:8000], owner=caller_principal(request) or "",
    )

    from maverick.runner import DEFAULT_MAX_DOLLARS, run_goal_in_thread
    budget = payload.get("budget")
    max_dollars = None
    if budget is not None:
        try:
            max_dollars = float(budget)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="budget must be a number")
        # Clamp to the same ceiling the REST route enforces. run_goal_in_thread
        # treats max_dollars as the highest-precedence override with no cap of
        # its own, so an unclamped webhook value (negative, or arbitrarily
        # large) would defeat the budget ceiling -- budget caps are not
        # optional, even on an externally reachable signed endpoint.
        max_dollars = min(max(max_dollars, 0.0), DEFAULT_MAX_DOLLARS)
    bg.add_task(run_goal_in_thread, goal_id, max_dollars)
    return JSONResponse({"goal_id": goal_id}, status_code=201)


@app.post("/webhook/linear")
async def webhook_linear(request: Request, bg: BackgroundTasks) -> JSONResponse:
    """Linear issue-assigned webhook -> goal. Signature in ``Linear-Signature``."""
    return await _handle_issue_webhook("linear", "Linear-Signature", request, bg)


@app.post("/webhook/jira")
async def webhook_jira(request: Request, bg: BackgroundTasks) -> JSONResponse:
    """Jira issue-assigned webhook -> goal. Signature in ``X-Hub-Signature``."""
    return await _handle_issue_webhook("jira", "X-Hub-Signature", request, bg)


@app.post("/webhook/github")
async def webhook_github(request: Request, bg: BackgroundTasks) -> JSONResponse:
    """GitHub App webhook -> issue→PR. A labeled/`/maverick`-commented issue
    drives a swarm that clones the repo, fixes it, and opens a PR
    (``maverick.github_app``). HMAC-verified via ``X-Hub-Signature-256`` against
    ``MAVERICK_GH_APP_WEBHOOK_SECRET`` (fails closed)."""
    import json as _json
    import os as _os

    from maverick.github_app import parse_webhook, process_issue, verify_signature
    from maverick.issue_webhooks import canonical_signature, replay_window_seconds

    signature = request.headers.get("X-Hub-Signature-256")
    body = await _read_limited_webhook_body(request)
    secret = _os.environ.get("MAVERICK_GH_APP_WEBHOOK_SECRET", "")
    if not verify_signature(body, signature, secret):
        return JSONResponse({"detail": "invalid signature"}, status_code=401)
    try:
        payload = parse_webhook(request.headers.get("X-GitHub-Event", ""), _json.loads(body))
    except (ValueError, TypeError):
        return JSONResponse({"detail": "bad payload"}, status_code=400)
    if payload is None:
        return JSONResponse({"status": "ignored"})

    # GitHub signs only the raw body, not a freshness timestamp.  Require its
    # delivery id for operator traceability, but key replay rejection on the
    # canonical body HMAC so a captured delivery cannot be resent with a
    # different X-GitHub-Delivery value to re-run the paid issue→PR workflow.
    if not (request.headers.get("X-GitHub-Delivery") or "").strip():
        return JSONResponse({"detail": "missing delivery id"}, status_code=403)
    dedup_signature = canonical_signature(signature)
    if not dedup_signature:
        return JSONResponse({"detail": "bad webhook signature"}, status_code=403)
    if _issue_webhook_replay_seen(dedup_signature, replay_window_seconds()):
        return JSONResponse({"detail": "duplicate webhook delivery"}, status_code=409)

    check_goal_rate_limit(request, source="webhook:github")

    async def _run() -> None:
        try:
            await process_issue(payload)
        except Exception:  # pragma: no cover -- never crash the worker
            log.exception("github_app: issue→PR run failed")

    bg.add_task(_run)
    return JSONResponse({"status": "accepted", "issue": payload.issue_number})


@app.post("/webhook/gitlab")
async def webhook_gitlab(request: Request, bg: BackgroundTasks) -> JSONResponse:
    """GitLab issue-assigned webhook -> goal.

    GitLab authenticates with a shared ``X-Gitlab-Token`` (no body HMAC), so
    this route verifies that token (constant-time, fail-closed) and keys
    replay-dedup on the required ``X-Gitlab-Event-UUID`` delivery id instead
    of a body signature.
    """
    import os as _os

    from maverick.issue_webhooks import (
        build_brief,
        parse_issue_event,
        replay_window_seconds,
        verify_gitlab_token,
    )

    secret = _os.environ.get("MAVERICK_GITLAB_WEBHOOK_TOKEN", "").strip()
    if not secret:
        raise HTTPException(
            status_code=401,
            detail="GitLab webhook not configured. Set MAVERICK_GITLAB_WEBHOOK_TOKEN.",
        )
    if not verify_gitlab_token(request.headers.get("X-Gitlab-Token"), secret):
        raise HTTPException(status_code=403, detail="bad webhook token")
    body = await _read_limited_webhook_body(request)
    try:
        payload = json.loads(body or b"{}")
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="body must be valid JSON")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")

    event = parse_issue_event("gitlab", payload)
    if event is None:
        return JSONResponse({"ignored": True}, status_code=200)

    # GitLab sends no signed timestamp; the per-delivery UUID is the dedup key.
    delivery = (request.headers.get("X-Gitlab-Event-UUID") or "").strip()
    if not delivery:
        raise HTTPException(status_code=403, detail="missing delivery id")
    if _issue_webhook_replay_seen(f"gitlab:{delivery}", replay_window_seconds()):
        raise HTTPException(status_code=409, detail="duplicate webhook delivery")

    if not _any_provider_key_set():
        raise HTTPException(
            status_code=400,
            detail="No LLM provider key configured. Run 'maverick init'.",
        )
    check_goal_rate_limit(request, source="webhook:gitlab")
    w = _world()
    title = f"{event.issue_id}: {event.title}".strip()
    goal_id = w.create_goal(title[:200], build_brief(event)[:8000], owner="")
    from maverick.runner import run_goal_in_thread
    bg.add_task(run_goal_in_thread, goal_id, None)
    return JSONResponse({"goal_id": goal_id}, status_code=201)


# Per-process replay dedup for inbound issue webhooks, keyed on the request's
# HMAC signature (unique per signed body), so a captured delivery replayed
# within the freshness window is rejected once per process. NOTE: this is
# per-process -- with multiple workers the stateless Linear/Jira freshness check
# (issue_webhooks.is_fresh) is the cross-worker bound; a shared store would be
# needed for cross-worker dedup.
_issue_webhook_seen: dict[str, float] = {}
_issue_webhook_seen_lock = threading.Lock()
_ISSUE_WEBHOOK_SEEN_MAX = 4096


def _issue_webhook_replay_seen(signature: str, ttl_seconds: int) -> bool:
    """True if ``signature`` was already delivered within ``ttl_seconds``.

    Records the signature with the current time and evicts expired/overflow
    entries. The first delivery returns False (and is recorded); a replay
    within the window returns True.
    """
    now = time.time()
    with _issue_webhook_seen_lock:
        for k, t in list(_issue_webhook_seen.items()):
            if t < now - ttl_seconds:
                _issue_webhook_seen.pop(k, None)
        if signature in _issue_webhook_seen:
            return True
        _issue_webhook_seen[signature] = now
        if len(_issue_webhook_seen) > _ISSUE_WEBHOOK_SEEN_MAX:
            # Hard cap: drop the oldest half so a flood can't grow unbounded.
            for k in sorted(_issue_webhook_seen, key=_issue_webhook_seen.get)[
                : len(_issue_webhook_seen) // 2
            ]:
                _issue_webhook_seen.pop(k, None)
        return False


async def _handle_issue_webhook(
    provider: str, sig_header: str, request: Request, bg: BackgroundTasks,
) -> JSONResponse:
    """Shared handler for inbound issue-assigned webhooks (Linear/Jira).

    HMAC-signed like ``/webhook/start`` (fail-closed: no secret -> 401, bad
    signature -> 403). When the payload isn't an issue assigned to the
    configured bot, acknowledge with ``{"ignored": true}`` instead of
    spawning a goal. On a real assignment, create a goal from the issue and
    enqueue the run, returning ``{"goal_id": <int>}``.
    """
    from maverick.issue_webhooks import (
        build_brief,
        canonical_signature,
        is_fresh,
        parse_issue_event,
        replay_window_seconds,
        verify_signature,
    )
    from maverick.webhooks import inbound_secret

    secret = inbound_secret()
    if not secret:
        raise HTTPException(
            status_code=401,
            detail=(
                "inbound webhooks are not configured. Set a [webhooks] "
                "secret in ~/.maverick/config.toml or MAVERICK_WEBHOOK_SECRET."
            ),
        )
    signature = request.headers.get(sig_header) or ""
    if not signature:
        raise HTTPException(status_code=403, detail="bad webhook signature")
    body = await _read_limited_webhook_body(request)
    if not verify_signature(body, signature, secret):
        raise HTTPException(status_code=403, detail="bad webhook signature")

    try:
        payload = json.loads(body or b"{}")
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="body must be valid JSON")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")

    event = parse_issue_event(provider, payload)
    if event is None:
        # Wrong event type, unassigned, or assigned to someone other than the
        # bot -- acknowledge without driving the swarm.
        return JSONResponse({"ignored": True}, status_code=200)

    # Replay defence for actionable (goal-spawning) events -- parity with
    # /webhook/start. Linear/Jira sign only the body, but it carries an
    # authenticated webhookTimestamp/timestamp we age-check, and the signature
    # is a per-delivery dedup key. A captured signed event must not be able to
    # re-create and re-run a paid goal indefinitely.
    if not is_fresh(provider, payload):
        raise HTTPException(status_code=403, detail="stale or undated webhook")
    dedup_signature = canonical_signature(signature)
    if not dedup_signature:
        raise HTTPException(status_code=403, detail="bad webhook signature")
    if _issue_webhook_replay_seen(dedup_signature, replay_window_seconds()):
        raise HTTPException(status_code=409, detail="duplicate webhook delivery")

    if not _any_provider_key_set():
        raise HTTPException(
            status_code=400,
            detail="No LLM provider key configured. Run 'maverick init'.",
        )
    check_goal_rate_limit(request, source=f"webhook:{provider}")
    w = _world()
    title = f"{event.issue_id}: {event.title}".strip()
    # Webhook-driven goal: no authenticated principal -> unowned ("").
    goal_id = w.create_goal(title[:200], build_brief(event)[:8000], owner="")
    from maverick.runner import run_goal_in_thread
    bg.add_task(run_goal_in_thread, goal_id, None)
    return JSONResponse({"goal_id": goal_id}, status_code=201)


@app.get("/chat/goal/{goal_id}", response_class=HTMLResponse)
async def chat_goal(request: Request, goal_id: int) -> HTMLResponse:
    g = _world().get_goal(goal_id)
    if g is None:
        raise HTTPException(status_code=404, detail="no such goal")
    assert_goal_access(request, g)
    return templates.TemplateResponse(request, "chat_goal.html", {"goal": g})


@app.get("/api/goal/{goal_id}")
async def api_goal_legacy(request: Request, goal_id: int) -> dict:
    g = _world().get_goal(goal_id)
    if g is None:
        raise HTTPException(status_code=404, detail="no such goal")
    assert_goal_access(request, g)
    return {"id": g.id, "status": g.status, "title": g.title, "result": g.result or ""}


def _build_plan_tree(world, goal_id: int, depth_cap: int = 6) -> dict:
    """Assemble the plan tree rooted at ``goal_id`` in two queries.

    Previous implementation was true N+1: ``_children`` ran one query
    per node, each with a correlated cost subquery. Depth-6 tree
    fanned out to thousands of SQL calls. This rewrite uses a single
    recursive CTE for the descendant set + one aggregate JOIN for
    costs, then assembles the tree in Python.
    """
    root = world.get_goal(goal_id)
    if root is None:
        return {}

    per_parent_cap = 50
    rows = world.conn.execute(
        """
        WITH RECURSIVE descendants(id, parent_id, title, status, depth, created_at) AS (
          SELECT id, parent_id, title, status, 0, created_at
            FROM goals WHERE id = ?
          UNION ALL
          SELECT child.id, child.parent_id, child.title, child.status, d.depth + 1, child.created_at
            FROM descendants d
            JOIN goals child
              ON child.id IN (
                SELECT g.id
                  FROM goals g
                 WHERE g.parent_id = d.id
                 ORDER BY g.created_at ASC, g.id ASC
                 LIMIT ?
              )
           WHERE d.depth < ?
        ),
        episode_totals AS (
          SELECT e.goal_id, SUM(e.cost_dollars) AS dollars
            FROM episodes e
            JOIN descendants d ON d.id = e.goal_id
           GROUP BY e.goal_id
        )
        SELECT d.id, d.parent_id, d.title, d.status, d.depth,
               COALESCE(e.dollars, 0) AS dollars
          FROM descendants d
          LEFT JOIN episode_totals e ON e.goal_id = d.id
         ORDER BY d.depth ASC, d.created_at ASC, d.id ASC
        """,
        (goal_id, per_parent_cap, depth_cap),
    ).fetchall()

    # This tree reads goals.title via raw SQL, so decrypt it the same way the
    # WorldModel accessors do when at-rest encryption seals the column.
    from maverick.world_model import _dec_field

    nodes: dict[int, dict] = {}
    for r in rows:
        nodes[r["id"]] = {
            "id":        r["id"],
            "parent_id": r["parent_id"],
            "title":     _dec_field(r["title"]),
            "status":    r["status"],
            "dollars":   float(r["dollars"] or 0.0),
            "children":  [],
        }
    # Assemble children lists. Per-parent fan-out cap stays at 50 to
    # match the prior LIMIT (truncates noisy fan-outs in the UI).
    for n in nodes.values():
        parent = nodes.get(n["parent_id"])
        if parent is not None and parent["id"] != n["id"]:
            if len(parent["children"]) < per_parent_cap:
                parent["children"].append(n)
    root_node = nodes.get(goal_id)
    if root_node is None:
        return {
            "id": root.id, "parent_id": root.parent_id,
            "title": root.title, "status": root.status,
            "dollars": 0.0, "children": [],
        }
    return root_node


@app.get("/api/v1/goals/{goal_id}/tree")
async def api_plan_tree(request: Request, goal_id: int) -> dict:
    """Plan-tree JSON: root + recursive children with status + cost."""
    w = _world()
    g = w.get_goal(goal_id)
    if g is None:
        raise HTTPException(status_code=404, detail="no such goal")
    assert_goal_access(request, g)
    return _build_plan_tree(w, goal_id)


@app.get("/api/v1/goals/{goal_id}/minimap", response_class=PlainTextResponse)
async def goal_minimap(request: Request, goal_id: int, depth: int = 3) -> PlainTextResponse:
    """Plan-tree minimap: the goal's subtree as compact one-line-per-node text.

    Pure render via ``maverick.plan_minimap`` (status glyphs, depth
    indentation, collapsed counts beyond the ``?depth=`` budget).
    """
    w = _world()
    g = w.get_goal(goal_id)
    if g is None:
        raise HTTPException(status_code=404, detail="no such goal")
    assert_goal_access(request, g)
    from maverick.plan_minimap import render_minimap
    try:
        depth = max(0, min(int(depth), 8))
    except (TypeError, ValueError):
        depth = 3
    text = render_minimap(w, goal_id, max_depth=depth)
    return PlainTextResponse(text + "\n", media_type="text/plain; charset=utf-8")


def _render_tree_html(node: dict) -> str:
    """Pre-render the plan-tree as nested <ul><li> HTML.

    Avoids Jinja's recursive-macro limitation (dict args aren't hashable
    for the autoescape cache). Escapes user-controlled fields with html
    escape to keep titles safe.
    """
    import html as _html

    def _esc(s) -> str:
        # quote=True so the value is safe in attribute context too — the
        # status string is interpolated into class="badge {status}".
        # Status is enum-bounded today, but a future writer shouldn't be
        # one missing quote away from attribute-injection.
        return _html.escape(str(s), quote=True) if s is not None else ""

    def _render(n: dict) -> str:
        dollars_html = (
            f' <span class="cost">${n["dollars"]:.4f}</span>'
            if n.get("dollars") else ""
        )
        node_html = (
            f'<a class="node" href="/goals#{n["id"]}">'
            f'<span class="nid">#{_esc(n["id"])}</span> '
            f'<span class="badge {_esc(n["status"])}">{_esc(n["status"])}</span> '
            f'<span class="title">{_esc(n.get("title") or "(untitled)")}</span>'
            f"{dollars_html}"
            f"</a>"
        )
        children = n.get("children") or []
        if not children:
            return f"<li>{node_html}</li>"
        children_html = "".join(_render(c) for c in children)
        return f"<li>{node_html}<ul>{children_html}</ul></li>"

    return f"<ul>{_render(node)}</ul>"


@app.get("/goals/{goal_id}/plan", response_class=HTMLResponse)
async def plan_tree_page(request: Request, goal_id: int) -> HTMLResponse:
    """HTML plan-tree visualization."""
    w = _world()
    g = w.get_goal(goal_id)
    if g is None:
        raise HTTPException(status_code=404, detail="no such goal")
    assert_goal_access(request, g)
    root = _build_plan_tree(w, goal_id)
    tree_html = _render_tree_html(root)
    return templates.TemplateResponse(
        request, "plan_tree.html",
        {"goal": g, "root": root, "tree_html": tree_html},
    )


@app.get("/goals/{goal_id}/trajectory", response_class=HTMLResponse)
async def trajectory_page(request: Request, goal_id: int) -> HTMLResponse:
    """Trajectory replay: timeline of every event with a scrubber."""
    w = _world()
    g = w.get_goal(goal_id)
    if g is None:
        raise HTTPException(status_code=404, detail="no such goal")
    assert_goal_access(request, g)
    events = w.goal_events(goal_id, limit=10_000)
    return templates.TemplateResponse(
        request, "trajectory.html",
        {"goal": g, "events": events},
    )


@app.get("/goals/{goal_id}/errors", response_class=HTMLResponse)
async def errors_page(request: Request, goal_id: int) -> HTMLResponse:
    """Error inspector: every failed turn for a goal, with full content."""
    w = _world()
    g = w.get_goal(goal_id)
    if g is None:
        raise HTTPException(status_code=404, detail="no such goal")
    assert_goal_access(request, g)
    errors = [e for e in w.goal_events(goal_id, limit=10_000) if e.kind == "error"]
    return templates.TemplateResponse(
        request, "errors.html",
        {"goal": g, "errors": errors},
    )


@app.get("/api/v1/cost.csv")
async def cost_csv(month: str | None = None) -> StreamingResponse:
    """CSV rollup of episode spend, streamed.

    Council perf finding: prior version fetched up to 100k episodes
    into memory, then filtered by month in Python before writing the
    CSV to a StringIO. Now: stream rows directly from the DB, with the
    month filter pushed to SQL.

    ``month`` filter: YYYY-MM (e.g. 2026-04). Omit for lifetime.
    Columns: episode_id, goal_id, started_at, ended_at, outcome,
    dollars, in_tokens, out_tokens, tool_calls.
    """
    import csv
    import datetime as _dt
    import io as _io

    w = _world()
    start_ts: float | None = None
    end_ts: float | None = None
    if month:
        try:
            start = _dt.datetime.strptime(month, "%Y-%m").replace(
                tzinfo=_dt.timezone.utc
            )
            # episodes.started_at is a UTC epoch, so build the window in UTC --
            # a naive strptime().timestamp() interprets midnight in the server's
            # LOCAL zone, shifting the month boundary by the UTC offset (the CSV
            # then drops/keeps the wrong rows for anyone not running in UTC).
            # Roll over by calendar month, not +31 days, which over-counts the
            # short months (e.g. Feb would leak early-March rows).
            if start.month == 12:
                nxt = start.replace(year=start.year + 1, month=1)
            else:
                nxt = start.replace(month=start.month + 1)
        except ValueError:
            # Don't echo strptime's internals (e.g. "unconverted data remains").
            raise HTTPException(status_code=400, detail="month must be YYYY-MM (e.g. 2026-04)")
        start_ts = start.timestamp()
        end_ts = nxt.timestamp()

    def generate():
        buf = _io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            "episode_id", "goal_id", "started_at", "ended_at", "outcome",
            "dollars", "input_tokens", "output_tokens", "tool_calls",
        ])
        yield buf.getvalue()
        buf.seek(0)
        buf.truncate(0)

        params: tuple = ()
        sql = (
            "SELECT id, goal_id, started_at, ended_at, outcome, "
            "cost_dollars, input_tokens, output_tokens, tool_calls "
            "FROM episodes"
        )
        if start_ts is not None:
            sql += " WHERE started_at >= ? AND started_at < ?"
            params = (start_ts, end_ts)
        sql += " ORDER BY id"

        # outcome is a sealed column when at-rest encryption is on; this CSV reads
        # it via raw SQL, so decrypt it like the WorldModel accessors do.
        from maverick.world_model import _dec_field
        for row in w.conn.execute(sql, params):
            writer.writerow([
                row["id"], row["goal_id"],
                row["started_at"], row["ended_at"] or "",
                _dec_field(row["outcome"]) or "",
                f"{(row['cost_dollars'] or 0):.6f}",
                row["input_tokens"], row["output_tokens"], row["tool_calls"],
            ])
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)

    fname = f"maverick-cost-{month}.csv" if month else "maverick-cost-all.csv"
    return StreamingResponse(
        generate(), media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@app.get("/api/goal/{goal_id}/events")
async def api_goal_events_legacy(
    request: Request, goal_id: int, since: int = 0, limit: int = 200,
) -> dict:
    w = _world()
    g = w.get_goal(goal_id)
    if g is None:
        raise HTTPException(status_code=404, detail="no such goal")
    assert_goal_access(request, g)
    limit = max(1, min(limit, 500))
    events = w.goal_events(goal_id, since_id=since, limit=limit)
    return {
        "status": g.status,
        "result": g.result or "",
        "next_id": events[-1].id if events else since,
        "events": [
            {"id": e.id, "agent": e.agent, "kind": e.kind,
             "content": e.content, "ts": e.ts}
            for e in events
        ],
    }


@app.get("/api/goal/{goal_id}/events/stream")
async def api_goal_events_stream(request: Request, goal_id: int, since: int = 0) -> StreamingResponse:
    """Server-Sent Events stream of new goal events.

    Council perf-seat fix: client polled this route every 2s (visible
    tab) / 5s (hidden tab) over the lifetime of every open goal page,
    burning 30 req/min/tab idle on a goal that finished an hour ago.
    SSE holds one TCP connection open, server polls SQLite at 0.5s
    cadence, yields ``data: {json}\\n\\n`` only when there's something
    new. EventSource on the client reconnects automatically and goes
    silent the moment status flips to done/cancelled/failed.

    Terminal statuses close the stream with a final event so the
    client knows it can stop listening (EventSource normally retries
    forever).
    """
    import asyncio as _asyncio
    import json as _json

    w = _world()
    g = w.get_goal(goal_id)
    if g is None:
        raise HTTPException(status_code=404, detail="no such goal")
    assert_goal_access(request, g)

    # Cap concurrent streams so thousands of EventSource opens can't exhaust
    # FDs/tasks. Acquire non-blocking and return 503 when full; release in the
    # generator's finally so a disconnect (CancelledError) frees a slot.
    sem = _get_sse_semaphore()
    if sem.locked():
        raise HTTPException(
            status_code=503,
            detail="too many concurrent event streams; retry shortly",
            headers={"Retry-After": "5"},
        )
    await sem.acquire()

    TERMINAL = ("done", "cancelled", "failed")
    POLL_INTERVAL = 0.5            # server-side cadence
    MAX_POLL_INTERVAL = 5.0        # cap idle backoff to reduce DB churn
    IDLE_HEARTBEAT_EVERY = 30      # send a comment line so proxies don't time out
    MAX_STREAM_SECONDS = 300       # lifetime cap per SSE stream
    MAX_BATCH = 200

    # EventSource reconnects on its own (a network blip, a proxy timeout,
    # or our MAX_STREAM_SECONDS cap). Without resume support it would
    # restart from ``?since=`` and replay the whole log as duplicates;
    # honor Last-Event-ID so a reconnect resumes exactly where it left off.
    resume_from = since
    last_event_id = request.headers.get("last-event-id")
    if last_event_id:
        try:
            resume_from = max(resume_from, int(last_event_id))
        except ValueError:
            pass

    async def generate():
        started = _asyncio.get_running_loop().time()
        sid = resume_from
        idle_ticks = 0
        poll_interval = POLL_INTERVAL
        # Advertise the reconnect delay (ms) to the client.
        yield "retry: 3000\n\n"
        # Initial flush: anything already on the board since `since`.
        try:
            while True:
                if (_asyncio.get_running_loop().time() - started) >= MAX_STREAM_SECONDS:
                    yield "event: timeout\ndata: {\"detail\": \"stream lifetime exceeded\"}\n\n"
                    return
                events = w.goal_events(goal_id, since_id=sid, limit=MAX_BATCH)
                g = w.get_goal(goal_id)
                if g is None:
                    yield "event: error\ndata: {\"detail\": \"goal vanished\"}\n\n"
                    return
                if events:
                    sid = events[-1].id
                    payload = {
                        "status": g.status,
                        "result": g.result or "",
                        "next_id": sid,
                        "events": [
                            {"id": e.id, "agent": e.agent, "kind": e.kind,
                             "content": e.content, "ts": e.ts}
                            for e in events
                        ],
                    }
                    yield f"id: {sid}\ndata: {_json.dumps(payload)}\n\n"
                    idle_ticks = 0
                    poll_interval = POLL_INTERVAL
                else:
                    idle_ticks += 1
                    if idle_ticks * POLL_INTERVAL >= IDLE_HEARTBEAT_EVERY:
                        # SSE comment line; ignored by EventSource but keeps
                        # intermediaries from closing the connection.
                        yield ": heartbeat\n\n"
                        idle_ticks = 0
                    poll_interval = min(MAX_POLL_INTERVAL, poll_interval * 1.5)
                if g.status in TERMINAL:
                    payload = {
                        "status": g.status,
                        "result": g.result or "",
                        "next_id": sid,
                        "events": [],
                        "terminal": True,
                    }
                    yield f"id: {sid}\nevent: terminal\ndata: {_json.dumps(payload)}\n\n"
                    return
                await _asyncio.sleep(poll_interval)
        except _asyncio.CancelledError:
            return
        finally:
            # Always free the stream slot, whether we ended on a terminal
            # status, the lifetime cap, or a client disconnect.
            sem.release()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # nginx/caddy: disable response buffering
        },
    )


# ----- roadmap cluster: graph editor / goal builder / embed / benchmarks /
#       walkthroughs / 3D plan tree -----

_STATIC_DIR = Path(__file__).parent / "static"


@app.get("/static/maverick-analytics.js")
async def embed_analytics_js() -> FileResponse:
    """The embeddable ``<maverick-analytics>`` web component (plain JS, no
    framework). See the file's header comment for the same-origin + token
    caveats; /embed-demo shows it running."""
    return FileResponse(
        _STATIC_DIR / "maverick-analytics.js",
        media_type="application/javascript; charset=utf-8",
    )


@app.get("/graph-editor", response_class=HTMLResponse)
async def graph_editor_page(request: Request) -> HTMLResponse:
    """Visual graph editor: the goal forest as an editable SVG node graph.

    Layout comes from the server (GET /api/v1/goal-tree); the page JS only
    draws and posts edits (retitle / re-parent / add child)."""
    from .goal_tree import forest_html, goal_nodes
    nodes = goal_nodes(_world(), owner=goal_owner_filter(request))
    return templates.TemplateResponse(
        request, "graph_editor.html",
        {"node_count": len(nodes), "fallback_html": forest_html(nodes)},
    )


@app.get("/goal-builder", response_class=HTMLResponse)
async def goal_builder_page(request: Request) -> HTMLResponse:
    """Drag-and-drop goal builder: compose a brief from blocks, then run it."""
    return templates.TemplateResponse(request, "goal_builder.html", {})


@app.get("/embed-demo", response_class=HTMLResponse)
async def embed_demo_page(request: Request) -> HTMLResponse:
    """Demo + honest usage notes for the <maverick-analytics> web component."""
    return templates.TemplateResponse(request, "embed_demo.html", {})


def _sparkline_points(values: list[float], width: int = 160, height: int = 36,
                      pad: int = 3) -> str:
    """SVG polyline ``points`` for a score series (server-side sparkline)."""
    if not values:
        return ""
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    n = len(values)
    pts = []
    for i, v in enumerate(values):
        x = pad + (width - 2 * pad) * (i / (n - 1) if n > 1 else 0.5)
        y = pad + (height - 2 * pad) * (1 - (v - lo) / span)
        pts.append(f"{x:.1f},{y:.1f}")
    return " ".join(pts)


@app.get("/benchmarks", response_class=HTMLResponse)
async def benchmarks_page(request: Request) -> HTMLResponse:
    """Continuous-benchmark history: this deployment's recorded runs only.

    Per-suite trend sparklines + a comparison table over the real
    ``~/.maverick/benchmarks/history.json`` store. No competitor numbers are
    shown or invented here — see docs/comparison.md for the qualitative
    comparison."""
    from .api import _benchmark_snapshot
    snap = _benchmark_snapshot()
    for s in snap["suites"]:
        s["spark"] = _sparkline_points([e["score"] for e in s["entries"]])
    return templates.TemplateResponse(request, "benchmarks.html", snap)


@app.get("/walkthroughs", response_class=HTMLResponse)
async def walkthroughs_page(request: Request) -> HTMLResponse:
    """Locally exported run walkthrough videos (no external hosting).

    Lists the MP4s under the walkthroughs dir with native <video> embeds and
    a captions track when the export produced one. The export itself is
    POST /api/v1/goals/{id}/walkthrough (replay-to-MP4 machinery)."""
    from .api import _walkthroughs_dir
    d = _walkthroughs_dir()
    items = []
    if d.is_dir():
        for p in sorted(d.glob("*.mp4"), key=lambda q: q.stat().st_mtime,
                        reverse=True):
            m = re.fullmatch(r"goal-(\d+)\.mp4", p.name)
            items.append({
                "name": p.name,
                "size_mb": round(p.stat().st_size / 1_048_576, 2),
                "mtime": p.stat().st_mtime,
                "captions": (p.with_suffix(".vtt").name
                             if p.with_suffix(".vtt").exists() else None),
                "goal_id": int(m.group(1)) if m else None,
            })
    # NB: not named "dir" — the context processor injects the page's text
    # direction under that key (RTL support) and would shadow it.
    return templates.TemplateResponse(
        request, "walkthroughs.html", {"items": items, "artifact_dir": str(d)},
    )


_WALKTHROUGH_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+\.(mp4|vtt)$")


@app.get("/walkthroughs/media/{name}")
async def walkthrough_media(name: str) -> FileResponse:
    """Serve one exported walkthrough artifact, strictly from the
    walkthroughs dir (the name pattern admits no path separators)."""
    from .api import _walkthroughs_dir
    if not _WALKTHROUGH_NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="invalid walkthrough name")
    path = _walkthroughs_dir() / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="no such walkthrough")
    media = "video/mp4" if name.endswith(".mp4") else "text/vtt"
    return FileResponse(path, media_type=media)


@app.get("/plan-tree-3d", response_class=HTMLResponse)
async def plan_tree_3d_page(request: Request) -> HTMLResponse:
    """The goal forest in 3D (vanilla WebGL; no three.js, no CDN).

    Progressive enhancement: without WebGL (or JS) the server-rendered text
    tree IS the page — it is also always present in a <details> for screen
    readers. WebXR shows an "Enter VR" button only when the browser reports
    support."""
    from .goal_tree import forest_html, goal_nodes
    nodes = goal_nodes(_world(), owner=goal_owner_filter(request))
    return templates.TemplateResponse(
        request, "plan_tree_3d.html",
        {"node_count": len(nodes), "fallback_html": forest_html(nodes)},
    )


@app.get("/livez")
async def livez() -> dict:
    """Process is alive (TCP-accept liveness only)."""
    return {"status": "ok"}


@app.get("/healthz")
async def healthz() -> JSONResponse:
    """Deep health: DB writable, LLM provider key present, runner alive."""
    from maverick.runner import MAX_CONCURRENT_GOALS, _run_semaphore
    checks: dict[str, str] = {}
    overall_ok = True

    try:
        from maverick.world_model import DEFAULT_DB, WorldModel
        wm = WorldModel(DEFAULT_DB)
        wm.conn.execute("SELECT 1").fetchone()
        checks["db"] = "ok"
    except Exception as e:
        # Council security finding: /healthz is auth-exempt so an
        # unauthenticated caller probing it during a DB failure used to
        # learn the absolute world.db path (and therefore the OS
        # username). Surface only the exception type when an
        # MAVERICK_DASHBOARD_TOKEN is configured (i.e. we're on a
        # potentially exposed deployment). Local-dev (no token set)
        # keeps the full detail for debuggability.
        if os.environ.get("MAVERICK_DASHBOARD_TOKEN"):
            checks["db"] = f"fail: {type(e).__name__}"
        else:
            checks["db"] = f"fail: {type(e).__name__}: {e}"
        overall_ok = False

    # Use the same gate the goal-creation routes use (`_any_provider_key_set`):
    # the dashboard accepts goals on any of the supported providers, so a
    # Gemini-only / OpenRouter-only deploy is healthy. Checking only ANTHROPIC/
    # OPENAI made /healthz + /readyz report 503 and got such a deploy pulled
    # from rotation by k8s/LB probes.
    if _any_provider_key_set():
        checks["llm_key"] = "ok"
    else:
        checks["llm_key"] = "missing"
        overall_ok = False

    in_flight = MAX_CONCURRENT_GOALS - _run_semaphore._value  # type: ignore[attr-defined]
    checks["runner"] = f"in_flight={in_flight}/{MAX_CONCURRENT_GOALS}"

    status = "ok" if overall_ok else "degraded"
    # /healthz + /readyz are auth-exempt (LB/k8s probes can't carry a bearer).
    # On a token-protected (i.e. potentially exposed) deployment, the detailed
    # `checks` block leaks operational signal to anyone on the network:
    # whether an LLM key is configured (llm_key: ok/missing) and a live
    # in-flight goal gauge. Mirror the DB-path redaction already done above and
    # collapse the exempt payload to just the status (LB probes only need the
    # 200/503). Local-dev (no token) keeps the full checks for debuggability.
    if os.environ.get("MAVERICK_DASHBOARD_TOKEN"):
        payload: dict[str, Any] = {"status": status}
    else:
        payload = {"status": status, "checks": checks}
    return JSONResponse(payload, status_code=200 if overall_ok else 503)


@app.get("/readyz")
async def readyz() -> JSONResponse:
    """Ready to serve traffic (alias for healthz today)."""
    return await healthz()


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics() -> PlainTextResponse:
    """Prometheus text format. Gated by the same bearer as /api/v1."""
    from maverick.runner import MAX_CONCURRENT_GOALS, _run_semaphore
    try:
        from maverick.world_model import DEFAULT_DB, WorldModel
        wm = WorldModel(DEFAULT_DB)
        rows = wm.conn.execute(
            "SELECT status, COUNT(*) FROM goals GROUP BY status"
        ).fetchall()
        spend = wm.total_spend()
    except Exception:
        rows = []
        spend = {"dollars": 0, "input_tokens": 0, "output_tokens": 0, "runs": 0}

    lines = [
        "# HELP maverick_goals_total Total goals by status",
        "# TYPE maverick_goals_total counter",
    ]
    for status, count in rows:
        lines.append(f'maverick_goals_total{{status="{status}"}} {count}')
    lines += [
        "# HELP maverick_cost_dollars_total Total LLM spend",
        "# TYPE maverick_cost_dollars_total counter",
        f"maverick_cost_dollars_total {spend['dollars']:.4f}",
        "# HELP maverick_tokens_total Total input/output tokens",
        "# TYPE maverick_tokens_total counter",
        f'maverick_tokens_total{{direction="input"}} {spend["input_tokens"]}',
        f'maverick_tokens_total{{direction="output"}} {spend["output_tokens"]}',
        "# HELP maverick_concurrent_goals Goals running right now",
        "# TYPE maverick_concurrent_goals gauge",
        f"maverick_concurrent_goals {MAX_CONCURRENT_GOALS - _run_semaphore._value}",
        "# HELP maverick_max_concurrent_goals Concurrency cap",
        "# TYPE maverick_max_concurrent_goals gauge",
        f"maverick_max_concurrent_goals {MAX_CONCURRENT_GOALS}",
    ]
    return PlainTextResponse("\n".join(lines) + "\n")


def _is_loopback_host(host: str) -> bool:
    return host in {"127.0.0.1", "localhost", "::1"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Maverick dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    if not _is_loopback_host(args.host) and not os.environ.get("MAVERICK_DASHBOARD_TOKEN"):
        raise SystemExit(
            "Refusing to bind dashboard to a non-loopback host without "
            "MAVERICK_DASHBOARD_TOKEN set."
        )

    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
