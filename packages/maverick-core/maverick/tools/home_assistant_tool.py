"""Home Assistant tool — IoT control.

Talks to a Home Assistant instance over its REST API.

Auth:
  - ``HASS_URL`` (e.g. http://homeassistant.local:8123)
  - ``HASS_TOKEN`` (long-lived access token, Profile → Security)

ops:
  - states(domain)                          — list entity states (optional domain filter)
  - state_get(entity_id)
  - call_service(domain, service, data, confirm)
  - history(entity_id, hours)
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from . import Tool

log = logging.getLogger(__name__)


_HASS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "op": {
            "type": "string",
            "enum": ["states", "state_get", "call_service", "history"],
        },
        "domain": {"type": "string"},
        "service": {"type": "string"},
        "data": {"type": "object"},
        "entity_id": {"type": "string"},
        "hours": {"type": "number"},
        "confirm": {"type": "boolean"},
    },
    "required": ["op"],
}


def _config() -> tuple[str, str]:
    url = os.environ.get("HASS_URL", "").strip().rstrip("/")
    tok = os.environ.get("HASS_TOKEN", "").strip()
    if not url or not tok:
        raise RuntimeError("Home Assistant requires HASS_URL + HASS_TOKEN.")
    return url, tok


def _headers() -> dict[str, str]:
    _u, tok = _config()
    return {"Authorization": f"Bearer {tok}",
            "Content-Type": "application/json"}


def _get(path: str) -> tuple[int, Any]:
    import httpx
    url, _ = _config()
    r = httpx.get(f"{url}{path}", headers=_headers(), timeout=15.0)
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, r.text[:300]


def _post(path: str, body: dict) -> tuple[int, Any]:
    import httpx
    url, _ = _config()
    r = httpx.post(f"{url}{path}", headers=_headers(),
                   json=body, timeout=15.0)
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, r.text[:300]


def _op_states(args: dict) -> str:
    code, data = _get("/api/states")
    if code >= 400 or not isinstance(data, list):
        return f"ERROR: states ({code}): {data}"
    domain = (args.get("domain") or "").strip()
    rows = [d for d in data if not domain or d.get("entity_id", "").startswith(domain + ".")]
    if not rows:
        return f"no entities (domain={domain or '*'})"
    return "\n".join(
        f"  {e.get('entity_id'):<40}  {e.get('state', '?'):<12}  "
        f"{(e.get('attributes') or {}).get('friendly_name', '')[:40]}"
        for e in rows[:200]
    )


def _op_state_get(args: dict) -> str:
    eid = (args.get("entity_id") or "").strip()
    if not eid:
        return "ERROR: state_get requires entity_id"
    code, data = _get(f"/api/states/{eid}")
    if code == 404:
        return f"entity {eid} not found"
    if code >= 400 or not isinstance(data, dict):
        return f"ERROR: state_get ({code}): {data}"
    attrs = data.get("attributes") or {}
    return (
        f"{data.get('entity_id')}  state={data.get('state')}\n"
        f"  last_changed:  {data.get('last_changed')}\n"
        f"  last_updated:  {data.get('last_updated')}\n"
        f"  attributes:    {json.dumps(attrs, default=str)[:500]}"
    )


def _op_call_service(args: dict) -> str:
    domain = (args.get("domain") or "").strip()
    service = (args.get("service") or "").strip()
    if not domain or not service:
        return "ERROR: call_service requires domain and service"
    if not args.get("confirm"):
        return (
            f"DRY RUN: would call {domain}.{service}. "
            "Re-run with confirm=true."
        )
    data = args.get("data") if isinstance(args.get("data"), dict) else {}
    code, body = _post(f"/api/services/{domain}/{service}", data)
    if code >= 400:
        return f"ERROR: call_service ({code}): {body}"
    affected = body if isinstance(body, list) else [body]
    return f"called {domain}.{service} ({len(affected)} state(s) changed)"


def _op_history(args: dict) -> str:
    eid = (args.get("entity_id") or "").strip()
    if not eid:
        return "ERROR: history requires entity_id"
    # HA's history endpoint defaults to last 24h. ``hours`` is reserved
    # in the schema for future use once we hand-build the start_time
    # query — current API takes no explicit window.
    _ = int(args.get("hours") or 1)
    code, data = _get(f"/api/history/period?filter_entity_id={eid}")
    if code >= 400 or not isinstance(data, list):
        return f"ERROR: history ({code}): {data}"
    series = data[0] if data else []
    if not series:
        return "no history"
    return "\n".join(
        f"  {s.get('last_changed')}  {s.get('state', '?')}"
        for s in series[-min(len(series), 100):]
    )


def _run(args: dict[str, Any]) -> str:
    op = args.get("op")
    if not op:
        return "ERROR: op is required"
    try:
        import httpx  # noqa: F401
    except ImportError:
        return "ERROR: httpx not installed."
    try:
        return {
            "states":       _op_states,
            "state_get":    _op_state_get,
            "call_service": _op_call_service,
            "history":      _op_history,
        }.get(op, lambda a: f"ERROR: unknown op {op!r}")(args)
    except RuntimeError as e:
        return f"ERROR: {e}"
    except Exception as e:
        return f"ERROR: Home Assistant request failed: {type(e).__name__}: {e}"


def home_assistant_tool() -> Tool:
    return Tool(
        name="home_assistant",
        description=(
            "Home Assistant IoT. ops: states (optional domain "
            "filter), state_get, call_service (domain + service + "
            "data; confirm=true required), history. Auth: HASS_URL "
            "+ HASS_TOKEN."
        ),
        input_schema=_HASS_SCHEMA,
        fn=_run,
    )
