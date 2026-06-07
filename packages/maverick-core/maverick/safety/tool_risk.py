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
    "mcp_*"        = "medium"    # glob -- relax MCP tools (they default to high)

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
    "obsidian": "high",
    "clipboard": "high",
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
    # high: dedicated-module enterprise connectors that mutate external business
    # state / move money / run remote code or SQL / send messages. (The long-tail
    # REST connectors in enterprise_connectors.py are covered by name separately.)
    "airtable": "high",
    "asana": "high",
    "bigquery": "high",
    "calendar": "high",
    "calendly": "high",
    "clickup": "high",
    "confluence": "high",
    "database": "high",
    "databricks": "high",
    "datadog": "high",
    "dropbox": "high",
    "dynamics": "high",
    "ga4": "high",
    "gdrive": "high",
    "gitlab": "high",
    "http_fetch": "high",
    "hubspot": "high",
    "jira": "high",
    "learn_capability": "high",
    "linear": "high",
    "mixpanel": "high",
    "msgraph": "high",
    "notebook_exec": "high",
    "notify": "high",
    "notion": "high",
    "onetrust": "high",
    "oracle": "high",
    "pagerduty": "high",
    "plausible": "high",
    "posthog": "high",
    "replicate": "high",
    "salesforce": "high",
    "sap": "high",
    "sentry": "high",
    "servicenow": "high",
    "snowflake": "high",
    "spotify": "high",
    "spreadsheet": "high",
    "teams": "high",
    "trello": "high",
    "workday": "high",
    "zoom": "high",
    # low: read-only / pure lookups
    "read_file": "low",
    "list_dir": "low",
    "repo_map": "low",
    "dep_graph": "low",
    "recall_past_goals": "low",  # real registered name (was "recall" -> dead)
    "web_search": "low",
    "knowledge_search": "low",
    "find_controls": "low",
    "wikipedia": "low",
    "arxiv": "low",
    "semantic_scholar": "low",
    "hackernews": "low",
    "geocode": "low",
    "dns_lookup": "low",
    "currency": "low",
    "preview_diff": "low",
    "erp_read": "low",  # read-only (GET) ERP access; no writes / host mutation
}

_DEFAULT_RISK_LEVEL = "medium"


# The long-tail enterprise connectors (built by ``enterprise_connectors.py`` via
# a shared REST/GraphQL factory) all expose write ops (post/put/patch/delete or
# GraphQL mutations), so they fail safe to "high" -- resolved by name from the
# connector spec list so newly-added connectors are covered automatically. The
# list is loaded lazily (the tools package imports this module, so a top-level
# import would be circular) and cached only on success; a config override or an
# explicit ``_DEFAULT_RISK`` entry still wins.
_ENTERPRISE_CONNECTORS: frozenset[str] | None = None


def _enterprise_connector_names() -> frozenset[str]:
    global _ENTERPRISE_CONNECTORS
    if _ENTERPRISE_CONNECTORS is not None:
        return _ENTERPRISE_CONNECTORS
    try:
        from ..tools.enterprise_connectors import ENTERPRISE_CONNECTOR_NAMES
    except Exception:
        return frozenset()  # tools not importable yet -- retry on the next call
    _ENTERPRISE_CONNECTORS = frozenset(ENTERPRISE_CONNECTOR_NAMES)
    return _ENTERPRISE_CONNECTORS


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
    built-in default.

    Two classes of tool fail safe to ``high`` when otherwise unclassified: an
    MCP tool (``mcp_*``), which runs arbitrary code through a third-party
    server; and an enterprise connector (the long-tail REST/GraphQL connectors
    from ``enterprise_connectors.py``), which is write-capable by construction.
    A config override is checked first, so either can be relaxed deliberately,
    e.g. ``[security.tool_risk]`` ``"mcp_*" = "medium"`` or ``okta = "medium"``.
    Any other unclassified tool falls back to ``medium``.
    """
    overrides = _load_overrides() if overrides is None else overrides
    if name in overrides:
        return overrides[name]
    for pattern, level in overrides.items():
        if any(ch in pattern for ch in "*?[") and fnmatch.fnmatchcase(name, pattern):
            return level
    if name in _DEFAULT_RISK:
        return _DEFAULT_RISK[name]
    # Unclassified. An MCP tool is externally-defined arbitrary code reached
    # through a third-party server, and an enterprise connector is write-capable
    # by construction -> both fail safe to high. Anything else -> medium.
    if name.startswith("mcp_"):
        return "high"
    if name in _enterprise_connector_names():
        return "high"
    return _DEFAULT_RISK_LEVEL


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
