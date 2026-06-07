"""`maverick onboard` CLI: generate + approve + save a domain pack (CliRunner).

Imports maverick.cli (the full kernel + click), so it runs in CI. Uses
``--no-llm`` for deterministic, network-free generation.
"""
from __future__ import annotations


def test_onboard_generates_and_activates(tmp_path, monkeypatch):
    from click.testing import CliRunner
    from maverick.cli import main

    monkeypatch.setenv("MAVERICK_DOMAINS_DIR", str(tmp_path / "domains"))
    doc = tmp_path / "policy.txt"
    doc.write_text("We ship within two business days.")

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["onboard", "--no-llm", "--name", "Acme Co", "--doc", str(doc), "--yes"],
        input="an online store\nretail\n",  # description + industry prompts
    )
    assert result.exit_code == 0, result.output
    assert "Activated" in result.output

    from maverick.domain import available_domains
    domains = available_domains()
    assert "acme_co" in domains
    assert domains["acme_co"].compartment == "acme_co"


def test_onboard_discards_without_approval(tmp_path, monkeypatch):
    from click.testing import CliRunner
    from maverick.cli import main

    monkeypatch.setenv("MAVERICK_DOMAINS_DIR", str(tmp_path / "domains"))
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["onboard", "--no-llm", "--name", "Beta Co"],
        # description, industry (blank), end document collection (blank), decline
        input="a logistics firm\n\n\nn\n",
    )
    assert result.exit_code == 0, result.output
    assert "Discarded" in result.output

    from maverick.domain import available_domains
    assert "beta_co" not in available_domains()  # nothing saved without a yes
