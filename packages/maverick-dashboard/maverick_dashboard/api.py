"""REST API for Maverick (mounted at /api/v1).

v0.1.6: BackgroundTask runner moved to maverick.runner.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from maverick.runner import (
    DEFAULT_MAX_DEPTH,
    DEFAULT_MAX_DOLLARS,
    DEFAULT_MAX_WALL_SECONDS,
)

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["v1"])


class GoalIn(BaseModel):
    title: str = Field(..., max_length=200)
    description: str = ""
    max_dollars: float = Field(5.0, ge=0.0, le=100.0)
    max_wall_seconds: float = Field(3600.0, ge=1.0, le=86400.0)
    max_depth: int = Field(3, ge=1, le=5)
    template: Optional[str] = None
    params: Optional[dict[str, str]] = None


class GoalOut(BaseModel):
    id: int
    status: str
    title: str
    description: Optional[str] = None
    result: Optional[str] = None


class GoalEventOut(BaseModel):
    id: int
    agent: str
    kind: str
    content: str
    ts: float


class GoalEventsResponse(BaseModel):
    status: str
    result: Optional[str]
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


_world_cache: dict[str, object] = {}


_PROVIDER_ENV_VARS = (
    "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY",
    "OPENROUTER_API_KEY", "MOONSHOT_API_KEY", "DEEPSEEK_API_KEY",
    "XAI_API_KEY",
)


def _any_provider_key_set() -> bool:
    """True iff at least one supported provider's env var is populated."""
    return any(os.environ.get(v) for v in _PROVIDER_ENV_VARS)


def _world():
    """Return a per-DB-path cached WorldModel (council perf fix).

    See ``maverick_dashboard.app._world`` for the rationale; both
    modules share the same cache pattern but keep their own dicts to
    avoid an import cycle.
    """
    from maverick.world_model import DEFAULT_DB, WorldModel
    key = str(DEFAULT_DB)
    cached = _world_cache.get(key)
    if cached is None:
        cached = WorldModel(DEFAULT_DB)
        _world_cache[key] = cached
    return cached


def _to_goal_out(g) -> GoalOut:
    return GoalOut(
        id=g.id, status=g.status, title=g.title,
        description=g.description, result=g.result,
    )


@router.post("/goals", response_model=GoalOut, status_code=201)
async def create_goal(payload: GoalIn, bg: BackgroundTasks) -> GoalOut:
    if not _any_provider_key_set():
        raise HTTPException(
            status_code=400,
            detail=(
                "No LLM provider key configured. Run 'maverick init', or "
                "export ANTHROPIC_API_KEY / OPENAI_API_KEY / "
                "GEMINI_API_KEY before starting the dashboard."
            ),
        )
    # Shared sliding-window cap across /chat/send + this route, so a
    # runaway loop can't spawn unbounded (paid) goals.
    from maverick_dashboard.app import check_goal_rate_limit
    check_goal_rate_limit()
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
    goal_id = w.create_goal(title[:200], description)
    from maverick.runner import run_goal_in_thread
    # Enforce server-side execution caps even when callers request larger values.
    max_dollars = min(payload.max_dollars, DEFAULT_MAX_DOLLARS)
    max_wall_seconds = min(payload.max_wall_seconds, DEFAULT_MAX_WALL_SECONDS)
    max_depth = min(payload.max_depth, DEFAULT_MAX_DEPTH)

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
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[GoalOut]:
    """List goals (newest first), paginated.

    Council perf fix: previous version pulled every goal ever into
    Python via ``list_goals()``, then sliced. Now the LIMIT/OFFSET are
    pushed to SQL.
    """
    w = _world()
    limit = max(1, min(int(limit or 50), 500))
    offset = max(0, int(offset or 0))
    goals = w.list_goals(status=status, limit=limit, offset=offset, order="desc")
    return [_to_goal_out(g) for g in goals]


@router.get("/goals/{goal_id}", response_model=GoalOut)
async def get_goal(goal_id: int) -> GoalOut:
    g = _world().get_goal(goal_id)
    if g is None:
        raise HTTPException(status_code=404, detail="no such goal")
    return _to_goal_out(g)


