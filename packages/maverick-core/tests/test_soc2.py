"""Tests for the SOC 2 evidence collector (``maverick.soc2``).

Hermetic: the autouse ``_isolate_maverick_home`` fixture in ``conftest.py``
points ``~/.maverick`` at a per-test temp dir, so these never touch a real
home or audit log. We monkeypatch the per-control ``enabled()`` predicates on
their *defining* modules (the collector imports them lazily by dotted path, so
patching the source attribute is what it sees).
"""
from __future__ import annotations

import maverick.capability as capability
import maverick.oidc as oidc
import maverick.paths as paths
import maverick.quotas as quotas
from maverick import soc2


def test_returns_expected_shape():
    """The snapshot always carries the documented top-level + control keys."""
    ev = soc2.collect_soc2_evidence()
    assert isinstance(ev, dict)

    assert set(ev) >= {
        "version",
        "collected_at",
        "controls",
        "audit_log",
        "audit_signing_key",
    }
    assert isinstance(ev["version"], str)
    assert isinstance(ev["collected_at"], float)

    controls = ev["controls"]
    assert set(controls) == {
        "capability_enforcement",
        "tenant_isolation",
        "usage_quotas",
        "oidc_auth",
    }
    # Every control probe reports a status from the known vocabulary.
    known = {
        soc2.STATUS_ENABLED,
        soc2.STATUS_DISABLED,
        soc2.STATUS_ABSENT,
        soc2.STATUS_UNKNOWN,
    }
    for probe in controls.values():
        assert probe["status"] in known

    # The audit sub-probes are dicts with a status.
    assert isinstance(ev["audit_log"], dict)
    assert "status" in ev["audit_log"]
    assert isinstance(ev["audit_signing_key"], dict)
    assert "status" in ev["audit_signing_key"]


def test_is_json_serializable():
    """An auditor / CLI serializes this to JSON — it must round-trip."""
    import json

    ev = soc2.collect_soc2_evidence()
    assert json.loads(json.dumps(ev)) == ev


def test_toggle_on_is_reflected(monkeypatch):
    """Flipping each enabled() predicate ON flips the snapshot to ``enabled``."""
    monkeypatch.setattr(capability, "capability_enforced", lambda: True)
    monkeypatch.setattr(paths, "tenant_by_user_enabled", lambda: True)
    monkeypatch.setattr(quotas, "quotas_enforced", lambda: True)
    monkeypatch.setattr(oidc, "oidc_enabled", lambda: True)

    controls = soc2.collect_soc2_evidence()["controls"]
    assert controls["capability_enforcement"] == {
        "status": soc2.STATUS_ENABLED,
        "enabled": True,
    }
    assert controls["tenant_isolation"]["status"] == soc2.STATUS_ENABLED
    assert controls["tenant_isolation"]["enabled"] is True
    assert controls["usage_quotas"]["status"] == soc2.STATUS_ENABLED
    assert controls["usage_quotas"]["enabled"] is True
    assert controls["oidc_auth"]["status"] == soc2.STATUS_ENABLED
    assert controls["oidc_auth"]["enabled"] is True


def test_toggle_off_is_reflected(monkeypatch):
    """Flipping each enabled() predicate OFF flips the snapshot to ``disabled``."""
    monkeypatch.setattr(capability, "capability_enforced", lambda: False)
    monkeypatch.setattr(paths, "tenant_by_user_enabled", lambda: False)
    monkeypatch.setattr(quotas, "quotas_enforced", lambda: False)
    monkeypatch.setattr(oidc, "oidc_enabled", lambda: False)

    controls = soc2.collect_soc2_evidence()["controls"]
    for cid in (
        "capability_enforcement",
        "tenant_isolation",
        "usage_quotas",
        "oidc_auth",
    ):
        assert controls[cid]["status"] == soc2.STATUS_DISABLED
        assert controls[cid]["enabled"] is False


def test_toggle_changes_snapshot(monkeypatch):
    """The same probe reports different statuses as the toggle moves on->off."""
    monkeypatch.setattr(capability, "capability_enforced", lambda: True)
    on = soc2.collect_soc2_evidence()["controls"]["capability_enforcement"]["status"]
    monkeypatch.setattr(capability, "capability_enforced", lambda: False)
    off = soc2.collect_soc2_evidence()["controls"]["capability_enforcement"]["status"]
    assert on == soc2.STATUS_ENABLED
    assert off == soc2.STATUS_DISABLED
    assert on != off


def test_oidc_probe_reflects_real_toggle_by_default():
    """``maverick.oidc`` ships and is off by default -> ``disabled`` (a real toggle,
    not ``absent``). Its presence is what makes OIDC an Implemented control."""
    probe = soc2.collect_soc2_evidence()["controls"]["oidc_auth"]
    assert probe["status"] == soc2.STATUS_DISABLED
    assert probe["enabled"] is False


def test_absent_optional_module_is_absent_not_crash():
    """A genuinely-missing optional module -> ``absent`` (and never raises).

    Exercised directly on ``_probe_toggle`` with a module name guaranteed not to
    exist, so the test stays true even as OIDC (which now ships) toggles on/off.
    This is the path a future-only optional control would take.
    """
    probe = soc2._probe_toggle("maverick._definitely_not_a_real_module", "anything")
    assert probe["status"] == soc2.STATUS_ABSENT
    assert probe["enabled"] is None


