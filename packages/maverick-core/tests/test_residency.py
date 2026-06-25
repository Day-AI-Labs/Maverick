"""Data residency / region pinning (#41): off by default; strict mode pins a
declared region against an allowed set and refuses boot when incoherent."""
from __future__ import annotations

import pytest
from maverick import residency


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for var in ("MAVERICK_RESIDENCY_STRICT", "MAVERICK_DATA_REGION",
                "MAVERICK_RESIDENCY_ALLOWED"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr("maverick.config.load_config", lambda *a, **k: {})


def test_off_by_default_is_noop():
    assert residency.residency_strict() is False
    ok, _ = residency.check_residency()
    assert ok is True
    residency.require_residency_or_die()  # no raise


def test_strict_without_region_fails(monkeypatch):
    monkeypatch.setenv("MAVERICK_RESIDENCY_STRICT", "1")
    ok, detail = residency.check_residency()
    assert ok is False and "no region declared" in detail
    with pytest.raises(residency.ResidencyError):
        residency.require_residency_or_die()


def test_strict_region_in_allowed_group_passes(monkeypatch):
    # region DE satisfies an allowed set of ["EU"] (group expansion).
    monkeypatch.setenv("MAVERICK_RESIDENCY_STRICT", "1")
    monkeypatch.setenv("MAVERICK_DATA_REGION", "de")
    monkeypatch.setenv("MAVERICK_RESIDENCY_ALLOWED", "EU")
    ok, detail = residency.check_residency()
    assert ok is True and "DE" in detail
    residency.require_residency_or_die()


def test_strict_region_outside_allowed_fails(monkeypatch):
    monkeypatch.setenv("MAVERICK_RESIDENCY_STRICT", "1")
    monkeypatch.setenv("MAVERICK_DATA_REGION", "US")
    monkeypatch.setenv("MAVERICK_RESIDENCY_ALLOWED", "EU")
    ok, detail = residency.check_residency()
    assert ok is False and "not in the allowed set" in detail
    with pytest.raises(residency.ResidencyError):
        residency.require_residency_or_die()


def test_strict_region_no_allowlist_passes(monkeypatch):
    # A declared region with no allowlist is unconstrained -> ok.
    monkeypatch.setenv("MAVERICK_RESIDENCY_STRICT", "1")
    monkeypatch.setenv("MAVERICK_DATA_REGION", "US")
    ok, _ = residency.check_residency()
    assert ok is True


def test_group_region_satisfied_by_member_allowlist(monkeypatch):
    # region EU is admitted when the allowlist names its members.
    monkeypatch.setenv("MAVERICK_RESIDENCY_STRICT", "1")
    monkeypatch.setenv("MAVERICK_DATA_REGION", "EU")
    monkeypatch.setenv("MAVERICK_RESIDENCY_ALLOWED", "DE,FR")
    ok, _ = residency.check_residency()
    assert ok is True


def test_config_drives_when_env_absent(monkeypatch):
    monkeypatch.setattr(
        "maverick.config.load_config",
        lambda *a, **k: {"residency": {
            "strict": True, "region": "US", "allowed_regions": ["EU"]}},
    )
    ok, detail = residency.check_residency()
    assert ok is False and "not in the allowed set" in detail


def test_verify_deployment_includes_residency(monkeypatch):
    # The guarantee surfaces in verify_deployment and passes when off.
    from maverick.deployment import verify_deployment
    names = {c.name for c in verify_deployment()}
    assert "Data residency" in names
