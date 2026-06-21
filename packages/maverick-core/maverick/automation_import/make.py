"""Make.com (Integromat) importer.

Make exposes a scenario's definition as a *blueprint* over its REST API
(``GET /api/v2/scenarios/{id}/blueprint`` -> ``{"response": {"blueprint":
{...}}}``). A blueprint is ``{name, flow[], metadata{}}`` where ``flow`` is the
ordered module list and each module is ``{id, module: "app:Operation",
parameters, mapper, metadata, routes?}``. The FIRST module is the trigger; the
rest are actions. Routers (``builtin:BasicRouter``) fan out into ``routes[].flow``
which we flatten in order (Lightwork runs the brief; branch fidelity is a
follow-on). Make schedules by interval/type in ``metadata.scheduling`` rather
than cron, so a scheduled scenario imports as a schedule trigger without an
auto-created cron (the operator sets the cadence when wiring it).

Single-tenant creds (env): ``MAKE_BASE_URL`` (e.g.
``https://eu1.make.com``) and ``MAKE_TOKEN`` (sent as ``Authorization: Token``).
"""
from __future__ import annotations

import os
from typing import Any

from .base import ImporterError, register
from .ir import (
    TRIGGER_EVENT,
    TRIGGER_SCHEDULE,
    TRIGGER_WEBHOOK,
    ImportedAutomation,
    ImportedStep,
    ImportedTrigger,
)

# Module-name fragments that mark the first module as a particular trigger kind.
_WEBHOOK_HINTS = ("customwebhook", "gateway", "webhook")
_SCHEDULE_HINTS = ("schedule", "clock", "timer")


def _split_module(module: str) -> tuple[str, str]:
    """``slack:CreateMessage`` -> ``("slack", "CreateMessage")``; a bare module
    name -> ``(name, "")``."""
    m = str(module or "")
    if ":" in m:
        app, _, op = m.partition(":")
        return app.strip(), op.strip()
    return m.strip(), ""


def _flatten_flow(flow: list) -> list[dict]:
    """Flatten a Make flow (with nested router ``routes[].flow``) to a flat,
    ordered module list. A router/filter is a control container with no action
    of its own -- skip the container, keep its branch modules in order."""
    out: list[dict] = []
    for mod in flow or []:
        if not isinstance(mod, dict):
            continue
        routes = mod.get("routes")
        if routes:
            for route in routes or []:
                if isinstance(route, dict):
                    out.extend(_flatten_flow(route.get("flow", []) or []))
        else:
            out.append(mod)
    return out


def _step_from_module(mod: dict) -> ImportedStep:
    app, op = _split_module(mod.get("module", ""))
    mapper = mod.get("mapper") if isinstance(mod.get("mapper"), dict) else {}
    label = mod.get("metadata", {}).get("designer", {}).get("name") if isinstance(mod.get("metadata"), dict) else None
    name = str(label or f"{app} {op}".strip() or "step")
    return ImportedStep(
        name=name,
        description=f"{op or 'use'} via {app}." if app else "module.",
        app=app,
        operation=op,
        params=mapper,
        tools_hint=[app] if app else [],
    )


def _trigger_from_module(mod: dict) -> ImportedTrigger:
    app, op = _split_module(mod.get("module", ""))
    low = f"{app}:{op}".lower()
    if any(h in low for h in _WEBHOOK_HINTS):
        kind = TRIGGER_WEBHOOK
    elif any(h in low for h in _SCHEDULE_HINTS):
        kind = TRIGGER_SCHEDULE
    else:
        kind = TRIGGER_EVENT
    return ImportedTrigger(
        kind=kind,
        app=app if kind == TRIGGER_EVENT else "",
        event=op or app,
        config=mod.get("mapper") if isinstance(mod.get("mapper"), dict) else {},
    )


def _unwrap(raw: dict) -> dict:
    """Accept the bare blueprint or the API envelope around it."""
    if "flow" in raw:
        return raw
    resp = raw.get("response") if isinstance(raw.get("response"), dict) else raw
    bp = resp.get("blueprint") if isinstance(resp, dict) else None
    if isinstance(bp, dict):
        return bp
    if isinstance(raw.get("blueprint"), dict):
        return raw["blueprint"]
    return raw


def translate(raw: dict[str, Any]) -> ImportedAutomation:
    """Lower one Make scenario blueprint into the shared IR."""
    if not isinstance(raw, dict):
        raise ImporterError("Make blueprint must be a JSON object")
    bp = _unwrap(raw)
    flow = bp.get("flow")
    if not isinstance(flow, list) or not flow:
        raise ImporterError("Make blueprint has no 'flow'")

    modules = _flatten_flow(flow)
    trigger = _trigger_from_module(modules[0]) if modules else ImportedTrigger()
    steps = [_step_from_module(m) for m in modules[1:]]

    return ImportedAutomation(
        source="make",
        source_id=str(bp.get("id") or raw.get("id") or ""),
        name=str(bp.get("name") or "untitled Make scenario"),
        trigger=trigger,
        steps=steps,
        raw=raw,
    )


class MakeImporter:
    source = "make"
    can_fetch_definitions = True

    def __init__(self, base_url: str | None = None, token: str | None = None):
        self.base_url = (base_url or os.environ.get("MAKE_BASE_URL", "")).strip().rstrip("/")
        self.token = (token or os.environ.get("MAKE_TOKEN", "")).strip()

    def _get(self, client, path: str, **kw):
        return client.get(
            f"{self.base_url}{path}",
            headers={"Authorization": f"Token {self.token}", "Accept": "application/json"},
            **kw,
        )

    def fetch(self) -> list[dict[str, Any]]:
        if not self.base_url or not self.token:
            raise ImporterError("Make import requires MAKE_BASE_URL + MAKE_TOKEN")
        try:
            import httpx
        except ImportError as e:  # pragma: no cover - optional dep
            raise ImporterError("httpx is required for live Make import") from e
        out: list[dict[str, Any]] = []
        with httpx.Client(timeout=30.0) as client:
            r = self._get(client, "/api/v2/scenarios", params={"pg[limit]": 100})
            r.raise_for_status()
            scenarios = (r.json() or {}).get("scenarios") or []
            for sc in scenarios:
                sid = sc.get("id")
                if sid is None:
                    continue
                br = self._get(client, f"/api/v2/scenarios/{sid}/blueprint")
                br.raise_for_status()
                out.append(br.json() if br.content else {})
        return out

    def translate(self, raw: dict[str, Any]) -> ImportedAutomation:
        return translate(raw)


register("make", MakeImporter)
