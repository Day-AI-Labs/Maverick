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

Two further load-time controls layer on top of the allowlist:

  - **Name-squat defense.** The allowlist matches entry-point *names*, but
    any installed package can register a given name. If two distributions
    both publish the same name (e.g. an attacker shadowing ``weather``), the
    loader refuses to load it ambiguously -- the user must pin the trusted
    provider as ``[plugins] enabled = ["weather@trusted-dist"]``.
  - **Manifest permissions.** A plugin may ship a ``maverick-plugin.toml``
    (see ``plugin_manifest``) declaring the permissions it needs
    (``network`` / ``fs_write`` / ``subprocess`` / ``sensitive_envs``). The
    user grants permissions via ``[plugins] grant = [...]``. A plugin that
    requests an ungranted permission is loaded with a warning by default, or
    skipped entirely when ``[plugins] enforce_permissions = true`` (or
    ``MAVERICK_PLUGINS_ENFORCE=1``).

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
from collections.abc import Callable
from typing import Any

from .embeddable import no_cli

log = logging.getLogger(__name__)

# Grantable permission names a manifest can request (see plugin_manifest).
_KNOWN_PERMISSIONS = ("network", "fs_write", "subprocess", "sensitive_envs")


def _plugins_config() -> dict:
    """Return the ``[plugins]`` config section, or {} (defensive)."""
    try:
        from .config import load_config
        cfg = load_config().get("plugins", {})
        return cfg if isinstance(cfg, dict) else {}
    except Exception as exc:
        log.warning(
            "plugin config read failed (%s: %s); treating as empty",
            type(exc).__name__, exc,
        )
        return {}


def _allowed_plugin_names() -> set[str] | None:
    """Return the set of enabled plugin names, or None if all are enabled.

    Resolution order:
      1. ``MAVERICK_PLUGINS_ALLOW`` env var (comma-separated; ``*`` = all)
      2. ``[plugins] enabled = [...]`` in ~/.maverick/config.toml
      3. Default: empty set (no plugins loaded)

    Entries may be a bare name (``weather``) or a dist-pinned ``name@dist``
    used to disambiguate a name published by more than one package.
    """
    raw = os.environ.get("MAVERICK_PLUGINS_ALLOW")
    # Treat an exported-but-blank env var as unset (common from CI/systemd/shell
    # wrappers) so it falls through to the config allowlist instead of silently
    # disabling every configured plugin.
    if raw is not None and not raw.strip():
        raw = None
    if raw is None:
        # Council finding: a bare except here used to swallow TOML parse errors,
        # silently disabling every plugin with no diagnostic. _plugins_config
        # logs + returns {} on failure, so a misconfigured user has something
        # to grep and we fall through to the empty (no-plugins) default.
        enabled = _plugins_config().get("enabled")
        if enabled is None:
            return set()
        if isinstance(enabled, str):
            raw = enabled
        else:
            items = {str(x).strip() for x in enabled if str(x).strip()}
            return None if "*" in items else items
    items = {p.strip() for p in raw.split(",") if p.strip()}
    if "*" in items:
        return None
    return items


def _permission_policy() -> tuple[set[str], bool]:
    """Return ``(granted_permissions, enforce)``.

    Default is "nothing granted, warn-only" so existing installs keep working
    (a plugin requesting a permission is loaded with a warning). Set
    ``[plugins] grant = ["network", ...]`` to grant, and
    ``[plugins] enforce_permissions = true`` (or ``MAVERICK_PLUGINS_ENFORCE=1``)
    to *skip* plugins requesting an ungranted permission instead of warning.
    """
    cfg = _plugins_config()
    grant = cfg.get("grant")
    if isinstance(grant, str):
        granted = {grant.strip().lower()} if grant.strip() else set()
    elif isinstance(grant, (list, tuple, set)):
        granted = {str(x).strip().lower() for x in grant if str(x).strip()}
    else:
        granted = set()
    enforce = bool(cfg.get("enforce_permissions", False))
    env = os.environ.get("MAVERICK_PLUGINS_ENFORCE")
    if env is not None and env.strip():
        enforce = env.strip().lower() in ("1", "true", "yes")
    return granted, enforce


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


