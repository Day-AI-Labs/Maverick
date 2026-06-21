"""Per-tenant OAuth token vault: sealed-at-rest, refresh-aware, tenant-isolated.

Hermetic: HOME/MAVERICK_HOME under tmp, and the KMS KEK pinned to a test value
so envelope sealing works without external key material. Needs the
``cryptography`` extra (AES-GCM); self-skips if it's absent.
"""
from __future__ import annotations

import importlib.util
import time

import pytest

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("cryptography") is None,
    reason="cryptography extra not installed (AES-GCM sealing unavailable)",
)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path))
    # A valid 32-byte KEK (64 hex chars) so envelope sealing works hermetically.
    monkeypatch.setenv("MAVERICK_KMS_KEK", "ab" * 32)
    # Clear any cached DEKs between tests so each tmp HOME is independent.
    from maverick.tenant import kms
    kms._clear_cache()


def _vault(tenant="__active__"):
    from maverick.oauth_vault import OAuthVault
    return OAuthVault(tenant)


class TestRoundTrip:
    def test_put_get_roundtrip(self):
        v = _vault()
        v.put("notion", {"access_token": "at-1", "refresh_token": "rt-1", "scope": "read"})
        rec = v.get("notion")
        assert rec["access_token"] == "at-1"
        assert rec["refresh_token"] == "rt-1"
        assert "obtained_at" in rec  # stamped

    def test_get_missing_is_none(self):
        assert _vault().get("nope") is None

    def test_delete(self):
        v = _vault()
        v.put("slack", {"access_token": "x"})
        assert v.delete("slack") is True
        assert v.get("slack") is None
        assert v.delete("slack") is False

    def test_providers_sorted(self):
        v = _vault()
        v.put("zebra", {"access_token": "z"})
        v.put("alpha", {"access_token": "a"})
        assert v.providers() == ["alpha", "zebra"]

    def test_overwrite(self):
        v = _vault()
        v.put("p", {"access_token": "old"})
        v.put("p", {"access_token": "new"})
        assert v.get("p")["access_token"] == "new"


class TestAtRestSealing:
    def test_file_is_sealed_not_plaintext(self):
        from maverick.paths import data_dir
        v = _vault()
        v.put("notion", {"access_token": "super-secret-token", "refresh_token": "rt"})
        blob = data_dir("oauth", "tokens.sealed").read_bytes()
        assert b"super-secret-token" not in blob
        assert b"rt" not in blob or b"refresh_token" not in blob  # not cleartext JSON

    def test_tenant_isolation(self, monkeypatch):
        # A second tenant's vault must not read the first's tokens, and the KMS
        # context binding means the blobs aren't interchangeable.
        from maverick.tenant import kms
        a = _vault("tenant-a")
        a.put("notion", {"access_token": "a-secret"})
        kms._clear_cache()
        b = _vault("tenant-b")
        assert b.get("notion") is None
        assert a.get("notion")["access_token"] == "a-secret"


class TestExpiryAndRefresh:
    def test_is_expired_semantics(self):
        from maverick.oauth_vault import is_expired
        now = 1_000_000.0
        assert is_expired({"expires_at": now - 10}, now=now) is True
        assert is_expired({"expires_at": now + 1000}, now=now, skew=0) is False
        # within skew window counts as expired
        assert is_expired({"expires_at": now + 30}, now=now, skew=60) is True
        # no expiry info -> never expired
        assert is_expired({"access_token": "x"}, now=now) is False

    def test_access_token_returns_valid(self):
        v = _vault()
        v.put("p", {"access_token": "good", "expires_at": time.time() + 3600})
        assert v.access_token("p") == "good"

    def test_access_token_expired_without_refresher_is_none(self):
        v = _vault()
        v.put("p", {"access_token": "stale", "expires_at": time.time() - 10})
        assert v.access_token("p") is None

    def test_access_token_refreshes_and_persists(self):
        v = _vault()
        v.put("p", {"access_token": "stale", "refresh_token": "rt-keep",
                    "expires_at": time.time() - 10})
        calls = []

        def refresher(record):
            calls.append(record)
            # Provider omits refresh_token on refresh (common) -> vault keeps old.
            return {"access_token": "fresh", "expires_in": 3600}

        assert v.access_token("p", refresher=refresher) == "fresh"
        assert len(calls) == 1
        # Rotated record persisted, old refresh token preserved.
        rec = v.get("p")
        assert rec["access_token"] == "fresh"
        assert rec["refresh_token"] == "rt-keep"
        # And a subsequent call uses the now-valid token, no refresh.
        assert v.access_token("p", refresher=refresher) == "fresh"
        assert len(calls) == 1

    def test_access_token_missing_provider_is_none(self):
        assert _vault().access_token("absent", refresher=lambda r: {}) is None


class TestToggles:
    def test_enabled_off_by_default(self, monkeypatch):
        monkeypatch.delenv("MAVERICK_OAUTH_VAULT", raising=False)
        import maverick.config as cfg
        monkeypatch.setattr(cfg, "load_config", lambda *a, **k: {})
        from maverick.oauth_vault import enabled
        assert enabled() is False

    def test_env_override_on(self, monkeypatch):
        monkeypatch.setenv("MAVERICK_OAUTH_VAULT", "1")
        from maverick.oauth_vault import enabled
        assert enabled() is True
