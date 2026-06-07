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
    # high (finance): money movement, posting to a system of record, filing with
    # an authority, or master-data mutation. Classified high so a max_risk="medium"
    # finance pack drops them from the registry and governance gates them as the
    # "never move money / post / file without a human" boundary (finance-agent-suite).
    "post_journal_entry": "high",
    "close_period": "high",
    "edit_chart_of_accounts": "high",
    "release_payment": "high",
    "release_payroll_payment": "high",
    "run_payroll": "high",
    "wire_transfer": "high",
    "ach_send": "high",
    "send_payment": "high",
    "send_invoice": "high",
    "write_off_balance": "high",
    "approve_expense": "high",
    "reimburse": "high",
    "vendor_master_change": "high",
    "approve_vendor": "high",
    "approve_po": "high",
    "edit_employee_bank_details": "high",
    "place_trade": "high",
    "create_order_instruction": "high",
    "delete_order_instruction": "high",
    "execute_fx_trade": "high",
    "dispose_asset": "high",
    "file_return": "high",
    "file_tax_return": "high",
    "remit_tax": "high",
    "file_with_sec": "high",
    "set_credit_limit": "high",
    # low (finance): read / draft / stage / propose / assurance. These never
    # mutate a system of record (drafts await a human post), so low-risk packs
    # (FP&A, SOX, Internal Audit) can use them under a max_risk="low" ceiling.
    "gl_read_trial_balance": "low", "gl_read_subledger": "low",
    "gl_read_journal": "low", "gl_read_actuals": "low",
    "ap_read_invoice": "low", "ap_read_po": "low", "ap_read_receipt": "low",
    "ar_read_aging": "low", "ar_read_invoice": "low", "fa_read_register": "low",
    "expense_read_report": "low", "expense_read_card": "low",
    "bank_read_balance": "low", "bank_read_transactions": "low",
    "hcm_read_employee": "low", "payroll_read_register": "low",
    "payroll_read_timesheet": "low", "epm_read_plan": "low",
    "bi_read_metric": "low", "audit_log_read": "low", "covenant_check": "low",
    "stage_journal_entry": "low", "reconcile_accounts": "low",
    "flux_analysis": "low", "stage_payment_batch": "low", "draft_invoice": "low",
    "propose_cash_application": "low", "stage_payroll_run": "low",
    "reconcile_payroll": "low", "draft_payroll_tax": "low",
    "draft_depreciation_schedule": "low", "stage_asset_entry": "low",
    "draft_revrec_schedule": "low", "stage_deferred_revenue": "low",
    "draft_elimination": "low", "draft_translation": "low",
    "flag_policy_violation": "low", "draft_accrual": "low",
    "build_variance_report": "low", "build_board_pack": "low",
    "build_forecast_scenario": "low", "build_cashflow_forecast": "low",
    "propose_transfer": "low", "propose_trade": "low", "propose_hedge": "low",
    "model_refinancing": "low", "compute_tax_provision": "low",
    "draft_tax_footnote": "low", "prepare_return": "low", "validate_nexus": "low",
    "tp_benchmark": "low", "draft_tp_documentation": "low", "test_control": "low",
    "log_deficiency": "low", "run_assessment": "low", "sod_conflict_scan": "low",
    "draft_workpaper": "low", "log_finding": "low",
    "assemble_evidence_package": "low", "run_fraud_model": "low",
    "open_case": "low", "flag_anomaly": "low", "update_risk_register": "low",
    "build_risk_report": "low", "score_credit": "low",
    "propose_credit_limit": "low", "analyze_spend": "low", "draft_po": "low",
    "screen_sanctions": "low", "validate_bank_details": "low",
    "draft_filing": "low", "tag_xbrl": "low", "run_disclosure_checklist": "low",
    "draft_earnings_materials": "low", "compute_sbc_expense": "low",
    "draft_sbc_entry": "low",
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
