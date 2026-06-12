"""`maverick tenant quota` input validation and display consistency.

User-testing findings: (1) a negative cap was silently clamped to 0 -- i.e.
UNLIMITED -- so a typo'd `-5` quietly removed the cap; (2) setting the cap to 0
printed "$0/day" while `tenant list` rendered the same value as "unlimited",
a contradiction in one operation.
"""
from __future__ import annotations

import pytest
from click.testing import CliRunner
from maverick.cli import main


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path))
    monkeypatch.delenv("MAVERICK_TENANT", raising=False)


def _provision(tenant_id="acme"):
    from maverick import tenant_registry as tr
    tr.create_tenant(tenant_id, plan="pro")


def test_quota_rejects_negative_instead_of_silently_unlimiting():
    _provision()
    res = CliRunner().invoke(main, ["tenant", "quota", "acme", "--", "-5"])
    assert res.exit_code == 2, res.output
    assert "negative" in res.output
    # The cap must be unchanged (still unlimited == 0), not the clamped value.
    from maverick.tenant_registry import get_tenant
    assert get_tenant("acme").max_daily_dollars == 0.0


def test_quota_zero_reads_as_unlimited_consistently():
    _provision()
    res = CliRunner().invoke(main, ["tenant", "quota", "acme", "0"])
    assert res.exit_code == 0, res.output
    assert "unlimited" in res.output
    assert "$0/day" not in res.output
    # ...and the listing agrees.
    lst = CliRunner().invoke(main, ["tenant", "list"])
    assert "quota=unlimited" in lst.output


def test_quota_positive_is_shown_per_day():
    _provision()
    res = CliRunner().invoke(main, ["tenant", "quota", "acme", "25"])
    assert res.exit_code == 0, res.output
    assert "$25/day" in res.output


def test_tenant_list_flags_over_quota():
    # Enforcement is at serve time, but the operator must be able to SEE which
    # tenants are over their daily cap from `tenant list`.
    from datetime import datetime, timezone

    from maverick import tenant_registry as tr
    from maverick.billing import ledger_for_tenant
    tr.create_tenant("acme", plan="pro")
    tr.set_quota("acme", 1.0)
    tr.create_tenant("beta", plan="free")  # unlimited -> never flagged
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    ledger_for_tenant("acme").record("user:x", 5.0, 1000, 200, day=today)

    res = CliRunner().invoke(main, ["tenant", "list"])
    assert res.exit_code == 0, res.output
    assert "OVER QUOTA" in res.output
    # The flag is on acme's line, not beta's.
    acme_line = next(ln for ln in res.output.splitlines() if ln.strip().startswith("acme"))
    beta_line = next(ln for ln in res.output.splitlines() if ln.strip().startswith("beta"))
    assert "OVER QUOTA" in acme_line and "OVER QUOTA" not in beta_line
