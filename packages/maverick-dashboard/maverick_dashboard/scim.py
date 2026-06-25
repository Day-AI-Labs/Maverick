"""SCIM 2.0 user provisioning (RFC 7643/7644).

Enterprise IdPs (Okta, Azure AD/Entra, OneLogin) provision and deprovision
users via SCIM. This exposes the standard ``/scim/v2`` surface so an admin can
wire Lightwork as a SCIM app and have user lifecycle flow automatically:
creating a SCIM user provisions a backing **tenant** (the product's isolation
unit), and deprovisioning (``active=false`` or DELETE) suspends/removes it.

Auth is a static bearer (``MAVERICK_SCIM_TOKEN``) the IdP sends on every call —
SCIM has no OIDC/session, so these routes carry their own credential and are
exempt from the dashboard-token middleware and the OIDC gate (the app wires the
``/scim/`` exemptions). OFF by default: with no token set, every route 404s, so
mounting the router is inert until an operator opts in.

State lives in ``<home>/scim_users.json`` (atomic 0600 write), keeping the full
SCIM core attributes (id/userName/externalId/name/emails/active) so a round-trip
with the IdP is faithful, and linking each user to a registry tenant.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time
import uuid
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from maverick.file_lock import atomic_write_text
from maverick.paths import maverick_home

router = APIRouter(prefix="/scim/v2", tags=["scim"])

_USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
_LIST_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
_ERROR_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:Error"
_PATCH_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:PatchOp"


# --------------------------------------------------------------------------
# Enable / auth
# --------------------------------------------------------------------------
def _scim_secrets() -> list[str]:
    """Configured SCIM bearer secret(s).

    ``MAVERICK_SCIM_TOKEN`` may hold a single token (legacy) or a
    **comma-separated set** so a rotation can keep the old and new token both
    valid for a grace window. Each entry is either a literal token or a
    ``sha256:<hex>`` digest, so the plaintext secret need not sit in the process
    environment. Order does not matter; all are checked constant-time."""
    raw = os.environ.get("MAVERICK_SCIM_TOKEN", "")
    return [s.strip() for s in raw.split(",") if s.strip()]


def scim_enabled() -> bool:
    """SCIM is active only when at least one IdP bearer is configured."""
    return bool(_scim_secrets())


def _token_matches(token: str, secret: str) -> bool:
    """Constant-time match of a presented bearer against one configured secret,
    supporting a ``sha256:<hex>`` hashed secret."""
    if secret.startswith("sha256:"):
        want = secret[len("sha256:"):].strip().lower()
        got = hashlib.sha256(token.encode("utf-8")).hexdigest()
        return hmac.compare_digest(got, want)
    return hmac.compare_digest(token.encode("utf-8"), secret.encode("utf-8"))


def _scim_error(status: int, detail: str, *, scim_type: str | None = None) -> JSONResponse:
    body: dict[str, Any] = {"schemas": [_ERROR_SCHEMA], "detail": detail, "status": str(status)}
    if scim_type:
        body["scimType"] = scim_type
    return JSONResponse(body, status_code=status, media_type="application/scim+json")


def _authorize(request: Request) -> JSONResponse | None:
    """None when the caller is authorized; a SCIM error response otherwise.

    Disabled (no token) -> 404 so the surface stays invisible until opted in.
    Wrong/absent bearer -> 401. Constant-time token compare."""
    secrets = _scim_secrets()
    if not secrets:
        return _scim_error(404, "SCIM is not enabled")
    auth = request.headers.get("authorization", "")
    token = auth[7:] if auth.startswith("Bearer ") else ""
    # Compare on bytes: hmac.compare_digest(str, str) raises TypeError on any
    # non-ASCII (>U+007F) codepoint, which would 500 this auth gate (the sole
    # gate for the IdP provisioning surface) on a crafted bearer -- a DoS /
    # info-leak amplifier. The channel verifiers were fixed the same way.
    # Any configured secret may match (rotation grace window); each compare is
    # constant-time.
    if not (token and any(_token_matches(token, s) for s in secrets)):
        return _scim_error(401, "invalid or missing SCIM bearer token")
    return None


# --------------------------------------------------------------------------
# Store
# --------------------------------------------------------------------------
def _store_path():
    return maverick_home() / "scim_users.json"


def _load() -> dict[str, dict]:
    try:
        import json
        raw = json.loads(_store_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    users = raw.get("users", []) if isinstance(raw, dict) else []
    return {u["id"]: u for u in users if isinstance(u, dict) and u.get("id")}


def _save(users: dict[str, dict]) -> None:
    import json
    payload = {"users": [users[k] for k in sorted(users)]}
    atomic_write_text(_store_path(), json.dumps(payload, indent=2, sort_keys=True))


# --------------------------------------------------------------------------
# SCIM <-> store mapping
# --------------------------------------------------------------------------
def _primary_email(resource: dict) -> str:
    emails = resource.get("emails") or []
    if isinstance(emails, list):
        for e in emails:
            if isinstance(e, dict) and e.get("primary") and e.get("value"):
                return str(e["value"])
        for e in emails:
            if isinstance(e, dict) and e.get("value"):
                return str(e["value"])
    return ""


def _record_from_resource(resource: dict, *, uid: str, created: float | None = None) -> dict:
    """Normalize an incoming SCIM User into our stored record."""
    name = resource.get("name") if isinstance(resource.get("name"), dict) else {}
    now = time.time()
    return {
        "id": uid,
        "userName": str(resource.get("userName") or "").strip(),
        "externalId": str(resource.get("externalId") or "").strip(),
        "displayName": str(resource.get("displayName")
                            or " ".join(p for p in [name.get("givenName"),
                                                    name.get("familyName")] if p)
                            or "").strip(),
        "givenName": str(name.get("givenName") or "").strip(),
        "familyName": str(name.get("familyName") or "").strip(),
        "email": _primary_email(resource),
        "active": bool(resource.get("active", True)),
        "created_at": float(created if created is not None else now),
        "updated_at": now,
    }


def _to_scim(rec: dict) -> dict:
    """Render a stored record as a SCIM User resource."""
    res: dict[str, Any] = {
        "schemas": [_USER_SCHEMA],
        "id": rec["id"],
        "userName": rec.get("userName", ""),
        "active": bool(rec.get("active", True)),
        "meta": {
            "resourceType": "User",
            "created": _iso(rec.get("created_at")),
            "lastModified": _iso(rec.get("updated_at")),
            "location": f"/scim/v2/Users/{rec['id']}",
        },
    }
    if rec.get("externalId"):
        res["externalId"] = rec["externalId"]
    if rec.get("displayName"):
        res["displayName"] = rec["displayName"]
    if rec.get("givenName") or rec.get("familyName"):
        res["name"] = {"givenName": rec.get("givenName", ""),
                       "familyName": rec.get("familyName", "")}
    if rec.get("email"):
        res["emails"] = [{"value": rec["email"], "primary": True}]
    return res


def _iso(ts: float | None) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(float(ts or 0.0), tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------
# Tenant linkage (best-effort: SCIM remains the source of truth for users)
# --------------------------------------------------------------------------
def _provision_tenant(uid: str, display_name: str) -> None:
    try:
        from maverick.tenant import registry
        if registry.get_tenant(uid) is None:
            registry.create_tenant(uid, display_name=display_name or uid)
    except Exception:  # pragma: no cover -- tenant linkage never blocks SCIM
        pass


def _revoke_user_sessions(rec: dict) -> None:
    """Kill any live dashboard session/bearer for a deprovisioned SCIM user, so
    deprovisioning ends current access, not just future logins.

    The OIDC session subject is IdP-specific, so revoke every plausible
    identifier: ``externalId`` is the usual OIDC ``sub`` for Okta/Entra, plus
    ``userName`` / ``email`` / our internal ``id``. revoke_principal is a no-op
    for a blank value, so over-revoking spare identifiers is harmless."""
    try:
        from .session_revocation import revoke_principal
        for key in ("externalId", "userName", "email", "id"):
            revoke_principal(str(rec.get(key) or ""))
    except Exception:  # pragma: no cover -- revocation never blocks SCIM
        pass


def _set_tenant_active(uid: str, active: bool, rec: dict | None = None) -> None:
    if not active and rec is not None:
        _revoke_user_sessions(rec)
    try:
        from maverick.tenant import registry
        if registry.get_tenant(uid) is None:
            return
        (registry.resume_tenant if active else registry.suspend_tenant)(uid)
    except Exception:  # pragma: no cover
        pass


def _delete_tenant(uid: str, rec: dict | None = None) -> None:
    if rec is not None:
        _revoke_user_sessions(rec)
    try:
        from maverick.tenant import registry
        registry.delete_tenant(uid)
    except Exception:  # pragma: no cover
        pass


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------
async def _json_body(request: Request) -> dict:
    try:
        data = await request.json()
    except Exception:  # noqa: BLE001
        return {}
    return data if isinstance(data, dict) else {}


@router.get("/ServiceProviderConfig")
async def service_provider_config(request: Request):
    if (err := _authorize(request)) is not None:
        return err
    cfg = {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"],
        "patch": {"supported": True},
        "bulk": {"supported": False, "maxOperations": 0, "maxPayloadSize": 0},
        "filter": {"supported": True, "maxResults": 200},
        "changePassword": {"supported": False},
        "sort": {"supported": False},
        "etag": {"supported": False},
        "authenticationSchemes": [{
            "type": "oauthbearertoken", "name": "OAuth Bearer Token",
            "description": "Authentication via a static bearer token.",
        }],
    }
    return JSONResponse(cfg, media_type="application/scim+json")


@router.get("/ResourceTypes")
async def resource_types(request: Request):
    if (err := _authorize(request)) is not None:
        return err
    rt = [{
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ResourceType"],
        "id": "User", "name": "User", "endpoint": "/Users",
        "schema": _USER_SCHEMA,
    }]
    return JSONResponse(rt, media_type="application/scim+json")


@router.get("/Users")
async def list_users(request: Request):
    if (err := _authorize(request)) is not None:
        return err
    users = _load()
    resources = [_to_scim(u) for u in (users[k] for k in sorted(users))]

    # Minimal filter support: `userName eq "value"` (the IdP existence probe).
    flt = request.query_params.get("filter", "").strip()
    if flt:
        match = _parse_username_eq(flt)
        if match is None:
            return _scim_error(400, f"unsupported filter: {flt}", scim_type="invalidFilter")
        resources = [r for r in resources if r.get("userName", "").lower() == match.lower()]

    # 1-based startIndex + count pagination.
    try:
        start = max(1, int(request.query_params.get("startIndex", "1")))
    except ValueError:
        start = 1
    try:
        count = int(request.query_params.get("count", str(len(resources))))
    except ValueError:
        count = len(resources)
    count = max(0, count)
    page = resources[start - 1: start - 1 + count]
    body = {
        "schemas": [_LIST_SCHEMA],
        "totalResults": len(resources),
        "startIndex": start,
        "itemsPerPage": len(page),
        "Resources": page,
    }
    return JSONResponse(body, media_type="application/scim+json")


@router.post("/Users")
async def create_user(request: Request):
    if (err := _authorize(request)) is not None:
        return err
    resource = await _json_body(request)
    username = str(resource.get("userName") or "").strip()
    if not username:
        return _scim_error(400, "userName is required", scim_type="invalidValue")
    users = _load()
    # SCIM uniqueness on userName -> 409.
    if any(u.get("userName", "").lower() == username.lower() for u in users.values()):
        return _scim_error(409, f"userName {username!r} already exists", scim_type="uniqueness")
    uid = uuid.uuid4().hex
    rec = _record_from_resource(resource, uid=uid)
    users[uid] = rec
    _save(users)
    _provision_tenant(uid, rec["displayName"] or username)
    if not rec["active"]:
        _set_tenant_active(uid, False, rec)
    return JSONResponse(_to_scim(rec), status_code=201, media_type="application/scim+json")


@router.get("/Users/{uid}")
async def get_user(uid: str, request: Request):
    if (err := _authorize(request)) is not None:
        return err
    rec = _load().get(uid)
    if rec is None:
        return _scim_error(404, f"user {uid} not found")
    return JSONResponse(_to_scim(rec), media_type="application/scim+json")


@router.put("/Users/{uid}")
async def replace_user(uid: str, request: Request):
    if (err := _authorize(request)) is not None:
        return err
    users = _load()
    existing = users.get(uid)
    if existing is None:
        return _scim_error(404, f"user {uid} not found")
    resource = await _json_body(request)
    rec = _record_from_resource(resource, uid=uid, created=existing.get("created_at"))
    # userName is immutable in practice; keep the stored one if the PUT omits it.
    if not rec["userName"]:
        rec["userName"] = existing.get("userName", "")
    was_active = bool(existing.get("active", True))
    users[uid] = rec
    _save(users)
    if rec["active"] != was_active:
        _set_tenant_active(uid, rec["active"], rec)
    return JSONResponse(_to_scim(rec), media_type="application/scim+json")


@router.patch("/Users/{uid}")
async def patch_user(uid: str, request: Request):
    if (err := _authorize(request)) is not None:
        return err
    users = _load()
    rec = users.get(uid)
    if rec is None:
        return _scim_error(404, f"user {uid} not found")
    body = await _json_body(request)
    was_active = bool(rec.get("active", True))
    applied = _apply_patch(rec, body)
    if applied is None:
        return _scim_error(400, "unsupported PATCH operation", scim_type="invalidValue")
    rec["updated_at"] = time.time()
    users[uid] = rec
    _save(users)
    if bool(rec.get("active", True)) != was_active:
        _set_tenant_active(uid, bool(rec.get("active", True)), rec)
    return JSONResponse(_to_scim(rec), media_type="application/scim+json")


@router.delete("/Users/{uid}")
async def delete_user(uid: str, request: Request):
    if (err := _authorize(request)) is not None:
        return err
    users = _load()
    if uid not in users:
        return _scim_error(404, f"user {uid} not found")
    rec = users.get(uid)
    del users[uid]
    _save(users)
    _delete_tenant(uid, rec)
    return JSONResponse(None, status_code=204)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _parse_username_eq(flt: str) -> str | None:
    """Parse ``userName eq "value"`` -> value (case-insensitive op). None if the
    filter isn't that exact, supported shape."""
    import re
    m = re.fullmatch(r'\s*userName\s+eq\s+"([^"]*)"\s*', flt, re.IGNORECASE)
    return m.group(1) if m else None


