"""Dashboard-owned runtime overrides.

The dashboard's permissions page lets a user disable a tool with one
click. Writing that into ``config.toml`` would clobber the user's
hand-tuned, comment-annotated, wizard-generated file. Instead the
dashboard owns a separate ``~/.maverick/runtime-overrides.toml`` that
the kernel unions into the deny-list at registry-build time.

Only a small, well-defined surface lives here today:

    [security]
    denied_tools = ["computer", "browser"]

``tool_acl.resolve_lists`` reads ``denied_tools`` and unions it with
the config + channel + user deny-lists, so a disable takes effect on
the next goal with no restart. config.toml is never touched.
"""
from __future__ import annotations

import logging
import math
import os
import re
from pathlib import Path

log = logging.getLogger(__name__)

OVERRIDES_PATH = Path.home() / ".maverick" / "runtime-overrides.toml"
_VALID_TOOL_NAME = re.compile(r"^[a-z0-9_-]+$")


def _tomllib():
    try:
        import tomllib  # 3.11+
    except ModuleNotFoundError:  # Python 3.10
        import tomli as tomllib  # type: ignore[no-redef]
    return tomllib


def _load() -> dict:
    if not OVERRIDES_PATH.exists():
        return {}
    try:
        with open(OVERRIDES_PATH, "rb") as f:
            return _tomllib().load(f)
    except (OSError, ValueError) as e:
        log.warning("runtime_overrides: cannot read %s: %s", OVERRIDES_PATH, e)
        return {}


_announced: set[str] = set()


def denied_tools() -> set[str]:
    """Tools the dashboard has disabled. Unioned into the ACL deny-list.

    Re-validates each name against the same charset the writer enforces, so a
    hand-edited / corrupt override file can't push junk or oversized entries
    into ACL resolution. Logs once (per distinct denial set) that the override
    file is actively restricting tools -- this file influences the security
    ACL but lives outside config.toml, so its effect should not be silent.
    """
    sec = (_load().get("security") or {})
    raw = sec.get("denied_tools") or []
    valid = {str(n) for n in raw if isinstance(n, str) and _VALID_TOOL_NAME.match(n)}
    dropped = [n for n in raw if not (isinstance(n, str) and _VALID_TOOL_NAME.match(n))]
    if dropped:
        log.warning(
            "runtime_overrides: ignoring %d invalid denied_tools entr(y/ies) in %s: %r",
            len(dropped), OVERRIDES_PATH, dropped[:10],
        )
    if valid:
        key = ",".join(sorted(valid))
        if key not in _announced:
            _announced.add(key)
            log.info(
                "runtime_overrides: %s is denying %d tool(s) via the dashboard "
                "overlay: %s", OVERRIDES_PATH, len(valid), ", ".join(sorted(valid)),
            )
    return valid


# A model spec is a bare id ("claude-sonnet-4-6") or "provider:model-id"
# ("anthropic:claude-opus-4-8"). Keep the charset tight so a hand-edited /
# corrupt override can't push junk into model resolution.
_VALID_MODEL = re.compile(r"^[A-Za-z0-9_.:/-]{1,128}$")
# Override keys under [models]: a role name (orchestrator, coder, ...) or the
# special "default" that applies to every role. Tight charset so a hand-edited
# file can't inject junk keys.
_VALID_ROLE = re.compile(r"^[a-z_]{1,40}$")


def _models_overlay() -> dict[str, str]:
    """The dashboard's ``[models]`` table: ``{"default": spec, "<role>": spec}``.
    Re-validated on read; junk keys/values are dropped."""
    raw = _load().get("models") or {}
    out: dict[str, str] = {}
    for k, v in raw.items():
        if (isinstance(k, str) and _VALID_ROLE.fullmatch(k)
                and isinstance(v, str) and _VALID_MODEL.fullmatch(v.strip())):
            out[k] = v.strip()
    return out


def default_model_override() -> str | None:
    """The dashboard's global default model pin, or None. Consulted by
    ``llm.model_for_role`` below the user's ``config.toml`` ``[models]`` and
    above the built-in ``ROLE_MODELS`` defaults."""
    return _models_overlay().get("default")


def role_model_override(role: str) -> str | None:
    """The dashboard's per-role model pin for ``role``, or None. Wins over the
    global default; consulted by ``llm.model_for_role`` at the same precedence."""
    return _models_overlay().get(role) if role != "default" else None


