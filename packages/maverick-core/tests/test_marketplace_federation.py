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
from maverick.marketplace.federation import (
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
    env1 = _export(entries=[dict(LISTING), {**LISTING, "name": "old-skill"}],
                   now=1_750_000_000.0)
    import_listings(env1, peers=_peers_for(env1), store_path=store)
    # A later re-export (newer created_at) withdraws old-skill upstream.
    env2 = _export(entries=[dict(LISTING)], now=1_750_000_500.0)
    import_listings(env2, peers=_peers_for(env2), store_path=store)
    names = [r["name"] for r in imported_listings("skills", store_path=store)]
    assert names == ["peer-a/summarize-url"]


def test_import_rejects_replayed_older_envelope_rollback(tmp_path):
    """Re-sync replaces an origin's whole set, so replaying an OLDER signed
    envelope would resurrect a withdrawn listing. The created_at watermark
    refuses any envelope not strictly newer than the last one applied."""
    store = tmp_path / "imports.json"
    # v1 carries a now-withdrawn listing; v2 (newer) drops it.
    env1 = _export(entries=[dict(LISTING), {**LISTING, "name": "pulled-malware"}],
                   now=1_750_000_000.0)
    env2 = _export(entries=[dict(LISTING)], now=1_750_000_500.0)
    assert import_listings(env1, peers=_peers_for(env1), store_path=store)["ok"]
    assert import_listings(env2, peers=_peers_for(env2), store_path=store)["ok"]
    assert "peer-a/summarize-url" in [
        r["name"] for r in imported_listings(store_path=store)]

    # Attacker replays the genuine, still-validly-signed v1 to bring it back.
    report = import_listings(env1, peers=_peers_for(env1), store_path=store)
    assert not report["ok"]
    assert "rollback" in report["reason"] or "newer" in report["reason"]
    # The withdrawn listing did NOT come back.
    names = [r["name"] for r in imported_listings(store_path=store)]
    assert "peer-a/pulled-malware" not in names
    assert names == ["peer-a/summarize-url"]


def test_import_rejects_exact_replay_of_latest(tmp_path):
    """created_at == watermark is also refused (exact replay, not just older)."""
    store = tmp_path / "imports.json"
    env = _export(now=1_750_000_000.0)
    assert import_listings(env, peers=_peers_for(env), store_path=store)["ok"]
    report = import_listings(env, peers=_peers_for(env), store_path=store)
    assert not report["ok"]


def test_import_rejects_missing_created_at(tmp_path):
    payload = {"schema": SCHEMA, "origin": "peer-a", "listings": [dict(LISTING)]}
    env = sign_envelope(payload)
    report = import_listings(env, peers=_peers_for(env),
                             store_path=tmp_path / "i.json")
    assert not report["ok"] and "created_at" in report["reason"]


def test_verify_envelope_rejects_recursion_bomb():
    """A deeply-nested envelope must be rejected at the depth gate, not crash the
    digest (json.dumps) with a RecursionError. The pubkey here matches the pinned
    key, so without the guard verification would reach _digest and blow the stack
    — an unauthenticated DoS (the pinned pubkey is public)."""
    from maverick.federation_envelope import verify_envelope
    deep: dict = {}
    cur = deep
    for _ in range(5000):
        cur["x"] = {}
        cur = cur["x"]
    deep.update({"schema": SCHEMA, "origin": "o", "sig": "ab", "pubkey": "ab" * 32})
    peers = {"o": {"origin": "o", "pubkey": "ab" * 32}}
    ok, reason = verify_envelope(deep, expected_schema=SCHEMA, peers=peers)
    assert ok is False
    assert "deep" in reason  # rejected cleanly, not via RecursionError


def test_distinct_origins_have_independent_watermarks(tmp_path):
    """One origin's watermark must not block a different origin's first import."""
    store = tmp_path / "imports.json"
    env_a = _export(origin="peer-a", now=1_750_000_900.0)
    import_listings(env_a, peers=_peers_for(env_a, "peer-a"), store_path=store)
    # peer-b's older-timestamped envelope is still its FIRST, so it's accepted.
    env_b = _export(origin="peer-b", now=1_750_000_100.0)
    report = import_listings(env_b, peers=_peers_for(env_b, "peer-b"),
                             store_path=store)
    assert report["ok"], report["reason"]


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
    import maverick.marketplace.federation as mod
    assert "Ratings do NOT federate" in (mod.__doc__ or "")


def test_listing_name_charset_is_validated():
    # A peer controls `name`; on import it becomes the f"{origin}/{name}" key.
    # _listing_for_export (the export AND import normalizer) must drop names with
    # a `/` (key injection), a leading `..`/`.` (traversal/hidden), or whitespace/
    # control chars, while keeping ordinary kebab/identifier/dotted/scoped names.
    from maverick.marketplace.federation import _listing_for_export

    base = {"kind": "skills", "summary": "s",
            "source": "gh:a:b", "sha256": "ab" * 32}
    for ok in ("summarize-url", "my_plugin", "tool.v2", "Weather3", "scope@pkg"):
        assert _listing_for_export({**base, "name": ok}) is not None, ok
    for bad in ("../etc", "other-origin/foo", "a/b", "a b", ".hidden", "x\ny", "/abs"):
        assert _listing_for_export({**base, "name": bad}) is None, bad


def test_concurrent_imports_from_different_origins_do_not_clobber(tmp_path):
    """import_listings does a load-modify-save of one shared store. Two
    concurrent imports from DIFFERENT origins must each keep their listings AND
    their rollback watermark -- without the lock the second save (built on the
    pre-first snapshot) wipes the first origin's listings + watermark, reopening
    the replay window."""
    import threading

    from maverick.marketplace.federation import _WATERMARK_KEY, _load_store

    store = tmp_path / "fed_store.json"
    env_a = _export(origin="peer-a", now=1_750_000_000.0)
    env_b = _export(origin="peer-b", now=1_750_000_500.0)
    peers = {"peer-a": {"origin": "peer-a", "pubkey": env_a["pubkey"]},
             "peer-b": {"origin": "peer-b", "pubkey": env_b["pubkey"]}}
    reports: list[dict] = []
    lock = threading.Lock()
    barrier = threading.Barrier(2)

    def do(env):
        barrier.wait()
        r = import_listings(env, peers=peers, store_path=store)
        with lock:
            reports.append(r)

    ts = [threading.Thread(target=do, args=(env_a,)),
          threading.Thread(target=do, args=(env_b,))]
    for t in ts:
        t.start()
    for t in ts:
        t.join()

    assert all(r["ok"] for r in reports), reports
    # Both origins' listings survive.
    names = {ls["name"] for ls in imported_listings(store_path=store)}
    assert "peer-a/summarize-url" in names
    assert "peer-b/summarize-url" in names
    # Both rollback watermarks survive (neither was clobbered).
    wm = _load_store(store).get(_WATERMARK_KEY) or {}
    assert "peer-a" in wm and "peer-b" in wm
    assert list(tmp_path.glob("*.tmp")) == []