def _load(ep, what: str) -> Any | None:
    """Resolve an entry point's target with logging on failure."""
    try:
        return ep.load()
    except Exception as e:
        log.warning("plugin %s.%s failed to load: %s", what, ep.name, e)
        return None


def _ep_dist_name(ep) -> str | None:
    """Best-effort distribution (package) name that provides ``ep``.

    None when it can't be determined (older metadata, test stubs). We only
    flag a name-squat when the providing distribution is *known*, so an
    unidentifiable entry point is never blocked on ambiguity grounds.
    """
    dist = getattr(ep, "dist", None)
    if dist is None:
        return None
    name = getattr(dist, "name", None)
    if name:
        return str(name)
    try:  # 3.10 fallback: name via metadata
        return str(dist.metadata["Name"])
    except Exception:
        return None


def _name_dist_map(eps) -> dict[str, set[str]]:
    """Map entry-point name -> set of distinct *known* distributions providing it.

    Used to detect name-squatting: a name backed by 2+ distributions is
    ambiguous. Entry points with an unknown distribution are not counted, so
    only proven collisions are flagged.
    """
    out: dict[str, set[str]] = {}
    for ep in eps:
        dist = _ep_dist_name(ep)
        if dist is None:
            continue
        out.setdefault(ep.name, set()).add(dist)
    return out


def _is_allowed(ep_name: str, allowlist: set[str] | None) -> bool:
    """Name-only allowlist check. allowlist=None means 'all allowed'.

    Kept for callers (e.g. ``hooks``) that gate by name without distribution
    context. The plugin loaders below use ``_allowed`` for dist-aware checks.
    """
    if allowlist is None:
        return True
    return ep_name in allowlist


def _allowed(ep_name: str, dist_name: str | None, allowlist: set[str] | None) -> bool:
    """Dist-aware allowlist check. allowlist=None means 'all allowed'.

    Matches either the bare ``name`` or the pinned ``name@dist`` form, so a
    user can disambiguate a squatted name by pinning the provider they trust.
    """
    if allowlist is None:
        return True
    if ep_name in allowlist:
        return True
    return bool(dist_name) and f"{ep_name}@{dist_name}" in allowlist


def _find_manifest(ep):
    """Locate + parse the plugin's ``maverick-plugin.toml`` via its distribution.

    Returns a ``PluginManifest`` or None (no distribution, no manifest file, or
    a parse failure). Never raises -- manifest problems must not break loading.
    """
    dist = getattr(ep, "dist", None)
    if dist is None:
        return None
    try:
        files = list(dist.files or [])
    except Exception:
        return None
    for f in files:
        if getattr(f, "name", "") != "maverick-plugin.toml":
            continue
        text = None
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            try:
                text = dist.locate_file(f).read_text(encoding="utf-8")
            except Exception:
                text = None
        if text is None:
            return None
        from .plugin_manifest import parse_text
        return parse_text(text, source=_ep_dist_name(ep) or "<plugin>")
    return None


def _permission_violations(manifest, granted: set[str]) -> list[str]:
    """Permissions the manifest requests that aren't in the granted set."""
    if manifest is None:
        return []
    perms = manifest.permissions
    requested: list[str] = []
    if perms.network:
        requested.append("network")
    if perms.fs_write:
        requested.append("fs_write")
    if perms.subprocess:
        requested.append("subprocess")
    if perms.sensitive_envs:
        requested.append("sensitive_envs")
    return [r for r in requested if r not in granted]


