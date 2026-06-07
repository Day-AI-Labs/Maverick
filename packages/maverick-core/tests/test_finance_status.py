"""Finance posture report (finance-agent-suite §5)."""
from __future__ import annotations

import json

import pytest
from maverick.finance.status import (
    finance_status,
    render_status_json,
    render_status_text,
)


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    # No config / no sanctions list / no signing -> a clean "fresh deploy" view.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    for var in ("MAVERICK_AUDIT_SIGN", "MAVERICK_ENTERPRISE",
                "MAVERICK_ENCRYPTION_KEY"):
        monkeypatch.delenv(var, raising=False)
    yield


def _by_control():
    return {c.control: c for c in finance_status()}


def test_sod_is_active_out_of_the_box():
    # The shipped roster is SoD-clean regardless of config.
    sod = _by_control()["Segregation of duties (roster)"]
    assert sod.status == "active"
    assert "clean" in sod.detail


def test_money_gate_needs_action_without_policy():
    checks = _by_control()
    assert checks["Maker-checker on money movement"].status == "action_needed"
    assert checks["Amount-aware authorization (DoA tiers)"].status == "action_needed"


def test_sanctions_needs_list():
    assert _by_control()["Sanctions screening"].status == "action_needed"


def test_all_controls_present():
    controls = set(_by_control())
    assert {
        "Segregation of duties (roster)",
        "Maker-checker on money movement",
        "Amount-aware authorization (DoA tiers)",
        "Tamper-evident book of record",
        "Sanctions screening",
        "Encryption at rest",
        "Data-egress lock",
        "Compliance regimes enabled",
    } <= controls


def test_render_text_and_json():
    checks = finance_status()
    text = render_status_text(checks)
    assert "Finance control coverage" in text
    assert "not an audit opinion" in text
    parsed = json.loads(render_status_json(checks))
    assert parsed["summary"]["total"] == len(checks)
    assert parsed["controls"]
