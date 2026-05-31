"""GDPR: `maverick erase` scrubs global facts that embed the subject id, and
`export-user` includes them. Facts are global key/value pairs with no
per-user attribution, so matching is a best-effort substring on the user id;
the removed keys are reported so a false positive is visible.
"""
from __future__ import annotations

import json


def test_facts_matching_by_key_or_value(tmp_path):
    from maverick.world_model import WorldModel
    w = WorldModel(tmp_path / "world.db")
    w.upsert_fact("u123_phone", "+1555")      # key contains token
    w.upsert_fact("note", "owner is u123")    # value contains token
    w.upsert_fact("office", "123 Main St")    # unrelated (no 'u123')
    assert set(w.facts_matching("u123")) == {"u123_phone", "note"}
    w.close()


def test_delete_facts_matching_returns_keys_and_keeps_others(tmp_path):
    from maverick.world_model import WorldModel
    w = WorldModel(tmp_path / "world.db")
    w.upsert_fact("u123_phone", "+1555")
    w.upsert_fact("note", "owner is u123")
    w.upsert_fact("office", "123 Main St")
    removed = w.delete_facts_matching("u123")
    assert removed == ["note", "u123_phone"]   # sorted
    assert set(w.get_facts()) == {"office"}     # unrelated kept
    # Empty token is a no-op (never nukes the whole table).
    assert w.delete_facts_matching("") == []
    assert set(w.get_facts()) == {"office"}
    w.close()


def _setup_subject_db(tmp_path):
    from maverick.world_model import WorldModel
    db = tmp_path / "world.db"
    w = WorldModel(db)
    w.get_or_create_conversation("telegram", "u123")  # erase needs a conv
    w.upsert_fact("u123_addr", "secret place")        # matches subject
    w.upsert_fact("global_cfg", "keep me")             # unrelated
    w.close()
    return db


def test_erase_scrubs_facts_containing_subject(tmp_path, monkeypatch):
    import maverick.audit as audit_mod
    from click.testing import CliRunner
    from maverick import cli as cli_mod
    from maverick.world_model import WorldModel

    monkeypatch.setattr(audit_mod, "scrub_user", lambda *a, **k: (0, 0))
    monkeypatch.setattr(audit_mod, "record", lambda kind, **payload: None)

    db = _setup_subject_db(tmp_path)
    res = CliRunner().invoke(cli_mod.main, [
        "--db", str(db), "erase", "--channel", "telegram",
        "--user", "u123", "--yes",
    ])
    assert res.exit_code == 0, res.output
    assert "1 fact(s) scrubbed" in res.output
    assert "u123_addr" in res.output  # the removed key is reported

    w = WorldModel(db)
    facts = w.get_facts()
    w.close()
    assert "u123_addr" not in facts               # scrubbed
    assert facts.get("global_cfg") == "keep me"   # unrelated kept


def test_export_user_includes_matching_facts(tmp_path):
    from click.testing import CliRunner
    from maverick import cli as cli_mod

    db = _setup_subject_db(tmp_path)
    res = CliRunner().invoke(cli_mod.main, [
        "--db", str(db), "export-user", "--channel", "telegram", "--user", "u123",
    ])
    assert res.exit_code == 0, res.output
    data = json.loads(res.output)
    assert data["facts"] == {"u123_addr": "secret place"}
