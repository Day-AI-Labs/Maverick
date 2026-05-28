"""FastAPI dashboard for Maverick.

v0.1.6: BackgroundTask runner moved to maverick.runner; this file just
imports it. Eliminates the duplicate that lived in app.py + api.py +
mcp/server.py.
"""
from __future__ import annotations

import argparse
import hmac
import ipaddress
import logging
import os
import re
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

from fastapi import BackgroundTasks, FastAPI, Form, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import (
    HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse,
    StreamingResponse,
)
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api import router as api_router

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

_VALID_THEMES = {"dark", "light", "solarized", "hicontrast"}


def _resolve_theme(request: "Request") -> str:
    """Pick the theme from ``?theme=`` query param, cookie, config, then dark."""
    q = (request.query_params.get("theme") or "").strip().lower()
    if q in _VALID_THEMES:
        return q
    c = (request.cookies.get("mvk_theme") or "").strip().lower()
    if c in _VALID_THEMES:
        return c
    try:
        from maverick.config import load_config
        cfg = (load_config() or {}).get("dashboard") or {}
        cfg_theme = (cfg.get("theme") or "").strip().lower()
        if cfg_theme in _VALID_THEMES:
            return cfg_theme
    except Exception:
        pass
    return "dark"


# Context processor: every template gets the `theme` variable for the
# body class + the theme switcher links.
def _theme_context(request: "Request") -> dict:
    return {"theme": _resolve_theme(request)}


# Register the per-request context processor with Starlette so every
# TemplateResponse picks up the resolved theme automatically.
templates.context_processors.append(_theme_context)


def _set_theme_cookie(response, theme: str) -> None:
    """Persist the theme choice as a cookie so it sticks across page loads."""
    if theme in _VALID_THEMES:
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
)
app.include_router(api_router)

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


@app.middleware("http")
async def persist_theme(request: Request, call_next):
    """If ?theme=X is in the URL, set a cookie so it sticks."""
    response = await call_next(request)
    q = request.query_params.get("theme")
    if q and q.lower() in _VALID_THEMES:
        _set_theme_cookie(response, q.lower())
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

_AUTH_EXEMPT = {
    "/healthz", "/livez", "/readyz",
    "/openapi.json", "/docs", "/redoc", "/docs/oauth2-redirect",
}

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
            if not _is_same_origin(request):
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
    csp = _DOCS_CSP if request.url.path in {"/docs", "/redoc"} else _DEFAULT_CSP
    response.headers.setdefault("Content-Security-Policy", csp)
    return response


_PROVIDER_ENV_VARS = (
    "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY",
    "OPENROUTER_API_KEY", "MOONSHOT_API_KEY", "DEEPSEEK_API_KEY",
    "XAI_API_KEY",
)


def _any_provider_key_set() -> bool:
    """True if at least one supported provider's env var is populated.

    Council UX fix: the dashboard used to hard-fail on missing
    ANTHROPIC_API_KEY even when the user had OpenAI or Gemini set up.
    """
    return any(os.environ.get(v) for v in _PROVIDER_ENV_VARS)


# ----- goal-creation rate limit -----
# Council safety-seat (round 1): nothing throttled /chat/send or
# POST /api/v1/goals. A runaway loop or a flood of same-origin posts
# could spawn unbounded goals, each costing real money. This is an
# in-process sliding-window limiter (no new dependency) shared by both
# goal-creating routes. Cap is generous and configurable.
_goal_times: "deque[float]" = deque()
_goal_rl_lock = threading.Lock()


def _max_goals_per_min() -> int:
    try:
        return max(1, int(os.environ.get("MAVERICK_DASHBOARD_MAX_GOALS_PER_MIN", "30")))
    except ValueError:
        return 30


def check_goal_rate_limit() -> None:
    """Raise HTTPException(429) if the goal-creation rate exceeds the cap.

    60-second sliding window. Shared by /chat/send and /api/v1/goals so
    the limit is global to the dashboard process, not per-route.
    """
    cap = _max_goals_per_min()
    now = time.monotonic()
    with _goal_rl_lock:
        cutoff = now - 60.0
        while _goal_times and _goal_times[0] < cutoff:
            _goal_times.popleft()
        if len(_goal_times) >= cap:
            retry = int(60 - (now - _goal_times[0])) + 1
            raise HTTPException(
                status_code=429,
                detail=f"goal rate limit reached ({cap}/min). Try again in {retry}s.",
                headers={"Retry-After": str(max(1, retry))},
            )
        _goal_times.append(now)


