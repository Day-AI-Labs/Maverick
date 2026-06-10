"""Plugin manifest schema + validation.

Third-party plugins published via the ``maverick.tools``/
``maverick.channels``/``maverick.skills``/``maverick.personas`` entry
points must ship a ``maverick-plugin.toml`` declaring:

  - API version they target (matched against ``MAVERICK_API_VERSION``)
  - Capabilities they expose (tools, channels, ...)
  - Permissions they request (network, fs writes, etc.)
  - Author + license + repo URL

At load time, the kernel validates the manifest. Mismatches surface
a warning (not a hard fail) so old plugins keep working while we
build out the ecosystem.

Schema (TOML):

    [plugin]
    name             = "my-plugin"
    version          = "0.1.0"
    api_version      = "1"
    description      = "Short description"
    author           = "Your Name <you@example.com>"
    license          = "MIT"
    repo             = "https://github.com/you/maverick-my-plugin"

    [plugin.capabilities]
    tools            = ["my_tool"]
    channels         = []
    skills           = []
    personas         = []

    [plugin.permissions]
    network          = false
    fs_write         = true
    subprocess       = false
    sensitive_envs   = []
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


# The kernel's current plugin API version. Bumped when we make
# breaking changes to the Tool/Channel/Skill/Persona contracts.
#
# v2 (released; see docs/plugin-api-v2.md): structured channel replies
# (``maverick_channels.Reply``), manifest permissions enforced by default,
# lockfile pinning, isolation modes, and TypeScript (NDJSON stdio) plugins.
# v1 plugins remain loadable through the deprecation window below.
MAVERICK_API_VERSION = "2"

# Majors the kernel still loads. v1 stays supported for one minor release
# (the RFC 0001 deprecation window) — a v1 plugin loads with a warning, a
# declared v3+ plugin is refused (forward-incompatible).
SUPPORTED_API_MAJORS = (1, 2)


def _major(api_version: str) -> int | None:
    """Parse a declared ``api_version`` to its MAJOR integer.

    Compatibility is by major version only, so ``"1"``, ``"1.0"``,
    ``"01"`` and ``"1.2"`` all map to ``1``. Returns None for a
    malformed/empty value so the caller can treat it as incompatible.
    """
    head = str(api_version or "").strip().split(".", 1)[0]
    try:
        return int(head)
    except ValueError:
        return None


@dataclass
class PluginCapabilities:
    tools: list[str] = field(default_factory=list)
    channels: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    personas: list[str] = field(default_factory=list)


@dataclass
class PluginPermissions:
    network: bool = False
    fs_write: bool = False
    subprocess: bool = False
    sensitive_envs: list[str] = field(default_factory=list)


@dataclass
class PluginManifest:
    name: str
    version: str
    api_version: str
    description: str = ""
    author: str = ""
    license: str = ""
    repo: str = ""
    capabilities: PluginCapabilities = field(default_factory=PluginCapabilities)
    permissions: PluginPermissions = field(default_factory=PluginPermissions)
    warnings: list[str] = field(default_factory=list)

    def is_compatible(self) -> bool:
        """True when the kernel loads this plugin's declared API major.

        Membership in ``SUPPORTED_API_MAJORS`` (not strict equality with the
        current version) so the v1 deprecation window works: v1 loads, the
        current v2 loads, an unknown v3+ is refused.
        """
        plugin_major = _major(self.api_version)
        if plugin_major is None:
            return False
        return plugin_major in SUPPORTED_API_MAJORS

    def is_deprecated_api(self) -> bool:
        """True for a compatible-but-older major (load with a warning)."""
        plugin_major = _major(self.api_version)
        current = _major(MAVERICK_API_VERSION)
        return (plugin_major is not None and current is not None
                and self.is_compatible() and plugin_major < current)


def _load_toml(path: Path) -> dict[str, Any]:
    try:
        import tomllib  # py>=3.11
    except ModuleNotFoundError:
        import tomli as tomllib  # py<3.11
    return tomllib.loads(path.read_text(encoding="utf-8"))


def parse(path: Path) -> PluginManifest | None:
    """Parse a ``maverick-plugin.toml``. Returns None on missing/invalid file."""
    if not path.exists() or not path.is_file():
        return None
    try:
        data = _load_toml(path)
    except Exception as e:
        log.warning("plugin_manifest: invalid TOML at %s: %s", path, e)
        return None
    return parse_dict(data, source=str(path))


def parse_text(text: str, *, source: str = "<text>") -> PluginManifest | None:
    """Parse manifest TOML text (e.g. read from an installed distribution)."""
    try:
        import tomllib  # py>=3.11
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore[no-redef]
    try:
        data = tomllib.loads(text)
    except Exception as e:
        log.warning("plugin_manifest: invalid TOML from %s: %s", source, e)
        return None
    return parse_dict(data, source=source)


def parse_dict(data: dict[str, Any], *, source: str = "<inline>") -> PluginManifest | None:
    """Parse a pre-loaded mapping. Useful for tests."""
    section = data.get("plugin") or data
    name = section.get("name")
    version = section.get("version")
    api_version = section.get("api_version")
    if not name or not version or not api_version:
        log.warning("plugin_manifest: %s missing required fields", source)
        return None
    cap_d = section.get("capabilities") or {}
    perm_d = section.get("permissions") or {}
    manifest = PluginManifest(
        name=str(name),
        version=str(version),
        api_version=str(api_version),
        description=str(section.get("description") or ""),
        author=str(section.get("author") or ""),
        license=str(section.get("license") or ""),
        repo=str(section.get("repo") or ""),
        capabilities=PluginCapabilities(
            tools=list(cap_d.get("tools") or []),
            channels=list(cap_d.get("channels") or []),
            skills=list(cap_d.get("skills") or []),
            personas=list(cap_d.get("personas") or []),
        ),
        permissions=PluginPermissions(
            network=bool(perm_d.get("network", False)),
            fs_write=bool(perm_d.get("fs_write", False)),
            subprocess=bool(perm_d.get("subprocess", False)),
            sensitive_envs=list(perm_d.get("sensitive_envs") or []),
        ),
    )
    if not manifest.is_compatible():
        manifest.warnings.append(
            f"api_version {manifest.api_version!r} not in supported majors "
            f"{SUPPORTED_API_MAJORS} (kernel is v{MAVERICK_API_VERSION})"
        )
    elif manifest.is_deprecated_api():
        manifest.warnings.append(
            f"api_version {manifest.api_version!r} is deprecated (kernel is "
            f"v{MAVERICK_API_VERSION}); v1 loads for one more minor release "
            "-- see docs/plugin-api-v2.md"
        )
    if not manifest.license:
        manifest.warnings.append("no license declared")
    if not manifest.author:
        manifest.warnings.append("no author declared")
    return manifest


__all__ = [
    "MAVERICK_API_VERSION",
    "SUPPORTED_API_MAJORS",
    "PluginCapabilities",
    "PluginPermissions",
    "PluginManifest",
    "parse",
    "parse_text",
    "parse_dict",
]