def _gate(ep, group: str, allow, name_dists, granted, enforce) -> bool:
    """Decide whether ``ep`` may load: allowlist + name-squat + permission gate.

    Returns True to load. Never invokes the entry point, so a rejected plugin's
    code never executes.
    """
    name = ep.name
    dist = _ep_dist_name(ep)
    if not _allowed(name, dist, allow):
        log.debug("plugin %s.%s not in allowlist; skipping", group, name)
        return False
    # Name-squat: a name backed by 2+ distinct distributions is ambiguous.
    # Refuse unless the allowlist pins the exact provider as 'name@dist'.
    providers = name_dists.get(name, set())
    if len(providers) > 1:
        pinned = (
            allow is not None and dist is not None and f"{name}@{dist}" in allow
        )
        if not pinned:
            log.warning(
                "plugin name %r is provided by multiple packages %s; refusing to "
                'load ambiguously -- pin the one you trust with [plugins] '
                'enabled = ["%s@<dist>"]',
                name, sorted(providers), name,
            )
            return False
    # Manifest-declared permissions vs the user's grant.
    violations = _permission_violations(_find_manifest(ep), granted)
    if violations:
        if enforce:
            log.warning(
                "plugin %s.%s (%s) requests ungranted permission(s) %s; skipping. "
                "Grant via [plugins] grant=[...] or unset enforce_permissions.",
                group, name, dist or "unknown-dist", violations,
            )
            return False
        log.warning(
            "plugin %s.%s (%s) requests permission(s) %s not in [plugins] grant; "
            "loading anyway (enforce_permissions is off).",
            group, name, dist or "unknown-dist", violations,
        )
    return True


def _iter_loaded(group: str, what: str):
    """Yield ``(name, target)`` for entry points in ``group`` that pass the
    allowlist + name-squat + permission gates and load successfully.

    Embedded mode (``MAVERICK_NO_CLI=1``) skips third-party auto-discovery
    entirely: a library embedder drives the toolset programmatically and
    shouldn't inherit whatever plugins happen to be installed/allowlisted in
    the host environment. The kernel's own tools/channels are unaffected.
    """
    if no_cli():
        return
    eps = list(_entry_points(group))
    if not eps:
        return
    name_dists = _name_dist_map(eps)
    allow = _allowed_plugin_names()
    granted, enforce = _permission_policy()
    for ep in eps:
        if not _gate(ep, group, allow, name_dists, granted, enforce):
            continue
        target = _load(ep, what)
        if target is None:
            continue
        yield ep.name, target


def discover_tools() -> list[Any]:
    """Return a list of (name, factory) tuples for installed tool plugins.

    The factory is called with no args; it must return a Tool. We delay
    invocation because Tool constructors may need access to the
    sandbox/world that only exists per-run.
    """
    out: list[tuple[str, Callable[[], Any]]] = []
    for name, target in _iter_loaded("maverick.tools", "tools"):
        if not callable(target):
            log.warning("plugin tool %s is not callable; skipping", name)
            continue
        out.append((name, target))
    return out


def discover_channels() -> list[tuple[str, Any]]:
    """Return (name, Channel subclass) tuples for installed channel plugins."""
    out: list[tuple[str, Any]] = []
    for name, target in _iter_loaded("maverick.channels", "channels"):
        # Heuristic: anything truthy + not a string passes; we don't import
        # the Channel base here to avoid a hard dep on maverick-channels.
        if isinstance(target, str):
            log.warning("plugin channel %s loaded a string; skipping", name)
            continue
        out.append((name, target))
    return out


def discover_skills() -> list[Any]:
    """Return a list of plugin-provided Skill objects."""
    return [target for _, target in _iter_loaded("maverick.skills", "skills")]


def discover_personas() -> dict[str, Callable[[], str]]:
    """Return {name: renderer} for installed persona plugins."""
    out: dict[str, Callable[[], str]] = {}
    for name, target in _iter_loaded("maverick.personas", "personas"):
        if not callable(target):
            log.warning("plugin persona %s is not callable; skipping", name)
            continue
        out[name] = target
    return out


def installed_plugins() -> dict[str, list[str]]:
    """Snapshot of all plugin slots. Used by `maverick version --plugins`."""
    return {
        "tools":     [name for name, _ in discover_tools()],
        "channels":  [name for name, _ in discover_channels()],
        "skills":    [getattr(s, "name", "<unnamed>") for s in discover_skills()],
        "personas":  list(discover_personas()),
    }
