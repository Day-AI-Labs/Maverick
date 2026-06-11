"""Plugin version-pinning lockfile (roadmap: 2027 H2 ecosystem).

The plugin allowlist says *which* plugins may load; it says nothing about
*which version* — a routine ``pip install -U`` silently swaps the code the
operator vetted for whatever shipped last night. The lockfile closes that
gap: ``maverick plugin lock`` records each active plugin distribution's
version, and discovery verifies the installed versions against the lock,
refusing (or warning, per policy) on drift.

Scope: the distributions that provide maverick entry points — the deps tree
in general belongs to :mod:`maverick.supply_chain`. Policy knob::

    [plugins]
    lock_policy = "off" | "warn" | "enforce"     # default "off"

``warn`` logs drift and loads anyway; ``enforce`` skips the drifted plugin
(fail closed for that plugin only — the rest keep loading). The lockfile
lives at ``data_dir("plugins.lock.json")``, atomic write, 0600.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

log = logging.getLogger(__name__)

_POLICIES = ("off", "warn", "enforce")


def lock_path() -> Path:
    from .paths import data_dir
    return data_dir() / "plugins.lock.json"


def lock_policy() -> str:
    env = os.environ.get("MAVERICK_PLUGIN_LOCK_POLICY", "").strip().lower()
    if env in _POLICIES:
        return env
    try:
        from .config import load_config
        pol = str(((load_config() or {}).get("plugins") or {})
                  .get("lock_policy", "off")).strip().lower()
        return pol if pol in _POLICIES else "off"
    except Exception:  # pragma: no cover -- config never blocks discovery
        return "off"


def _active_plugin_dists() -> dict[str, str]:
    """{distribution_name: version} for every dist providing maverick entry
    points (whether or not currently allowlisted — the lock should survive
    allowlist edits)."""
    from . import plugins as plugins_mod
    dists: dict[str, str] = {}
    for group in ("maverick.tools", "maverick.channels",
                  "maverick.skills", "maverick.personas"):
        for ep in plugins_mod._entry_points(group):
            name = plugins_mod._ep_dist_name(ep)
            if not name:
                continue
            version = ""
            dist = getattr(ep, "dist", None)
            if dist is not None:
                version = str(getattr(dist, "version", "") or "")
            if not version:
                try:
                    from importlib.metadata import version as _v
                    version = _v(name)
                except Exception:
                    version = "unknown"
            dists[name] = version
    return dists


def write_lock(path: Path | None = None) -> dict[str, str]:
    """Record the active plugin distributions' versions. Returns the pins."""
    pins = _active_plugin_dists()
    p = Path(path) if path else lock_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(
        {"generated_at": time.time(), "pins": pins}, indent=2, sort_keys=True,
    ), encoding="utf-8")
    os.replace(tmp, p)
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass
    return pins


def read_lock(path: Path | None = None) -> dict[str, str] | None:
    p = Path(path) if path else lock_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        pins = data.get("pins")
        return {str(k): str(v) for k, v in pins.items()} if isinstance(pins, dict) else None
    except (OSError, ValueError):
        return None


def verify_lock(path: Path | None = None) -> dict:
    """Compare installed plugin dists against the lock.

    Returns ``{ok, drifted: [(name, pinned, installed)], unpinned: [...],
    missing: [...]}`` — ``ok`` iff no drift and nothing pinned is missing.
    No lockfile -> ``{ok: True, unlocked: True}`` (nothing to enforce).
    """
    pins = read_lock(path)
    if pins is None:
        return {"ok": True, "unlocked": True, "drifted": [], "unpinned": [], "missing": []}
    installed = _active_plugin_dists()
    drifted = [(n, pins[n], installed[n])
               for n in sorted(set(pins) & set(installed)) if pins[n] != installed[n]]
    missing = sorted(set(pins) - set(installed))
    unpinned = sorted(set(installed) - set(pins))
    return {"ok": not drifted and not missing, "unlocked": False,
            "drifted": drifted, "unpinned": unpinned, "missing": missing}


def dist_allowed_by_lock(dist_name: str | None) -> bool:
    """Per-dist gate used by plugin discovery.

    - policy off, or no lockfile: always True (today's behavior).
    - warn: True, but drift logs a warning (once per process per dist).
    - enforce: a drifted or unpinned dist is refused; pinned-and-matching
      loads. Unknown dist names load (can't be pinned).
    """
    policy = lock_policy()
    if policy == "off" or not dist_name:
        return True
    pins = read_lock()
    if pins is None:
        return True
    installed = _active_plugin_dists().get(dist_name)
    pinned = pins.get(dist_name)
    if pinned is None:
        if policy == "enforce":
            _warn_once(dist_name, f"plugin {dist_name} is not in plugins.lock; refusing (enforce)")
            return False
        return True
    if installed is not None and installed != pinned:
        msg = (f"plugin {dist_name} version drift: locked {pinned}, "
               f"installed {installed}")
        if policy == "enforce":
            _warn_once(dist_name, msg + "; refusing (enforce)")
            return False
        _warn_once(dist_name, msg)
    return True


_warned: set[str] = set()


def _warn_once(key: str, msg: str) -> None:
    if key not in _warned:
        _warned.add(key)
        log.warning("%s", msg)


def reset_warned() -> None:
    """Tests."""
    _warned.clear()


__all__ = ["lock_path", "lock_policy", "write_lock", "read_lock",
           "verify_lock", "dist_allowed_by_lock", "reset_warned"]
