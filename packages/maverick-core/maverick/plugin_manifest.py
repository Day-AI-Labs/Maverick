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
from typing import Any, Optional

log = logging.getLogger(__name__)


# The kernel's current plugin API version. Bumped when we make
# breaking changes to the Tool/Channel/Skill/Persona contracts.
MAVERICK_API_VERSION = "1"


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
        return self.api_version == MAVERICK_API_VERSION


def _load_toml(path: Path) -> dict[str, Any]:
    try:
        import tomllib  # py>=3.11
    except ModuleNotFoundError:
        import tomli as tomllib  # py<3.11
    return tomllib.loads(path.read_text(encoding="utf-8"))


def parse(path: Path) -> Optional[PluginManifest]:
    """Parse a ``maverick-plugin.toml``. Returns None on missing/invalid file."""
    if not path.exists() or not path.is_file():
        return None
    try:
        data = _load_toml(path)
    except Exception as e:
        log.warning("plugin_manifest: invalid TOML at %s: %s", path, e)
        return None
    return parse_dict(data, source=str(path))


def parse_dict(data: dict[str, Any], *, source: str = "<inline>") -> Optional[PluginManifest]:
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
            f"api_version {manifest.api_version!r} != kernel "
            f"MAVERICK_API_VERSION {MAVERICK_API_VERSION!r}"
        )
    if not manifest.license:
        manifest.warnings.append("no license declared")
    if not manifest.author:
        manifest.warnings.append("no author declared")
    return manifest


__all__ = [
    "MAVERICK_API_VERSION",
    "PluginCapabilities",
    "PluginPermissions",
    "PluginManifest",
    "parse",
    "parse_dict",
]
