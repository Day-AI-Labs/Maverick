"""Federated shield rules updates: signed bundles, fail-closed verification."""

from __future__ import annotations

import json
import sys

import pytest
from maverick import shield_updates
from maverick.audit import signing
from maverick.shield_updates import (
    UpdateRefused,
    apply_update,
    check_and_apply,
    current_version,
    sign_bundle,
    verify_bundle,
)

cryptography = pytest.importorskip("cryptography")
from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ed25519  # noqa: E402

RULES_V1 = [{"id": "block-curl-pipe-sh", "pattern": "curl.*\\|.*sh"}]
RULES_V2 = RULES_V1 + [{"id": "block-ptrace", "pattern": "ptrace"}]


@pytest.fixture(scope="module")
def keypair():
    priv = ed25519.Ed25519PrivateKey.generate()
    priv_hex = priv.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    ).hex()
    pub_hex = (
        priv.public_key()
        .public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        .hex()
    )
    return priv_hex, pub_hex


@pytest.fixture
def rules_file(tmp_path):
    return tmp_path / "shield_rules.json"


# ---- bundle verification (fails CLOSED) ------------------------------------


def test_signed_bundle_roundtrip(keypair):
    priv, pub = keypair
    bundle = sign_bundle(3, RULES_V1, priv)
    assert verify_bundle(bundle, pub) == (3, RULES_V1)


def test_unsigned_bundle_refused(keypair):
    _, pub = keypair
    with pytest.raises(UpdateRefused, match="unsigned"):
        verify_bundle({"version": 1, "rules": []}, pub)


def test_bad_signature_refused(keypair):
    priv, pub = keypair
    bundle = sign_bundle(1, RULES_V1, priv)
    bundle["sig"] = "00" * 64
    with pytest.raises(UpdateRefused, match="signature does not verify"):
        verify_bundle(bundle, pub)


def test_tampered_rules_refused(keypair):
    priv, pub = keypair
    bundle = sign_bundle(1, RULES_V1, priv)
    bundle["rules"] = RULES_V2  # post-signing mutation
    with pytest.raises(UpdateRefused, match="signature does not verify"):
        verify_bundle(bundle, pub)


def test_malformed_bundles_refused(keypair):
    _, pub = keypair
    for bad in (
        None,
        [],
        "x",
        {"rules": []},
        {"version": -1, "rules": [], "sig": "aa"},
        {"version": True, "rules": [], "sig": "aa"},
        {"version": 1, "rules": {}, "sig": "aa"},
    ):
        with pytest.raises(UpdateRefused):
            verify_bundle(bad, pub)


def test_no_configured_pubkey_refused(keypair):
    priv, _ = keypair
    with pytest.raises(UpdateRefused, match="update_pubkey"):
        verify_bundle(sign_bundle(1, RULES_V1, priv), "")


def test_missing_crypto_refuses_closed(keypair, monkeypatch):
    priv, pub = keypair
    bundle = sign_bundle(1, RULES_V1, priv)
    monkeypatch.setattr(signing, "_have_crypto", lambda: False)
    with pytest.raises(UpdateRefused, match="cryptography"):
        verify_bundle(bundle, pub)


# ---- apply (atomic staging, downgrade protection) ---------------------------


def test_apply_stages_rules_file_0600(keypair, rules_file):
    priv, pub = keypair
    result = apply_update(sign_bundle(1, RULES_V1, priv), pubkey_hex=pub, path=rules_file)
    assert result.applied and result.version == 1 and result.previous_version is None
    assert result.added == ["block-curl-pipe-sh"] and result.removed == []
    staged = json.loads(rules_file.read_text(encoding="utf-8"))
    assert staged["version"] == 1 and staged["rules"] == RULES_V1 and staged["sig"]
    assert (rules_file.stat().st_mode & 0o777) == 0o600
    assert not rules_file.with_name(rules_file.name + ".tmp").exists()


def test_apply_reports_what_changed(keypair, rules_file):
    priv, pub = keypair
    apply_update(sign_bundle(1, RULES_V1, priv), pubkey_hex=pub, path=rules_file)
    result = apply_update(
        sign_bundle(2, RULES_V2[1:], priv),
        pubkey_hex=pub,
        path=rules_file,
    )
    assert result.applied and result.previous_version == 1
    assert result.added == ["block-ptrace"]
    assert result.removed == ["block-curl-pipe-sh"]
    assert "block-ptrace" in result.summary()


