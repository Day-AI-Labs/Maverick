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


def _world():
    from maverick.world_model import DEFAULT_DB, WorldModel
    return WorldModel(DEFAULT_DB)


def _to_goal_out(g) -> GoalOut:
    return GoalOut(
        id=g.id, status=g.status, title=g.title,
        description=g.description, result=g.result,
    )


@router.post("/goals", response_model=GoalOut, status_code=201)
async def create_goal(payload: GoalIn, bg: BackgroundTasks) -> GoalOut:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(
            status_code=400,
            detail="ANTHROPIC_API_KEY not set. Run `maverick init` first.",
        )
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
    w = _world()
    goals = w.list_goals(status=status)
    if offset:
        goals = goals[:-offset] if offset < len(goals) else []
    return [_to_goal_out(g) for g in goals[-limit:]]


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
    qs = w.open_questions(goal_id=goal_id)
    if not any(q.id == payload.question_id for q in qs):
        raise HTTPException(status_code=404, detail="no such open question for this goal")
    w.answer(payload.question_id, payload.answer)


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


@router.post("/skills", response_model=SkillOut, status_code=201)
async def install_skill_endpoint(payload: SkillInstallIn) -> SkillOut:
    from maverick.skills import install_skill
    try:
        s = install_skill(payload.source, trusted_local=False)
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
