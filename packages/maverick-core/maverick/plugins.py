"""Plugin SDK: discover and load third-party extensions via entry_points.

External packages can register Tools, Channels, Skills, or Personas by
declaring entry_points in their ``pyproject.toml``::

    [project.entry-points."maverick.tools"]
    weather = "myplugin:weather_tool"

    [project.entry-points."maverick.channels"]
    discordv2 = "myplugin:DiscordV2Channel"

    [project.entry-points."maverick.skills"]
    weather = "myplugin:WEATHER_SKILL"

    [project.entry-points."maverick.personas"]
    pirate = "myplugin:render_pirate"

Each loader is forgiving: a plugin that raises at load time logs the
error and is skipped -- one broken plugin can't take the swarm down.

Council finding (Tier 0): the loader used to execute every installed
entry_point on first agent run. Anyone who `pip install`-ed a package
declaring `[project.entry-points."maverick.tools"]` got arbitrary
in-process code execution before any shield was built. Plugins now
require an explicit allowlist in config -- set ``MAVERICK_PLUGINS_ALLOW``
or ``[plugins] enabled = ["weather", ...]`` in ``~/.maverick/config.toml``.
Set ``MAVERICK_PLUGINS_ALLOW=*`` (or ``[plugins] enabled = ["*"]``) to
load everything (matches the pre-0.2 behavior). Empty / unset = no
plugins loaded.

Each plugin entry must conform to a contract:

  - ``maverick.tools``: callable that returns a ``maverick.tools.Tool``
    when invoked with no args. The tool is registered in every agent's
    base registry under its declared name.
  - ``maverick.channels``: a ``Channel`` subclass (NOT an instance --
    `maverick serve` constructs one with the handler bound).
  - ``maverick.skills``: a ``maverick.skills.Skill`` instance.
  - ``maverick.personas``: callable returning a system-prompt suffix
    string, addressed by name via ``[persona] name = "..."``.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Callable, Optional

log = logging.getLogger(__name__)


def _allowed_plugin_names() -> Optional[set[str]]:
    """Return the set of enabled plugin names, or None if all are enabled.

    Resolution order:
      1. ``MAVERICK_PLUGINS_ALLOW`` env var (comma-separated; ``*`` = all)
      2. ``[plugins] enabled = [...]`` in ~/.maverick/config.toml
      3. Default: empty set (no plugins loaded)
    """
    raw = os.environ.get("MAVERICK_PLUGINS_ALLOW")
    if raw is None:
        try:
            from .config import load_config
            cfg = load_config()
            enabled = cfg.get("plugins", {}).get("enabled")
            if enabled is None:
                return set()
            if isinstance(enabled, str):
                raw = enabled
            else:
                items = {str(x).strip() for x in enabled}
                return None if "*" in items else items
        except Exception as exc:
            # Council finding: bare except swallowed TOML parse errors,
            # silently disabling every plugin with no diagnostic. Log
            # the failure so a misconfigured user has something to grep.
            log.warning(
                "plugin allowlist read from config failed (%s: %s); "
                "loading no plugins",
                type(exc).__name__, exc,
            )
            return set()
    if raw is None:
        return set()
    items = {p.strip() for p in raw.split(",") if p.strip()}
    if "*" in items:
        return None
    return items


def _entry_points(group: str):
    """Iterate entry_points for a group. Empty iterable if none registered.

    Wrapper handles the stdlib API drift between Python 3.10 and 3.12+.
    """
    try:
        from importlib.metadata import entry_points
    except ImportError:  # pragma: no cover -- 3.10+ always has this
        return []
    try:
        eps = entry_points(group=group)
    except TypeError:
        # 3.9 fallback (we don't support it but keep this defensive)
        eps = entry_points().get(group, [])  # type: ignore[attr-defined]
    return eps


def _load(ep, what: str) -> Optional[Any]:
    """Resolve an entry point's target with logging on failure."""
    try:
        return ep.load()
    except Exception as e:
        log.warning("plugin %s.%s failed to load: %s", what, ep.name, e)
        return None


def _ep_dist_name(ep) -> Optional[str]:
    """Providing distribution name for an entry point, or None.

    ``ep.dist`` exists on importlib.metadata 3.10+, but be defensive.
    """
    dist = getattr(ep, "dist", None)
    name = getattr(dist, "name", None) if dist is not None else None
    return str(name) if name else None