def test_version_downgrade_refused(keypair, rules_file):
    priv, pub = keypair
    apply_update(sign_bundle(5, RULES_V1, priv), pubkey_hex=pub, path=rules_file)
    with pytest.raises(UpdateRefused, match="downgrade"):
        apply_update(sign_bundle(4, RULES_V2, priv), pubkey_hex=pub, path=rules_file)
    # the staged file is untouched
    assert current_version(rules_file) == 5


def test_same_version_is_noop(keypair, rules_file):
    priv, pub = keypair
    apply_update(sign_bundle(2, RULES_V1, priv), pubkey_hex=pub, path=rules_file)
    result = apply_update(sign_bundle(2, RULES_V1, priv), pubkey_hex=pub, path=rules_file)
    assert not result.applied and "already at v2" in result.reason


def test_current_version_fails_open_on_corrupt_file(rules_file):
    assert current_version(rules_file) is None  # missing
    rules_file.write_text("{not json", encoding="utf-8")
    assert current_version(rules_file) is None  # corrupt


# ---- pull entry point (default OFF, injected fetcher) ------------------------


def _write_config(tmp_path, monkeypatch, body: str):
    cfg = tmp_path / "config.toml"
    cfg.write_text(body, encoding="utf-8")
    monkeypatch.setenv("MAVERICK_CONFIG", str(cfg))


def test_check_and_apply_default_off(tmp_path, monkeypatch):
    _write_config(tmp_path, monkeypatch, "")

    def explode(url):
        raise AssertionError("fetcher must not run when the feature is off")

    result = check_and_apply(fetcher=explode)
    assert not result.applied and "federated_updates is off" in result.reason


def test_check_and_apply_fetches_verifies_and_stages(tmp_path, monkeypatch, keypair):
    priv, pub = keypair
    _write_config(
        tmp_path,
        monkeypatch,
        "[shield]\nfederated_updates = true\n"
        f'update_url = "https://rules.example/bundle.json"\nupdate_pubkey = "{pub}"\n',
    )
    urls = []

    def fetcher(url):
        urls.append(url)
        return json.dumps(sign_bundle(7, RULES_V2, priv))

    result = check_and_apply(fetcher=fetcher)
    assert urls == ["https://rules.example/bundle.json"]
    assert result.applied and result.version == 7
    staged = json.loads(shield_updates.rules_path().read_text(encoding="utf-8"))
    assert staged["rules"] == RULES_V2


def test_check_and_apply_refuses_unparseable_or_failed_fetch(tmp_path, monkeypatch, keypair):
    _, pub = keypair
    _write_config(
        tmp_path,
        monkeypatch,
        "[shield]\nfederated_updates = true\n"
        f'update_url = "https://rules.example/b.json"\nupdate_pubkey = "{pub}"\n',
    )
    with pytest.raises(UpdateRefused, match="not valid JSON"):
        check_and_apply(fetcher=lambda url: "<html>not a bundle</html>")

    def boom(url):
        raise OSError("connection refused")

    with pytest.raises(UpdateRefused, match="fetch failed"):
        check_and_apply(fetcher=boom)


def test_check_and_apply_refuses_oversized_injected_bundle(tmp_path, monkeypatch, keypair):
    _, pub = keypair
    _write_config(
        tmp_path,
        monkeypatch,
        "[shield]\nfederated_updates = true\n"
        f'update_url = "https://rules.example/huge.json"\nupdate_pubkey = "{pub}"\n',
    )
    oversized = " " * (shield_updates.MAX_BUNDLE_BYTES + 1)
    with pytest.raises(UpdateRefused, match="maximum size"):
        check_and_apply(fetcher=lambda url: oversized)


def test_default_fetcher_refuses_oversized_stream_before_json(monkeypatch):
    class FakeResponse:
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def raise_for_status(self):
            return None

        def iter_bytes(self):
            yield b"{"
            yield b" " * shield_updates.MAX_BUNDLE_BYTES

    class FakeHttpx:
        @staticmethod
        def stream(method, url, *, timeout, follow_redirects):
            assert method == "GET"
            assert timeout == 30.0
            assert follow_redirects is True
            return FakeResponse()

    monkeypatch.setitem(sys.modules, "httpx", FakeHttpx)
    with pytest.raises(UpdateRefused, match="maximum size"):
        shield_updates._default_fetcher("https://rules.example/huge.json")


def test_module_never_imports_maverick_shield():
    """Kernel rule 1: the updater only STAGES the rules file -- it must work
    (and import clean) on deployments without maverick_shield installed."""
    import pathlib

    src = pathlib.Path(shield_updates.__file__).read_text(encoding="utf-8")
    assert "import maverick_shield" not in src
    assert "from maverick_shield" not in src