def budget_override() -> float | None:
    """The per-goal spend cap (USD) the dashboard's settings page has set, or
    None. Consulted by ``budget.budget_from_config`` above the ``[budget]``
    config section. Re-validated on read; only a finite, positive number wins."""
    raw = (_load().get("budget") or {}).get("max_dollars")
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) and v > 0 else None


# Plugin / entry-point name: alnum plus _.@- (covers "weather", "weather@dist").
_VALID_PLUGIN = re.compile(r"^[A-Za-z0-9_.@-]{1,128}$")


def plugin_overlay() -> tuple[set[str], set[str]]:
    """The dashboard's ``[plugins]`` overlay as ``(force_enabled, force_disabled)``
    name sets. Consulted by ``plugins._allowed_plugin_names`` -- ``enabled`` adds
    to the config allowlist, ``disabled`` removes from it (disable wins).
    Re-validated on read; junk entries dropped."""
    p = _load().get("plugins") or {}

    def _clean(key: str) -> set[str]:
        return {n.strip() for n in (p.get(key) or [])
                if isinstance(n, str) and _VALID_PLUGIN.fullmatch(n.strip())}
    on, off = _clean("enabled"), _clean("disabled")
    return on - off, off  # disable wins if a name appears in both


def allowed_models() -> set[str]:
    """The admin allow-list of model specs (dashboard ``[access] allowed_models``).
    When non-empty, ``llm.model_for_role`` caps every role to this set and the
    settings pickers offer only these. Empty = no restriction. Re-validated on
    read so a tampered file can't inject junk."""
    raw = (_load().get("access") or {}).get("allowed_models") or []
    return {s.strip() for s in raw
            if isinstance(s, str) and _VALID_MODEL.fullmatch(s.strip())}


# MCP server name: bare TOML key charset (no dots, so the ``[mcp_servers.<name>]``
# header is unambiguous). The kernel revalidates the whole spec at load time.
_VALID_SERVER_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def mcp_overlay() -> dict[str, dict]:
    """Dashboard-added MCP servers as ``{name: spec_dict}`` (overlay
    ``[mcp_servers.<name>]``). Unioned into ``mcp_client.load_mcp_specs_from_config``
    so a server added from the dashboard runs on the next goal with no config.toml
    edit -- config wins on a name clash. Re-validated on read: a name must be a
    bare key and the spec a dict carrying ``command`` (stdio) or ``url`` (http)."""
    raw = _load().get("mcp_servers") or {}
    out: dict[str, dict] = {}
    for name, spec in raw.items():
        if (isinstance(name, str) and _VALID_SERVER_NAME.fullmatch(name)
                and isinstance(spec, dict)
                and ("command" in spec or "url" in spec)):
            out[name] = spec
    return out


