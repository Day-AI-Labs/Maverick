"""Pluggable secret resolution (#54): default env backend is unchanged; the
file backend reads mounted vault/Docker/k8s secret files with env fallback."""
from __future__ import annotations

import pytest
from maverick import secret_provider as sp


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in ("MAVERICK_SECRETS_BACKEND", "MAVERICK_SECRETS_DIR"):
        monkeypatch.delenv(var, raising=False)
    # No config in the way; tests opt in explicitly.
    monkeypatch.setattr("maverick.config.load_config", lambda *a, **k: {})


def test_default_backend_is_env(monkeypatch):
    monkeypatch.setenv("MY_SECRET", "from-env")
    assert sp.get_secret("MY_SECRET") == "from-env"
    assert sp.get_secret("ABSENT") is None
    assert sp.get_secret("ABSENT", "fallback") == "fallback"


def test_file_backend_reads_mounted_secret(monkeypatch, tmp_path):
    (tmp_path / "MAVERICK_OIDC_CLIENT_SECRET").write_text("vault-value\n")
    monkeypatch.setenv("MAVERICK_SECRETS_BACKEND", "file")
    monkeypatch.setenv("MAVERICK_SECRETS_DIR", str(tmp_path))
    # Trailing newline stripped; file wins over a (here absent) env var.
    assert sp.get_secret("MAVERICK_OIDC_CLIENT_SECRET") == "vault-value"


def test_file_backend_falls_back_to_env(monkeypatch, tmp_path):
    monkeypatch.setenv("MAVERICK_SECRETS_BACKEND", "file")
    monkeypatch.setenv("MAVERICK_SECRETS_DIR", str(tmp_path))
    monkeypatch.setenv("ONLY_IN_ENV", "env-value")
    # No file present -> env fallback keeps partial migrations working.
    assert sp.get_secret("ONLY_IN_ENV") == "env-value"


def test_file_backend_lowercase_sibling(monkeypatch, tmp_path):
    (tmp_path / "my_token").write_text("lower")
    monkeypatch.setenv("MAVERICK_SECRETS_BACKEND", "file")
    monkeypatch.setenv("MAVERICK_SECRETS_DIR", str(tmp_path))
    assert sp.get_secret("MY_TOKEN") == "lower"


def test_file_backend_rejects_traversal_name(monkeypatch, tmp_path):
    monkeypatch.setenv("MAVERICK_SECRETS_BACKEND", "file")
    monkeypatch.setenv("MAVERICK_SECRETS_DIR", str(tmp_path))
    monkeypatch.setenv("../etc/passwd", "should-not-read")
    # An unsafe name never forms a path; env fallback returns the env value.
    assert sp.get_secret("../etc/passwd") == "should-not-read"


def test_backend_from_config_when_env_absent(monkeypatch, tmp_path):
    (tmp_path / "CFG_SECRET").write_text("cfg")
    monkeypatch.setattr(
        "maverick.config.load_config",
        lambda *a, **k: {"secrets": {"backend": "file", "dir": str(tmp_path)}},
    )
    assert sp.get_secret("CFG_SECRET") == "cfg"
