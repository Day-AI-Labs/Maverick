"""Marketplace federation: signed listing bundles, fail-closed import.

Offline: signing uses the per-test isolated audit keypair (conftest pins
HOME); listings are injected — no catalog fetch, no network.
"""
from __future__ import annotations

import os
import stat

import pytest
from maverick.catalog import CatalogEntry
from maverick.federation_envelope import (
    FederationError,
    peer_allowlist,
    sign_envelope,
    verify_envelope,
)
from maverick.marketplace_federation import (
    MAX_LISTINGS_PER_ENVELOPE,
    SCHEMA,
    export_listings,
    import_listings,
    imported_listings,
)

LISTING = {
    "name": "summarize-url",
    "version": "1.0.0",
    "kind": "skills",
    "summary": "Fetch a URL and summarise it cleanly.",
    "source": "gh:cdayAI/awesome-maverick-skills:summarize-url/SKILL.md",
    "sha256": "ab" * 32,
    "author": "cday",
}


def _export(**kw):
    kw.setdefault("entries", [dict(LISTING)])
    kw.setdefault("origin", "peer-a")
    kw.setdefault("now", 1_750_000_000.0)
    return export_listings(**kw)


def _peers_for(envelope, origin="peer-a"):
    return {origin: {"origin": origin, "pubkey": envelope["pubkey"]}}


# ---------------------------------------------------------------- export ----

def test_export_envelope_shape_and_signature():
    env = _export()
    assert env["schema"] == SCHEMA
    assert env["origin"] == "peer-a"
    assert env["created_at"].startswith("2025-06-15")
    assert [ls["name"] for ls in env["listings"]] == ["summarize-url"]
    for field in ("sig", "pubkey", "key_id"):
        assert env[field]
    ok, reason = verify_envelope(env, expected_schema=SCHEMA, peers=_peers_for(env))
    assert ok, reason


def test_export_accepts_catalog_entries_and_strips_self_asserted_aggregates():
    entry = CatalogEntry(
        name="x", version="1.2.3", kind="skills", summary="s", source="gh:a:b",
        sha256="cd" * 32, author="a", verified=True, install_count=99,
        rating=4.9, ratings_count=12,
    )
    env = _export(entries=[entry])
    (listing,) = env["listings"]
    assert listing["name"] == "x" and listing["version"] == "1.2.3"
    # Ratings do NOT federate; nor do the other self-asserted display fields.
    for absent in ("rating", "ratings_count", "verified", "install_count"):
        assert absent not in listing


def test_export_skips_malformed_entries():
    env = _export(entries=[dict(LISTING), {"name": "", "kind": "skills"},
                           {"name": "y", "kind": "not-a-kind"}, "junk"])
    assert [ls["name"] for ls in env["listings"]] == ["summarize-url"]


def test_export_refuses_unsigned(monkeypatch):
    import maverick.audit.signing as audit_signing
    monkeypatch.setattr(audit_signing, "_have_crypto", lambda: False)
    with pytest.raises(FederationError):
        _export()


# ------------------------------------------------------- import (happy) ----

def test_import_round_trip_namespaces_and_persists(tmp_path):
    store = tmp_path / "imports.json"
    env = _export()
    report = import_listings(env, peers=_peers_for(env), store_path=store,
                             now=1_750_000_100.0)
    assert report["ok"] and report["origin"] == "peer-a"
    assert report["accepted"] == ["peer-a/summarize-url"]
    rows = imported_listings("skills", store_path=store)
    (row,) = rows
    assert row["name"] == "peer-a/summarize-url"
    assert row["fed_origin"] == "peer-a"
    assert row["fed_name"] == "summarize-url"
    assert row["imported_at"] == 1_750_000_100.0
    # Atomic 0600 store.
    mode = stat.S_IMODE(os.stat(store).st_mode)
    assert mode == 0o600
    # Namespacing: every imported name carries the validated origin prefix,
    # so it can never equal a plain local listing name.
    assert all(r["name"].startswith("peer-a/") for r in rows)


def test_reimport_replaces_origin_set(tmp_path):
    store = tmp_path / "imports.json"
    env1 = _export(entries=[dict(LISTING), {**LISTING, "name": "old-skill"}])
    import_listings(env1, peers=_peers_for(env1), store_path=store)
    env2 = _export(entries=[dict(LISTING)])  # old-skill withdrawn upstream
    import_listings(env2, peers=_peers_for(env2), store_path=store)
    names = [r["name"] for r in imported_listings("skills", store_path=store)]
    assert names == ["peer-a/summarize-url"]


# -------------------------------------------------- import (fail-closed) ----

