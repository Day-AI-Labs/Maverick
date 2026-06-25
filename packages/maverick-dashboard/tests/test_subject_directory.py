"""Login-time OIDC subject directory: bridges IdP identifiers to the session
``sub`` so SCIM deprovision can revoke a pairwise-``sub`` session (Entra)."""
from __future__ import annotations

import json

import pytest
from maverick_dashboard import subject_directory as sd


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path))


def test_record_then_lookup_by_each_identifier():
    sd.record_login("pairwise-sub-xyz", ["alice@x.com", "alice", "aad-oid-1"])
    assert sd.subs_for(["alice@x.com"]) == {"pairwise-sub-xyz"}
    assert sd.subs_for(["aad-oid-1"]) == {"pairwise-sub-xyz"}
    assert sd.subs_for(["alice"]) == {"pairwise-sub-xyz"}
    assert sd.subs_for(["unknown@x.com"]) == set()


def test_lookup_is_case_and_space_insensitive():
    sd.record_login("s1", ["Alice@X.com"])
    assert sd.subs_for(["  alice@x.com "]) == {"s1"}


def test_blank_sub_or_identifiers_are_noops():
    sd.record_login("", ["a@x.com"])
    sd.record_login("s", ["", "   ", None])
    assert sd.subs_for(["a@x.com"]) == set()


def test_raw_identifiers_never_hit_disk():
    # Privacy: lookup keys are hashed; the raw email must not appear in the file.
    sd.record_login("s1", ["secret.person@example.com"])
    raw = sd._path().read_text(encoding="utf-8")
    assert "secret.person@example.com" not in raw
    assert "example.com" not in raw
    # The opaque sub (the revocation key, not PII) is stored.
    assert "s1" in raw


def test_corrupt_directory_degrades_to_empty():
    sd._path().parent.mkdir(parents=True, exist_ok=True)
    sd._path().write_text("{ not json", encoding="utf-8")
    # A damaged directory must not raise into login/SCIM -- it only weakens reach.
    assert sd.subs_for(["a@x.com"]) == set()
    sd.record_login("s1", ["a@x.com"])  # overwrites the corrupt file
    assert sd.subs_for(["a@x.com"]) == {"s1"}


def test_lru_prune_keeps_newest(monkeypatch):
    monkeypatch.setattr(sd, "_MAX_ENTRIES", 3)
    for i in range(5):
        sd.record_login(f"sub{i}", [f"user{i}@x.com"], at=float(i))
    data = json.loads(sd._path().read_text(encoding="utf-8"))
    assert len(data) == 3
    # The three newest survive; the two oldest are pruned.
    assert sd.subs_for(["user4@x.com"]) == {"sub4"}
    assert sd.subs_for(["user0@x.com"]) == set()


def test_forget_drops_entries():
    sd.record_login("s1", ["a@x.com", "a"])
    sd.forget(["a@x.com", "a"])
    assert sd.subs_for(["a@x.com"]) == set()


def test_relogin_updates_sub_last_wins():
    sd.record_login("old-sub", ["alice@x.com"], at=1.0)
    sd.record_login("new-sub", ["alice@x.com"], at=2.0)
    assert sd.subs_for(["alice@x.com"]) == {"new-sub"}
