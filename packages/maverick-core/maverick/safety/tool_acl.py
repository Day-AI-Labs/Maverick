"""Tool allow-list / deny-list ACLs.

A user can declare in ``~/.maverick/config.toml``:

    [security]
    allowed_tools = ["shell", "read_file", "write_file"]   # whitelist
    denied_tools  = ["computer", "browser"]                # blacklist

The ToolRegistry consults these at construction time:

  - ``allowed_tools`` is non-empty -> ONLY those tools are kept.
  - ``denied_tools`` is non-empty  -> those tools are dropped.
  - Both: allow-list takes precedence; deny-list further filters.

This lets a deployment lock down what an agent can do without
touching the kernel. Per-channel / per-user ACLs can layer on top
(Q2 2026 roadmap).
"""
from __future__ import annotations

import logging
from typing import Iterable

log = logging.getLogger(__name__)


def _load_lists() -> tuple[set[str], set[str]]:
    """Load (allowed, denied) sets from ~/.maverick/config.toml."""
    try:
        from ..config import load_config
        cfg = load_config()
    except Exception as e:
        log.debug("tool_acl: cannot load config: %s", e)
        return set(), set()
    sec = (cfg or {}).get("security") or {}
    allowed = sec.get("allowed_tools") or []
    denied = sec.get("denied_tools") or []
    return set(allowed), set(denied)


def filter_tools(
    tool_names: Iterable[str],
    *,
    allowed: set[str] | None = None,
    denied: set[str] | None = None,
) -> set[str]:
    """Apply the allow/deny lists to ``tool_names``. Returns the kept set.

    Override the lists explicitly via kwargs; if both kwargs are None,
    the config is consulted.
    """
    if allowed is None and denied is None:
        allowed, denied = _load_lists()
    else:
        allowed = allowed or set()
        denied = denied or set()
    names = set(tool_names)
    if allowed:
        names = names & allowed
    if denied:
        names = names - denied
    return names


def apply_to_registry(reg) -> None:
    """Mutate a ToolRegistry in place by removing denied / non-allowed tools."""
    allowed, denied = _load_lists()
    if not allowed and not denied:
        return
    reg.set_acl(allowed=allowed, denied=denied)
    current = {t.name for t in reg.all()}
    keep = filter_tools(current, allowed=allowed, denied=denied)
    drop = current - keep
    for name in drop:
        # ToolRegistry exposes _tools; we use the private API
        # because there's no public remove() yet -- adding one as
        # part of this change.
        reg._tools.pop(name, None)
    if drop:
        log.info("tool_acl: dropped %d tool(s): %s", len(drop), sorted(drop))