_world_cache: dict[str, Any] = {}


def _world():
    """Return a per-DB-path cached WorldModel.

    Council perf finding: opening a new WorldModel on every request
    re-runs the PRAGMAs and the schema-migration check, leaks the
    connection (no close()), and serialises the asyncio loop because
    sqlite3 is sync. Cache by absolute DB path so test fixtures that
    monkeypatch ``DEFAULT_DB`` to a fresh ``tmp_path`` still get an
    isolated WorldModel per test.
    """
    from maverick.world_model import DEFAULT_DB, WorldModel
    key = str(DEFAULT_DB)
    cached = _world_cache.get(key)
    if cached is None:
        cached = WorldModel(DEFAULT_DB)
        _world_cache[key] = cached
    return cached


def _load_skills():
    from maverick.skills import load_skills
    return load_skills()


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    w = _world()
    # Use SQL aggregation instead of pulling every goal into Python.
    rows = w.conn.execute(
        "SELECT status, COUNT(*) FROM goals GROUP BY status"
    ).fetchall()
    by_status = {r[0]: int(r[1]) for r in rows}
    counts = {
        "total":   sum(by_status.values()),
        "active":  by_status.get("active", 0),
        "done":    by_status.get("done", 0),
        "blocked": by_status.get("blocked", 0),
    }
    # Bounded recent slice instead of "load every goal ever, take last 20".
    recent = w.list_goals(limit=20, order="desc")
    facts = w.get_facts()
    skills = _load_skills()
    return templates.TemplateResponse(
        request, "index.html",
        {"counts": counts, "goals": recent,
         "facts": facts, "skills": skills[:10]},
    )


@app.get("/goals", response_class=HTMLResponse)
async def goals_page(request: Request) -> HTMLResponse:
    goals = _world().list_goals(limit=200, order="desc")
    return templates.TemplateResponse(request, "goals.html", {"goals": goals})


@app.get("/skills", response_class=HTMLResponse)
async def skills_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "skills.html", {"skills": _load_skills()})


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


def safe_audit_day(day: Optional[str]) -> Optional[str]:
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
    return templates.TemplateResponse(
        request, "audit.html",
        {"events": events, "n": n, "day": day},
    )


@app.get("/plugins", response_class=HTMLResponse)
async def plugins_page(request: Request) -> HTMLResponse:
    """Discovered + enabled plugins."""
    try:
        from maverick.plugins import _entry_points, _allowed_plugin_names
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
        from maverick.tools import base_registry
        from maverick.sandbox import build_sandbox
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
        from maverick.tools import base_registry
        from maverick.sandbox import build_sandbox
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


@app.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request) -> HTMLResponse:
    recent = _world().list_goals(limit=10, order="desc")
    return templates.TemplateResponse(request, "chat.html", {"recent": recent})


@app.post("/chat/send")
async def chat_send(
    request: Request,
    bg: BackgroundTasks,
    title: str = Form(...),
) -> RedirectResponse:
    if not _is_same_origin(request):
        raise HTTPException(status_code=403, detail="cross-site form post blocked")
    if not _any_provider_key_set():
        raise HTTPException(
            status_code=400,
            detail=(
                "No LLM provider key configured. Run 'maverick init', or "
                "export ANTHROPIC_API_KEY / OPENAI_API_KEY before starting "
                "the dashboard."
            ),
        )
    check_goal_rate_limit()
    title = (title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="goal text is required")
    w = _world()
    goal_id = w.create_goal(title[:200], title[:8000])
    # Use the shared runner so this path gets the same concurrency cap,
    # budget defaults, and error handling as the REST API and MCP server.
    from maverick.runner import run_goal_in_thread
    bg.add_task(run_goal_in_thread, goal_id)
    return RedirectResponse(f"/chat/goal/{goal_id}", status_code=303)


