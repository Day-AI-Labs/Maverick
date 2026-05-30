"""HubSpot tool — contacts, companies, deals.

Auth: ``HUBSPOT_TOKEN`` (private app access token).

ops:
  - contacts(limit, query)
  - contact_get(contact_id)
  - contact_create(email, firstname, lastname, properties, confirm)
  - contact_update(contact_id, properties, confirm)
  - companies(limit)
  - deals(limit, stage)
"""
from __future__ import annotations

import logging
import os
from typing import Any

from . import Tool, as_bool

log = logging.getLogger(__name__)


_HS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "op": {
            "type": "string",
            "enum": ["contacts", "contact_get", "contact_create",
                     "contact_update", "companies", "deals"],
        },
        "limit": {"type": "integer"},
        "query": {"type": "string"},
        "contact_id": {"type": "string"},
        "email": {"type": "string"},
        "firstname": {"type": "string"},
        "lastname": {"type": "string"},
        "properties": {"type": "object"},
        "stage": {"type": "string"},
        "confirm": {"type": "boolean"},
    },
    "required": ["op"],
}


_API = "https://api.hubapi.com"


def _token() -> str:
    t = os.environ.get("HUBSPOT_TOKEN", "").strip()
    if not t:
        raise RuntimeError("HubSpot requires HUBSPOT_TOKEN (private app access token).")
    return t


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_token()}",
        "Content-Type": "application/json",
    }


def _get(path: str, params: dict | None = None) -> tuple[int, Any]:
    import httpx
    r = httpx.get(f"{_API}{path}", headers=_headers(),
                  params=params or {}, timeout=30.0)
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, r.text[:300]


def _post(path: str, body: dict) -> tuple[int, Any]:
    import httpx
    r = httpx.post(f"{_API}{path}", headers=_headers(), json=body, timeout=30.0)
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, r.text[:300]


def _patch(path: str, body: dict) -> tuple[int, Any]:
    import httpx
    r = httpx.patch(f"{_API}{path}", headers=_headers(), json=body, timeout=30.0)
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, r.text[:300]


def _op_contacts(args: dict) -> str:
    limit = max(1, min(int(args.get("limit") or 25), 100))
    query = (args.get("query") or "").strip()
    if query:
        code, data = _post("/crm/v3/objects/contacts/search", {
            "query": query, "limit": limit,
            "properties": ["email", "firstname", "lastname"],
        })
    else:
        code, data = _get("/crm/v3/objects/contacts", {
            "limit": limit, "properties": "email,firstname,lastname",
        })
    if code >= 400 or not isinstance(data, dict):
        return f"ERROR: contacts ({code}): {data}"
    rows = data.get("results") or []
    if not rows:
        return "no contacts"
    return "\n".join(
        f"  {c.get('id')}  {(c.get('properties') or {}).get('email', '?')}  "
        f"{(c.get('properties') or {}).get('firstname', '')} "
        f"{(c.get('properties') or {}).get('lastname', '')}"
        for c in rows
    )


def _op_contact_get(args: dict) -> str:
    cid = (args.get("contact_id") or "").strip()
    if not cid:
        return "ERROR: contact_get requires contact_id"
    code, data = _get(f"/crm/v3/objects/contacts/{cid}",
                       {"properties": "email,firstname,lastname,company,phone"})
    if code == 404:
        return f"contact {cid} not found"
    if code >= 400 or not isinstance(data, dict):
        return f"ERROR: contact_get ({code}): {data}"
    p = data.get("properties") or {}
    return (
        f"{data.get('id')}  {p.get('email', '?')}\n"
        f"  name:    {p.get('firstname', '')} {p.get('lastname', '')}\n"
        f"  phone:   {p.get('phone', '?')}\n"
        f"  company: {p.get('company', '?')}\n"
        f"  created: {data.get('createdAt')}\n"
        f"  updated: {data.get('updatedAt')}"
    )


