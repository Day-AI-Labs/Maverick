"""Tests for the config validator (maverick.config_lint)."""
from __future__ import annotations

from maverick.config_lint import Finding, format_findings, lint_config


def _by_section(findings):
    return {f.section: f for f in findings}


def test_clean_config_no_findings():
    cfg = {
        "deployment": {"type": "desktop"},
        "providers": {"anthropic": {"api_key": "${ANTHROPIC_API_KEY}"}},
        "models": {"orchestrator": "anthropic:claude-opus-4-7"},
        "budget": {"max_dollars": 5.0, "max_tool_calls": 500},
        "safety": {"profile": "balanced", "scan_input": True},
        "sandbox": {"backend": "local", "timeout": 60},
        "features": {"skills": True, "world_model": True, "streaming": False},
        "durable": {"enabled": False, "keep_last": 5},
        "mcp_servers": {"filesystem": {"command": "npx", "args": ["-y", "x"]}},
    }
    assert lint_config(cfg) == []
    assert format_findings(lint_config(cfg)) == "config OK"


def test_unknown_section_warns_with_suggestion():
    # "budgets" is a typo for the known "budget" section.
    findings = lint_config({"budgets": {"max_dollars": 5.0}})
    assert len(findings) == 1
    f = findings[0]
    assert f.section == "budgets"
    assert f.key is None
    assert f.severity == "warning"
    assert "budget" in f.message  # close-match suggestion present


def test_unknown_section_without_close_match_still_warns():
    findings = lint_config({"zzzqqq": {"foo": 1}})
    assert len(findings) == 1
    assert findings[0].severity == "warning"
    assert findings[0].section == "zzzqqq"


def test_unknown_key_in_fixed_section_warns():
    # [budget] has a fixed key set; "max_dollar" is a typo of "max_dollars".
    findings = lint_config({"budget": {"max_dollar": 5.0}})
    assert len(findings) == 1
    f = findings[0]
    assert f.section == "budget"
    assert f.key == "max_dollar"
    assert f.severity == "warning"
    assert "max_dollars" in f.message


def test_bad_type_budget_max_dollars_is_error():
    findings = lint_config({"budget": {"max_dollars": "lots"}})
    assert len(findings) == 1
    f = findings[0]
    assert f.section == "budget"
    assert f.key == "max_dollars"
    assert f.severity == "error"
    assert "number" in f.message


def test_bad_type_enabled_must_be_bool():
    findings = lint_config({"durable": {"enabled": "yes"}})
    assert len(findings) == 1
    f = findings[0]
    assert f.severity == "error"
    assert f.section == "durable"
    assert f.key == "enabled"


def test_dynamic_section_accepts_arbitrary_keys():
    # providers.<name> is open-ended: any subkey is fine, no findings.
    cfg = {
        "providers": {
            "anthropic": {
                "api_key": "${ANTHROPIC_API_KEY}",
                "base_url": "https://example",
                "some_future_knob": 123,
            }
        }
    }
    assert lint_config(cfg) == []


def test_never_raises_on_weird_dict():
    # Non-dict section values, non-string keys, and a non-dict top-level
    # are all tolerated without raising.
    assert lint_config({"budget": "not-a-table"}) == []
    assert lint_config({42: {"x": 1}}) == []
    assert lint_config("not-a-dict") == []  # type: ignore[arg-type]


def test_format_findings_summary():
    findings = [
        Finding("budget", "max_dollars", "error", "must be a number, got str"),
        Finding("budgets", None, "warning", 'unknown config section "budgets"'),
    ]
    out = format_findings(findings)
    assert "1 error(s), 1 warning(s)" in out
    # Error is ordered before the warning.
    err_idx = out.index("[error]")
    warn_idx = out.index("[warning]")
    assert err_idx < warn_idx
    assert "budget.max_dollars" in out
