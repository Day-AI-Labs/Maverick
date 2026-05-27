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
from urllib.parse import urlparse

from fastapi import BackgroundTasks, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .api import router as api_router

log = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

app = FastAPI(
    title="Maverick Dashboard + REST API",
    description="Local browser UI plus REST API for programmatic access.",
    version="0.1.0",
)
app.include_router(api_router)


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
_query_token_warned = False


def _is_same_origin(request: Request) -> bool:
    """Allow only same-origin browser submissions for mutating form POSTs."""
    expected = request.url.netloc
    for header in ("origin", "referer"):
        value = request.headers.get(header)
        if not value:
            continue
        parsed = urlparse(value)
        if parsed.netloc == expected:
            return True
        return False
    # Non-browser/API clients commonly omit both headers.
    return True


@app.middleware("http")
async def bearer_auth(request: Request, call_next):
    global _query_token_warned
    expected = os.environ.get("MAVERICK_DASHBOARD_TOKEN")
    if not expected or request.url.path in _AUTH_EXEMPT:
        return await call_next(request)
    auth = request.headers.get("authorization", "")
    header_token = auth[7:] if auth.startswith("Bearer ") else ""
    query_token = request.query_params.get("token", "")
    ok_header = header_token and hmac.compare_digest(header_token, expected)
    ok_query = query_token and hmac.compare_digest(query_token, expected)
    if ok_header:
        return await call_next(request)
    if ok_query:
        if not _query_token_warned:
            log.warning(
                "Bearer token accepted via ?token= -- leaks via Referer/logs. "
                "Prefer Authorization: Bearer."
            )
            _query_token_warned = True
        return await call_next(request)
    return JSONResponse({"detail": "unauthorized"}, status_code=401)


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


def main() -> None:
    parser = argparse.ArgumentParser(description="Maverick dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
