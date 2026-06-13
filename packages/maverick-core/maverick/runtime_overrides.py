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


def default_model_override() -> str | None:
    """The model the dashboard's settings page has pinned, or None.

    Consulted by ``llm.model_for_role`` *below* the user's per-role
    ``config.toml`` ``[models]`` (so explicit per-role config still wins) and
    above the built-in ``ROLE_MODELS`` defaults. Re-validated on read so a
    tampered file can't inject an arbitrary string into resolution.
    """
    raw = (_load().get("models") or {}).get("default")
    if isinstance(raw, str) and _VALID_MODEL.fullmatch(raw.strip()):
        return raw.strip()
    return None


def _write_state(denied: set[str], default_model: str | None) -> None:
    """Serialise the whole overlay: [security] denied_tools + optional
    [models] default. One file holds both surfaces, so every write renders
    the full state -- writing a model choice must not drop tool denials and
    vice versa. Atomic write at 0o600; no tomli-w dependency.

    With ``default_model`` None the [security] block is byte-identical to the
    historical writer, so tool-only callers are unaffected.
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
    if default_model:
        body += f"\n[models]\ndefault = {_toml_string(default_model)}\n"
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


def disable_tool(name: str) -> set[str]:
    """Add ``name`` to the overlay deny-list. Returns the new set."""
    current = denied_tools()
    current.add(_validate_tool_name(name))
    _write_state(current, default_model_override())
    return current


def enable_tool(name: str) -> set[str]:
    """Remove ``name`` from the overlay deny-list. Returns the new set.

    Note: this only clears a dashboard-set override. If a tool is
    denied in config.toml itself, re-enabling requires editing config.
    """
    current = denied_tools()
    current.discard(_validate_tool_name(name))
    _write_state(current, default_model_override())
    return current


def set_default_model(model: str) -> str:
    """Pin the dashboard's default model. Returns the stored spec."""
    spec = _validate_model(model)
    _write_state(denied_tools(), spec)
    return spec


def clear_default_model() -> None:
    """Drop the dashboard model pin, reverting to config.toml / defaults."""
    _write_state(denied_tools(), None)


__all__ = [
    "denied_tools", "disable_tool", "enable_tool",
    "default_model_override", "set_default_model", "clear_default_model",
    "OVERRIDES_PATH",
]