@app.get("/chat/goal/{goal_id}", response_class=HTMLResponse)
async def chat_goal(request: Request, goal_id: int) -> HTMLResponse:
    g = _world().get_goal(goal_id)
    if g is None:
        raise HTTPException(status_code=404, detail="no such goal")
    return templates.TemplateResponse(request, "chat_goal.html", {"goal": g})


@app.get("/api/goal/{goal_id}")
async def api_goal_legacy(goal_id: int) -> dict:
    g = _world().get_goal(goal_id)
    if g is None:
        raise HTTPException(status_code=404, detail="no such goal")
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
            JOIN (
              SELECT g.id, g.parent_id, g.title, g.status, g.created_at,
                     ROW_NUMBER() OVER (
                       PARTITION BY g.parent_id
                       ORDER BY g.created_at ASC, g.id ASC
                     ) AS rn
                FROM goals g
            ) child ON child.parent_id = d.id
           WHERE d.depth < ?
             AND child.rn <= ?
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
        (goal_id, depth_cap, per_parent_cap),
    ).fetchall()

    nodes: dict[int, dict] = {}
    for r in rows:
        nodes[r["id"]] = {
            "id":        r["id"],
            "parent_id": r["parent_id"],
            "title":     r["title"],
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
async def api_plan_tree(goal_id: int) -> dict:
    """Plan-tree JSON: root + recursive children with status + cost."""
    w = _world()
    g = w.get_goal(goal_id)
    if g is None:
        raise HTTPException(status_code=404, detail="no such goal")
    return _build_plan_tree(w, goal_id)


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
    events = w.goal_events(goal_id, limit=10_000)
    return templates.TemplateResponse(
        request, "trajectory.html",
        {"goal": g, "events": events},
    )


@app.get("/api/v1/cost.csv")
async def cost_csv(month: Optional[str] = None) -> StreamingResponse:
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
    start_ts: Optional[float] = None
    end_ts: Optional[float] = None
    if month:
        try:
            start_ts = _dt.datetime.strptime(month, "%Y-%m").timestamp()
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"bad month: {e}")
        end_ts = start_ts + 31 * 86_400

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

        for row in w.conn.execute(sql, params):
            writer.writerow([
                row["id"], row["goal_id"],
                row["started_at"], row["ended_at"] or "",
                row["outcome"] or "",
                f"{(row['cost_dollars'] or 0):.6f}",
                row["input_tokens"], row["output_tokens"], row["tool_calls"],
            ])
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)

    return StreamingResponse(generate(), media_type="text/csv")


@app.get("/api/goal/{goal_id}/events")
async def api_goal_events_legacy(goal_id: int, since: int = 0, limit: int = 200) -> dict:
    w = _world()
    g = w.get_goal(goal_id)
    if g is None:
        raise HTTPException(status_code=404, detail="no such goal")
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
    if w.get_goal(goal_id) is None:
        raise HTTPException(status_code=404, detail="no such goal")

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

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # nginx/caddy: disable response buffering
        },
    )


@app.get("/livez")
async def livez() -> dict:
    """Process is alive (TCP-accept liveness only)."""
    return {"status": "ok"}


@app.get("/healthz")
async def healthz() -> JSONResponse:
    """Deep health: DB writable, LLM provider key present, runner alive."""
    from maverick.runner import _run_semaphore, MAX_CONCURRENT_GOALS
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

    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY"):
        checks["llm_key"] = "ok"
    else:
        checks["llm_key"] = "missing"
        overall_ok = False

    in_flight = MAX_CONCURRENT_GOALS - _run_semaphore._value  # type: ignore[attr-defined]
    checks["runner"] = f"in_flight={in_flight}/{MAX_CONCURRENT_GOALS}"

    payload = {"status": "ok" if overall_ok else "degraded", "checks": checks}
    return JSONResponse(payload, status_code=200 if overall_ok else 503)


@app.get("/readyz")
async def readyz() -> JSONResponse:
    """Ready to serve traffic (alias for healthz today)."""
    return await healthz()


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics() -> PlainTextResponse:
    """Prometheus text format. Gated by the same bearer as /api/v1."""
    from maverick.runner import _run_semaphore, MAX_CONCURRENT_GOALS
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
