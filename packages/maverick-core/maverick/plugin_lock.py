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

import hashlib
import json
import logging
import os
import time
from pathlib import Path

log = logging.getLogger(__name__)

_POLICIES = ("off", "warn", "enforce")


def _dist_content_hash(dist_name: str) -> str | None:
    """SHA-256 over a distribution's installed Python sources (deterministic).

    Closes the "same version, different bytes" hole that version pinning alone
    can't catch: a malicious rebuild that keeps the version number, or a locally
    tampered file, changes this hash. Hashes only ``.py`` sources (sorted by
    path) so compiled ``.pyc`` nondeterminism and metadata churn don't perturb
    it. Returns None when the file list isn't introspectable (then we fall back
    to version-only pinning rather than pinning a partial/empty hash)."""
    try:
        from importlib.metadata import files as _meta_files
        pkg_files = _meta_files(dist_name) or []
    except Exception:
        return None
    pys = sorted((f for f in pkg_files if str(f).endswith(".py")), key=str)
    if not pys:
        return None
    h = hashlib.sha256()
    for f in pys:
        try:
            # PackagePath exposes locate() (the concrete path), not read_bytes().
            data = Path(f.locate()).read_bytes()
        except Exception:
            return None  # can't read a source -> don't pin a partial hash
        h.update(str(f).encode("utf-8"))
        h.update(b"\0")
        h.update(data)
        h.update(b"\0")
    return h.hexdigest()


def lock_path() -> Path:
    from .paths import data_dir
    return data_dir() / "plugins.lock.json"


def _enterprise_default_policy() -> str:
    """Lock policy when nothing is configured: ``enforce`` under enterprise mode
    (a regulated deployment refuses drifted/unpinned plugins once a lockfile
    exists -- and it's a no-op with no lockfile, so it never breaks a fresh
    install), ``off`` for single-tenant/dev."""
    try:
        from .enterprise import enterprise_enabled
        return "enforce" if enterprise_enabled() else "off"
    except Exception:  # pragma: no cover -- config never blocks discovery
        return "off"


def lock_policy() -> str:
    """``MAVERICK_PLUGIN_LOCK_POLICY`` env wins over ``[plugins] lock_policy``.
    When neither is set the default depends on the deployment profile (see
    :func:`_enterprise_default_policy`); an explicit setting always wins."""
    env = os.environ.get("MAVERICK_PLUGIN_LOCK_POLICY", "").strip().lower()
    if env in _POLICIES:
        return env
    try:
        from .config import load_config
        raw = ((load_config() or {}).get("plugins") or {}).get("lock_policy")
    except Exception:  # pragma: no cover -- config never blocks discovery
        return _enterprise_default_policy()
    if raw is not None:
        pol = str(raw).strip().lower()
        if pol in _POLICIES:
            return pol
    return _enterprise_default_policy()


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
    """Record the active plugin distributions' versions AND content hashes.

    Returns the version pins. The content hash (where introspectable) lets
    enforce mode detect a tampered-but-same-version plugin, not just a version
    bump. Additive: a lockfile from before this change has no ``hashes`` block
    and simply keeps version-only semantics."""
    pins = _active_plugin_dists()
    hashes = {n: h for n in pins if (h := _dist_content_hash(n)) is not None}
    p = Path(path) if path else lock_path()
    # Unique temp + os.replace (0600): a fixed ".tmp" collides if two CLI
    # invocations regenerate the lockfile concurrently.
    from .file_lock import atomic_write_text
    atomic_write_text(p, json.dumps(
        {"generated_at": time.time(), "pins": pins, "hashes": hashes},
        indent=2, sort_keys=True,
    ))
    return pins


def read_hashes(path: Path | None = None) -> dict[str, str]:
    """The pinned ``{dist_name: content_hash}`` map (empty for legacy locks)."""
    p = Path(path) if path else lock_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        hashes = data.get("hashes")
        return {str(k): str(v) for k, v in hashes.items()} if isinstance(hashes, dict) else {}
    except (OSError, ValueError):
        return {}


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
    missing: [...]}`` — ``ok`` iff no drift, missing pins, or unpinned dists.
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
    return {"ok": not drifted and not missing and not unpinned, "unlocked": False,
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
    # Content-integrity check: a pinned hash that no longer matches means the
    # code changed even though the version did not -- a tampered or swapped
    # build. Only checked when a hash was pinned (newer lockfiles) and the
    # current files are introspectable; otherwise we fall back to version-only.
    pinned_hash = read_hashes().get(dist_name)
    if pinned_hash:
        current_hash = _dist_content_hash(dist_name)
        if current_hash is not None and current_hash != pinned_hash:
            hmsg = (f"plugin {dist_name} content drift: code changed since lock "
                    f"(same version {pinned})")
            if policy == "enforce":
                _warn_once(dist_name + ":hash", hmsg + "; refusing (enforce)")
                return False
            _warn_once(dist_name + ":hash", hmsg)
    return True


_warned: set[str] = set()


def _warn_once(key: str, msg: str) -> None:
    if key not in _warned:
        _warned.add(key)
        log.warning("%s", msg)


def reset_warned() -> None:
    """Tests."""
    _warned.clear()


__all__ = ["lock_path", "lock_policy", "write_lock", "read_lock", "read_hashes",
           "verify_lock", "dist_allowed_by_lock", "reset_warned"]
