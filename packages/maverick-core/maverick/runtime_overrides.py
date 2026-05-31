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


def _write_denied(names: set[str]) -> None:
    """Serialise the overlay. Only the [security] denied_tools list today.

    Hand-rolled TOML (no tomli-w dependency) since the shape is fixed:
    one table, one string-list. Atomic write at 0o600.
    """
    OVERRIDES_PATH.parent.mkdir(parents=True, exist_ok=True)
    rendered = ", ".join(_toml_string(n) for n in sorted(names))
    body = (
        "# Dashboard-managed overrides. Edit via the dashboard's\n"
        "# permissions page, not by hand (the dashboard rewrites this\n"
        "# file). Your config.toml is never touched by the dashboard.\n\n"
        "[security]\n"
        f"denied_tools = [{rendered}]\n"
    )
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


def disable_tool(name: str) -> set[str]:
    """Add ``name`` to the overlay deny-list. Returns the new set."""
    current = denied_tools()
    current.add(_validate_tool_name(name))
    _write_denied(current)
    return current


def enable_tool(name: str) -> set[str]:
    """Remove ``name`` from the overlay deny-list. Returns the new set.

    Note: this only clears a dashboard-set override. If a tool is
    denied in config.toml itself, re-enabling requires editing config.
    """
    current = denied_tools()
    current.discard(_validate_tool_name(name))
    _write_denied(current)
    return current


__all__ = ["denied_tools", "disable_tool", "enable_tool", "OVERRIDES_PATH"]