@router.get("/goals/{goal_id}/events", response_model=GoalEventsResponse)
async def goal_events(
    goal_id: int, since: int = 0, limit: int = 200,
) -> GoalEventsResponse:
    w = _world()
    g = w.get_goal(goal_id)
    if g is None:
        raise HTTPException(status_code=404, detail="no such goal")
    events = w.goal_events(goal_id, since_id=since, limit=limit)
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


@router.post("/goals/{goal_id}/answer", status_code=204)
async def answer_question(goal_id: int, payload: AnswerIn) -> None:
    w = _world()
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
async def upload_attachment(goal_id: int, file: UploadFile = File(...)) -> AttachmentOut:
    """Upload a file (text, image, or PDF) and attach it to a goal.

    Size and mime-type validation are enforced server-side; the agent's
    `list_attachments` tool exposes the uploaded set, and image
    attachments are auto-embedded as vision blocks on the first message.
    """
    w = _world()
    if w.get_goal(goal_id) is None:
        raise HTTPException(status_code=404, detail="no such goal")

    from maverick.attachments import (
        AttachmentRejected,
        MAX_FILE_BYTES,
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
async def list_goal_attachments(goal_id: int) -> list[AttachmentOut]:
    w = _world()
    if w.get_goal(goal_id) is None:
        raise HTTPException(status_code=404, detail="no such goal")
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
    _world().upsert_fact(payload.key, payload.value)


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
async def cancel_goal(goal_id: int) -> None:
    """Mark a goal as cancelled.

    The agent loop checks status at each tool-call boundary; setting
    'cancelled' here causes the next check to short-circuit the run.
    Already-done goals are a no-op.
    """
    w = _world()
    g = w.get_goal(goal_id)
    if g is None:
        raise HTTPException(status_code=404, detail="no such goal")
    if g.status in ("done", "cancelled", "failed"):
        return
    w.set_goal_status(goal_id, "cancelled", result="cancelled via dashboard")


@router.get("/goals/{goal_id}/open_questions")
async def goal_open_questions(goal_id: int) -> dict:
    """List unanswered questions an agent has parked for this goal."""
    w = _world()
    if w.get_goal(goal_id) is None:
        raise HTTPException(status_code=404, detail="no such goal")
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
        from maverick.plugins import _entry_points, _allowed_plugin_names
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
        from maverick.tools import base_registry
        from maverick.sandbox import build_sandbox
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
async def audit_tail(n: int = 100, day: Optional[str] = None) -> dict:
    """Tail the audit log (NDJSON at ~/.maverick/audit/YYYY-MM-DD.ndjson)."""
    from maverick.audit import default_audit_log
    n = max(1, min(int(n or 100), 1000))
    return {"events": default_audit_log().tail(n, day=day)}


@router.get("/audit/grep")
async def audit_grep(pattern: str, day: Optional[str] = None) -> dict:
    """Regex-search the audit log for the given day (default: today).

    Mirrors the CLI's ``maverick audit grep <pattern>`` — exists in the
    kernel as a method on AuditLog but had no HTTP surface before.
    """
    if not pattern:
        raise HTTPException(status_code=400, detail="pattern is required")
    if len(pattern) > 500:
        raise HTTPException(status_code=400, detail="pattern too long")
    try:
        import re
        re.compile(pattern)
    except re.error as e:
        raise HTTPException(status_code=400, detail=f"bad regex: {e}")
    from maverick.audit import default_audit_log
    return {"events": default_audit_log().grep(pattern, day=day)}


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


@router.post("/goals/{goal_id}/resume", status_code=204)
async def resume_goal(goal_id: int, bg: BackgroundTasks) -> None:
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
    # Block resuming things that have no parked work.
    if g.status not in ("blocked", "cancelled", "failed"):
        raise HTTPException(
            status_code=400,
            detail=f"goal is {g.status!r}; only blocked/cancelled/failed goals can resume",
        )
    w.set_goal_status(goal_id, "pending", result=None)
    from maverick.runner import run_goal_in_thread
    bg.add_task(run_goal_in_thread, goal_id)
