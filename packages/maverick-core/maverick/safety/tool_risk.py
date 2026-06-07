"""Per-tool risk levels + per-identity max-risk ceiling.

Each tool has a coarse risk level -- ``low``, ``medium``, or ``high``.
A deployment can cap what a given context may reach by setting a
``max_risk`` ceiling; tools whose risk exceeds the ceiling are dropped
from the registry (in addition to the explicit allow/deny lists in
``tool_acl``).

Config (``~/.maverick/config.toml``):

    [security]
    max_risk = "medium"          # global ceiling (optional)

    [security.channels.telegram]
    max_risk = "low"             # nothing destructive over Telegram

    [security.users."tg:12345"]
    max_risk = "high"            # this user is trusted

    [security.tool_risk]
    my_plugin_tool = "high"      # override / classify a tool
    "mcp_*"        = "medium"    # glob -- applies to any matching name

Default ceiling is *unset*, meaning no cap (all risk levels allowed), so
behaviour is unchanged unless a ceiling is configured.
"""
from __future__ import annotations

import fnmatch
import logging

log = logging.getLogger(__name__)

# Ordered low -> high. Index is the comparable rank.
RISK_LEVELS = ("low", "medium", "high")

# Built-in risk classification. Anything not listed (and not matched by a
# configured override) defaults to ``medium``. High-risk tools can mutate
# the host, run arbitrary code, or drive a real machine/browser; low-risk
# tools are read-only or pure lookups.
_DEFAULT_RISK: dict[str, str] = {
    # high: arbitrary code / host mutation / full control
    "shell": "high",
    "computer": "high",
    "browser": "high",
    "apply_patch": "high",
    "write_file": "high",
    "str_replace_editor": "high",
    "ast_edit": "high",
    "compute": "high",
    "code_exec": "high",
    "memory": "high",
    # high: mutate external state / money / send messages / drive infra or a
    # device / recursively spawn. These used to fall through to the "medium"
    # default, so a max_risk="medium" channel ceiling failed to drop them.
    "sql_query": "high",
    "lambda": "high",
    "cloudflare": "high",
    "vercel": "high",
    "git_advanced": "high",
    "github_actions": "high",
    "openapi_runner": "high",
    "pandas_query": "high",
    "s3": "high",
    "dynamodb": "high",
    "mongodb": "high",
    "redis": "high",
    "elasticsearch": "high",
    "stripe": "high",
    "plaid": "high",
    "shopify": "high",
    "email": "high",
    "gmail": "high",
    "ses": "high",
    "sns": "high",
    "twilio": "high",
    "slack_bot": "high",
    "discord_bot": "high",
    "home_assistant": "high",
    "android": "high",
    "ios_sim": "high",
    "spawn_subagent": "high",
    "spawn_swarm": "high",
    # low: read-only / pure lookups
    "read_file": "low",
    "list_dir": "low",
    "repo_map": "low",
    "dep_graph": "low",
    "recall_past_goals": "low",  # real registered name (was "recall" -> dead)
    "web_search": "low",
    "knowledge_search": "low",
    "wikipedia": "low",
    "arxiv": "low",
    "semantic_scholar": "low",
    "hackernews": "low",
    "geocode": "low",
    "dns_lookup": "low",
    "currency": "low",
    "preview_diff": "low",
}

_DEFAULT_RISK_LEVEL = "medium"


def risk_rank(level: str) -> int:
    """Rank of a risk level (0=low). Unknown levels rank as medium."""
    try:
        return RISK_LEVELS.index(level)
    except ValueError:
        return RISK_LEVELS.index(_DEFAULT_RISK_LEVEL)


def _load_overrides() -> dict[str, str]:
    """Read ``[security.tool_risk]`` overrides. name -> level."""
    try:
        from ..config import load_config
        cfg = load_config() or {}
    except Exception as e:
        log.debug("tool_risk: cannot load config: %s", e)
        return {}
    section = (cfg.get("security") or {}).get("tool_risk") or {}
    out: dict[str, str] = {}
    for name, level in section.items():
        if isinstance(level, str) and level in RISK_LEVELS:
            out[name] = level
        else:
            log.warning("tool_risk: bad risk level for %s: %r", name, level)
    return out


def tool_risk(name: str, overrides: dict[str, str] | None = None) -> str:
    """Risk level for a tool: config override (exact then glob), then the
    built-in default, then ``medium``."""
    overrides = _load_overrides() if overrides is None else overrides
    if name in overrides:
        return overrides[name]
    for pattern, level in overrides.items():
        if any(ch in pattern for ch in "*?[") and fnmatch.fnmatchcase(name, pattern):
            return level
    return _DEFAULT_RISK.get(name, _DEFAULT_RISK_LEVEL)


def tools_exceeding(
    tool_names,
    max_risk: str | None,
    overrides: dict[str, str] | None = None,
) -> set[str]:
    """Names whose risk exceeds ``max_risk``. Empty set when no ceiling."""
    if not max_risk:
        return set()
    ceiling = risk_rank(max_risk)
    overrides = _load_overrides() if overrides is None else overrides
    return {
        n for n in tool_names
        if risk_rank(tool_risk(n, overrides)) > ceiling
    }


__all__ = ["RISK_LEVELS", "risk_rank", "tool_risk", "tools_exceeding"]
