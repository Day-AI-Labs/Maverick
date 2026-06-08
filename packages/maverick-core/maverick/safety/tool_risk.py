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
    # high: generic enterprise REST/GraphQL connectors can perform
    # credentialed writes to external SaaS/cloud systems when confirm=true.
    "zendesk": "high",
    "freshdesk": "high",
    "freshservice": "high",
    "intercom": "high",
    "okta": "high",
    "box": "high",
    "docusign": "high",
    "coupa": "high",
    "ariba": "high",
    "smartsheet": "high",
    "wrike": "high",
    "bamboohr": "high",
    "greenhouse": "high",
    "lever": "high",
    "tableau": "high",
    "powerbi": "high",
    "looker": "high",
    "newrelic": "high",
    "dynatrace": "high",
    "grafana": "high",
    "zoho": "high",
    "pipedrive": "high",
    "salesloft": "high",
    "outreach": "high",
    "gong": "high",
    "clari": "high",
    "creatio": "high",
    "pega": "high",
    "sage_intacct": "high",
    "epicor": "high",
    "ifs": "high",
    "unit4": "high",
    "acumatica": "high",
    "quickbooks": "high",
    "xero": "high",
    "billdotcom": "high",
    "genesys": "high",
    "nice_cxone": "high",
    "five9": "high",
    "talkdesk": "high",
    "helpscout": "high",
    "kustomer": "high",
    "sprinklr": "high",
    "bmc_helix": "high",
    "ivanti": "high",
    "solarwinds": "high",
    "manageengine": "high",
    "xmatters": "high",
    "rippling": "high",
    "gusto": "high",
    "fastly": "high",
    "akamai": "high",
    "digitalocean": "high",
    "terraform": "high",
    "vault": "high",
    "pingone": "high",
    "cyberark": "high",
    "sailpoint": "high",
    "onelogin": "high",
    "auth0": "high",
    "duo": "high",
    "crowdstrike": "high",
    "splunk": "high",
    "zscaler": "high",
    "tenable": "high",
    "qualys": "high",
    "rapid7": "high",
    "sentinelone": "high",
    "proofpoint": "high",
    "snyk": "high",
    "fortinet": "high",
    "qlik": "high",
    "thoughtspot": "high",
    "sisense": "high",
    "domo": "high",
    "mode": "high",
    "metabase": "high",
    "jenkins": "high",
    "circleci": "high",
    "jfrog": "high",
    "sonarqube": "high",
    "azure_devops": "high",
    "mailchimp": "high",
    "klaviyo": "high",
    "braze": "high",
    "marketo": "high",
    "sfmc": "high",
    "segment": "high",
    "adobe_analytics": "high",
    "aem": "high",
    "bigcommerce": "high",
    "sendgrid": "high",
    "fivetran": "high",
    "dbt": "high",
    "airflow": "high",
    "confluent": "high",
    "informatica": "high",
    "talend": "high",
    "matillion": "high",
    "cloudera": "high",
    "miro": "high",
    "coda": "high",
    "basecamp": "high",
    "planview": "high",
    "infor": "high",
    "netsuite": "high",
    "adp": "high",
    "ukg": "high",
    "mulesoft": "high",
    "boomi": "high",
    "workato": "high",
    "zapier": "high",
    "kubernetes": "high",
    "openshift": "high",
    "vsphere": "high",
    "azure": "high",
    "gcp": "high",
    "ibm_cloud": "high",
    "alibaba_cloud": "high",
    "sentinel": "high",
    "defender": "high",
    "qradar": "high",
    "palo_alto": "high",
    "jamf": "high",
    "ringcentral": "high",
    "vonage": "high",
    "webex": "high",
    "neo4j": "high",
    "teradata": "high",
    "microstrategy": "high",
    "cognos": "high",
    "concur": "high",
    "anaplan": "high",
    "smartrecruiters": "high",
    "gainsight": "high",
    "amplitude": "high",
    "square": "high",
    "paypal": "high",
    "adyen": "high",
    "ramp": "high",
    "brex": "high",
    "blackline": "high",
    "workiva": "high",
    "successfactors": "high",
    "cornerstone": "high",
    "icims": "high",
    "paylocity": "high",
    "workable": "high",
    "deel": "high",
    "magento": "high",
    "salesforce_commerce": "high",
    "sap_commerce": "high",
    "appdynamics": "high",
    "sumologic": "high",
    "logicmonitor": "high",
    "netskope": "high",
    "cisco_umbrella": "high",
    "vanta": "high",
    "drata": "high",
    "logicgate": "high",
    "apollo": "high",
    "zoominfo": "high",
    "clearbit": "high",
    "argocd": "high",
    "harness": "high",
    "octopus_deploy": "high",
    "dockerhub": "high",
    "iterable": "high",
    "pendo": "high",
    "dialpad": "high",
    "aircall": "high",
    "front": "high",
    "gladly": "high",
    "figma": "high",
    "lucid": "high",
    "eventbrite": "high",
    "cvent": "high",
    "monday": "high",
    "wiz": "high",
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
    built-in default.

    An *unclassified* MCP tool (``mcp_*``) fails safe to ``high``: it runs
    arbitrary code through a third-party server, so it is treated as dangerous
    until a deployment says otherwise (an unclassified non-MCP tool still falls
    back to ``medium``). A config override is checked first, so a trusted MCP
    server can be relaxed deliberately, e.g. ``[security.tool_risk]``
    ``"mcp_*" = "medium"``.
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
    # through a third-party server -> fail safe to high. Anything else falls
    # back to the medium default.
    if name.startswith("mcp_"):
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
