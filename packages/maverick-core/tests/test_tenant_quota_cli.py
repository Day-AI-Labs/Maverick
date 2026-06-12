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
