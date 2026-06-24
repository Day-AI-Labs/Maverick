"""Client binding — one Maverick deployment, exactly one enterprise client.

Maverick is deployed **one instance per enterprise client** (never a shared,
hosted multi-tenant service). This module makes that binding explicit and
**fail-closed** so client data can never land in an ambiguous, un-scoped
location:

* the deployment declares its client via ``[client] id`` or
  ``MAVERICK_CLIENT_ID``;
* that id becomes the tenant **floor** (consumed by
  :func:`maverick.paths.current_tenant_id`), so every data path — world DB,
  audit chain + keys, cross-session memory, fleet memory — resolves under
  ``~/.maverick/tenants/<client>/...`` instead of a shared root. There is no
  un-scoped global location for client data to accumulate in;
* in **enforced** mode (``[client] enforce = true``, ``MAVERICK_CLIENT_ENFORCE``,
  or enterprise mode) a missing/invalid client id REFUSES to start — there is no
  silent fallback to the shared root.

Off by default (no client id configured) => legacy single-root behaviour,
byte-for-byte unchanged, so existing single-tenant installs are unaffected.

The client id is immutable for a deployment's lifetime, so it is resolved once
and cached; set ``MAVERICK_CLIENT_ID`` in the service unit / image so the hot
path (every ``data_dir`` call resolves the tenant floor) never parses config.
"""
from __future__ import annotations

import logging
import os
import re

from ._envparse import coerce_bool, is_truthy

log = logging.getLogger(__name__)

# A client id becomes the tenant path segment, so it must satisfy the tenant
# charset (paths._SAFE_TENANT_CHARS): digits/._- and LOWERCASE letters only.
# Lowercase is required because the id is a directory name: on a case-insensitive
# filesystem (macOS APFS, Windows NTFS) "Acme" and "acme" resolve to the SAME
# directory, so allowing mixed case would let two distinct client ids collide
# onto one data root — the one thing the per-client binding must prevent.
_CLIENT_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")

# Resolved once per process (the binding is immutable for a deployment). Tests
# reset via reset_client_cache().
_UNSET = object()
_cached: object = _UNSET


class ClientBindingError(RuntimeError):
    """Raised when a client-bound deployment is started without a valid client id."""


def reset_client_cache() -> None:
    """Forget the cached client id (test hook; the id is immutable in prod)."""
    global _cached
    _cached = _UNSET


def _raw_client_id() -> str:
    """The configured client id, unvalidated. ``MAVERICK_CLIENT_ID`` wins over
    ``[client] id``; empty string when neither is set."""
    raw = (os.environ.get("MAVERICK_CLIENT_ID") or "").strip()
    if not raw:
        try:
            from .config import load_config
            raw = str(((load_config() or {}).get("client") or {}).get("id") or "").strip()
        except Exception:  # pragma: no cover - config never blocks path resolution
            raw = ""
    return raw


def _resolve() -> str | None:
    raw = _raw_client_id()
    if not raw:
        return None
    if not _CLIENT_RE.fullmatch(raw):
        # Resilient on the hot path (every data_dir call): an invalid id resolves
        # to None here so diagnostics/tests don't crash. Production fails closed
        # at the startup guard require_client_binding(), which raises rather than
        # let a misconfigured floor silently serve from the shared root.
        log.warning("[client] id %r is invalid (want %s); ignoring it",
                    raw, _CLIENT_RE.pattern)
        return None
    return raw


def client_id() -> str | None:
    """The deployment's bound client id, or ``None`` (legacy shared root).

    ``MAVERICK_CLIENT_ID`` wins over ``[client] id``. Cached for the process.
    """
    global _cached
    if _cached is _UNSET:
        _cached = _resolve()
    return _cached  # type: ignore[return-value]


def client_binding_enforced() -> bool:
    """Is a client binding REQUIRED to operate?

    On via ``MAVERICK_CLIENT_ENFORCE``, ``[client] enforce = true``, or
    enterprise mode (a deployment handling a real client's sensitive data must
    be provably bound to that client). Off by default."""
    env = os.environ.get("MAVERICK_CLIENT_ENFORCE")
    if env is not None and env.strip() != "":
        return is_truthy(env)
    try:
        from .enterprise import enterprise_enabled
        if enterprise_enabled():
            return True
    except Exception:  # pragma: no cover
        pass
    try:
        from .config import load_config
        return coerce_bool(((load_config() or {}).get("client") or {}).get("enforce"))
    except Exception:
        return False


