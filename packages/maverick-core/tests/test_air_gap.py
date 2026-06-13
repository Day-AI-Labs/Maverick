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


def _all_local_llm():
    return dict.fromkeys(ROLE_MODELS, _LOCAL)


def test_default_config_is_not_air_gapped():
    # No local override -> default role models are remote (Anthropic).
    rep = audit(config={})
    assert rep["clean"] is False
    assert any("remote model" in v for v in rep["violations"])
    assert any("egress is not deny-all" in v for v in rep["violations"])


def test_fully_local_with_deny_all_is_clean():
    cfg = {"llm": _all_local_llm(), "egress": {"deny": ["*"]}}
    rep = audit(config=cfg)
    assert rep["clean"] is True and rep["violations"] == []


def test_partial_local_override_still_flags_remote_defaults():
    # only one role overridden -> the rest keep remote defaults
    one = dict.fromkeys(list(ROLE_MODELS)[:1], _LOCAL)
    rep = audit(config={"llm": one, "egress": {"deny": ["*"]}})
    assert rep["clean"] is False
    assert any("remote model" in v for v in rep["violations"])


def test_flags_allow_all_egress():
    cfg = {"llm": _all_local_llm(), "egress": {"deny": [], "allow": []}}
    rep = audit(config=cfg)
    assert any("egress is not deny-all" in v for v in rep["violations"])


def test_flags_sandbox_network():
    cfg = {"llm": _all_local_llm(), "egress": {"deny": ["*"]},
           "sandbox": {"allow_network": True}}
    rep = audit(config=cfg)
    assert any("allow_network" in v for v in rep["violations"])


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