def _op_contact_create(args: dict) -> str:
    email = (args.get("email") or "").strip()
    if not email:
        return "ERROR: contact_create requires email"
    if not as_bool(args.get("confirm")):
        return f"DRY RUN: would create contact {email}. Re-run with confirm=true."
    props = {"email": email}
    if args.get("firstname"):
        props["firstname"] = args["firstname"]
    if args.get("lastname"):
        props["lastname"] = args["lastname"]
    extra = args.get("properties") if isinstance(args.get("properties"), dict) else {}
    props.update({str(k): str(v) for k, v in extra.items()})
    code, data = _post("/crm/v3/objects/contacts", {"properties": props})
    if code >= 400 or not isinstance(data, dict):
        return f"ERROR: contact_create ({code}): {data}"
    return f"created contact {data.get('id')} ({email})"


def _op_contact_update(args: dict) -> str:
    cid = (args.get("contact_id") or "").strip()
    props = args.get("properties") if isinstance(args.get("properties"), dict) else None
    if not cid or not props:
        return "ERROR: contact_update requires contact_id and properties"
    if not as_bool(args.get("confirm")):
        return f"DRY RUN: would update {cid}. Re-run with confirm=true."
    code, data = _patch(
        f"/crm/v3/objects/contacts/{cid}",
        {"properties": {str(k): str(v) for k, v in props.items()}},
    )
    if code >= 400 or not isinstance(data, dict):
        return f"ERROR: contact_update ({code}): {data}"
    return f"updated {cid}"


def _op_companies(args: dict) -> str:
    limit = max(1, min(int(args.get("limit") or 25), 100))
    code, data = _get("/crm/v3/objects/companies", {
        "limit": limit, "properties": "name,domain,industry",
    })
    if code >= 400 or not isinstance(data, dict):
        return f"ERROR: companies ({code}): {data}"
    rows = data.get("results") or []
    if not rows:
        return "no companies"
    return "\n".join(
        f"  {c.get('id')}  {(c.get('properties') or {}).get('name', '?')}  "
        f"{(c.get('properties') or {}).get('domain', '')}"
        for c in rows
    )


def _op_deals(args: dict) -> str:
    limit = max(1, min(int(args.get("limit") or 25), 100))
    stage = (args.get("stage") or "").strip()
    if stage:
        code, data = _post("/crm/v3/objects/deals/search", {
            "filterGroups": [{"filters": [{
                "propertyName": "dealstage", "operator": "EQ", "value": stage,
            }]}],
            "limit": limit,
            "properties": ["dealname", "amount", "dealstage", "closedate"],
        })
    else:
        code, data = _get("/crm/v3/objects/deals", {
            "limit": limit,
            "properties": "dealname,amount,dealstage,closedate",
        })
    if code >= 400 or not isinstance(data, dict):
        return f"ERROR: deals ({code}): {data}"
    rows = data.get("results") or []
    if not rows:
        return "no deals"
    return "\n".join(
        f"  {d.get('id')}  {(d.get('properties') or {}).get('dealname', '?'):<40}  "
        f"${(d.get('properties') or {}).get('amount', '?')}  "
        f"stage={(d.get('properties') or {}).get('dealstage', '?')}"
        for d in rows
    )


def _run(args: dict[str, Any]) -> str:
    op = args.get("op")
    if not op:
        return "ERROR: op is required"
    try:
        import httpx  # noqa: F401
    except ImportError:
        return "ERROR: httpx not installed. Run: pip install 'maverick-agent[issue-trackers]'"
    try:
        return {
            "contacts":       _op_contacts,
            "contact_get":    _op_contact_get,
            "contact_create": _op_contact_create,
            "contact_update": _op_contact_update,
            "companies":      _op_companies,
            "deals":          _op_deals,
        }.get(op, lambda a: f"ERROR: unknown op {op!r}")(args)
    except RuntimeError as e:
        return f"ERROR: {e}"
    except Exception as e:
        return f"ERROR: HubSpot request failed: {type(e).__name__}: {e}"


def hubspot_tool() -> Tool:
    return Tool(
        name="hubspot",
        description=(
            "HubSpot CRM. ops: contacts (search or list), "
            "contact_get / contact_create / contact_update "
            "(mutations need confirm=true), companies (list), "
            "deals (optional stage filter). Auth: HUBSPOT_TOKEN."
        ),
        input_schema=_HS_SCHEMA,
        fn=_run,
    )
