"""Tenant lifecycle / provisioning registry — the hosted control plane's roster.

A :class:`Workspace` isolates one tenant's *data*; this registry is the
*operator's* record of which tenants exist, their status (active / suspended),
plan, and per-tenant quota. It lives at the **un-namespaced** root
(``<home>/tenant_registry.json``, ``tenant=None``) because it is cross-tenant
control-plane state, not any one tenant's data.

Lifecycle: ``create`` → ``suspend`` / ``resume`` → ``delete`` (optionally
purging the tenant's data dir). :func:`assert_tenant_active` is the enforcement
hook a request path calls before doing work for a tenant, so a suspended tenant
is refused. The registry is opt-in: with no tenants provisioned the file does
not exist and :func:`assert_tenant_active` is a no-op, so single-tenant and
unprovisioned deployments are unchanged.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, replace

from .paths import _tenant_segment, maverick_home

ACTIVE = "active"
SUSPENDED = "suspended"
_STATUSES = frozenset({ACTIVE, SUSPENDED})


class TenantSuspended(PermissionError):
    """Raised when work is attempted for a suspended (or deleted) tenant."""


class UnknownTenant(KeyError):
    """Raised when an operation targets a tenant that was never provisioned."""


def _registry_path():
    return maverick_home() / "tenant_registry.json"


@dataclass(frozen=True)
class TenantRecord:
    """One provisioned tenant."""

    id: str
    status: str = ACTIVE
    plan: str = "free"
    display_name: str = ""
    # Per-tenant aggregate spend cap (USD/day); 0 = unlimited (defer to global).
    max_daily_dollars: float = 0.0
    created_at: float = 0.0
    updated_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id, "status": self.status, "plan": self.plan,
            "display_name": self.display_name,
            "max_daily_dollars": self.max_daily_dollars,
            "created_at": self.created_at, "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> TenantRecord:
        if not isinstance(d, dict) or not d.get("id"):
            raise ValueError("tenant record must be an object with an id")
        status = str(d.get("status") or ACTIVE)
        if status not in _STATUSES:
            status = ACTIVE
        try:
            cap = float(d.get("max_daily_dollars") or 0.0)
        except (TypeError, ValueError):
            cap = 0.0
        return cls(
            id=str(d["id"]), status=status, plan=str(d.get("plan") or "free"),
            display_name=str(d.get("display_name") or ""),
            max_daily_dollars=max(0.0, cap),
            created_at=float(d.get("created_at") or 0.0),
            updated_at=float(d.get("updated_at") or 0.0),
        )

    @property
    def active(self) -> bool:
        return self.status == ACTIVE


def _validate_id(tenant_id: str) -> str:
    tid = (tenant_id or "").strip()
    if not tid:
        raise ValueError("tenant id is required")
    # Reuse the path encoder's guard so a registry id is always a safe segment
    # (it raises InvalidTenantError on an over-long id).
    _tenant_segment(tid)
    return tid


def _load() -> dict[str, TenantRecord]:
    try:
        raw = json.loads(_registry_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[str, TenantRecord] = {}
    for d in raw.get("tenants", []) if isinstance(raw, dict) else []:
        try:
            rec = TenantRecord.from_dict(d)
        except ValueError:
            continue
        out[rec.id] = rec
    return out


def _save(records: dict[str, TenantRecord]) -> None:
    path = _registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"tenants": [records[k].to_dict() for k in sorted(records)]}
    # 0600: the roster is operator control-plane metadata.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)


def list_tenants() -> list[TenantRecord]:
    return [_load()[k] for k in sorted(_load())]


def get_tenant(tenant_id: str) -> TenantRecord | None:
    return _load().get((tenant_id or "").strip())


def create_tenant(
    tenant_id: str, *, plan: str = "free", display_name: str = "",
    max_daily_dollars: float = 0.0,
) -> TenantRecord:
    """Provision a tenant + its workspace dir. Raises ValueError if it exists."""
    tid = _validate_id(tenant_id)
    records = _load()
    if tid in records:
        raise ValueError(f"tenant already exists: {tid!r}")
    now = time.time()
    rec = TenantRecord(
        id=tid, status=ACTIVE, plan=plan, display_name=display_name,
        max_daily_dollars=max(0.0, float(max_daily_dollars or 0.0)),
        created_at=now, updated_at=now,
    )
    records[tid] = rec
    _save(records)
    # Materialize the workspace home so the tenant's data dir exists.
    from .workspace import Workspace
    Workspace(tid).root.mkdir(parents=True, exist_ok=True)
    return rec


def _mutate(tenant_id: str, **changes) -> TenantRecord:
    tid = (tenant_id or "").strip()
    records = _load()
    rec = records.get(tid)
    if rec is None:
        raise UnknownTenant(tid)
    rec = replace(rec, updated_at=time.time(), **changes)
    records[tid] = rec
    _save(records)
    return rec


def suspend_tenant(tenant_id: str) -> TenantRecord:
    return _mutate(tenant_id, status=SUSPENDED)


def resume_tenant(tenant_id: str) -> TenantRecord:
    return _mutate(tenant_id, status=ACTIVE)


def set_quota(tenant_id: str, max_daily_dollars: float) -> TenantRecord:
    return _mutate(tenant_id, max_daily_dollars=max(0.0, float(max_daily_dollars or 0.0)))


def set_plan(tenant_id: str, plan: str) -> TenantRecord:
    return _mutate(tenant_id, plan=str(plan or "free"))


def delete_tenant(tenant_id: str, *, purge: bool = False) -> bool:
    """Remove a tenant from the registry. With ``purge=True`` also delete its
    data directory (irreversible). Returns False if the tenant was unknown."""
    tid = (tenant_id or "").strip()
    records = _load()
    if tid not in records:
        return False
    del records[tid]
    _save(records)
    if purge:
        import shutil

        from .workspace import Workspace
        root = Workspace(tid).root
        # Only purge under the tenants/ tree, never the shared root.
        if "tenants" in root.parts:
            shutil.rmtree(root, ignore_errors=True)
    return True


def is_active(tenant_id: str | None) -> bool:
    """Whether a tenant may do work. Unprovisioned/None tenants are active
    (the registry is opt-in; no roster ⇒ no enforcement)."""
    tid = (tenant_id or "").strip()
    if not tid:
        return True
    rec = _load().get(tid)
    return True if rec is None else rec.active


def assert_tenant_active(tenant_id: str | None) -> None:
    """Enforcement hook: raise :class:`TenantSuspended` for a suspended tenant.
    No-op for None / unprovisioned tenants, so existing flows are unchanged."""
    if not is_active(tenant_id):
        raise TenantSuspended(f"tenant is suspended: {tenant_id!r}")


__all__ = [
    "ACTIVE", "SUSPENDED", "TenantRecord", "TenantSuspended", "UnknownTenant",
    "list_tenants", "get_tenant", "create_tenant", "suspend_tenant",
    "resume_tenant", "delete_tenant", "set_quota", "set_plan",
    "is_active", "assert_tenant_active",
]
