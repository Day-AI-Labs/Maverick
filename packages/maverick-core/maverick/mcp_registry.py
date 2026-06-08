"""MCP server registry: discover + install external MCP servers by name.

The remote-HTTP client transport (`mcp_client.StreamableHttpMCPClient`) and the
stdio client let Maverick *consume* MCP servers once they're in
``[mcp_servers.<name>]``; this module is the missing **discovery + install**
layer (ROADMAP B2 "Registry"). It reuses the generic federated catalog
(`catalog.load_catalog("mcp")`) so a registry is just a self-hostable
``<base>/mcp/index.json`` — point ``[mcp_registries] indexes`` at your own.

Unlike skills (whose installable artifact is a fetched ``SKILL.md`` verified by
``sha256``), an MCP server's installable artifact is *configuration*: a spec
(command/args/env or url/headers). So a registry entry carries that spec
**inline** (`CatalogEntry.spec`), and the supply-chain defense is the spec's
``pin_sha256`` — verified against the resolved executable at spawn time by
`MCPClient.start()` (the CVE-2026-30615 class) — not a hash of the spec text.

Install validates the spec through `MCPServerSpec.from_config` (the same
subprocess-injection / url checks the kernel applies to hand-written config),
then applies registry-specific hardening before writing it to
``~/.maverick/config.toml`` under ``[mcp_servers.<name>]``.
"""
from __future__ import annotations

import logging
import re

from . import catalog
from .mcp_client import MCPServerSpec

log = logging.getLogger(__name__)

# Default registry host: the same awesome-maverick base the skills catalog uses
# (it serves ``/mcp/index.json`` alongside ``/skills/index.json``). Override with
# ``[mcp_registries] indexes`` in config or by passing ``indexes=`` explicitly.
DEFAULT_MCP_REGISTRIES = catalog.DEFAULT_INDEXES

_REGISTRY_EVAL_FLAGS = {
    "sh": {"-c"},
    "bash": {"-c"},
    "dash": {"-c"},
    "zsh": {"-c"},
    "fish": {"-c"},
    "ksh": {"-c"},
    "csh": {"-c"},
    "tcsh": {"-c"},
    "python": {"-c"},
    "python2": {"-c"},
    "python3": {"-c"},
    "node": {"-e", "--eval", "-p", "--print"},
    "perl": {"-e", "-E"},
    "ruby": {"-e"},
    "php": {"-r", "-B", "-R", "-E"},
    "lua": {"-e"},
    "powershell": {"-command", "-encodedcommand", "-enc"},
    "pwsh": {"-command", "-encodedcommand", "-enc"},
    "cmd": {"/c", "/k"},
}

_BARE_KEY_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _configured_mcp_registries() -> list[str]:
    """Registry base URLs from ``[mcp_registries] indexes``, else the default.

    Kept separate from skills' ``[catalogs] indexes`` because MCP registries are
    typically different hosts (e.g. the official MCP registry vs an awesome-list).
    """
    try:
        from .config import load_config
        cfg = (load_config() or {}).get("mcp_registries") or {}
        indexes = cfg.get("indexes")
        if isinstance(indexes, list) and indexes:
            return [str(i).rstrip("/") for i in indexes]
    except Exception as e:  # pragma: no cover -- never block discovery on config
        log.debug("mcp registry: config read failed: %s", e)
    return [i.rstrip("/") for i in DEFAULT_MCP_REGISTRIES]


def load_mcp_registry(*, indexes: list[str] | None = None) -> list[catalog.CatalogEntry]:
    """Return merged MCP server entries across all configured registries."""
    return catalog.load_catalog(
        "mcp", indexes=indexes if indexes is not None else _configured_mcp_registries())


def resolve_mcp(name: str, *, indexes: list[str] | None = None) -> catalog.CatalogEntry | None:
    """Find a single MCP registry entry by name, or None."""
    return catalog.resolve(
        name, "mcp", indexes=indexes if indexes is not None else _configured_mcp_registries())


def _command_basename(command: str) -> str:
    """Return a normalized executable basename for registry policy checks."""
    base = command.replace("\\", "/").rsplit("/", 1)[-1].lower()
    if base.endswith(".exe"):
        base = base[:-4]
    return base


def _validate_registry_spec(spec: MCPServerSpec) -> None:
    """Apply extra policy for untrusted registry-sourced stdio specs.

    Operator-authored config may intentionally launch arbitrary local commands,
    but registry entries are network-fed data. Require stdio registry entries to
    pin their executable and reject shell/interpreter inline-eval forms such as
    ``sh -c`` or ``node -e`` that turn the registry args into host code.
    """
    if spec.is_http:
        return
    if not spec.pin_sha256:
        raise ValueError(
            f"MCP registry entry {spec.name!r} uses stdio command {spec.command!r} "
            "without pin_sha256; registry-installed commands must pin the "
            "executable hash"
        )
    # Reject inline-eval whether the interpreter is the command itself
    # (``sh -c``) or smuggled through argv by a wrapper (``busybox sh -c``,
    # ``env sh -c``, ``xargs sh -c``, ``nice sh -c``). Treat the command and
    # every arg position as a potential interpreter and scan the tokens that
    # follow it for that interpreter's eval flag.
    argv = [spec.command, *spec.args]
    for i, token in enumerate(argv):
        eval_flags = _REGISTRY_EVAL_FLAGS.get(_command_basename(token))
        if not eval_flags:
            continue
        lowered_flags = {flag.lower() for flag in eval_flags}
        for arg in argv[i + 1:]:
            if arg.split("=", 1)[0].lower() in lowered_flags:
                raise ValueError(
                    f"MCP registry entry {spec.name!r} reaches interpreter "
                    f"{token!r} with inline execution flag {arg!r}; registry "
                    "entries must reference a pinned MCP executable or script "
                    "file instead"
                )


