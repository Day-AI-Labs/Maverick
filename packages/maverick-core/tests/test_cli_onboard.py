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
    import sqlite3

    from click.testing import CliRunner
    from maverick.cli import main

    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path))
    monkeypatch.delenv("MAVERICK_DOMAINS_DIR", raising=False)
    monkeypatch.delenv("MAVERICK_TENANT", raising=False)
    doc = tmp_path / "policy.txt"
    doc.write_text("Beta Co's private retention schedule is confidential.")

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["onboard", "--no-llm", "--name", "Beta Co", "--doc", str(doc)],
        # description, industry (blank), decline
        input="a logistics firm\n\nn\n",
    )
    assert result.exit_code == 0, result.output
    assert "Discarded" in result.output

    from maverick.domain import available_domains
    from maverick.workspace import Workspace

    assert "beta_co" not in available_domains()  # nothing saved without a yes
    db_path = Workspace.current().knowledge_path
    with sqlite3.connect(db_path) as db:
        (rows,) = db.execute("SELECT COUNT(*) FROM chunks").fetchone()
    assert rows == 0


def test_onboard_persists_documents(tmp_path, monkeypatch):
    from click.testing import CliRunner
    from maverick.cli import main

    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path))
    monkeypatch.delenv("MAVERICK_DOMAINS_DIR", raising=False)
    monkeypatch.delenv("MAVERICK_TENANT", raising=False)
    doc = tmp_path / "policy.txt"
    doc.write_text("Our refund window is thirty days from purchase.")

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["onboard", "--no-llm", "--name", "Acme Co", "--doc", str(doc), "--yes"],
        input="an online store\nretail\n",
    )
    assert result.exit_code == 0, result.output

    # The uploaded doc must SURVIVE the command (the bug was a :memory: store):
    # query the saved pack's knowledge collection from a fresh KB at the tenant
    # store path and find the content.
    from maverick.config import get_knowledge
    from maverick.domain import available_domains
    from maverick.workspace import Workspace
    from maverick_knowledge import KnowledgeBase, build_embedder, build_store

    coll = available_domains()["acme_co"].knowledge_sources[0]
    kb = KnowledgeBase(
        store=build_store({"path": str(Workspace.current().knowledge_path)}),
        embedder=build_embedder(get_knowledge()),  # same fallback dim as onboard
    )
    hits = kb.search(coll, "refund window", k=3)
    assert hits and "refund" in hits[0].text.lower()
