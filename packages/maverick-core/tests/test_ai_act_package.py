"""AI Act conformance package: honest assembly from recorded posture."""
from __future__ import annotations

import json

from maverick import ai_act_package as pkg


def test_build_package_shape(tmp_path, monkeypatch):
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path / "home"))
    p = pkg.build_package()
    assert p["kind"] == "ai-act-technical-documentation"
    assert "classification" in p and "human_oversight" in p
    assert "logging" in p and "evidence" in p
    # nothing recorded in a fresh home -> evidence sections are None
    assert p["evidence"]["redteam"] is None
    assert p["evidence"]["reliability_cert"] is None


def test_render_says_no_evidence_when_absent(tmp_path, monkeypatch):
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path / "home"))
    md = pkg.render_markdown(pkg.build_package())
    assert "no evidence recorded" in md
    assert "Annex III" in md and "Art. 14" in md and "Art. 12" in md
    assert "Completed by the provider" in md  # honest scope split


def test_render_embeds_present_evidence(tmp_path, monkeypatch):
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path / "home"))
    from maverick.paths import data_dir
    cert = data_dir("reliability_cert.json")
    cert.parent.mkdir(parents=True, exist_ok=True)
    cert.write_text(json.dumps({"passed": True, "checks": {}}), encoding="utf-8")
    md = pkg.render_markdown(pkg.build_package())
    assert "reliability certificate: present" in md
    assert '"passed": true' in md


def test_oversight_reflects_env(monkeypatch, tmp_path):
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("MAVERICK_CONSENT_MODE", "dashboard")
    p = pkg.build_package()
    assert p["human_oversight"]["consent_mode"] == "dashboard"
    assert "HALT" in p["human_oversight"]["killswitch_path"]


def test_oversight_consent_mode_matches_real_resolver(monkeypatch, tmp_path):
    """The reported default must mirror the actual resolver, not a guess.

    Regression: _oversight() used to hardcode 'ask (default)' when no consent
    mode was configured, telling an auditor human oversight was in place while
    the real default (consent._resolve_mode) is 'auto-approve'.
    """
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("MAVERICK_CONSENT_MODE", raising=False)
    monkeypatch.delenv("MAVERICK_ENTERPRISE", raising=False)
    from maverick.safety import consent

    resolved = consent._resolve_mode()
    p = pkg.build_package()
    mode = p["human_oversight"]["consent_mode"]
    assert mode.startswith(resolved), (resolved, mode)
    # The fabricated posture must be gone.
    assert mode != "ask (default)"
    assert resolved == "auto-approve"


def test_package_is_json_serializable(tmp_path, monkeypatch):
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path / "home"))
    json.dumps(pkg.build_package(), default=str)
