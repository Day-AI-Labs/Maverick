"""Share links + device handoff: signed, expiring, one-time semantics."""
from __future__ import annotations

import pytest
from maverick import share_link as sl


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setenv("MAVERICK_SHARE_SECRET", "test-secret")


def test_share_roundtrip():
    token = sl.mint_share_link(42, now=1000.0)
    assert sl.verify_share_link(token, now=1000.0 + 60) == 42


def test_share_expiry_fails_closed():
    token = sl.mint_share_link(42, ttl_seconds=60, now=1000.0)
    with pytest.raises(ValueError, match="expired"):
        sl.verify_share_link(token, now=1000.0 + 61)


def test_share_tamper_fails():
    token = sl.mint_share_link(42, now=1000.0)
    gid, exp, sig = token.split(".")
    with pytest.raises(ValueError, match="signature"):
        sl.verify_share_link(f"43.{exp}.{sig}", now=1000.0)
    with pytest.raises(ValueError, match="malformed"):
        sl.verify_share_link("garbage")


def test_no_secret_refuses(monkeypatch):
    monkeypatch.delenv("MAVERICK_SHARE_SECRET", raising=False)
    monkeypatch.setattr("maverick.config.load_config", lambda: {})
    with pytest.raises(sl.SharingDisabled):
        sl.mint_share_link(1)
    with pytest.raises(sl.SharingDisabled):
        sl.verify_share_link("1.2.3")


def test_handoff_roundtrip_and_one_time(tmp_path):
    session = {"goal_id": 7, "conversation_id": 3, "channel": "telegram",
               "user_id": "alice"}
    code = sl.pack_handoff(session, now=1000.0)
    nonces = tmp_path / "nonces.json"
    claimed = sl.claim_handoff(code, now=1010.0, nonce_path=nonces)
    assert claimed == session
    # second claim of the same code is refused
    with pytest.raises(ValueError, match="already claimed"):
        sl.claim_handoff(code, now=1020.0, nonce_path=nonces)


def test_handoff_expiry(tmp_path):
    code = sl.pack_handoff({"goal_id": 1}, ttl_seconds=300, now=1000.0)
    with pytest.raises(ValueError, match="expired"):
        sl.claim_handoff(code, now=1000.0 + 301, nonce_path=tmp_path / "n.json")


def test_handoff_tamper_fails(tmp_path):
    code = sl.pack_handoff({"goal_id": 1}, now=1000.0)
    b64, sig = code.split(".")
    with pytest.raises(ValueError, match="signature"):
        sl.claim_handoff(f"{b64}.{'0'*32}", now=1000.0,
                         nonce_path=tmp_path / "n.json")


def test_handoff_nonce_store_pruned(tmp_path):
    nonces = tmp_path / "n.json"
    c1 = sl.pack_handoff({"goal_id": 1}, ttl_seconds=10, now=1000.0)
    sl.claim_handoff(c1, now=1001.0, nonce_path=nonces)
    # much later, a new claim prunes the long-expired nonce
    c2 = sl.pack_handoff({"goal_id": 2}, ttl_seconds=10, now=5000.0)
    sl.claim_handoff(c2, now=5001.0, nonce_path=nonces)
    import json
    stored = json.loads(nonces.read_text())
    assert len(stored) == 1  # only c2's nonce kept


def test_handoff_rejects_invalid_signature_before_json_parse(tmp_path):
    import base64

    body = "[" * 1200
    b64 = base64.urlsafe_b64encode(body.encode("utf-8")).decode("ascii").rstrip("=")
    with pytest.raises(ValueError, match="signature"):
        sl.claim_handoff(f"{b64}.{'0' * 32}", now=1000.0, nonce_path=tmp_path / "n.json")


def test_handoff_concurrent_claim_is_one_time(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    session = {"goal_id": 7, "conversation_id": 3, "channel": "telegram",
               "user_id": "alice"}
    code = sl.pack_handoff(session, now=1000.0)
    nonces = tmp_path / "nonces.json"

    def claim_once():
        try:
            return sl.claim_handoff(code, now=1010.0, nonce_path=nonces)
        except ValueError as e:
            return str(e)

    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(lambda _: claim_once(), range(16)))

    assert results.count(session) == 1
    assert results.count("handoff code already claimed (one-time use)") == 15
