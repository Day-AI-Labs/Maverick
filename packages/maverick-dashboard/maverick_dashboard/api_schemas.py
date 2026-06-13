"""Pydantic request/response models for the dashboard REST API.

Extracted verbatim from api.py to keep that module focused on routing.
Importing here changes no behavior: these are pure data schemas.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


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


class AttachmentOut(BaseModel):
    id: int
    filename: str
    mime: str
    size_bytes: int
    sha256: str


class CatalogInstallIn(BaseModel):
    name: str = Field(..., max_length=200)


class HaltIn(BaseModel):
    reason: str = Field("manual via dashboard", max_length=200)


class FleetRunIn(BaseModel):
    agent: str = Field(..., max_length=64)
    prompt: str = Field(..., max_length=8000)
    max_dollars: float | None = Field(None, ge=0.0, le=100.0)


class FleetAgentIn(BaseModel):
    name: str = Field(..., max_length=64)
    role: str = Field("", max_length=64)
    description: str = Field("", max_length=500)


class FleetCreateIn(BaseModel):
    name: str = Field(..., max_length=64)
    agents: list[FleetAgentIn] = Field(default_factory=list)


class RedactIn(BaseModel):
    text: str = Field(max_length=200_000)
    kinds: list[str] = Field(default_factory=list)  # empty = all kinds


class CachePurgeIn(BaseModel):
    scopes: list[str] = Field(default_factory=lambda: ["all"])


class RetitleIn(BaseModel):
    title: str = Field(..., max_length=200)


class ReparentIn(BaseModel):
    parent_id: int | None = None


class ChildIn(BaseModel):
    title: str = Field(..., max_length=200)
    description: str = ""


class ComposeIn(BaseModel):
    title: str = Field(..., max_length=200)
    steps: list[str] = Field(default_factory=list)
    budget_dollars: float | None = Field(None, ge=0.0, le=100.0)
    channel: str | None = Field(None, max_length=64)
    priority: str | None = Field(None, max_length=16)