def require_client_binding() -> str | None:
    """Fail-closed startup guard. Returns the bound client id.

    Raises :class:`ClientBindingError` when the binding is enforced but no valid
    client id is configured — so a client-bound surface never serves from the
    un-scoped shared root by accident. A no-op (returns ``None``) when binding
    is not enforced.
    """
    raw = _raw_client_id()
    if raw and not _CLIENT_RE.fullmatch(raw):
        # A configured-but-invalid id is an unambiguous misconfiguration of the
        # immutable binding (e.g. uppercase letters that would collide on a
        # case-insensitive filesystem). Fail closed at startup rather than
        # silently fall back to the shared root — regardless of enforce.
        raise ClientBindingError(
            f"[client] id {raw!r} is invalid: must match {_CLIENT_RE.pattern} "
            "(lowercase letters, digits, '.', '_', '-'; lowercase is required so "
            "the data directory can't collide with a differently-cased id on a "
            "case-insensitive filesystem). Refusing to start."
        )
    cid = client_id()
    if cid:
        return cid
    if client_binding_enforced():
        raise ClientBindingError(
            "client binding is enforced but no client id is configured. Set "
            "MAVERICK_CLIENT_ID (recommended, in the service unit) or "
            "[client] id in config. Refusing to start unbound so client data "
            "cannot land in the shared root."
        )
    return None


def data_root():
    """The resolved data root for this deployment (for doctor/diagnostics)."""
    from .paths import data_dir
    return data_dir()


def erase_client(*, keep_audit: bool = False) -> dict:
    """Erase ALL of this client's data (offboarding / right-to-erasure).

    Because one deployment serves exactly one client, the client's entire data
    set lives under one root (``data_dir()`` = ``tenants/<client>/``): world DB,
    cross-session memory, fleet memory, the managed trust registry, caches, and
    (unless ``keep_audit``) the audit chain. Wiping that tree is therefore a
    *provably complete* tenant erase — there is no other place the client's data
    resides on this node.

    Fail-closed: refuses unless a client is bound, so it can never target the
    shared/legacy root. Returns a summary. ``keep_audit=True`` preserves the
    signed audit chain for legal retention.

    NOTE: external stores a deployment may add (a remote Postgres/Qdrant/Redis)
    are out of scope here — erase those via their own admin path; this covers the
    on-node client tree.
    """
    cid = client_id()
    if not cid:
        raise ClientBindingError(
            "refusing to erase: no client is bound (this would target the shared "
            "root). Set MAVERICK_CLIENT_ID / [client] id first."
        )
    from .paths import data_dir
    root = data_dir()
    removed = 0
    if root.exists():
        for p in sorted(root.rglob("*"), key=lambda x: len(x.parts), reverse=True):
            rel = p.relative_to(root)
            if keep_audit and rel.parts and rel.parts[0] == "audit":
                continue
            try:
                if p.is_file() or p.is_symlink():
                    p.unlink()
                    removed += 1
                elif p.is_dir():
                    import contextlib
                    with contextlib.suppress(OSError):
                        p.rmdir()
            except OSError as e:  # pragma: no cover
                log.warning("erase: could not remove %s: %s", p, e)
    log.warning("client erase: removed %d path(s) under %s (keep_audit=%s)",
                removed, root, keep_audit)
    return {"client_id": cid, "root": str(root), "removed": removed,
            "kept_audit": keep_audit}


def status() -> dict:
    """Binding summary for ``maverick doctor`` / readiness."""
    cid = client_id()
    return {
        "client_id": cid,
        "enforced": client_binding_enforced(),
        "bound": bool(cid),
        "data_root": str(data_root()),
    }


__all__ = [
    "ClientBindingError",
    "client_id",
    "client_binding_enforced",
    "require_client_binding",
    "reset_client_cache",
    "data_root",
    "erase_client",
    "status",
]