def test_present_module_missing_attr_is_absent():
    """A shipped module without the expected predicate -> ``absent``, not a crash."""
    probe = soc2._probe_toggle("maverick.capability", "no_such_predicate_xyz")
    assert probe["status"] == soc2.STATUS_ABSENT
    assert probe["enabled"] is None


def test_failsoft_when_toggle_probe_raises(monkeypatch):
    """A predicate that throws -> that control is ``unknown``; dict still returns."""

    def boom():
        raise RuntimeError("config blew up")

    monkeypatch.setattr(capability, "capability_enforced", boom)

    ev = soc2.collect_soc2_evidence()
    assert isinstance(ev, dict)
    probe = ev["controls"]["capability_enforcement"]
    assert probe["status"] == soc2.STATUS_UNKNOWN
    assert probe["enabled"] is None
    assert "config blew up" in probe.get("error", "")
    # The blast radius is one control — the others still report normally.
    assert ev["controls"]["tenant_isolation"]["status"] in {
        soc2.STATUS_ENABLED,
        soc2.STATUS_DISABLED,
    }


def test_failsoft_when_toggle_probe_raises_base_exception(monkeypatch):
    """Even a ``BaseException`` (e.g. a native-crypto pyo3 panic) is contained.

    A half-installed crypto backend raises ``BaseException``, which ``except
    Exception`` would miss. The probe must still degrade to ``unknown``.
    """

    def panic():
        raise BaseException("native backend panic")  # noqa: TRY002

    monkeypatch.setattr(capability, "capability_enforced", panic)

    ev = soc2.collect_soc2_evidence()
    assert isinstance(ev, dict)
    assert ev["controls"]["capability_enforcement"]["status"] == soc2.STATUS_UNKNOWN


def test_failsoft_when_audit_probe_raises(monkeypatch):
    """An exploding audit sub-probe is contained; snapshot still returns a dict."""

    def boom():
        raise RuntimeError("audit subsystem on fire")

    monkeypatch.setattr(soc2, "_probe_audit_chain", boom)
    monkeypatch.setattr(soc2, "_probe_signing_key", boom)

    ev = soc2.collect_soc2_evidence()
    assert isinstance(ev, dict)
    assert ev["audit_log"] == {"status": soc2.STATUS_UNKNOWN}
    assert ev["audit_signing_key"] == {"status": soc2.STATUS_UNKNOWN}


def test_audit_chain_empty_on_fresh_home():
    """With an isolated, empty home there are no day-files -> ``empty``."""
    probe = soc2.collect_soc2_evidence()["audit_log"]
    # Fresh isolated home: no audit written yet. Tolerate ``no_crypto`` in case
    # ``cryptography`` is absent in the matrix, but the common case is ``empty``.
    assert probe["status"] in {"empty", "no_crypto", soc2.STATUS_UNKNOWN}


def _write_one_event(*, sign: bool):
    """Write a single audit event to the isolated home via a fresh AuditLog.

    Uses an explicit ``AuditLog`` (not the process singleton, which caches its
    signing decision at construction) so each test controls signing in its own
    isolated home. Returns the resolved audit dir.
    """
    from maverick.audit import AuditEvent, EventKind
    from maverick.audit.writer import AuditLog

    log = AuditLog(sign=sign)
    assert log.record(
        AuditEvent(ts=0.0, kind=EventKind.GOAL_START, payload={"title": "soc2 test"})
    )
    return log.audit_dir


def test_audit_chain_unsigned_when_signing_off():
    """Day-files written with signing OFF report ``unsigned`` (not ``broken``).

    ``unsigned`` is a benign configuration state; conflating it with ``broken``
    would falsely alarm an auditor. Works whether or not crypto is installed.
    """
    _write_one_event(sign=False)
    probe = soc2.collect_soc2_evidence()["audit_log"]
    # With crypto present the per-row "missing hash/sig" maps to ``unsigned``.
    # With crypto absent ``verify_chain`` short-circuits to ``no_crypto``. With a
    # *broken* native crypto backend (it panics), the probe is fail-soft
    # ``unknown``. The load-bearing assertion is that it is never ``broken`` —
    # signing-off must not be mistaken for tampering.
    assert probe["status"] in {"unsigned", "no_crypto", soc2.STATUS_UNKNOWN}
    assert probe["status"] != "broken"


def test_audit_chain_ok_after_a_signed_write():
    """After a real *signed* audit write, the chain verifies clean (``ok``).

    Skips when ``cryptography`` is unavailable — either genuinely absent (then
    the chain status is ``no_crypto``, not ``ok``) or a broken native install
    that panics on import (a ``BaseException``). This test asserts the happy
    ``ok`` path; the fail-soft / unsigned paths are covered above.
    """
    import pytest
    from maverick.audit import signing

    try:
        crypto_ok = signing._have_crypto()
    except BaseException:  # noqa: BLE001 — broken native crypto backend panics
        crypto_ok = False
    if not crypto_ok:
        pytest.skip("cryptography unavailable; no signed chain to verify")

    _write_one_event(sign=True)

    ev = soc2.collect_soc2_evidence()
    assert ev["audit_log"]["status"] == "ok"
    assert ev["audit_log"]["files_checked"] >= 1
    # A signed write implies the trust-anchor key was created.
    assert ev["audit_signing_key"]["status"] == soc2.STATUS_ENABLED
    assert ev["audit_signing_key"]["present"] is True
