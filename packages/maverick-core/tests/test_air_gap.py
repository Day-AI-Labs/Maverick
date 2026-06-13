"""Air-gapped preflight audit: flag remote providers / egress / sandbox network."""
from __future__ import annotations

from click.testing import CliRunner
from maverick.air_gap import audit
from maverick.cli import main
from maverick.llm import ROLE_MODELS
from maverick.provider_local_first import is_local

# A model spec the local-first classifier recognizes as local.
_LOCAL = next((m for m in ("ollama:llama3", "vllm:x", "tgi:x", "local:x")
               if is_local(m)), "ollama:llama3")


def _all_local_models():
    return {role: _LOCAL for role in ROLE_MODELS}


def test_default_config_is_not_air_gapped():
    # No local override -> default role models are remote (Anthropic).
    rep = audit(config={})
    assert rep["clean"] is False
    assert any("remote model" in v for v in rep["violations"])
    assert any("egress is not deny-all" in v for v in rep["violations"])


def test_fully_local_with_deny_all_is_clean():
    cfg = {"models": _all_local_models(), "egress": {"deny": ["*"]},
           "sandbox": {"backend": "docker"}}
    rep = audit(config=cfg)
    assert rep["clean"] is True and rep["violations"] == []


def test_partial_local_override_still_flags_remote_defaults():
    # only one role overridden -> the rest keep remote defaults
    one = {role: _LOCAL for role in list(ROLE_MODELS)[:1]}
    rep = audit(config={"models": one, "egress": {"deny": ["*"]},
                        "sandbox": {"backend": "docker"}})
    assert rep["clean"] is False
    assert any("remote model" in v for v in rep["violations"])


def test_flags_allow_all_egress():
    cfg = {"models": _all_local_models(), "egress": {"deny": [], "allow": []},
           "sandbox": {"backend": "docker"}}
    rep = audit(config=cfg)
    assert any("egress is not deny-all" in v for v in rep["violations"])


def test_flags_sandbox_network():
    cfg = {"models": _all_local_models(), "egress": {"deny": ["*"]},
           "sandbox": {"backend": "docker", "allow_network": True}}
    rep = audit(config=cfg)
    assert any("allow_network" in v for v in rep["violations"])


def test_llm_section_does_not_hide_runtime_remote_defaults():
    cfg = {"llm": _all_local_models(), "egress": {"deny": ["*"]},
           "sandbox": {"backend": "docker"}}
    rep = audit(config=cfg)
    assert rep["clean"] is False
    assert any("remote model" in v for v in rep["violations"])


def test_default_local_sandbox_is_not_air_gapped():
    cfg = {"models": _all_local_models(), "egress": {"deny": ["*"]}}
    rep = audit(config=cfg)
    assert rep["clean"] is False
    assert any("backend=local" in v for v in rep["violations"])


def test_flags_backend_specific_sandbox_network():
    base = {"models": _all_local_models(), "egress": {"deny": ["*"]}}
    for sandbox in (
        {"backend": "devcontainer"},
        {"backend": "firecracker", "network": "egress-allow"},
        {"backend": "firecracker", "network": "bridge=br0"},
        {"backend": "ssh"},
    ):
        rep = audit(config={**base, "sandbox": sandbox})
        assert rep["clean"] is False
        assert any("sandbox" in v for v in rep["violations"])


def test_cli_airgap_check_fails_when_dirty(monkeypatch):
    monkeypatch.setattr("maverick.air_gap.audit",
                        lambda: {"clean": False, "violations": ["remote model(s) in use: x"]})
    res = CliRunner().invoke(main, ["airgap", "check"])
    assert res.exit_code == 1
    assert "NOT air-gapped" in res.output


def test_cli_airgap_check_passes_when_clean(monkeypatch):
    monkeypatch.setattr("maverick.air_gap.audit",
                        lambda: {"clean": True, "violations": []})
    res = CliRunner().invoke(main, ["airgap", "check"])
    assert res.exit_code == 0
    assert "AIR-GAPPED" in res.output