def test_import_rejects_tampered_payload(tmp_path):
    store = tmp_path / "imports.json"
    env = _export()
    env["listings"][0]["summary"] = "now with malware"
    report = import_listings(env, peers=_peers_for(env), store_path=store)
    assert not report["ok"]
    assert "signature" in report["reason"]
    assert not store.exists()  # nothing persisted


def test_import_rejects_missing_signature(tmp_path):
    env = _export()
    del env["sig"]
    report = import_listings(env, peers=_peers_for(env),
                             store_path=tmp_path / "i.json")
    assert not report["ok"] and "signature" in report["reason"]


def test_import_rejects_unknown_origin(tmp_path):
    env = _export()
    report = import_listings(env, peers={}, store_path=tmp_path / "i.json")
    assert not report["ok"]
    assert "trust list" in report["reason"]


def test_import_rejects_pinned_key_mismatch(tmp_path):
    env = _export()
    peers = {"peer-a": {"origin": "peer-a", "pubkey": "0" * 64}}
    report = import_listings(env, peers=peers, store_path=tmp_path / "i.json")
    assert not report["ok"]
    assert "pinned" in report["reason"]


def test_import_rejects_wrong_schema_and_garbage(tmp_path):
    env = _export()
    env["schema"] = "maverick-marketplace-fed/2"
    assert not import_listings(env, peers=_peers_for(env),
                               store_path=tmp_path / "i.json")["ok"]
    assert not import_listings("junk", peers={}, store_path=tmp_path / "i.json")["ok"]
    assert not import_listings(None, peers={}, store_path=tmp_path / "i.json")["ok"]


def test_import_rejects_without_crypto(monkeypatch, tmp_path):
    env = _export()
    peers = _peers_for(env)
    import maverick.audit.signing as audit_signing
    monkeypatch.setattr(audit_signing, "_have_crypto", lambda: False)
    report = import_listings(env, peers=peers, store_path=tmp_path / "i.json")
    assert not report["ok"]
    assert "cryptography" in report["reason"]


def test_import_rejects_oversized_envelope(tmp_path):
    payload = {
        "schema": SCHEMA, "origin": "peer-a", "created_at": "2025-01-01T00:00:00",
        "listings": [dict(LISTING) for _ in range(MAX_LISTINGS_PER_ENVELOPE + 1)],
    }
    env = sign_envelope(payload)
    report = import_listings(env, peers=_peers_for(env),
                             store_path=tmp_path / "i.json")
    assert not report["ok"] and "max" in report["reason"]


# ----------------------------------------------- moderation + donations ----

def test_moderation_gauntlet_filters_imports(tmp_path):
    bad = {**LISTING, "name": "replica-bags", "summary": "counterfeit goods"}
    env = _export(entries=[dict(LISTING), bad])
    report = import_listings(env, peers=_peers_for(env),
                             store_path=tmp_path / "i.json")
    assert report["ok"]
    assert report["accepted"] == ["peer-a/summarize-url"]
    (rej,) = report["rejected"]
    assert rej["name"] == "replica-bags"
    assert any("moderation REJECT" in r for r in rej["reasons"])


def test_invalid_donation_url_is_stripped_valid_kept(tmp_path):
    good = {**LISTING, "donation_url": "https://ko-fi.com/cday"}
    bad = {**LISTING, "name": "other-skill",
           "donation_url": "https://evil.example.com/pay"}
    env = _export(entries=[good, bad])
    report = import_listings(env, peers=_peers_for(env),
                             store_path=tmp_path / "i.json")
    assert report["ok"] and report["stripped_donations"] == ["other-skill"]
    rows = {r["fed_name"]: r for r in imported_listings(store_path=tmp_path / "i.json")}
    assert rows["summarize-url"]["donation_url"] == "https://ko-fi.com/cday"
    assert "donation_url" not in rows["other-skill"]


# ----------------------------------------------------- peer config seam ----

def test_peer_allowlist_parses_tables_and_strings():
    cfg = {"federation": {"marketplace_peers": [
        {"origin": "peer-a", "pubkey": "ab" * 32},
        "peer-b=" + "cd" * 32,
        {"origin": "BAD/ORIGIN", "pubkey": "ab" * 32},   # slash -> skipped
        {"origin": "peer-c", "pubkey": "not-hex"},        # bad key -> skipped
        42,
    ]}}
    peers = peer_allowlist("marketplace_peers", cfg)
    assert set(peers) == {"peer-a", "peer-b"}
    assert peers["peer-b"]["pubkey"] == "cd" * 32


def test_module_states_ratings_do_not_federate():
    import maverick.marketplace_federation as mod
    assert "Ratings do NOT federate" in (mod.__doc__ or "")