def spec_from_entry(entry: catalog.CatalogEntry) -> MCPServerSpec:
    """Build a validated MCPServerSpec from a registry entry's inline spec.

    Raises CatalogError if the entry has no inline spec, and ValueError if the
    spec is malformed or violates registry-specific untrusted-input policy."""
    if not entry.spec:
        raise catalog.CatalogError(
            f"MCP registry entry {entry.name!r} has no inline spec to install")
    # from_config applies the baseline subprocess-injection + url checks used
    # for hand-written config; registry entries then get stricter supply-chain
    # policy because they are untrusted network-fed data.
    spec = MCPServerSpec.from_config(entry.name, entry.spec)
    _validate_registry_spec(spec)
    return spec


def install_mcp_from_registry(name: str, *, indexes: list[str] | None = None) -> MCPServerSpec:
    """Resolve ``name`` in the registry and return a validated spec to install.

    Pure lookup + validation; the caller writes it to config (so a dry-run /
    preview is possible). Raises ValueError if the name isn't in the registry."""
    entry = resolve_mcp(name, indexes=indexes)
    if entry is None:
        raise ValueError(f"no MCP server {name!r} in the registry")
    return spec_from_entry(entry)


# ---- config mutation (dependency-free TOML, append/scan) ---------------------
#
# Python ships no stdlib TOML *writer*, and tomli_w isn't a declared dependency,
# so we emit the one ``[mcp_servers.<name>]`` table by hand (append on add,
# text-scan on remove). This is also the least-destructive approach: it leaves
# the rest of a hand-edited config.toml — comments, ordering — untouched.


def _toml_basic_string(s: str) -> str:
    out = s.replace("\\", "\\\\").replace('"', '\\"')
    out = out.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    return f'"{out}"'


def _toml_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, str):
        return _toml_basic_string(v)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    if isinstance(v, dict):
        # Inline table (env / headers are small string maps).
        inner = ", ".join(f"{_toml_key(k)} = {_toml_value(val)}" for k, val in v.items())
        return "{" + inner + "}"
    raise ValueError(f"cannot serialize {type(v).__name__} to TOML")


def _toml_key(k: str) -> str:
    return k if _BARE_KEY_RE.match(k) else _toml_basic_string(k)


def _emit_server_block(name: str, spec_dict: dict) -> str:
    lines = [f"[mcp_servers.{_toml_key(name)}]"]
    for key, val in spec_dict.items():
        if key == "name":  # the table key already carries the name
            continue
        lines.append(f"{key} = {_toml_value(val)}")
    return "\n".join(lines) + "\n"


def _load_config_dict(path):
    try:
        import tomllib  # 3.11+
    except ModuleNotFoundError:  # Python 3.10
        import tomli as tomllib  # type: ignore[no-redef]
    if not path.exists():
        return {}
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except Exception:  # a malformed config is the caller's problem to surface
        return {}


def _config_path(path=None):
    if path is not None:
        return path
    from .config import config_path
    return config_path()


def add_mcp_server_to_config(name: str, spec_dict: dict, *, path=None) -> None:
    """Append a ``[mcp_servers.<name>]`` table to config.toml.

    Raises ValueError if a server of that name is already configured (so an
    install never silently shadows a hand-tuned entry)."""
    p = _config_path(path)
    existing = _load_config_dict(p).get("mcp_servers") or {}
    if name in existing:
        raise ValueError(
            f"MCP server {name!r} is already in config; remove it first "
            f"(maverick mcp-registry remove {name})")
    p.parent.mkdir(parents=True, exist_ok=True)
    block = _emit_server_block(name, spec_dict)
    if p.exists():
        prior = p.read_text(encoding="utf-8")
        sep = "" if prior.endswith("\n\n") else ("\n" if prior.endswith("\n") else "\n\n")
        p.write_text(prior + sep + block, encoding="utf-8")
    else:
        p.write_text(block, encoding="utf-8")


def remove_mcp_server_from_config(name: str, *, path=None) -> bool:
    """Remove the ``[mcp_servers.<name>]`` table (and any subtables) from
    config.toml by text scan. Returns True if it was present and removed.

    Text-scan (not a full TOML round-trip) so the rest of the file — comments,
    ordering, unrelated tables — is preserved byte-for-byte."""
    p = _config_path(path)
    if not p.exists():
        return False
    if name not in (_load_config_dict(p).get("mcp_servers") or {}):
        return False
    header_re = re.compile(r"^\s*\[")
    # Matches [mcp_servers.<name>] and [mcp_servers.<name>.<sub>], with the name
    # optionally quoted, tolerating inner whitespace.
    key = re.escape(name)
    target_re = re.compile(
        rf'^\s*\[\s*mcp_servers\s*\.\s*(?:{key}|"{key}"|\'{key}\')\s*(?:\..*)?\]')
    out: list[str] = []
    skipping = False
    for line in p.read_text(encoding="utf-8").splitlines(keepends=True):
        if header_re.match(line):
            skipping = bool(target_re.match(line))
        if not skipping:
            out.append(line)
    p.write_text("".join(out), encoding="utf-8")
    return True


__all__ = [
    "DEFAULT_MCP_REGISTRIES",
    "load_mcp_registry",
    "resolve_mcp",
    "spec_from_entry",
    "install_mcp_from_registry",
    "add_mcp_server_to_config",
    "remove_mcp_server_from_config",
]