def _toml_inline(value) -> str:
    """Render a scalar / list / string-map as a TOML inline value. Used for the
    ``[mcp_servers.<name>]`` blocks (args list, env/headers/oauth inline tables)
    -- the rest of the overlay is plain string lists handled inline above."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return _toml_string(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_toml_inline(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{" + ", ".join(
            f"{_toml_string(str(k))} = {_toml_inline(v)}" for k, v in value.items()) + "}"
    raise ValueError(f"cannot serialise {type(value).__name__} to TOML")


def _render_mcp(servers: dict[str, dict]) -> str:
    """Render ``[mcp_servers.<name>]`` tables. Names are bare keys (validated by
    add_mcp_server) so the header is unambiguous; these tables come LAST in the
    file so no top-level key is captured by a subtable."""
    body = ""
    for name in sorted(servers):
        body += f"\n[mcp_servers.{name}]\n"
        for key, val in servers[name].items():
            if key == "name":  # the table key already carries the name
                continue
            body += f"{key} = {_toml_inline(val)}\n"
    return body


def _write_state(denied: set[str], models: dict[str, str] | None,
                 budget: float | None,
                 plugins: tuple[set[str], set[str]] | None = None,
                 allowed: set[str] | None = None,
                 mcp: dict[str, dict] | None = None) -> None:
    """Serialise the whole overlay: [security] denied_tools + optional [models]
    (default + per-role) + [budget] max_dollars + [plugins] enabled/disabled +
    [access] allowed_models + [mcp_servers.<name>] tables. One file holds every
    surface, so each write renders the full state -- changing one must not drop
    the others. Optional params default to the on-disk overlay so the existing
    callers preserve what they don't touch. Atomic write at 0o600; no tomli-w
    dependency.
    """
    OVERRIDES_PATH.parent.mkdir(parents=True, exist_ok=True)
    rendered = ", ".join(_toml_string(n) for n in sorted(denied))
    body = (
        "# Dashboard-managed overrides. Edit via the dashboard's\n"
        "# permissions page, not by hand (the dashboard rewrites this\n"
        "# file). Your config.toml is never touched by the dashboard.\n\n"
        "[security]\n"
        f"denied_tools = [{rendered}]\n"
    )
    if models:
        body += "\n[models]\n"
        # "default" first (if present), then roles sorted -- deterministic.
        ordered = (["default"] if "default" in models else []) \
            + sorted(k for k in models if k != "default")
        for k in ordered:
            body += f"{k} = {_toml_string(models[k])}\n"
    if budget is not None:
        body += f"\n[budget]\nmax_dollars = {float(budget)}\n"
    on, off = plugin_overlay() if plugins is None else plugins
    if on or off:
        body += "\n[plugins]\n"
        if on:
            body += f"enabled = [{', '.join(_toml_string(n) for n in sorted(on))}]\n"
        if off:
            body += f"disabled = [{', '.join(_toml_string(n) for n in sorted(off))}]\n"
    allow = allowed_models() if allowed is None else allowed
    if allow:
        body += ("\n[access]\nallowed_models = ["
                 f"{', '.join(_toml_string(s) for s in sorted(allow))}]\n")
    # MCP server tables come last: once a subtable header is emitted every
    # following key belongs to it, so no top-level section may follow.
    servers = mcp_overlay() if mcp is None else mcp
    if servers:
        body += _render_mcp(servers)
    tmp_path = OVERRIDES_PATH.with_suffix(".toml.tmp")
    fd = os.open(tmp_path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(body)
    os.replace(tmp_path, OVERRIDES_PATH)
    try:
        os.chmod(OVERRIDES_PATH, 0o600)
    except OSError:
        pass


def _toml_string(value: str) -> str:
    import json
    return json.dumps(value)


def _validate_tool_name(name: str) -> str:
    n = (name or "").strip()
    if not _VALID_TOOL_NAME.fullmatch(n):
        raise ValueError("invalid tool name")
    return n


def _validate_model(model: str) -> str:
    m = (model or "").strip()
    if not _VALID_MODEL.fullmatch(m):
        raise ValueError("invalid model id")
    return m


def _validate_role(role: str) -> str:
    r = (role or "").strip().lower()
    if r == "default" or not _VALID_ROLE.fullmatch(r):
        # the global pin goes through set_default_model, not the per-role path
        raise ValueError("invalid role")
    return r


def disable_tool(name: str) -> set[str]:
    """Add ``name`` to the overlay deny-list. Returns the new set."""
    current = denied_tools()
    current.add(_validate_tool_name(name))
    _write_state(current, _models_overlay() or None, budget_override())
    return current


def enable_tool(name: str) -> set[str]:
    """Remove ``name`` from the overlay deny-list. Returns the new set.

    Note: this only clears a dashboard-set override. If a tool is
    denied in config.toml itself, re-enabling requires editing config.
    """
    current = denied_tools()
    current.discard(_validate_tool_name(name))
    _write_state(current, _models_overlay() or None, budget_override())
    return current


def set_default_model(model: str) -> str:
    """Pin the dashboard's global default model. Returns the stored spec."""
    spec = _validate_model(model)
    models = _models_overlay()
    models["default"] = spec
    _write_state(denied_tools(), models, budget_override())
    return spec


def clear_default_model() -> None:
    """Drop the global default model pin (per-role pins are untouched)."""
    models = _models_overlay()
    models.pop("default", None)
    _write_state(denied_tools(), models or None, budget_override())


def set_role_models(updates: dict[str, str | None]) -> None:
    """Batch set/clear per-role model pins in one write. A falsy value clears
    that role. Invalid role/model ids raise ValueError before anything writes."""
    models = _models_overlay()
    cleaned = {_validate_role(role): (_validate_model(spec) if spec else None)
               for role, spec in updates.items()}
    for r, spec in cleaned.items():
        if spec:
            models[r] = spec
        else:
            models.pop(r, None)
    _write_state(denied_tools(), models or None, budget_override())


