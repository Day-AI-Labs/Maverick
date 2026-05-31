"""Regression tests for bug-hunt wave-5 fixes."""
from __future__ import annotations

import os
import stat

import pytest


class TestSecretsURLToken:
    def test_query_string_credential_redacted(self):
        from maverick.secrets import scrub
        out = scrub("GET https://api.x.com/cb?access_token=abc123secret&page=2")
        assert "abc123secret" not in out
        assert "[REDACTED:url_secret]" in out
        # Non-secret params are preserved.
        assert "page=2" in out

    def test_presigned_sig_redacted(self):
        from maverick.secrets import scrub
        out = scrub("https://s3/obj?X=1&sig=DEADBEEFsignature123")
        assert "DEADBEEFsignature123" not in out


class TestAuditKeyPerms:
    @pytest.mark.skipif(os.name != "posix", reason="POSIX perms")
    def test_private_key_created_0600(self, monkeypatch, tmp_path):
        from maverick.audit import signing
        monkeypatch.setattr(signing, "KEY_DIR", tmp_path / "keys")
        priv_path = signing._save_keypair(b"PRIVATEKEYBYTES", b"PUBKEY", "k1")
        mode = stat.S_IMODE(priv_path.stat().st_mode)
        assert mode == 0o600, oct(mode)


class TestWorldDBPerms:
    @pytest.mark.skipif(os.name != "posix", reason="POSIX perms")
    def test_db_file_created_0600(self, tmp_path):
        from maverick.world_model import open_world
        db = tmp_path / "world.db"
        w = open_world(db)
        try:
            mode = stat.S_IMODE(db.stat().st_mode)
            assert mode == 0o600, oct(mode)
        finally:
            w.close()
