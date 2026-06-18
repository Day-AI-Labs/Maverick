"""``maverick support`` — a redacted diagnostics bundle for a support ticket.

Filing a ticket previously meant hand-running ``version`` + ``doctor`` + ``diag``
+ ``logs`` and manually redacting config. This assembles one structured,
**secret-redacted** snapshot (versions, runtime, client binding, readiness, a
redacted config, and a recent-failures summary) so an operator can attach a
single file. Best-effort: every section is independently guarded, so a failure
in one never blocks the rest.
"""
from __future__ import annotations

import platform
import sys
import time
from typing import Any

# Config keys whose VALUE is a credential — redacted by name regardless of the
# value-level secret scrubber (which only catches recognised secret shapes).
_SECRET_KEY_HINTS = (
    "key", "token", "secret", "password", "passwd", "credential", "dsn",
)


def _redact(obj: Any) -> Any:
    """Recursively redact a config tree: drop values under secret-named keys,
    and run the value-level secret scrubber over every remaining string."""
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            if isinstance(k, str) and any(h in k.lower() for h in _SECRET_KEY_HINTS):
                out[k] = "[REDACTED]" if v not in (None, "", {}, []) else v
            else:
                out[k] = _redact(v)
        return out
    if isinstance(obj, list):
        return [_redact(v) for v in obj]
    if isinstance(obj, str):
        try:
            from .secrets import scrub
            return scrub(obj)
        except Exception:  # pragma: no cover - never let scrubbing block the bundle
            return "[unscrubbable]"
    return obj


def _versions() -> dict:
    import importlib.metadata as md
    pkgs = {
        "maverick-agent": ("maverick-agent", "maverick"),
        "maverick-shield": ("maverick-shield",),
        "maverick-channels": ("maverick-channels",),
        "maverick-dashboard": ("maverick-dashboard",),
        "maverick-mcp-server": ("maverick-mcp-server",),
        "maverick-installer": ("maverick-installer",),
    }
    out: dict[str, str] = {}
    for display, candidates in pkgs.items():
        for c in candidates:
            try:
                out[display] = md.version(c)
                break
            except md.PackageNotFoundError:
                continue
        else:
            out[display] = "not installed"
    return out


def _runtime() -> dict:
    info: dict[str, Any] = {
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "machine": platform.machine(),
    }
    try:
        from .world_model import SCHEMA_VERSION
        info["world_schema_version"] = SCHEMA_VERSION
    except Exception:
        pass
    try:
        from maverick_shield import Shield
        info["shield_backend"] = Shield.from_config(warn_if_missing=False).backend
    except Exception:
        info["shield_backend"] = "not installed"
    return info


def _readiness() -> dict:
    """The same deep checks /readyz and doctor run (client binding, shield,
    agent-trust), as pass/fail strings."""
    checks: dict[str, str] = {}
    try:
        from .client import client_binding_enforced, client_id
        checks["client_binding"] = (
            "fail: enforced but no valid client id"
            if client_binding_enforced() and not client_id() else "ok")
    except Exception as e:  # pragma: no cover
        checks["client_binding"] = f"unknown: {type(e).__name__}"
    try:
        from .shield_policy import shield_available, shield_required
        checks["shield"] = (
            "fail: required but unavailable"
            if shield_required() and not shield_available() else "ok")
    except Exception as e:  # pragma: no cover
        checks["shield"] = f"unknown: {type(e).__name__}"
    try:
        from .agent_trust import load_trust_state
        enforced, registry = load_trust_state()
        checks["agent_trust"] = (
            "fail: engaged but registry empty"
            if enforced and not registry else "ok")
    except Exception as e:  # pragma: no cover
        checks["agent_trust"] = f"unknown: {type(e).__name__}"
    return checks


def _providers() -> dict:
    out: dict[str, Any] = {}
    try:
        from .config import any_provider_configured
        out["any_configured"] = any_provider_configured()
    except Exception:
        out["any_configured"] = None
    try:
        from .providers import KNOWN_PROVIDERS
        out["known"] = list(KNOWN_PROVIDERS)
    except Exception:
        pass
    return out


def _recent_failures() -> dict:
    out: dict[str, Any] = {}
    try:
        from .failure_telemetry import summarize
        out["failure_modes"] = summarize()
    except Exception:
        out["failure_modes"] = "unavailable"
    try:
        from .job_queue import JobQueue
        failed = JobQueue().list(status="failed", limit=20)
        out["failed_jobs"] = [
            {"id": getattr(j, "id", None), "kind": getattr(j, "kind", None),
             "last_error": (getattr(j, "last_error", "") or "")[:200]}
            for j in failed
        ]
    except Exception:
        out["failed_jobs"] = "unavailable"
    return out


def collect() -> dict:
    """Assemble the full redacted diagnostics bundle."""
    bundle: dict[str, Any] = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "versions": _versions(),
        "runtime": _runtime(),
        "readiness": _readiness(),
        "providers": _providers(),
        "recent_failures": _recent_failures(),
    }
    try:
        from .client import status as client_status
        bundle["client"] = client_status()
    except Exception:
        bundle["client"] = "unavailable"
    try:
        from .config import load_config
        bundle["config_redacted"] = _redact(load_config() or {})
    except Exception:
        bundle["config_redacted"] = "unavailable"
    return bundle


__all__ = ["collect"]