def _apply_patch(rec: dict, body: dict) -> bool | None:
    """Apply a SCIM PatchOp in place. Supports the common Okta/Azure shape:
    replace ``active`` (and a few core scalars). Returns True on success, None if
    nothing applicable was found."""
    if _PATCH_SCHEMA not in (body.get("schemas") or []):
        return None
    ops = body.get("Operations") or body.get("operations") or []
    if not isinstance(ops, list):
        return None
    applied = False
    for op in ops:
        if not isinstance(op, dict):
            continue
        if str(op.get("op", "")).lower() not in ("replace", "add"):
            continue
        path = str(op.get("path") or "").strip()
        value = op.get("value")
        if path:
            applied = _patch_path(rec, path, value) or applied
        elif isinstance(value, dict):
            # No path: value is an attribute bag (Azure sends this form).
            for k, v in value.items():
                applied = _patch_path(rec, k, v) or applied
    return True if applied else None


def _patch_path(rec: dict, path: str, value: Any) -> bool:
    p = path.lower()
    if p == "active":
        rec["active"] = value if isinstance(value, bool) else str(value).lower() == "true"
        return True
    if p == "displayname":
        rec["displayName"] = str(value or "")
        return True
    if p == "username":
        rec["userName"] = str(value or "")
        return True
    return False


__all__ = ["router", "scim_enabled"]
