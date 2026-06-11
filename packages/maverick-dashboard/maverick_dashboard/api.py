"""REST API for Maverick (mounted at /api/v1).

v0.1.6: BackgroundTask runner moved to maverick.runner.
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import json
import logging
import os
import threading
import time

from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from maverick.runner import (
    DEFAULT_MAX_DEPTH,
    DEFAULT_MAX_DOLLARS,
    DEFAULT_MAX_WALL_SECONDS,
)
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from starlette.responses import StreamingResponse

from ._shared import _any_provider_key_set, _world
from ._shared import _world_cache as _world_cache  # re-export: tests clear api._world_cache
from .auth import (
    assert_goal_access,
    caller_principal,
    execution_user_id_from_request,
    goal_owner_filter,
    is_dashboard_admin,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["v1"])


class GoalIn(BaseModel):
    title: str = Field(..., max_length=200)
    description: str = ""
    max_dollars: float = Field(5.0, ge=0.0, le=100.0)
    max_wall_seconds: float = Field(3600.0, ge=1.0, le=86400.0)
    max_depth: int = Field(3, ge=1, le=5)
    template: str | None = None
    params: dict[str, str] | None = None


class GoalOut(BaseModel):
    id: int
    status: str
    title: str
    description: str | None = None
    result: str | None = None


class GoalEventOut(BaseModel):
    id: int
    agent: str
    kind: str
    content: str
    ts: float


class GoalEventsResponse(BaseModel):
    status: str
    result: str | None
    next_id: int
    events: list[GoalEventOut]


class FactIn(BaseModel):
    key: str
    value: str


class AnswerIn(BaseModel):
    question_id: int
    answer: str


class SkillInstallIn(BaseModel):
    source: str = Field(..., description="https://... or gh:org/repo[:path]")


class SkillOut(BaseModel):
    name: str
    triggers: list[str]
    tools_needed: list[str]


def _to_goal_out(g) -> GoalOut:
    return GoalOut(
        id=g.id, status=g.status, title=g.title,
        description=g.description, result=g.result,
    )


@router.post("/goals", response_model=GoalOut, status_code=201)
async def create_goal(request: Request, payload: GoalIn, bg: BackgroundTasks) -> GoalOut:
    if not _any_provider_key_set():
        raise HTTPException(
            status_code=400,
            detail=(
                "No LLM provider key or endpoint configured. Run 'maverick "
                "init', export ANTHROPIC_API_KEY / OPENAI_API_KEY / "
                "GEMINI_API_KEY, or add a [providers.<name>] api_key/base_url "
                "to ~/.maverick/config.toml before starting the dashboard."
            ),
        )
    # Shared sliding-window cap across /chat/send + this route, so a
    # runaway loop can't spawn unbounded (paid) goals.
    from maverick_dashboard.app import check_goal_rate_limit
    check_goal_rate_limit(request)
    title = payload.title
    description = payload.description
    if payload.template:
        from maverick.templates import load_template
        try:
            tpl = load_template(payload.template)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))
        try:
            title, description = tpl.render(**(payload.params or {}))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    title = (title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="title is required")
    w = _world()
    goal_id = w.create_goal(title[:200], description, owner=caller_principal(request) or "")
    from maverick.runner import run_goal_in_thread
    # Enforce server-side execution caps even when callers request larger values.
    max_dollars = min(payload.max_dollars, DEFAULT_MAX_DOLLARS)
    max_wall_seconds = min(payload.max_wall_seconds, DEFAULT_MAX_WALL_SECONDS)
    max_depth = min(payload.max_depth, DEFAULT_MAX_DEPTH)

    user_id = execution_user_id_from_request(request)
    if user_id:
        bg.add_task(
            run_goal_in_thread, goal_id,
            max_dollars, max_wall_seconds, max_depth,
            channel="api", user_id=user_id,
        )
    else:
        bg.add_task(
            run_goal_in_thread, goal_id,
            max_dollars, max_wall_seconds, max_depth,
        )
    g = w.get_goal(goal_id)
    if g is None:
        raise HTTPException(status_code=500, detail="goal vanished after create")
    return _to_goal_out(g)


@router.get("/goals", response_model=list[GoalOut])
async def list_goals(
    request: Request,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[GoalOut]:
    """List goals (newest first), paginated.

    Council perf fix: previous version pulled every goal ever into
    Python via ``list_goals()``, then sliced. Now the LIMIT/OFFSET are
    pushed to SQL.

    Owner-scoped: a non-admin authenticated caller sees only their own goals;
    auth-off and admin callers see all (``goal_owner_filter`` returns None).
    """
    w = _world()
    limit = max(1, min(int(limit or 50), 500))
    offset = max(0, int(offset or 0))
    goals = w.list_goals(
        status=status, owner=goal_owner_filter(request),
        limit=limit, offset=offset, order="desc",
    )
    return [_to_goal_out(g) for g in goals]


@router.get("/goals/search", response_model=list[GoalOut])
async def search_goals(request: Request, q: str, limit: int = 50) -> list[GoalOut]:
    """Search across runs (goals) by text in title / description / result.

    Owner-scoped: a non-admin authenticated caller searches only their own
    goals; auth-off and admin callers search all. Declared before
    ``/goals/{goal_id}`` so the literal ``search`` path wins over the int param.
    """
    query = (q or "").strip()
    if not query:
        return []
    limit = max(1, min(int(limit or 50), 200))
    goals = _world().search_goals(query, owner=goal_owner_filter(request), limit=limit)
    return [_to_goal_out(g) for g in goals]


@router.get("/goals/{goal_id}", response_model=GoalOut)
async def get_goal(request: Request, goal_id: int) -> GoalOut:
    g = _world().get_goal(goal_id)
    if g is None:
        raise HTTPException(status_code=404, detail="no such goal")
    assert_goal_access(request, g)
    return _to_goal_out(g)


@router.get("/goals/{goal_id}/events", response_model=GoalEventsResponse)
async def goal_events(
    request: Request, goal_id: int, since: int = 0, limit: int = 200,
) -> GoalEventsResponse:
    w = _world()
    g = w.get_goal(goal_id)
    if g is None:
        raise HTTPException(status_code=404, detail="no such goal")
    assert_goal_access(request, g)
    events = w.goal_events(goal_id, since_id=since, limit=max(1, min(limit, 500)))
    return GoalEventsResponse(
        status=g.status,
        result=g.result,
        next_id=events[-1].id if events else since,
        events=[
            GoalEventOut(id=e.id, agent=e.agent, kind=e.kind,
                         content=e.content, ts=e.ts)
            for e in events
        ],
    )


def _sse_event(e) -> str:
    """Format one goal event as a Server-Sent Event frame."""
    data = json.dumps({"id": e.id, "agent": e.agent, "kind": e.kind,
                       "content": e.content, "ts": e.ts})
    kind = str(e.kind or "message").replace("\n", " ").replace("\r", " ")
    return f"id: {e.id}\nevent: {kind}\ndata: {data}\n\n"


_TERMINAL_STATUSES = frozenset({"done", "failed", "cancelled", "blocked", "error"})


@router.get("/goals/{goal_id}/events/stream")
async def goal_events_stream(
    request: Request, goal_id: int, since: int = 0, limit: int = 0,
    poll: float = 1.0,
) -> StreamingResponse:
    """Real-time **SSE** stream of a goal's events (`text/event-stream`).

    Tails the durable `goal_events` log (so it works across the worker/dashboard
    process split, unlike an in-process bus): emits each new event as it lands,
    ends when the goal reaches a terminal status with no more events, or on
    client disconnect. ``limit`` (>0) closes after N events — used by tests and
    bounded consumers; ``poll`` is the tail interval.
    """
    w = _world()
    g = w.get_goal(goal_id)
    if g is None:
        raise HTTPException(status_code=404, detail="no such goal")
    assert_goal_access(request, g)

    async def _gen():
        last = since
        sent = 0
        yield ": connected\n\n"   # open the stream immediately
        while True:
            if await request.is_disconnected():
                break
            events = await run_in_threadpool(
                w.goal_events, goal_id, last, 200)  # (goal_id, since_id, limit)
            for e in events:
                yield _sse_event(e)
                last = e.id
                sent += 1
                if limit and sent >= limit:
                    return
            cur = w.get_goal(goal_id)
            if not events and cur is not None and cur.status in _TERMINAL_STATUSES:
                yield f"event: end\ndata: {json.dumps({'status': cur.status})}\n\n"
                return
            await asyncio.sleep(max(0.0, poll))

    return StreamingResponse(_gen(), media_type="text/event-stream")


@router.post("/goals/{goal_id}/answer", status_code=204)
async def answer_question(request: Request, goal_id: int, payload: AnswerIn) -> None:
    w = _world()
    g = w.get_goal(goal_id)
    if g is None:
        raise HTTPException(status_code=404, detail="no such goal")
    assert_goal_access(request, g)
    answer = (payload.answer or "").strip()
    if not answer:
        raise HTTPException(status_code=400, detail="answer is required")
    qs = w.open_questions(goal_id=goal_id)
    if not any(q.id == payload.question_id for q in qs):
        raise HTTPException(status_code=404, detail="no such open question for this goal")
    w.answer(payload.question_id, answer)


class AttachmentOut(BaseModel):
    id: int
    filename: str
    mime: str
    size_bytes: int
    sha256: str


@router.post(
    "/goals/{goal_id}/attachments",
    response_model=AttachmentOut,
    status_code=201,
)
async def upload_attachment(
    request: Request, goal_id: int, file: UploadFile = File(...),
) -> AttachmentOut:
    """Upload a file (text, image, or PDF) and attach it to a goal.

    Size and mime-type validation are enforced server-side; the agent's
    `list_attachments` tool exposes the uploaded set, and image
    attachments are auto-embedded as vision blocks on the first message.
    """
    w = _world()
    g = w.get_goal(goal_id)
    if g is None:
        raise HTTPException(status_code=404, detail="no such goal")
    assert_goal_access(request, g)

    from maverick.attachments import (
        MAX_FILE_BYTES,
        AttachmentRejected,
        store,
    )

    data = await file.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"file too large: {len(data)} bytes (limit {MAX_FILE_BYTES})"
            ),
        )

    mime = file.content_type or "application/octet-stream"
    filename = file.filename or "upload"

    existing = sum(a.size_bytes for a in w.list_attachments(goal_id))
    try:
        stored = store(
            goal_id,
            filename=filename,
            mime=mime,
            data=data,
            existing_total=existing,
        )
    except AttachmentRejected as e:
        raise HTTPException(status_code=400, detail=str(e))

    aid = w.add_attachment(
        goal_id=goal_id,
        filename=stored.filename,
        mime=stored.mime,
        size_bytes=stored.size_bytes,
        sha256=stored.sha256,
        path=str(stored.path),
    )
    return AttachmentOut(
        id=aid,
        filename=stored.filename,
        mime=stored.mime,
        size_bytes=stored.size_bytes,
        sha256=stored.sha256,
    )


@router.get("/goals/{goal_id}/attachments", response_model=list[AttachmentOut])
async def list_goal_attachments(request: Request, goal_id: int) -> list[AttachmentOut]:
    w = _world()
    g = w.get_goal(goal_id)
    if g is None:
        raise HTTPException(status_code=404, detail="no such goal")
    assert_goal_access(request, g)
    return [
        AttachmentOut(
            id=a.id, filename=a.filename, mime=a.mime,
            size_bytes=a.size_bytes, sha256=a.sha256,
        )
        for a in w.list_attachments(goal_id)
    ]


@router.get("/facts", response_model=dict[str, str])
async def list_facts() -> dict[str, str]:
    return _world().get_facts()


@router.post("/facts", status_code=204)
async def set_fact(payload: FactIn) -> None:
    key = (payload.key or "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="fact key is required")
    _world().upsert_fact(key, payload.value)


@router.get("/skills", response_model=list[SkillOut])
async def list_installed_skills() -> list[SkillOut]:
    from maverick.skills import load_skills
    return [
        SkillOut(name=s.name, triggers=s.triggers, tools_needed=s.tools_needed)
        for s in load_skills()
    ]


def _require_skill_install_opt_in() -> None:
    if os.environ.get("MAVERICK_ALLOW_SKILL_INSTALL", "").lower() not in {"1", "true", "yes"}:
        raise HTTPException(
            status_code=403,
            detail=(
                "skill install via REST is disabled. Set "
                "MAVERICK_ALLOW_SKILL_INSTALL=1 to opt in, or use "
                "`maverick skill install` on the host."
            ),
        )


@router.post("/skills", response_model=SkillOut, status_code=201)
async def install_skill_endpoint(payload: SkillInstallIn) -> SkillOut:
    """Install a skill from a URL or ``gh:org/repo[:path]``.

    Skill install runs untrusted code at the next agent invocation. The
    endpoint is gated behind ``MAVERICK_ALLOW_SKILL_INSTALL=1`` so a
    compromised dashboard token can't be turned into one-shot RCE; an
    operator opting in is taking explicit ownership of the supply
    chain. CLI ``maverick skill install`` remains available without
    the flag because it requires shell access on the host.
    """
    _require_skill_install_opt_in()
    from maverick.skills import install_skill
    try:
        s = install_skill(payload.source, trusted_local=False)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return SkillOut(name=s.name, triggers=s.triggers, tools_needed=s.tools_needed)


class CatalogInstallIn(BaseModel):
    name: str = Field(..., max_length=200)


@router.get("/diag/tail-latency")
async def diag_tail_latency(ratio: float = 3.0, min_count: int = 20) -> dict:
    """Tools with a fat latency tail (p99/p50 ≥ ratio) — the ones worth hunting.

    Reads this serving process's in-memory per-tool latency samples, so it's
    meaningful on a long-lived dashboard/worker, not a fresh CLI invocation."""
    from maverick.tail_latency import hunt
    return {"flagged": hunt(ratio_threshold=ratio, min_count=min_count)}


@router.get("/marketplace/stats")
async def marketplace_stats() -> dict:
    """Aggregate stats over the local ratings ledger (total / average / 1–5★
    distribution / per-kind / top-rated). Self-host-first: the operator's own
    ratings, the JSON face of the marketplace stats view."""
    from maverick.marketplace_ratings import RatingsLedger
    from maverick.marketplace_stats import summarize
    return summarize(RatingsLedger())


@router.get("/templates")
async def templates_catalog() -> dict:
    """The goal-template catalog with the operator's own ratings — the JSON
    face of the /templates marketplace page."""
    from maverick_dashboard.app import template_market_entries
    return {"templates": template_market_entries()}


@router.get("/templates/suggested")
async def templates_suggested(request: Request, k: int = 5) -> dict:
    """Personalized starter templates: the catalog ranked for THIS user from
    their goal-title history (pure scorer, no LLM — ``maverick.starter_templates``).
    Owner-scoped history: an authenticated non-admin is ranked on their own
    goals only."""
    from maverick.starter_templates import suggest
    k = max(1, min(int(k or 5), 20))
    return {
        "suggested": suggest(_world(), k=k, owner=goal_owner_filter(request)),
    }


@router.get("/voice/captions")
async def voice_captions(source: str = "default", max_chars: int = 160) -> StreamingResponse:
    """Live captions (SSE) over the voice transcript seam.

    Streams one ``data: {caption, final, ts}`` frame per transcript segment
    from the named source in ``maverick.live_captions``'s source registry,
    then ``event: end`` when the source is exhausted. Default-off: the
    registry starts empty (no live mic — a deployment registers its ASR
    pipeline; tests register scripted sources), so an unregistered source
    404s.
    """
    from maverick.live_captions import caption_stream, get_source
    factory = get_source(source)
    if factory is None:
        raise HTTPException(
            status_code=404,
            detail=f"no caption source registered as {source!r}; "
                   "register one via maverick.live_captions.register_source",
        )
    try:
        max_chars = max(16, min(int(max_chars), 500))
    except (TypeError, ValueError):
        max_chars = 160

    async def _gen():
        yield ": captions\n\n"
        async for frame in caption_stream(factory(), max_chars=max_chars):
            yield f"data: {json.dumps(frame)}\n\n"
        yield "event: end\ndata: {}\n\n"

    return StreamingResponse(_gen(), media_type="text/event-stream")


@router.get("/catalog/{kind}")
async def catalog_list(kind: str) -> dict:
    """List federated catalog entries for a kind (skills/plugins/mcp/personas).

    Tolerates an unreachable index by returning an empty list, so a
    fresh install shows "no catalog entries" rather than 500ing.
    """
    from maverick.catalog import VALID_KINDS, load_catalog
    if kind not in VALID_KINDS:
        raise HTTPException(
            status_code=400,
            detail=f"unknown kind {kind!r}; valid: {', '.join(VALID_KINDS)}",
        )
    entries = load_catalog(kind)
    return {"kind": kind, "entries": [e.to_dict() for e in entries]}


@router.post("/catalog/skills/install", response_model=SkillOut, status_code=201)
async def catalog_install_skill(payload: CatalogInstallIn) -> SkillOut:
    """Install a catalog skill by name.

    Catalog metadata (source + hash) can come from remote indexes, so
    this endpoint keeps the same operator opt-in gate as free-text skill
    installs.
    """
    _require_skill_install_opt_in()
    from maverick.skills import install_from_catalog
    try:
        s = install_from_catalog(payload.name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return SkillOut(name=s.name, triggers=s.triggers, tools_needed=s.tools_needed)


@router.delete("/skills/{name}", status_code=204)
async def remove_skill_endpoint(name: str) -> None:
    from maverick.skills import remove_skill
    if not remove_skill(name):
        raise HTTPException(status_code=404, detail="no such skill")


# ---------- self-learning: learned ledger + generated tools (#427) ----------


def _learned_snapshot(limit: int = 50) -> dict:
    """Read-only view of the self-learning ledger + on-disk generated tools.

    Powers the /learned page and GET /api/v1/learned. Degrades to empty
    lists if the self-learning module / ledger / dir is unavailable, so a
    fresh install (feature never enabled) renders "nothing learned yet"
    instead of 500ing.
    """
    learned: list[dict] = []
    tools: list[str] = []
    try:
        from maverick import self_learning
        # Pass the path explicitly: history()'s default arg is bound at
        # import time, so reading the module global here lets the live
        # LEARNED_PATH (and tests) take effect.
        learned = [
            e.to_dict()
            for e in self_learning.history(
                limit=limit, path=self_learning.LEARNED_PATH,
            )
        ]
        d = self_learning.GENERATED_TOOLS_DIR
        if d.exists():
            tools = sorted(
                p.name for p in d.glob("*.py")
                if not p.name.startswith((".", "_"))
            )
    except Exception as e:  # pragma: no cover -- never block the page
        log.debug("learned snapshot failed: %s", e)
    return {"learned": learned, "generated_tools": tools}


def _resolve_generated_tool(name: str):
    """Resolve ``name`` to a ``*.py`` file strictly inside GENERATED_TOOLS_DIR.

    Path-safety guard for the removal endpoint: the resolved target must be
    a direct child of the generated-tools dir and end in ``.py``. Rejects
    traversal (``..``), absolute paths, and subdirectory escapes by
    comparing the resolved parent against the resolved dir. Returns the
    Path or raises HTTPException(400).
    """
    from maverick import self_learning
    d = self_learning.GENERATED_TOOLS_DIR
    # A legitimate generated-tool filename is a bare ``<name>.py`` with no
    # separators; reject anything with a path separator or traversal token
    # before touching the filesystem.
    if "/" in name or "\\" in name or name in ("", ".", "..") or not name.endswith(".py"):
        raise HTTPException(status_code=400, detail="invalid generated-tool name")
    target = (d / name).resolve()
    base = d.resolve()
    if target.parent != base:
        raise HTTPException(status_code=400, detail="path outside generated_tools")
    return target


@router.get("/learned")
async def learned_api() -> dict:
    """Learned-capability ledger entries + on-disk generated tool filenames."""
    return _learned_snapshot()


@router.delete("/generated-tools/{name}", status_code=204)
async def remove_generated_tool(name: str) -> None:
    """Delete a persisted generated tool so a bad one can be pulled.

    The valuable mutation of #427: removes ~/.maverick/generated_tools/<name>
    without filesystem access. The path is resolved strictly under the
    generated-tools dir (see ``_resolve_generated_tool``) so traversal /
    absolute / out-of-dir names are refused. Auth/same-origin is enforced
    centrally by the dashboard's bearer_auth middleware (DELETE is a
    mutating method, so the same-origin check applies).
    """
    target = _resolve_generated_tool(name)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="no such generated tool")
    try:
        target.unlink()
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"could not remove: {e}")


@router.get("/spend")
async def get_spend() -> dict:
    w = _world()
    total = w.total_spend()
    episodes = w.list_episodes(limit=30)
    return {
        "total": total,
        "episodes": [
            {
                "id": e.id, "goal_id": e.goal_id, "started_at": e.started_at,
                "ended_at": e.ended_at, "outcome": e.outcome,
                "cost_dollars": e.cost_dollars,
                "input_tokens": e.input_tokens,
                "output_tokens": e.output_tokens,
                "tool_calls": e.tool_calls,
            }
            for e in episodes
        ],
    }


_SECURITY_REGISTER_CACHE_TTL_SECONDS = 60.0
_SECURITY_REGISTER_HUNT_DAYS = 7
_security_register_cache: tuple[float, dict] | None = None
_security_register_cache_lock = threading.Lock()


def _security_hunt_window() -> tuple[str, str]:
    today = _dt.datetime.now(_dt.timezone.utc).date()
    since = today - _dt.timedelta(days=_SECURITY_REGISTER_HUNT_DAYS - 1)
    return since.isoformat(), today.isoformat()


def _security_register_snapshot_uncached() -> dict:
    controls: list[dict] = []
    try:
        from maverick.compliance import compliance_report
        controls = [
            {"control": c.control, "status": c.status, "regulation": c.regulation,
             "detail": c.detail, "framework": c.framework}
            for c in compliance_report()
        ]
    except Exception:
        log.warning("security register: compliance probe failed", exc_info=True)

    threat: dict = {"risk": "clear", "events_scanned": 0, "findings": []}
    breaches: list[dict] = []
    try:
        from maverick.threat_hunt import hunt
        since, until = _security_hunt_window()
        r = hunt(all_days=False, since=since, until=until)
        findings = [
            {"kind": f.kind, "title": f.title, "severity": f.severity,
             "count": f.count, "agents": f.agents}
            for f in r.findings
        ]
        threat = {
            "risk": r.risk_rating, "events_scanned": r.events_scanned,
            "window": {"since": since, "until": until},
            "findings": findings,
        }
        breaches = [
            {"kind": f.kind, "title": f.title, "severity": f.severity, "count": f.count}
            for f in r.findings
        ]
    except Exception:
        log.warning("security register: threat hunt failed", exc_info=True)

    remediation: dict = {"auto_fix_enabled": False, "gaps": [], "breaches": breaches}
    try:
        from maverick.remediation import plan
        p = plan(include_breaches=False)
        remediation = {
            "auto_fix_enabled": p.auto_fix_enabled,
            "gaps": [
                {"control": g.control, "title": g.title, "auto": g.auto,
                 "rationale": g.rationale}
                for g in p.gaps
            ],
            "breaches": breaches,
        }
    except Exception:
        log.warning("security register: remediation plan failed", exc_info=True)

    return {"controls": controls, "threat_hunt": threat, "remediation": remediation}


def _security_register_snapshot() -> dict:
    global _security_register_cache
    with _security_register_cache_lock:
        now = time.monotonic()
        if (
            _security_register_cache is not None
            and now - _security_register_cache[0] < _SECURITY_REGISTER_CACHE_TTL_SECONDS
        ):
            return _security_register_cache[1]
        snapshot = _security_register_snapshot_uncached()
        _security_register_cache = (time.monotonic(), snapshot)
        return snapshot


@router.get("/security")
async def security_register() -> dict:
    """The privacy/security agent team's register, read-only and fail-soft.

    The audit hunt is bounded to a recent window, cached briefly, and run off
    the event loop so cross-site or repeated GETs cannot force unbounded
    synchronous audit-log scans on every request.
    """
    return await run_in_threadpool(_security_register_snapshot)


# ---------- council pass: control surface ----------

class HaltIn(BaseModel):
    reason: str = Field("manual via dashboard", max_length=200)


@router.get("/halt")
async def halt_status() -> dict:
    """Is the killswitch armed?

    Council round-2 capabilities-seat fix: round-1 only surfaced the
    file path. Now also returns the reason string (from the file body
    when the halt was set via POST) and the file's mtime as ``armed_at``
    so the UI can show "halted 3m ago for: <reason>".
    """
    from maverick.killswitch import _halt_file_path, is_active
    p = _halt_file_path()
    out: dict = {
        "active": is_active(),
        "file": str(p),
        "file_present": p.exists(),
        "reason": None,
        "armed_at": None,
    }
    if p.exists():
        try:
            body = p.read_text(errors="replace").strip()
            out["reason"] = body or None
        except OSError:
            pass
        try:
            out["armed_at"] = p.stat().st_mtime
        except OSError:
            pass
    return out


@router.post("/halt", status_code=204)
async def halt_set(payload: HaltIn) -> None:
    """Arm the killswitch by touching ~/.maverick/HALT.

    Honoured by every agent at the next tool-call boundary. Use the
    DELETE endpoint or ``rm ~/.maverick/HALT`` to clear.
    """
    from maverick.killswitch import _halt_file_path
    p = _halt_file_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text((payload.reason or "manual via dashboard") + "\n")
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"cannot write halt file: {e}")


@router.delete("/halt", status_code=204)
async def halt_clear() -> None:
    """Clear the killswitch (delete ~/.maverick/HALT)."""
    from maverick.killswitch import _halt_file_path, clear
    p = _halt_file_path()
    if p.exists():
        try:
            p.unlink()
        except OSError as e:
            raise HTTPException(status_code=500, detail=f"cannot remove halt file: {e}")
    clear()


@router.post("/goals/{goal_id}/cancel", status_code=204)
async def cancel_goal(request: Request, goal_id: int) -> None:
    """Mark a goal as cancelled.

    The agent loop checks status at each tool-call boundary; setting
    'cancelled' here causes the next check to short-circuit the run.
    Already-done goals are a no-op.
    """
    w = _world()
    g = w.get_goal(goal_id)
    if g is None:
        raise HTTPException(status_code=404, detail="no such goal")
    assert_goal_access(request, g)
    if g.status in ("done", "cancelled", "failed"):
        return
    w.set_goal_status(goal_id, "cancelled", result="cancelled via dashboard")


@router.get("/goals/{goal_id}/open_questions")
async def goal_open_questions(request: Request, goal_id: int) -> dict:
    """List unanswered questions an agent has parked for this goal."""
    w = _world()
    g = w.get_goal(goal_id)
    if g is None:
        raise HTTPException(status_code=404, detail="no such goal")
    assert_goal_access(request, g)
    qs = w.open_questions(goal_id=goal_id)
    return {
        "open_questions": [
            {"id": q.id, "question": q.question, "asked_at": q.asked_at}
            for q in qs
        ],
    }


@router.get("/plugins")
async def list_plugins() -> dict:
    """Discovered + allow-listed plugins, broken out by kind."""
    try:
        from maverick.plugins import _allowed_plugin_names, _entry_points
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"plugin discovery failed: {e}")
    allow = _allowed_plugin_names()
    out: dict[str, list[dict]] = {
        "tools": [], "channels": [], "skills": [], "personas": [],
    }
    for kind, group in (
        ("tools",    "maverick.tools"),
        ("channels", "maverick.channels"),
        ("skills",   "maverick.skills"),
        ("personas", "maverick.personas"),
    ):
        try:
            for ep in _entry_points(group):
                out[kind].append({
                    "name": ep.name,
                    "module": getattr(ep, "value", str(ep)),
                    "enabled": allow is None or ep.name in allow,
                })
        except Exception:
            continue
    return {"plugins": out, "allowlist_active": allow is not None}


@router.get("/mcp")
async def list_mcp_servers() -> dict:
    """Configured MCP servers from ~/.maverick/config.toml."""
    try:
        from maverick.config import load_config
        cfg = (load_config() or {}).get("mcp_servers") or {}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"config read failed: {e}")
    return {
        "servers": [
            {"name": name, "command": s.get("command"), "args": s.get("args", [])}
            for name, s in cfg.items()
        ],
    }


@router.get("/tools")
async def list_tools() -> dict:
    """Tools the agent currently has registered (post-ACL, post-rate-limit)."""
    try:
        from maverick.sandbox import build_sandbox
        from maverick.tools import base_registry
        from maverick.world_model import DEFAULT_DB, WorldModel
        wm = WorldModel(DEFAULT_DB)
        sb = build_sandbox()
        reg = base_registry(world=wm, sandbox=sb)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"registry build failed: {e}")
    return {
        "tools": [
            {"name": t.name, "description": (t.description or "")[:200]}
            for t in reg.all()
        ],
    }


@router.get("/channels")
async def list_channels() -> dict:
    """Enabled channels from ~/.maverick/config.toml."""
    try:
        from maverick.config import load_config
        cfg = (load_config() or {}).get("channels") or {}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"config read failed: {e}")
    return {
        "channels": [
            {"name": name, "enabled": bool(c.get("enabled", True))}
            for name, c in cfg.items()
        ],
    }


@router.get("/audit/tail")
async def audit_tail(n: int = 100, day: str | None = None) -> dict:
    """Tail the audit log (NDJSON at ~/.maverick/audit/YYYY-MM-DD.ndjson)."""
    from maverick.audit import default_audit_log

    from maverick_dashboard.app import safe_audit_day
    n = max(1, min(int(n or 100), 1000))
    return {"events": default_audit_log().tail(n, day=safe_audit_day(day))}


@router.get("/audit/grep")
async def audit_grep(pattern: str, day: str | None = None) -> dict:
    """Search recent audit events for the given literal pattern.

    Intentionally uses bounded, literal (case-insensitive) matching rather
    than a user-supplied regex: a regex over the HTTP surface invites
    catastrophic-backtracking ReDoS that blocks the dashboard event loop.
    Bounds the scan to the most recent 1000 events and caps results at 200.
    """
    if not pattern:
        raise HTTPException(status_code=400, detail="pattern is required")
    if len(pattern) > 200:
        raise HTTPException(status_code=400, detail="pattern too long")
    from maverick.audit import default_audit_log

    from maverick_dashboard.app import safe_audit_day
    events = default_audit_log().tail(1000, day=safe_audit_day(day))
    needle = pattern.lower()
    matches = [
        e for e in events
        if needle in json.dumps(e, ensure_ascii=False).lower()
    ]
    return {"events": matches[:200]}


@router.get("/permissions")
async def permissions() -> dict:
    """Everything the agent is currently allowed to do (read-only)."""
    from maverick_dashboard.app import _permissions_snapshot
    return _permissions_snapshot()


@router.post("/permissions/tools/{name}/disable", status_code=204)
async def disable_tool(name: str) -> None:
    """Disable a tool via the dashboard runtime overlay.

    Writes ~/.maverick/runtime-overrides.toml (NOT config.toml), which
    the kernel unions into the deny-list. Takes effect on the next goal
    with no restart.
    """
    from maverick.runtime_overrides import disable_tool as _disable
    try:
        _disable(name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/permissions/tools/{name}/enable", status_code=204)
async def enable_tool(name: str) -> None:
    """Clear a dashboard-set tool override.

    Only clears overrides set here; a tool denied in config.toml itself
    stays denied (the response is still 204 — the overlay no longer
    denies it, config does).
    """
    from maverick.runtime_overrides import enable_tool as _enable
    try:
        _enable(name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/approvals")
async def list_approvals() -> dict:
    """Pending high-risk actions parked by safety.consent (dashboard mode)."""
    w = _world()
    return {
        "approvals": [
            {
                "id": a.id, "action": a.action, "risk": a.risk,
                "scope": a.scope, "detail": a.detail,
                "requested_at": a.requested_at,
                # Collaborative supervision: who is handling this review.
                "claimed_by": getattr(a, "claimed_by", None),
                "claimed_at": getattr(a, "claimed_at", None),
            }
            for a in w.pending_approvals()
        ],
    }


def _supervisor(request: Request) -> str:
    """The acting supervisor's identity for claims/attribution.

    The authenticated principal when auth is on; the shared "operator"
    identity in single-user/no-auth deployments (claims still prevent
    double-handling across that operator's browser tabs)."""
    from .auth import caller_principal
    return caller_principal(request) or "operator"


@router.post("/approvals/{approval_id}/approve", status_code=204)
async def approve_approval(request: Request, approval_id: int) -> None:
    """Approve a parked action; the polling consent path then proceeds."""
    if not _world().decide_approval(approval_id, "approved",
                                    decided_by=_supervisor(request)):
        raise HTTPException(status_code=404, detail="no such pending approval")


@router.post("/approvals/{approval_id}/deny", status_code=204)
async def deny_approval(request: Request, approval_id: int) -> None:
    """Deny a parked action; the polling consent path then refuses it."""
    if not _world().decide_approval(approval_id, "denied",
                                    decided_by=_supervisor(request)):
        raise HTTPException(status_code=404, detail="no such pending approval")


@router.post("/approvals/{approval_id}/claim")
async def claim_approval(request: Request, approval_id: int) -> dict:
    """Claim a pending approval (collaborative supervision).

    Marks "I'm handling this" so two supervisors don't double-work the same
    review. 409 when another supervisor already holds the claim."""
    who = _supervisor(request)
    if _world().claim_approval(approval_id, who):
        return {"claimed_by": who}
    a = _world().get_approval(approval_id)
    if a is None or a.status != "pending":
        raise HTTPException(status_code=404, detail="no such pending approval")
    raise HTTPException(status_code=409,
                        detail=f"already claimed by {a.claimed_by}")


@router.post("/approvals/{approval_id}/release")
async def release_approval(request: Request, approval_id: int) -> dict:
    """Release a claim you hold. 409 when you don't hold it."""
    who = _supervisor(request)
    if _world().release_approval(approval_id, who):
        return {"released": True}
    raise HTTPException(status_code=409, detail="you do not hold this claim")


@router.get("/oversight/active")
async def oversight_active(request: Request) -> dict:
    """Active agents right now: running goals + their latest activity.

    Owner-scoped (auth-off/admin -> all). Powers the live "Active now" panel on
    the oversight console -- polled client-side so the operator watches the
    fleet work without a full-page reload. Fail-soft per goal: a goal whose
    event tail can't be read still lists with an empty activity.
    """
    from maverick.world_model import _dec_field
    w = _world()
    goals = w.list_goals(
        status="active", owner=goal_owner_filter(request), limit=50, order="desc",
    )
    out = []
    for g in goals:
        activity = ""
        updated_at = g.updated_at
        try:
            row = w.conn.execute(
                "SELECT kind, content, ts FROM goal_events WHERE goal_id = ? "
                "ORDER BY id DESC LIMIT 1",
                (g.id,),
            ).fetchone()
            if row:
                # content is sealed at rest -> decode (no-op when encryption off);
                # kind is stored plain.
                content = (_dec_field(row[1]) or "")[:120]
                activity = f"{row[0] or ''}: {content}".strip(": ").strip()
                updated_at = row[2]
        except Exception:
            activity = ""
            updated_at = g.updated_at
        out.append({
            "id": g.id, "title": g.title, "status": g.status,
            "updated_at": updated_at, "activity": activity,
        })
    return {"goals": out}


@router.get("/oversight/why/{goal_id}")
async def oversight_why(request: Request, goal_id: int, limit: int = 40) -> dict:
    """Explain *why* an agent is doing what it's doing — the governance drill-down.

    For one goal: status, cost-so-far, a by-kind summary, and the most-recent
    event chain (plan → tool → decision) that led here, so a supervisor can
    answer "why is this agent acting / why is this approval being requested"
    inline on the oversight console without hopping to the trajectory page.
    Owner-scoped via ``assert_goal_access``; fail-soft on cost so a spend-read
    error never 500s the drill-down.
    """
    from collections import Counter

    w = _world()
    g = w.get_goal(goal_id)
    if g is None:
        raise HTTPException(status_code=404, detail="no such goal")
    assert_goal_access(request, g)
    limit = max(1, min(limit, 200))
    events = w.recent_goal_events(goal_id, limit=limit)
    by_kind: Counter = Counter(e.kind for e in events)
    cost = 0.0
    try:
        cost = sum(ep.cost_dollars for ep in w.list_episodes(goal_id=goal_id, limit=200))
    except Exception:  # pragma: no cover -- cost is best-effort, never blocks
        cost = 0.0
    return {
        "goal_id": goal_id,
        "title": g.title,
        "status": g.status,
        "result": g.result,
        "cost_dollars": round(cost, 4),
        "summary": dict(by_kind),
        "events": [
            {"id": e.id, "agent": e.agent, "kind": e.kind,
             "content": (e.content or "")[:400], "ts": e.ts}
            for e in events
        ],
    }


@router.get("/fleets")
async def list_fleets_api(request: Request) -> dict:
    """The operator console roster: each fleet, its owner, and its agents.

    Read-only mirror of the ``/fleets`` page (Layer C of the enterprise control
    plane). Fail-soft to an empty list so a missing registry never 500s.

    Owner-scoped: a non-admin authenticated caller sees only the fleets they
    own; auth-off and admin callers see all (``goal_owner_filter`` returns None).
    """
    try:
        from maverick.fleet import list_fleets
        fleets = list_fleets()
    except Exception:
        fleets = []
    owner = goal_owner_filter(request)
    if owner is not None:
        fleets = [f for f in fleets if f.owner == owner]
    return {"fleets": [f.to_dict() for f in fleets]}


class FleetRunIn(BaseModel):
    agent: str = Field(..., max_length=64)
    prompt: str = Field(..., max_length=8000)
    max_dollars: float | None = Field(None, ge=0.0, le=100.0)


@router.post("/fleets/{fleet_name}/run", status_code=201)
async def run_fleet_agent(
    request: Request, fleet_name: str, payload: FleetRunIn, bg: BackgroundTasks,
) -> dict:
    """Dispatch a governed goal AS a fleet agent, from the operator console.

    The agent runs least-privileged under both its RBAC role's capability and
    the dispatching user's capability, while keeping its own audit principal
    (``agent:<fleet>.<agent>``), so the oversight control plane
    governs the work automatically (mirrors ``maverick fleet run``). Owner-scoped:
    only the fleet's owner -- or an admin / auth-off caller -- may dispatch; a
    cross-owner (or missing) fleet 404s, never revealing existence.
    """
    if not _any_provider_key_set():
        raise HTTPException(
            status_code=400,
            detail="No LLM provider key configured (run 'maverick init').",
        )
    from maverick_dashboard.app import check_goal_rate_limit
    check_goal_rate_limit(request)

    from maverick.capability import (
        UnknownRoleError,
        capability_for_role,
        capability_from_config,
    )
    from maverick.fleet import load_fleet, record_run
    from maverick.runner import run_goal_in_thread

    fleet = load_fleet(fleet_name)
    principal = caller_principal(request)
    is_admin = principal is not None and is_dashboard_admin(principal)
    if fleet is None or (
        principal is not None
        and not is_admin
        and fleet.owner != principal
    ):
        raise HTTPException(status_code=404, detail="no such fleet")
    agent = next((a for a in fleet.agents if a.name == payload.agent), None)
    if agent is None:
        raise HTTPException(status_code=404, detail="no such agent in fleet")
    prompt = (payload.prompt or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is required")

    agent_principal = fleet.principal_for(agent.name)
    try:
        cap = capability_for_role(agent.role, principal=agent_principal)
    except UnknownRoleError:
        # A saved fleet may carry an undefined/empty role (created before role
        # validation, or with RBAC roles opt-out). The CLI rejects these at
        # `fleet create`, but the dashboard run endpoint stays lenient so a
        # previously-runnable fleet keeps working: fall back to the base grant,
        # which is attenuated to the caller below -- a non-admin can therefore
        # never exceed their own capability. (capability_for_role was made
        # strict in #931, which otherwise 500s this legacy path.)
        cap = capability_from_config(agent_principal, user_id=agent_principal)
    if principal is not None and not is_admin:
        caller_cap = capability_from_config(principal, user_id=principal)
        cap = cap.attenuate(
            allow=caller_cap.allow_tools or None,
            deny=caller_cap.deny_tools,
            max_risk=caller_cap.max_risk,
            allow_paths=caller_cap.allow_paths or None,
            allow_hosts=caller_cap.allow_hosts or None,
        )
    max_dollars = (
        min(payload.max_dollars, DEFAULT_MAX_DOLLARS)
        if payload.max_dollars is not None else DEFAULT_MAX_DOLLARS
    )

    w = _world()
    goal_id = w.create_goal(prompt[:200], prompt, owner=fleet.owner)
    record_run(fleet_name, agent.name, goal_id)
    bg.add_task(
        run_goal_in_thread, goal_id, max_dollars,
        channel="fleet", user_id=agent_principal, capability=cap,
    )
    return {"goal_id": goal_id, "principal": agent_principal, "role": agent.role}


class FleetAgentIn(BaseModel):
    name: str = Field(..., max_length=64)
    role: str = Field("", max_length=64)
    description: str = Field("", max_length=500)


class FleetCreateIn(BaseModel):
    name: str = Field(..., max_length=64)
    agents: list[FleetAgentIn] = Field(default_factory=list)


@router.post("/fleets", status_code=201)
async def create_fleet(request: Request, payload: FleetCreateIn) -> dict:
    """Create (or replace) a fleet from the operator console, owned by the caller.

    Mirrors ``maverick fleet create`` so a non-technical operator never needs the
    CLI. Owner-scoped: replacing a fleet owned by someone else 404s (never
    reveals it). Blank agent rows are dropped; each agent needs a valid name
    and a configured RBAC role when roles are configured.
    """
    from maverick.capability import configured_roles
    from maverick.fleet import Fleet, FleetAgent, load_fleet, save_fleet, valid_name

    if not valid_name(payload.name):
        raise HTTPException(status_code=400, detail="invalid fleet name")
    agents = tuple(
        FleetAgent(
            name=a.name.strip(), role=a.role.strip(), description=a.description.strip(),
        )
        for a in payload.agents if a.name.strip()
    )
    configured = configured_roles()
    for a in agents:
        if not valid_name(a.name):
            raise HTTPException(status_code=400, detail=f"invalid agent name: {a.name!r}")
        if not a.role:
            raise HTTPException(status_code=400, detail=f"missing role for agent: {a.name!r}")
        if configured and a.role not in configured:
            raise HTTPException(status_code=400, detail=f"unknown role for agent: {a.name!r}")

    principal = caller_principal(request)
    owner = principal or ""
    existing = load_fleet(payload.name)
    if (
        existing is not None and existing.owner != owner
        and principal is not None and not is_dashboard_admin(principal)
    ):
        raise HTTPException(status_code=404, detail="no such fleet")

    try:
        save_fleet(Fleet(name=payload.name, owner=owner, agents=agents))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"fleet": load_fleet(payload.name).to_dict()}


@router.delete("/fleets/{fleet_name}", status_code=204)
async def delete_fleet(request: Request, fleet_name: str) -> None:
    """Remove a fleet. Owner-scoped: a cross-owner or missing fleet 404s."""
    from maverick.fleet import load_fleet, remove_fleet

    fleet = load_fleet(fleet_name)
    principal = caller_principal(request)
    is_admin = principal is not None and is_dashboard_admin(principal)
    if fleet is None or (
        principal is not None
        and not is_admin
        and fleet.owner != principal
    ):
        raise HTTPException(status_code=404, detail="no such fleet")
    remove_fleet(fleet_name)


def _compliance_checks(framework: str):
    """Run the core control-coverage report, filtered like the CLI.

    Single source of truth for the /compliance page and these exports:
    ``maverick.compliance.compliance_report()`` (GDPR + EU AI Act + US
    frameworks). ``framework`` is one of ``eu``/``us``/``all``; anything else
    falls back to ``all``. Fail-soft to an empty list so a missing core install
    yields an empty (still-downloadable) report rather than a 500.
    """
    framework = framework if framework in {"eu", "us", "all"} else "all"
    try:
        from maverick.compliance import compliance_report
        checks = compliance_report()
    except Exception:  # pragma: no cover - never 500 the export if core is absent
        return framework, []
    if framework != "all":
        checks = [c for c in checks if c.framework == framework]
    return framework, checks


@router.get("/compliance/report.md")
async def compliance_report_md(framework: str = "all") -> Response:
    """Download the control-coverage report as Markdown for an auditor.

    Same data as the /compliance page (``maverick.compliance``). The
    ``?framework=eu|us|all`` filter mirrors ``maverick compliance``. Returned as
    an attachment so an operator can hand the file to an auditor.
    """
    from maverick.compliance import render_report_text
    framework, checks = _compliance_checks(framework)
    body = render_report_text(checks)
    fname = f"maverick-compliance-{framework}.md"
    return Response(
        content=body,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/compliance/report.csv")
async def compliance_report_csv(framework: str = "all") -> Response:
    """Download the control-coverage report as CSV for an auditor.

    Same data source + ``?framework=`` filter as ``report.md``. One row per
    control: framework, control, regulation, status, detail.
    """
    import csv
    import io as _io

    from maverick.compliance import COMPLIANCE_DISCLAIMER
    framework, checks = _compliance_checks(framework)
    buf = _io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["framework", "control", "regulation", "status", "detail"])
    for c in checks:
        writer.writerow([c.framework, c.control, c.regulation, c.status, c.detail])
    writer.writerow([])
    writer.writerow(["disclaimer", COMPLIANCE_DISCLAIMER])
    fname = f"maverick-compliance-{framework}.csv"
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


class RedactIn(BaseModel):
    text: str = Field(max_length=200_000)
    kinds: list[str] = Field(default_factory=list)  # empty = all kinds


@router.post("/redact/preview")
async def redact_preview(payload: RedactIn) -> dict:
    """Granular redaction preview: per-finding spans + kinds, nothing stored.

    ``kinds`` filters which detector classes to act on (e.g. only
    ``secret:*`` or only ``pii:email``) — the granular half; empty = all.
    The response carries each finding (kind + a safe preview of WHERE, never
    the raw value) and the fully-redacted text for the selected kinds.
    """
    from maverick.provable_redaction import redact_proven, verify_redacted
    from maverick.safety import pii_detector, secret_detector

    text = payload.text or ""
    findings = []
    for m in secret_detector.scan(text):
        findings.append({"kind": f"secret:{m.name}", "span": list(m.span)})
    for m in pii_detector.scan(text):
        findings.append({"kind": f"pii:{m.kind}", "span": list(m.span)})
    selected = set(payload.kinds or [])

    if not selected:
        proof = redact_proven(text)
        redacted, proven = proof.redacted, proof.proven
    else:
        # granular: replace only the selected kinds' spans (end-to-start)
        spans = [f for f in findings if f["kind"] in selected]
        redacted = text
        for f in sorted(spans, key=lambda f: f["span"][0], reverse=True):
            a, b = f["span"]
            redacted = redacted[:a] + f"[REDACTED:{f['kind'].split(':', 1)[1]}]" + redacted[b:]
        proven = not verify_redacted(redacted)

    return {
        "findings": findings,
        "redacted": redacted,
        "proven_clean": proven,
        "residual": verify_redacted(redacted),
    }


@router.get("/glance")
async def watch_glance() -> dict:
    """The Apple Watch glance payload (tiny fixed shape; see maverick.glance)."""
    from maverick.glance import build_glance
    from maverick.world_model import open_world
    world = open_world()
    try:
        return build_glance(world)
    finally:
        try:
            world.close()
        except Exception:
            pass


@router.get("/offline/bundle")
async def offline_bundle(request: Request) -> dict:
    """Bounded, versioned snapshot (``maverick-offline/1``) for the mobile
    companion's offline cache. Read-only; owner-scoped like ``/goals``."""
    from maverick.offline_bundle import build_bundle
    return await run_in_threadpool(
        build_bundle, _world(), owner=goal_owner_filter(request),
    )


@router.get("/perf")
async def perf_dashboard() -> dict:
    """Public perf dashboard data: SLA measurements + benchmark history.

    One JSON face for the perf story (roadmap 2027-H1 "public perf
    dashboard"): the live perf-SLA measurements against their published
    thresholds (docs/perf-sla.md), the recorded benchmark score history with
    short-window regression verdicts, and the longitudinal era retrospective.
    Everything is measured/read locally -- nothing fabricated; sections with
    no recorded data say so.
    """
    out: dict = {"sla": [], "benchmarks": {}, "retrospective": None}
    try:
        import asyncio

        from maverick.perf_sla import run_all
        # run_all's dispatch probe drives its own event loop; run it in a
        # worker thread so it never nests inside the server's running loop.
        results = await asyncio.to_thread(run_all)
        out["sla"] = [
            {"name": r.name, "measured": r.measured, "threshold": r.threshold,
             "unit": r.unit, "passed": r.passed}
            for r in results
        ]
    except Exception as e:  # measurement must never 500 the dashboard
        out["sla_error"] = f"{type(e).__name__}: {e}"
    try:
        import json as _json

        from maverick.benchmark_retrospective import analyze, coverage
        from maverick.continuous_benchmark import _store_path, detect_regression
        store = _store_path()
        history: list[dict] = []
        if store.is_dir():
            for f in sorted(store.glob("*.json")):
                try:
                    rows = _json.loads(f.read_text(encoding="utf-8"))
                    if isinstance(rows, list):
                        history.extend(r for r in rows if isinstance(r, dict))
                except (OSError, ValueError):
                    continue
        names = sorted({r.get("name") for r in history if r.get("name")})
        for name in names:
            scores = [r["score"] for r in history if r.get("name") == name]
            verdict = detect_regression(history, name)
            out["benchmarks"][name] = {
                "runs": len(scores),
                "latest": scores[-1] if scores else None,
                "best": max(scores) if scores else None,
                "regression": verdict,
            }
        span = coverage(history)
        if span:
            retros = analyze(history)
            out["retrospective"] = {
                "coverage": list(span),
                "trends": {n: {"trend": r.trend,
                               "net_change": round(r.net_change, 4)}
                           for n, r in retros.items()},
            }
    except Exception as e:
        out["benchmarks_error"] = f"{type(e).__name__}: {e}"
    return out


@router.get("/cache/stats")
async def cache_stats() -> dict:
    """In-process cache sizes (file reads, repo-map, skill embeddings).

    Mirrors ``maverick cache stats`` — surfaced here so the dashboard
    Cache page can render without shelling out.
    """
    from maverick.cache import stats
    return stats()


class CachePurgeIn(BaseModel):
    scopes: list[str] = Field(default_factory=lambda: ["all"])


@router.post("/cache/purge")
async def cache_purge(payload: CachePurgeIn) -> dict:
    """Purge one or more cache scopes.

    Valid scopes (from maverick.cache._VALID_SCOPES): files, repo_map,
    skill_embeddings, all. Unknown scopes are ignored.
    """
    from maverick.cache import purge
    return purge(payload.scopes or ["all"])


# ---------- goal graph: forest view + structural edits (graph editor) ----------


@router.get("/goal-tree")
async def goal_tree_api(request: Request, limit: int = 300) -> dict:
    """The caller's goal forest with a server-computed layered layout.

    Powers /graph-editor and /plan-tree-3d: nodes carry (x, y) pixel
    positions so the client JS is a thin renderer. Owner-scoped like
    GET /goals (auth-off/admin see all).
    """
    from .goal_tree import forest_view, goal_nodes
    nodes = goal_nodes(_world(), owner=goal_owner_filter(request), limit=limit)
    return forest_view(nodes)


class RetitleIn(BaseModel):
    title: str = Field(..., max_length=200)


@router.post("/goals/{goal_id}/retitle", status_code=204)
async def retitle_goal(request: Request, goal_id: int, payload: RetitleIn) -> None:
    """Rename a goal (graph editor).

    The world model has no title-update method (``create_goal`` /
    ``set_goal_status`` only), so this updates the row through the world's
    write lock, sealing the column the same way ``create_goal`` does.
    """
    w = _world()
    g = w.get_goal(goal_id)
    if g is None:
        raise HTTPException(status_code=404, detail="no such goal")
    assert_goal_access(request, g)
    title = (payload.title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="title is required")
    from maverick.world_model import _enc_field
    with w._writing() as conn:
        conn.execute(
            "UPDATE goals SET title = ?, updated_at = ? WHERE id = ?",
            (_enc_field(title[:200]), time.time(), goal_id),
        )


class ReparentIn(BaseModel):
    parent_id: int | None = None


@router.post("/goals/{goal_id}/reparent", status_code=204)
async def reparent_goal(request: Request, goal_id: int, payload: ReparentIn) -> None:
    """Move a goal under a new parent — or to the root (``parent_id: null``).

    Refuses self-parenting and any move that would create a cycle (the new
    parent being a descendant of the goal). Both ends are access-checked.
    """
    w = _world()
    g = w.get_goal(goal_id)
    if g is None:
        raise HTTPException(status_code=404, detail="no such goal")
    assert_goal_access(request, g)
    new_parent = payload.parent_id
    if new_parent is not None:
        if new_parent == goal_id:
            raise HTTPException(status_code=400, detail="a goal cannot be its own parent")
        p = w.get_goal(new_parent)
        if p is None:
            raise HTTPException(status_code=404, detail="no such parent goal")
        assert_goal_access(request, p)
        from .goal_tree import descendant_ids
        pairs = [
            (r["id"], r["parent_id"])
            for r in w._read_all("SELECT id, parent_id FROM goals")
        ]
        if new_parent in descendant_ids(pairs, goal_id):
            raise HTTPException(
                status_code=400,
                detail="cannot re-parent a goal under its own descendant",
            )
    with w._writing() as conn:
        conn.execute(
            "UPDATE goals SET parent_id = ?, updated_at = ? WHERE id = ?",
            (new_parent, time.time(), goal_id),
        )


class ChildIn(BaseModel):
    title: str = Field(..., max_length=200)
    description: str = ""


@router.post("/goals/{goal_id}/children", response_model=GoalOut, status_code=201)
async def create_child_goal(request: Request, goal_id: int, payload: ChildIn) -> GoalOut:
    """Create a child goal under ``goal_id`` (graph editor "add child").

    Structural only: the child is created ``pending`` and is NOT queued to
    run — start it later via chat or POST /api/v1/goals. It inherits the
    parent's owner so the subtree stays visible to the same principal.
    """
    w = _world()
    g = w.get_goal(goal_id)
    if g is None:
        raise HTTPException(status_code=404, detail="no such goal")
    assert_goal_access(request, g)
    from maverick_dashboard.app import check_goal_rate_limit
    check_goal_rate_limit(request)
    title = (payload.title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="title is required")
    child_id = w.create_goal(
        title[:200], (payload.description or "")[:8000],
        parent_id=goal_id, owner=g.owner or (caller_principal(request) or ""),
    )
    c = w.get_goal(child_id)
    if c is None:
        raise HTTPException(status_code=500, detail="goal vanished after create")
    return _to_goal_out(c)


# ---------- goal builder: compose a goal from blocks ----------

_COMPOSE_PRIORITIES = ("low", "normal", "high")


class ComposeIn(BaseModel):
    title: str = Field(..., max_length=200)
    steps: list[str] = Field(default_factory=list)
    budget_dollars: float | None = Field(None, ge=0.0, le=100.0)
    channel: str | None = Field(None, max_length=64)
    priority: str | None = Field(None, max_length=16)


@router.post("/goals/compose", response_model=GoalOut, status_code=201)
async def compose_goal(request: Request, payload: ComposeIn, bg: BackgroundTasks) -> GoalOut:
    """Goal-builder submit: blocks -> structured brief -> create + run.

    The goals table has no metadata columns (see ``WorldModel.create_goal``),
    so the budget/channel/priority blocks are folded into the description the
    agent reads; the budget block additionally becomes the run's real
    ``max_dollars`` cap. Steps become a markdown checklist.
    """
    if not _any_provider_key_set():
        raise HTTPException(
            status_code=400,
            detail=(
                "No LLM provider key or endpoint configured. Run 'maverick "
                "init', export ANTHROPIC_API_KEY / OPENAI_API_KEY / "
                "GEMINI_API_KEY, or add a [providers.<name>] api_key/base_url "
                "to ~/.maverick/config.toml before starting the dashboard."
            ),
        )
    from maverick_dashboard.app import check_goal_rate_limit
    check_goal_rate_limit(request)
    title = (payload.title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="title is required")
    steps = [s.strip()[:500] for s in payload.steps if s and s.strip()]
    if len(steps) > 50:
        raise HTTPException(status_code=400, detail="too many steps (max 50)")
    priority = (payload.priority or "").strip().lower() or None
    if priority is not None and priority not in _COMPOSE_PRIORITIES:
        raise HTTPException(
            status_code=400,
            detail=f"priority must be one of: {', '.join(_COMPOSE_PRIORITIES)}",
        )
    channel = (payload.channel or "").strip() or None

    parts: list[str] = []
    if steps:
        parts.append("## Steps\n" + "\n".join(f"- [ ] {s}" for s in steps))
    meta: list[str] = []
    if payload.budget_dollars is not None:
        meta.append(
            f"Budget cap: ${payload.budget_dollars:.2f} "
            "(also enforced as the run's max_dollars)"
        )
    if channel:
        meta.append(f"Announce progress on: {channel}")
    if priority:
        meta.append(f"Priority: {priority}")
    if meta:
        parts.append("\n".join(meta))
    description = "\n\n".join(parts) if parts else title

    w = _world()
    goal_id = w.create_goal(
        title[:200], description[:8000], owner=caller_principal(request) or "",
    )
    from maverick.runner import run_goal_in_thread
    max_dollars = (
        min(payload.budget_dollars, DEFAULT_MAX_DOLLARS)
        if payload.budget_dollars is not None else DEFAULT_MAX_DOLLARS
    )
    user_id = execution_user_id_from_request(request)
    if user_id:
        bg.add_task(run_goal_in_thread, goal_id, max_dollars,
                    channel="api", user_id=user_id)
    else:
        bg.add_task(run_goal_in_thread, goal_id, max_dollars)
    g = w.get_goal(goal_id)
    if g is None:
        raise HTTPException(status_code=500, detail="goal vanished after create")
    return _to_goal_out(g)


# ---------- continuous-benchmark history ----------


def _benchmark_snapshot() -> dict:
    """Recorded benchmark runs, grouped per suite, with regression verdicts.

    Reads the same store ``maverick.continuous_benchmark`` (the bench_track
    tool) persists to — this deployment's own recorded runs, nothing else.
    Malformed rows (hand-edited file) are skipped, not invented around.
    """
    from maverick import continuous_benchmark as cb
    path = cb._store_path()
    history: list[dict] = []
    for h in cb.load_history(path):
        if not isinstance(h, dict) or not h.get("name"):
            continue
        try:
            score = float(h.get("score"))
        except (TypeError, ValueError):
            continue
        history.append({"name": str(h["name"]), "score": score,
                        "commit": str(h.get("commit") or ""), "t": h.get("t")})
    names: list[str] = []
    for h in history:
        if h["name"] not in names:
            names.append(h["name"])
    suites = []
    for name in names:
        entries = [h for h in history if h["name"] == name]
        r = cb.detect_regression(history, name)
        suites.append({
            "name": name,
            "runs": len(entries),
            "entries": entries[-50:],
            "latest": r["latest"],
            "baseline_mean": r["baseline_mean"],
            "delta": r["delta"],
            "drop_pct": r["drop_pct"],
            "regressed": r["regressed"],
        })
    return {"suites": suites, "history_path": str(path)}


@router.get("/benchmarks")
async def benchmarks_api() -> dict:
    """Benchmark history for this deployment (see ``_benchmark_snapshot``)."""
    snap = _benchmark_snapshot()
    if not snap["suites"]:
        snap["note"] = (
            "no benchmark runs recorded — record one with the bench_track "
            "tool (op=record, name, score) or "
            "maverick.continuous_benchmark.record_result"
        )
    return snap


# ---------- walkthrough export (replay video into the walkthroughs dir) ----------


def _walkthroughs_dir():
    """Where the dashboard's exported walkthrough videos live.

    ``maverick.replay_video.render`` writes wherever the caller points it
    (there is no fixed dir in core), so the dashboard standardises on
    ``<maverick home>/walkthroughs`` for everything the /walkthroughs page
    lists and serves.
    """
    from maverick.paths import maverick_home
    return maverick_home() / "walkthroughs"


def _vtt_for_frames(frames) -> str:
    """A WebVTT captions track derived from the storyboard frames.

    One cue per frame, timed by the frames' real durations; cue text is the
    frame's (already secret-scrubbed) caption, flattened to one line.
    """
    def ts(sec: float) -> str:
        ms = int(round(sec * 1000))
        h, rem = divmod(ms, 3_600_000)
        m, rem = divmod(rem, 60_000)
        s, ms = divmod(rem, 1000)
        return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"

    lines = ["WEBVTT", ""]
    t = 0.0
    for f in frames:
        end = t + f.seconds
        text = f"[{f.kind}] {f.caption}".replace("\n", " ").replace("-->", "→").strip()
        lines += [f"{ts(t)} --> {ts(end)}", text or "(no caption)", ""]
        t = end
    return "\n".join(lines)


@router.post("/goals/{goal_id}/walkthrough", status_code=201)
async def export_walkthrough(request: Request, goal_id: int) -> dict:
    """Export a run's replay video into the walkthroughs dir.

    Uses the real machinery (``maverick.replay_video.render``): always writes
    the frame manifest + a WebVTT captions track derived from the storyboard;
    the MP4 encode itself needs Pillow + ffmpeg and the response says honestly
    whether it happened (``encoded``/``detail``) and carries the exact ffmpeg
    command for out-of-band encoding when it didn't.
    """
    w = _world()
    g = w.get_goal(goal_id)
    if g is None:
        raise HTTPException(status_code=404, detail="no such goal")
    assert_goal_access(request, g)
    events = [
        {"kind": e.kind, "ts": e.ts, "agent": e.agent, "content": e.content}
        for e in w.goal_events(goal_id, limit=5000)
    ]
    if not events:
        raise HTTPException(
            status_code=400,
            detail="no events recorded for this goal — run it first, then export",
        )
    from maverick.replay_video import render, storyboard
    out_dir = _walkthroughs_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = storyboard(goal_id, events=events)
    vtt_name = f"goal-{goal_id}.vtt"
    (out_dir / vtt_name).write_text(_vtt_for_frames(frames), encoding="utf-8")
    try:
        from maverick.sandbox import build_sandbox
        sandbox = build_sandbox()
    except Exception:  # render falls back to the scrubbed-env runner
        sandbox = None
    out_path = out_dir / f"goal-{goal_id}.mp4"
    result = await run_in_threadpool(
        render, goal_id, out_path, sandbox=sandbox, events=events,
    )
    return {
        "goal_id": goal_id,
        "frames": result.frames,
        "encoded": result.encoded,
        "detail": result.detail,
        "video": out_path.name if result.encoded else None,
        "captions": vtt_name,
        "ffmpeg_command": result.command,
    }


@router.post("/goals/{goal_id}/resume", status_code=204)
async def resume_goal(goal_id: int, request: Request, bg: BackgroundTasks) -> None:
    """Resume a blocked / cancelled goal.

    Capabilities-seat finding: the CLI has ``maverick resume`` but the
    dashboard's only way to flip a cancelled goal back was to start a
    brand-new one. This route flips status back to 'pending' and
    re-queues the runner, so the next goal-event poll picks it back up.
    """
    w = _world()
    g = w.get_goal(goal_id)
    if g is None:
        raise HTTPException(status_code=404, detail="no such goal")
    assert_goal_access(request, g)
    # Block resuming things that have no parked work.
    if g.status not in ("blocked", "cancelled", "failed"):
        raise HTTPException(
            status_code=400,
            detail=f"goal is {g.status!r}; only blocked/cancelled/failed goals can resume",
        )
    w.set_goal_status(goal_id, "pending", result=None)
    from maverick.runner import run_goal_in_thread
    user_id = execution_user_id_from_request(request)
    if user_id:
        bg.add_task(run_goal_in_thread, goal_id, channel="api", user_id=user_id)
    else:
        bg.add_task(run_goal_in_thread, goal_id)