def set_budget(max_dollars: float) -> float:
    """Set the dashboard's per-goal spend cap (USD). Returns the stored value."""
    try:
        v = float(max_dollars)
    except (TypeError, ValueError) as exc:
        raise ValueError("budget must be a number") from exc
    if not math.isfinite(v) or v <= 0:
        raise ValueError("budget must be a positive number")
    _write_state(denied_tools(), _models_overlay() or None, v)
    return v


def clear_budget() -> None:
    """Drop the dashboard spend cap, reverting to config.toml / defaults."""
    _write_state(denied_tools(), _models_overlay() or None, None)


def _validate_plugin(name: str) -> str:
    n = (name or "").strip()
    if not _VALID_PLUGIN.fullmatch(n):
        raise ValueError("invalid plugin name")
    return n


def _set_plugins(on: set[str], off: set[str]) -> None:
    _write_state(denied_tools(), _models_overlay() or None, budget_override(),
                 (on, off))


def enable_plugin(name: str) -> None:
    """Force-enable a plugin from the dashboard (adds it to the allowlist)."""
    n = _validate_plugin(name)
    on, off = plugin_overlay()
    on.add(n)
    off.discard(n)
    _set_plugins(on, off)


def disable_plugin(name: str) -> None:
    """Force-disable a plugin from the dashboard (removes it from the allowlist,
    even when config.toml enables it)."""
    n = _validate_plugin(name)
    on, off = plugin_overlay()
    off.add(n)
    on.discard(n)
    _set_plugins(on, off)


def reset_plugin(name: str) -> None:
    """Clear any dashboard plugin override, reverting to config.toml."""
    n = _validate_plugin(name)
    on, off = plugin_overlay()
    on.discard(n)
    off.discard(n)
    _set_plugins(on, off)


def set_allowed_models(specs) -> set[str]:
    """Set the admin model allow-list (an empty list clears it). Validates each
    spec before writing; returns the stored set."""
    allow: set[str] = set()
    for s in (specs or []):
        m = (str(s) or "").strip()
        if not m:
            continue
        if not _VALID_MODEL.fullmatch(m):
            raise ValueError("invalid model id")
        allow.add(m)
    _write_state(denied_tools(), _models_overlay() or None, budget_override(),
                 allowed=allow)
    return allow


def add_mcp_server(name: str, spec: dict) -> dict:
    """Add (or replace) a dashboard-managed MCP server. Validates the spec the
    same way the kernel will at load time (``MCPServerSpec.from_config`` -- the
    subprocess-injection / url guards), stores the normalised dict, and returns
    it. Raises ValueError on a bad name or spec; config.toml is never touched."""
    n = (name or "").strip()
    if not _VALID_SERVER_NAME.fullmatch(n):
        raise ValueError("invalid MCP server name")
    if not isinstance(spec, dict) or ("command" not in spec and "url" not in spec):
        raise ValueError("MCP server needs a command (stdio) or url (http)")
    from .mcp_client import MCPServerSpec  # lazy: avoid an import cycle
    stored = MCPServerSpec.from_config(n, spec).to_dict()
    servers = mcp_overlay()
    servers[n] = stored
    _write_state(denied_tools(), _models_overlay() or None, budget_override(),
                 mcp=servers)
    return stored


def remove_mcp_server(name: str) -> bool:
    """Remove a dashboard-managed MCP server. Returns True if one was removed.
    Only clears a dashboard-added server; a config.toml server is not touched."""
    n = (name or "").strip()
    servers = mcp_overlay()
    if n not in servers:
        return False
    del servers[n]
    _write_state(denied_tools(), _models_overlay() or None, budget_override(),
                 mcp=servers)
    return True


__all__ = [
    "denied_tools", "disable_tool", "enable_tool",
    "default_model_override", "set_default_model", "clear_default_model",
    "role_model_override", "set_role_models",
    "budget_override", "set_budget", "clear_budget",
    "plugin_overlay", "enable_plugin", "disable_plugin", "reset_plugin",
    "allowed_models", "set_allowed_models",
    "mcp_overlay", "add_mcp_server", "remove_mcp_server",
    "OVERRIDES_PATH",
]
