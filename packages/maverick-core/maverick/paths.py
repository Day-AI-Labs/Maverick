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

import contextlib
import contextvars
import os
from pathlib import Path

_TENANT: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "maverick_tenant", default=None
)

# A tenant id becomes a path segment. Keep already-safe identifiers readable,
# but percent-encode every other UTF-8 byte so distinct tenant ids cannot
# collapse onto the same on-disk namespace.
_SAFE_TENANT_CHARS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-"
)
MAX_TENANT_SEGMENT_LENGTH = 200


class InvalidTenantError(ValueError):
    """Raised when a tenant id cannot be represented safely on disk."""


def _tenant_segment(tenant: str) -> str:
    if tenant in {".", ".."}:
        segment = "%2E" * len(tenant)
    else:
        segment = "".join(
            chr(byte) if chr(byte) in _SAFE_TENANT_CHARS else f"%{byte:02X}"
            for byte in tenant.encode("utf-8")
        )
    if len(segment) > MAX_TENANT_SEGMENT_LENGTH:
        raise InvalidTenantError("tenant id is too long")
    return segment


def current_tenant() -> str | None:
    """The active tenant id (path-encoded), or ``None`` for the shared/legacy root.

    Explicit :func:`set_tenant` scope wins over the ``MAVERICK_TENANT`` env var.
    """
    t = _TENANT.get()
    if t:
        return _tenant_segment(t)
    env = os.environ.get("MAVERICK_TENANT", "").strip()
    return _tenant_segment(env) if env else None


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
        segment = current_tenant()
    else:
        segment = _tenant_segment(tenant) if tenant else None
    base = maverick_home()
    if segment:
        base = base / "tenants" / segment
    return base.joinpath(*parts)


def tenant_by_user_enabled() -> bool:
    """Opt-in, off by default. ``MAVERICK_TENANT_BY_USER=1`` or
    ``[tenancy] by_user = true`` makes the server isolate each channel user
    into their own tenant (so one user's cross-session memory can't leak to
    another). Off -> single shared tenant, behaviour unchanged."""
    if os.environ.get("MAVERICK_TENANT_BY_USER", "").strip().lower() in {
        "1", "true", "yes", "on",
    }:
        return True
    try:
        from .config import load_config
        cfg = (load_config() or {}).get("tenancy") or {}
        return bool(cfg.get("by_user"))
    except Exception:
        return False


@contextlib.contextmanager
def tenant_scope(*, channel: str | None = None, user_id: str | None = None,
                 tenant: str | None = None):
    """Pin the active tenant for the duration of the block, then restore it.

    No-op (yields with the tenant unchanged) unless an explicit ``tenant`` is
    given, or ``tenant_by_user_enabled()`` and a ``user_id`` is present — in
    which case the tenant is ``"<channel>:<user_id>"`` (sanitized). The reset
    on exit makes this safe for a server that handles messages sequentially on
    one task or concurrently across tasks.
    """
    if tenant is None and user_id is not None and tenant_by_user_enabled():
        tenant = f"{channel or 'unknown'}:{user_id}"
    if tenant is None:
        yield
        return
    token = set_tenant(tenant)
    try:
        yield
    finally:
        reset_tenant(token)


__all__ = [
    "current_tenant",
    "set_tenant",
    "reset_tenant",
    "maverick_home",
    "data_dir",
    "InvalidTenantError",
    "MAX_TENANT_SEGMENT_LENGTH",
    "tenant_by_user_enabled",
    "tenant_scope",
]
