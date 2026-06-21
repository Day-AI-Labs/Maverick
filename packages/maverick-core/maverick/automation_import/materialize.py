"""Map an :class:`~.ir.ImportedAutomation` onto Lightwork's existing primitives.

The actions become a signed user ``Template`` (so the whole run path -- render →
``create_goal`` → orchestrator, with budget guardrails -- is reused unchanged).
The trigger becomes either a cron **schedule** (created here via the core
``scheduler`` when a JobQueue is supplied) or a **webhook trigger** (which lives
in the dashboard's ``triggers_store``, so we don't create it here -- we return a
``suggested_trigger`` the CLI/dashboard wires up). Runs spawned later are tagged
through the existing ``goal_origins`` table by those trigger/schedule paths, so
imported automations appear in the Automations history automatically.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .ir import TRIGGER_SCHEDULE, TRIGGER_WEBHOOK, ImportedAutomation


@dataclass
class MaterializeResult:
    template_name: str
    title: str
    created_template: bool
    suggested_trigger: dict[str, Any] | None = None   # for webhook triggers
    schedule: dict[str, Any] | None = None            # {job_id, run_at, cron} if created
    tool_hints: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def materialize(
    automation: ImportedAutomation,
    *,
    save: bool = True,
    budget_dollars: float = 5.0,
    budget_wall_seconds: float = 3600.0,
    queue: Any | None = None,
    overwrite: bool = True,
) -> MaterializeResult:
    """Create the Template (and optionally a cron schedule) for one automation.

    ``queue`` (a ``maverick.job_queue.JobQueue``) enables auto-creating a cron
    schedule for ``schedule``-triggered automations whose cron we recovered.
    Webhook/event triggers are returned as ``suggested_trigger`` for the caller
    to wire (the webhook trigger store is a dashboard concern).
    """
    from ..templates import save_user_template

    title, body = automation.render()
    tname = automation.template_name()
    notes: list[str] = []

    created = False
    if save:
        save_user_template(
            tname,
            title=title,
            body=body,
            params=[],
            budget_dollars=float(budget_dollars),
            budget_wall_seconds=float(budget_wall_seconds),
            overwrite=overwrite,
        )
        created = True

    result = MaterializeResult(
        template_name=tname,
        title=title,
        created_template=created,
        tool_hints=automation.tool_hints(),
        notes=notes,
    )

    trig = automation.trigger
    if trig.kind == TRIGGER_SCHEDULE:
        if trig.cron and queue is not None:
            from uuid import uuid4

            from ..scheduler import CronError, schedule_cron
            # Match the dashboard /api/v1/schedules payload exactly: the worker's
            # start_goal handler mints a fresh goal from "text" on every fire and
            # requires it to be non-empty (a {"template": ...} payload would fail
            # at run time). We snapshot the rendered brief as the goal text, like
            # the dashboard does, and carry a schedule_id for run provenance.
            schedule_id = uuid4().hex
            payload = {
                "text": body,
                "title": title[:200],
                "__cron__": trig.cron,
                "schedule_id": schedule_id,
            }
            try:
                job_id, run_at = schedule_cron(queue, trig.cron, "start_goal", payload)
                result.schedule = {
                    "job_id": job_id, "run_at": run_at, "cron": trig.cron,
                    "schedule_id": schedule_id,
                }
            except CronError as e:
                notes.append(f"could not create schedule from cron {trig.cron!r}: {e}")
        elif trig.cron:
            result.suggested_trigger = {"kind": "schedule", "cron": trig.cron, "template": tname}
            notes.append("schedule recovered; pass a queue (or use the dashboard) to activate it")
        else:
            notes.append("source trigger is a schedule but no cron expression was recoverable; "
                         "set one when wiring the schedule")
    elif trig.kind in (TRIGGER_WEBHOOK,):
        result.suggested_trigger = {"kind": "webhook", "template": tname, "name": tname}
        notes.append("wire an inbound webhook trigger bound to this template "
                     "(dashboard Automations, or `maverick` trigger tooling)")
    else:
        result.suggested_trigger = {"kind": trig.kind, "template": tname, "name": tname,
                                    "event": f"{trig.app} {trig.event}".strip()}
        notes.append(f"source trigger ({trig.render()}) has no direct Lightwork equivalent; "
                     "bind the template to a webhook/schedule, or run it on demand")

    return result
