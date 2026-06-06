"""Tenant-aware data paths — the P1 multi-tenancy primitive.

Maverick keeps its state under ``~/.maverick``. For multi-tenant deployments,
a *tenant* namespaces that state so one tenant's data (cross-session memory,
history, ...) is isolated from another's on disk.

The active tenant is resolved in order:

1. an explicit :func:`set_tenant` scope (a :class:`contextvars.ContextVar`, so
   concurrent async runs can each pin their own tenant safely);
2. the ``MAVERICK_TENANT`` environment variable;
3. none.

With **no** tenant, paths resolve to the legacy ``~/.maverick/<...>`` locations,
so single-tenant deployments are completely unchanged. With tenant ``t``, they
resolve under ``~/.maverick/tenants/<t>/<...>``.

This increment routes the cross-session **memory** store through here (the most
leak-sensitive per-tenant store); the world model and audit log are migrated in
follow-on increments.
"""
from __future__ import annotations

import contextvars
import os
import re
from pathlib import Path

_TENANT: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "maverick_tenant", default=None
)

# A tenant id becomes a path segment, so confine it to a safe charset and
# bound its length. Anything else collapses to a placeholder rather than
# escaping the data root.
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")
_DEFAULT_TENANT = "default"


def _sanitize(tenant: str) -> str:
    cleaned = _UNSAFE.sub("_", tenant.strip()).strip(".")[:128]
    return cleaned or _DEFAULT_TENANT


def current_tenant() -> str | None:
    """The active tenant id (sanitized), or ``None`` for the shared/legacy root.

    Explicit :func:`set_tenant` scope wins over the ``MAVERICK_TENANT`` env var.
    """
    t = _TENANT.get()
    if t:
        return _sanitize(t)
    env = os.environ.get("MAVERICK_TENANT", "").strip()
    return _sanitize(env) if env else None


def set_tenant(tenant: str | None):
    """Pin the active tenant for the current (async) context.

    Returns a token; pass it to :func:`reset_tenant` (or use try/finally) to
    restore the previous value. Concurrent runs on the same loop each see their
    own tenant because it lives in a ContextVar.
    """
    return _TENANT.set(tenant)


def reset_tenant(token) -> None:
    try:
        _TENANT.reset(token)
    except (ValueError, LookupError):  # pragma: no cover -- cross-context reset
        pass


def maverick_home() -> Path:
    """The base data dir (``~/.maverick``). NOT tenant-scoped; use
    :func:`data_dir` for tenant-isolated paths."""
    return Path.home() / ".maverick"


def data_dir(*parts: str, tenant: str | None = "__active__") -> Path:
    """A data path under the (optionally tenant-scoped) home.

    With an active tenant ``t`` this is ``<home>/tenants/<t>/<parts...>``;
    with none it is the legacy ``<home>/<parts...>`` (single-tenant unchanged).
    Pass ``tenant=None`` to force the shared, un-namespaced location regardless
    of the active tenant.
    """
    if tenant == "__active__":
        tenant = current_tenant()
    base = maverick_home()
    if tenant:
        base = base / "tenants" / _sanitize(tenant)
    return base.joinpath(*parts)


__all__ = [
    "current_tenant",
    "set_tenant",
    "reset_tenant",
    "maverick_home",
    "data_dir",
]
