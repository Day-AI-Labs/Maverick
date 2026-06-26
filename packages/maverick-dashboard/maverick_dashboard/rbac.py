"""Dashboard RBAC: admin-managed user roles (admin / operator / auditor / viewer).

This is the dashboard's *access-control* layer and is deliberately distinct from
the kernel's ``[roles]`` (``maverick.capability``), which only ATTENUATES an
agent's tool scope. Here a role GRANTS UI/API privilege, so it must never be
conflated with the kernel's attenuating roles.

Safety invariants (see maverick_dashboard.auth):
  * Meaningful only when an auth mode is on (OIDC / reverse-proxy / session).
    In no-token local mode ``caller_principal`` is None and every gate is a
    no-op — the local operator stays omnipotent, exactly as before.
  * A config-pinned bootstrap admin (``MAVERICK_DASHBOARD_ADMINS`` /
    ``[dashboard] admins``) is ALWAYS admin and is not stored here, so a wiped
    or tampered store can never lock every admin out.
  * The roster is control-plane data: one GLOBAL file, never per-tenant.

Store: ``~/.maverick/dashboard-users.json`` (0600), ``{principal: role}``.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

ROLES = ("admin", "operator", "auditor", "viewer")

# Serializes a roster load-modify-save in-process; cross_process_lock in
# _locked() extends it across processes (multiple dashboard workers edit roles).
_RBAC_LOCK = threading.Lock()


def _locked(path: Path):
    from contextlib import ExitStack

    from maverick.file_lock import cross_process_lock
    stack = ExitStack()
    stack.enter_context(_RBAC_LOCK)
    stack.enter_context(cross_process_lock(path))
    return stack

# Permission lattice. The "audit" permission gates the audit-trail read surface
# (/api/v1/audit/*): the who-did-what-when record that can name principals, tool
# inputs and costs. It is held by "admin" and by the dedicated read-only
# "auditor" role -- separation of duties, so a compliance reviewer can read the
# audit log WITHOUT also holding operate/admin (run goals, change settings,
# manage users). "auditor" deliberately grants NOTHING operational: audit + view
# only. "operator"/"viewer" do NOT get "audit" -- reading the trail is a
# distinct grant, not implied by operate.
_PERMISSIONS: dict[str, frozenset[str]] = {
    "admin": frozenset({"admin", "audit", "operate", "view"}),  # users, settings, secrets, + all
    "operator": frozenset({"operate", "view"}),                 # run/cancel goals, approve, tools
    "auditor": frozenset({"audit", "view"}),                    # read audit trail (read-only)
    "viewer": frozenset({"view"}),                              # read-only
}


def store_path() -> Path:
    return Path.home() / ".maverick" / "dashboard-users.json"


def default_role() -> str:
    """Role for an authenticated user with no explicit assignment. Defaults to
    ``operator`` (authenticated users keep today's access); set
    ``[dashboard] default_role = "viewer"`` for deny-by-default."""
    try:
        from maverick.config import load_config
        r = (load_config().get("dashboard", {}) or {}).get("default_role")
        if isinstance(r, str) and r in ROLES:
            return r
    except Exception:  # pragma: no cover - config read must never gate auth
        pass
    return "operator"


def permissions_for(role: str | None) -> frozenset[str]:
    return _PERMISSIONS.get(role or "", frozenset())


def _load() -> dict[str, str]:
    p = store_path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    # Re-validate on read so a hand-edited / corrupt store can't inject an
    # unknown role or a non-string principal.
    return {
        str(k): v for k, v in data.items()
        if isinstance(k, str) and k.strip() and isinstance(v, str) and v in ROLES
    }


def _write(data: dict[str, str]) -> None:
    # Unique temp + os.replace (0600): the fixed ".json.tmp" collided between
    # two concurrent dashboard workers (one os.replace moved it out from under
    # the other). Cross-process serialization of the RMW is in the mutators.
    from maverick.file_lock import atomic_write_text
    atomic_write_text(store_path(), json.dumps(data, indent=2, sort_keys=True))


def list_users() -> dict[str, str]:
    """All explicitly-assigned {principal: role} (bootstrap admins excluded)."""
    return _load()


def get_stored_role(principal: str) -> str | None:
    return _load().get((principal or "").strip())


def set_role(principal: str, role: str) -> None:
    principal = (principal or "").strip()
    if not principal:
        raise ValueError("empty principal")
    if role not in ROLES:
        raise ValueError("unknown role")
    with _locked(store_path()):
        data = _load()
        data[principal] = role
        _write(data)


def remove_user(principal: str) -> None:
    with _locked(store_path()):
        data = _load()
        if data.pop((principal or "").strip(), None) is not None:
            _write(data)


# --- Per-tenant role memberships ---------------------------------------------
# A principal can hold a different role per tenant (e.g. admin of "acme",
# viewer of "globex"). This OVERRIDES the global stored role for that tenant
# only. The config-pinned bootstrap admin stays globally admin regardless, so
# tenant memberships can never lock every admin out. Store is a separate global
# control-plane file: ``{tenant: {principal: role}}``.


def tenant_store_path() -> Path:
    return Path.home() / ".maverick" / "dashboard-tenant-roles.json"


def _load_tenant() -> dict[str, dict[str, str]]:
    p = tenant_store_path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, dict[str, str]] = {}
    for tenant, members in data.items():
        if not (isinstance(tenant, str) and tenant.strip() and isinstance(members, dict)):
            continue
        out[tenant] = {
            str(k): v for k, v in members.items()
            if isinstance(k, str) and k.strip() and isinstance(v, str) and v in ROLES
        }
    return out


def _write_tenant(data: dict[str, dict[str, str]]) -> None:
    from maverick.file_lock import atomic_write_text
    atomic_write_text(tenant_store_path(),
                      json.dumps(data, indent=2, sort_keys=True))


def get_tenant_role(tenant: str, principal: str) -> str | None:
    """The principal's role within ``tenant``, or None if no membership."""
    members = _load_tenant().get((tenant or "").strip(), {})
    return members.get((principal or "").strip())


def set_tenant_role(tenant: str, principal: str, role: str) -> None:
    tenant = (tenant or "").strip()
    principal = (principal or "").strip()
    if not tenant or not principal:
        raise ValueError("empty tenant or principal")
    if role not in ROLES:
        raise ValueError("unknown role")
    with _locked(tenant_store_path()):
        data = _load_tenant()
        data.setdefault(tenant, {})[principal] = role
        _write_tenant(data)


def remove_tenant_role(tenant: str, principal: str) -> None:
    with _locked(tenant_store_path()):
        data = _load_tenant()
        members = data.get((tenant or "").strip())
        if members and members.pop((principal or "").strip(), None) is not None:
            if not members:
                data.pop((tenant or "").strip(), None)
            _write_tenant(data)


def list_tenant_roles(tenant: str) -> dict[str, str]:
    """All {principal: role} memberships within ``tenant``."""
    return dict(_load_tenant().get((tenant or "").strip(), {}))


__all__ = [
    "ROLES", "store_path", "default_role", "permissions_for",
    "list_users", "get_stored_role", "set_role", "remove_user",
    "tenant_store_path", "get_tenant_role", "set_tenant_role",
    "remove_tenant_role", "list_tenant_roles",
]
