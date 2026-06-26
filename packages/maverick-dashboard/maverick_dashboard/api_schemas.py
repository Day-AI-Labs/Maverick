"""Pydantic request/response models for the dashboard REST API.

Extracted verbatim from api.py to keep that module focused on routing.
Importing here changes no behavior: these are pure data schemas.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class WorkflowStepIn(BaseModel):
    name: str = Field(..., max_length=80)
    instruction: str = ""
    tools: list[str] = Field(default_factory=list)
    gate: str | None = None


class AgentOverrideIn(BaseModel):
    """A tenant override patch for a domain pack (agent). Every field is
    optional: only the ones the client actually sets are persisted, so the
    pack inherits everything else from its built-in base. ``extends`` forks a
    base under a new name; omit it to customize the pack in place."""
    description: str | None = None
    persona: str | None = None
    allow_tools: list[str] | None = None
    deny_tools: list[str] | None = None
    max_risk: str | None = None
    knowledge_sources: list[str] | None = None
    models: dict[str, str] | None = None
    workflow: list[WorkflowStepIn] | None = None
    compartment: str | None = None
    extends: str | None = None


class SignoffIn(BaseModel):
    """A human's sign-off on a finished, gated deliverable -- the certify/reject
    decision the pack's output gate calls for, with an optional review note."""
    decision: str = Field(..., pattern="^(approved|rejected)$")
    note: str | None = Field(default=None, max_length=2000)


class RoleOverrideIn(BaseModel):
    """A per-tenant override for a core agent role: a system-prompt addendum
    appended to the role's base template, plus optional model/effort overrides
    that win over the global [models]/[effort] config. Empty fields clear; an
    all-empty patch clears the role's override."""
    system_addendum: str | None = None
    model: str | None = None
    effort: str | None = None


class GoalIn(BaseModel):
    title: str = Field(..., max_length=200)
    # Bound the description like the title: it flows into SQLite, the at-rest
    # seal, and every downstream prompt, so an unbounded value from an untrusted
    # REST caller is a cost / DB-bloat amplification vector. 16k chars is ample
    # for a goal brief; oversized payloads get a 422 rather than silent bloat.
    description: str = Field("", max_length=16000)
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


class ScheduleIn(BaseModel):
    """Arm a recurring run on a 5-field cron expression. Provide either a saved
    ``template`` (rendered with ``params`` each fire) or a raw ``text`` prompt.
    Executed by ``maverick worker`` as a ``start_goal`` job."""
    cron: str = Field(..., max_length=120)
    template: str | None = None
    params: dict[str, str] | None = None
    text: str | None = None
    title: str | None = Field(None, max_length=200)


class ScheduleOut(BaseModel):
    id: int
    cron: str
    kind: str
    title: str
    next_run: float
    # Stable across cron re-arms (the job id changes each occurrence); used to
    # group a schedule's run history. Empty for schedules armed before v15.
    schedule_id: str = ""


class ImportRunIn(BaseModel):
    """Import automations from an external platform into Lightwork templates.

    ``source`` is one of the registered importers (n8n/make/.../zapier). Provide
    ``definitions`` (exported definition JSON objects) for an offline/connect
    import, or omit it to live-fetch from the platform's API (server env creds).
    ``dry_run`` previews without writing; ``activate_schedules`` auto-creates
    schedules for recovered cron triggers; ``create_webhook_triggers`` wires an
    inbound webhook trigger for each webhook-triggered automation.
    """
    source: str = Field(..., max_length=40)
    definitions: list[dict] | None = Field(default=None, max_length=25)
    dry_run: bool = False
    activate_schedules: bool = False
    create_webhook_triggers: bool = False


class ImportResultOut(BaseModel):
    source: str
    name: str
    template: str
    created: bool
    trigger: str
    webhook_trigger: str | None = None
    schedule: dict | None = None
    tools: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ImportRunOut(BaseModel):
    imported: list[ImportResultOut]
    dry_run: bool
    webhook_url: str
    secret_configured: bool


class TriggerIn(BaseModel):
    """Bind a saved template to an inbound webhook. ``params`` are the operator's
    default values (baked at registration); an HMAC-signed POST to /webhook/run
    may override declared params at fire time. ``name`` defaults to the template
    name (slugified)."""
    template: str = Field(..., max_length=80)
    params: dict[str, str] | None = None
    name: str | None = Field(None, max_length=48)


class TriggerOut(BaseModel):
    name: str
    template: str
    params: dict[str, str] = Field(default_factory=dict)
    webhook_url: str
    secret_configured: bool


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


class OutcomeIn(BaseModel):
    """A real downstream outcome for a past episode (the Consequence Engine)."""
    goal_id: int
    episode_id: int
    value: float
    kind: str = ""


class AnswerIn(BaseModel):
    question_id: int
    answer: str


class SkillInstallIn(BaseModel):
    source: str = Field(..., description="https://... or gh:org/repo[:path]")


class SkillCreateIn(BaseModel):
    """Author a skill in the dashboard: a name, the trigger phrases that
    activate it, the tools it needs, and the instructions (markdown body)."""
    name: str = Field(..., max_length=80)
    instructions: str = Field(..., max_length=20000)
    triggers: list[str] = Field(default_factory=list)
    tools_needed: list[str] = Field(default_factory=list)


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


class WorkflowDraftIn(BaseModel):
    """Chat-path drafting: a natural-language brief. ``form`` selects the
    artifact — a reusable ``"template"`` (default) or an agent ``"playbook"``."""
    description: str = Field("", max_length=8000)
    form: str = Field("template", max_length=16)


class WorkflowRefineIn(BaseModel):
    """Refine an existing draft with a follow-up instruction. ``current`` is the
    draft as last shown/edited; ``form`` selects template vs playbook parsing."""
    form: str = Field("template", max_length=16)
    instruction: str = Field(..., max_length=2000)
    current: dict = Field(default_factory=dict)


class WorkflowSaveIn(BaseModel):
    """Persist an (AI-drafted, possibly edited) workflow as a user template."""
    name: str = Field(..., max_length=48)
    title: str = Field(..., max_length=200)
    body: str = Field(..., max_length=20000)
    params: list[str] = Field(default_factory=list)
    budget_dollars: float = Field(5.0, ge=0.0, le=100.0)
    budget_wall_seconds: float = Field(3600.0, ge=1.0, le=86400.0)


class TenantCreateIn(BaseModel):
    """Provision a new tenant (admin only)."""
    id: str = Field(..., max_length=128)
    plan: str = Field("free", pattern="^(free|pro|enterprise)$")
    display_name: str = Field("", max_length=200)
    max_daily_dollars: float = Field(0.0, ge=0.0)


class TenantPlanIn(BaseModel):
    plan: str = Field(..., pattern="^(free|pro|enterprise)$")


class TenantQuotaIn(BaseModel):
    max_daily_dollars: float = Field(..., ge=0.0)


class TenantOut(BaseModel):
    """A provisioned tenant. ``config_path`` is where to drop this tenant's own
    config.toml (its provider keys / model choices / budget overlay)."""
    id: str
    status: str
    plan: str
    display_name: str
    max_daily_dollars: float
    created_at: float
    updated_at: float
    config_path: str


class TenantRoleIn(BaseModel):
    """Grant a principal a role within one tenant (per-tenant RBAC)."""
    role: str = Field(..., pattern="^(admin|operator|auditor|viewer)$")