def _is_allowed(ep, allowlist: Optional[set[str]]) -> bool:
    """allowlist=None means 'all allowed' (the wildcard case).

    Otherwise the allowlist entry may be the bare entry-point name
    (``weather``) OR a distribution-qualified name (``my-dist:weather``).
    Matching the qualified form defends against name-squatting (#463): a
    hostile package declaring a ``maverick.tools`` entry point named
    ``weather`` no longer silently satisfies an allowlist of ``weather``
    when a different dist is expected — the operator can pin
    ``expected-dist:weather``. The bare name is still honored for the
    common single-provider case.
    """
    if allowlist is None:
        return True
    name = getattr(ep, "name", "")
    if name in allowlist:
        return True
    dist = _ep_dist_name(ep)
    return bool(dist and f"{dist}:{name}" in allowlist)


def _eligible(group: str, what: str):
    """Yield allowlisted entry points for ``group``, deduped by name.

    Dedup (#463): two installed distributions can declare the same
    entry-point name; loading both executes two different packages' code
    under one name. We keep the FIRST and warn about the shadowing one
    (qualified by dist so the operator can tell them apart).
    """
    allow = _allowed_plugin_names()
    seen: dict[str, Optional[str]] = {}
    for ep in _entry_points(group):
        name = getattr(ep, "name", "")
        if not _is_allowed(ep, allow):
            log.debug("plugin %s %s not in allowlist; skipping", what, name)
            continue
        if name in seen:
            log.warning(
                "duplicate plugin %s entry point %r (kept dist=%s, ignoring "
                "dist=%s); disambiguate with a dist-qualified allowlist entry",
                what, name, seen[name] or "?", _ep_dist_name(ep) or "?",
            )
            continue
        seen[name] = _ep_dist_name(ep)
        yield ep


def discover_tools() -> list[Any]:
    """Return a list of (name, factory) tuples for installed tool plugins.

    The factory is called with no args; it must return a Tool. We delay
    invocation because Tool constructors may need access to the
    sandbox/world that only exists per-run.
    """
    out: list[tuple[str, Callable[[], Any]]] = []
    for ep in _eligible("maverick.tools", "tool"):
        target = _load(ep, "tools")
        if target is None:
            continue
        if not callable(target):
            log.warning("plugin tool %s is not callable; skipping", ep.name)
            continue
        out.append((ep.name, target))
    return out


def discover_channels() -> list[tuple[str, Any]]:
    """Return (name, Channel subclass) tuples for installed channel plugins."""
    out: list[tuple[str, Any]] = []
    for ep in _eligible("maverick.channels", "channel"):
        target = _load(ep, "channels")
        if target is None:
            continue
        # Heuristic: anything truthy + not a string passes; we don't import
        # the Channel base here to avoid a hard dep on maverick-channels.
        if isinstance(target, str):
            log.warning("plugin channel %s loaded a string; skipping", ep.name)
            continue
        out.append((ep.name, target))
    return out


def discover_skills() -> list[Any]:
    """Return a list of plugin-provided Skill objects."""
    out: list[Any] = []
    for ep in _eligible("maverick.skills", "skill"):
        target = _load(ep, "skills")
        if target is None:
            continue
        out.append(target)
    return out


def discover_personas() -> dict[str, Callable[[], str]]:
    """Return {name: renderer} for installed persona plugins."""
    out: dict[str, Callable[[], str]] = {}
    for ep in _eligible("maverick.personas", "persona"):
        target = _load(ep, "personas")
        if target is None:
            continue
        if not callable(target):
            log.warning("plugin persona %s is not callable; skipping", ep.name)
            continue
        out[ep.name] = target
    return out


def installed_plugins() -> dict[str, list[str]]:
    """Snapshot of all plugin slots. Used by `maverick version --plugins`."""
    return {
        "tools":     [name for name, _ in discover_tools()],
        "channels":  [name for name, _ in discover_channels()],
        "skills":    [getattr(s, "name", "<unnamed>") for s in discover_skills()],
        "personas":  list(discover_personas()),
    }
