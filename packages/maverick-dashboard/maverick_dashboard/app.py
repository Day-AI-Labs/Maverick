"""FastAPI dashboard for Maverick.

v0.1.6: BackgroundTask runner moved to maverick.runner; this file just
imports it. Eliminates the duplicate that lived in app.py + api.py +
mcp/server.py.
"""
from __future__ import annotations

import argparse
import hmac
import logging
import os
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from fastapi import BackgroundTasks, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

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


@app.middleware("http")
async def bearer_auth(request: Request, call_next):
    expected = os.environ.get("MAVERICK_DASHBOARD_TOKEN")
    if not expected or request.url.path in _AUTH_EXEMPT:
        return await call_next(request)
    auth = request.headers.get("authorization", "")
    header_token = auth[7:] if auth.startswith("Bearer ") else ""
    # ``?token=`` query auth was removed: it leaks the bearer through
    # browser history, Referer headers on outbound link clicks, uvicorn
    # access logs, and any logging proxy in front. Require the
    # ``Authorization: Bearer`` header.
    if header_token and hmac.compare_digest(header_token, expected):
        return await call_next(request)
    return JSONResponse({"detail": "unauthorized"}, status_code=401)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Apply baseline browser-security headers to every response.

    These are cheap, well-supported, and close a class of attacks
    (clickjacking, MIME sniffing, Referer leakage) the dashboard had
    no defense against before.
    """
    response = await call_next(request)
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault(
        "Cross-Origin-Opener-Policy", "same-origin",
    )
    return response


def _world():
    from maverick.world_model import DEFAULT_DB, WorldModel
    return WorldModel(DEFAULT_DB)


def _load_skills():
    from maverick.skills import load_skills
    return load_skills()


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    w = _world()
    goals = w.list_goals()
    facts = w.get_facts()
    skills = _load_skills()
    counts = {
        "total":  len(goals),
        "active": sum(1 for g in goals if g.status == "active"),
        "done":   sum(1 for g in goals if g.status == "done"),
        "blocked": sum(1 for g in goals if g.status == "blocked"),
    }
    return templates.TemplateResponse(
        request, "index.html",
        {"counts": counts, "goals": list(reversed(goals[-20:])),
         "facts": facts, "skills": skills[:10]},
    )


@app.get("/goals", response_class=HTMLResponse)
async def goals_page(request: Request) -> HTMLResponse:
    goals = list(reversed(_world().list_goals()))
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


@app.get("/api/v1/providers")
async def providers_api() -> JSONResponse:
    from maverick.provider_health import get as _health
    return JSONResponse({"providers": _health().snapshot()})


@app.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request) -> HTMLResponse:
    recent = list(reversed(_world().list_goals()[-10:]))
    return templates.TemplateResponse(request, "chat.html", {"recent": recent})


@app.post("/chat/send")
async def chat_send(
    request: Request,
    bg: BackgroundTasks,
    title: str = Form(...),
) -> RedirectResponse:
    if not _is_same_origin(request):
        raise HTTPException(status_code=403, detail="cross-site form post blocked")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(status_code=400, detail="ANTHROPIC_API_KEY not set.")
    w = _world()
    goal_id = w.create_goal(title.strip()[:200], title.strip())
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
    """Recursively assemble the plan tree rooted at goal_id."""
    root = world.get_goal(goal_id)
    if root is None:
        return {}

    def _children(parent_id: int) -> list:
        rows = world.conn.execute(
            "SELECT id, parent_id, title, status, "
            "(SELECT COALESCE(SUM(cost_dollars), 0) FROM episodes WHERE episodes.goal_id = goals.id) AS dollars "
            "FROM goals WHERE parent_id = ? ORDER BY created_at ASC LIMIT 50",
            (parent_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def _attach(node: dict, depth: int) -> dict:
        if depth >= depth_cap:
            node["children"] = []
            return node
        node["children"] = [_attach(c, depth + 1) for c in _children(node["id"])]
        return node

    root_d = {
        "id": root.id, "parent_id": root.parent_id,
        "title": root.title, "status": root.status,
        "dollars": 0.0,
    }
    # Lookup dollars for root.
    row = world.conn.execute(
        "SELECT COALESCE(SUM(cost_dollars), 0) AS d FROM episodes WHERE goal_id = ?",
        (root.id,),
    ).fetchone()
    root_d["dollars"] = float(row["d"]) if row else 0.0
    return _attach(root_d, 0)


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
        return _html.escape(str(s)) if s is not None else ""

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


@app.get("/api/v1/cost.csv", response_class=PlainTextResponse)
async def cost_csv(month: Optional[str] = None) -> str:
    """CSV rollup of episode spend.

    ``month`` filter: YYYY-MM (e.g. 2026-04). Omit for lifetime.
    Columns: episode_id, goal_id, started_at, ended_at, outcome,
    dollars, in_tokens, out_tokens, tool_calls.
    """
    import csv
    import datetime as _dt
    import io as _io

    w = _world()
    episodes = w.list_episodes(limit=100_000)
    if month:
        try:
            start = _dt.datetime.strptime(month, "%Y-%m").timestamp()
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"bad month: {e}")
        end = start + 31 * 86_400
        episodes = [e for e in episodes if start <= (e.started_at or 0) < end]

    buf = _io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "episode_id", "goal_id", "started_at", "ended_at", "outcome",
        "dollars", "input_tokens", "output_tokens", "tool_calls",
    ])
    for e in episodes:
        writer.writerow([
            e.id, e.goal_id,
            e.started_at, e.ended_at or "",
            e.outcome or "",
            f"{e.cost_dollars:.6f}",
            e.input_tokens, e.output_tokens, e.tool_calls,
        ])
    return buf.getvalue()


@app.get("/api/goal/{goal_id}/events")
async def api_goal_events_legacy(goal_id: int, since: int = 0, limit: int = 200) -> dict:
    w = _world()
    g = w.get_goal(goal_id)
    if g is None:
        raise HTTPException(status_code=404, detail="no such goal")
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
