"""`maverick health` / `diagnose` recognize every backend build_sandbox supports.

Previously `_check_sandbox` only knew local/docker/ssh, so a valid podman /
devcontainer / kubernetes / firecracker config was reported as "unsupported"
even though build_sandbox runs it. These pin the expanded coverage.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from maverick import config, health
from maverick.tools import diagnose as d


def _health_details(cfg, monkeypatch, *, which=True, run_ok=True) -> str:
    rows: list[str] = []
    monkeypatch.setattr(
        health, "_row",
        lambda marker, label, detail="", fix="": rows.append(f"{detail} || {fix}"),
    )
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}" if which else None)
    if run_ok:
        monkeypatch.setattr("subprocess.run", lambda *a, **k: MagicMock(returncode=0))
    health._check_sandbox(cfg)
    return "\n".join(rows)


class TestHealthBackendCoverage:
    @pytest.mark.parametrize("backend,needle", [
        ("podman", "podman responding"),
        ("kubernetes", "kubectl present"),
        ("devcontainer", "devcontainer"),
    ])
    def test_backend_recognized(self, backend, needle, monkeypatch):
        out = _health_details({"sandbox": {"backend": backend}}, monkeypatch)
        assert needle in out
        assert "not recognized" not in out

    def test_firecracker_local_binary_present(self, monkeypatch):
        out = _health_details(
            {"sandbox": {"backend": "firecracker", "provider": "local"}}, monkeypatch,
        )
        assert "firecracker binary present" in out

    def test_firecracker_e2b_requires_key(self, monkeypatch):
        monkeypatch.delenv("E2B_API_KEY", raising=False)
        cfg = {"sandbox": {"backend": "firecracker", "provider": "e2b"}}
        assert "E2B_API_KEY unset" in _health_details(cfg, monkeypatch, which=False)
        monkeypatch.setenv("E2B_API_KEY", "x")
        assert "via E2B" in _health_details(cfg, monkeypatch, which=False)

    def test_podman_missing_binary_is_red(self, monkeypatch):
        out = _health_details({"sandbox": {"backend": "podman"}}, monkeypatch, which=False)
        assert "podman not on PATH" in out

    def test_truly_unknown_backend_still_flagged(self, monkeypatch):
        out = _health_details({"sandbox": {"backend": "frobnicator"}}, monkeypatch)
        assert "not recognized" in out


class TestDiagnoseBackendCoverage:
    @pytest.mark.parametrize("backend", ["devcontainer", "kubernetes"])
    def test_missing_binary_flagged(self, backend, monkeypatch):
        monkeypatch.setattr(config, "get_sandbox", lambda: {"backend": backend})
        monkeypatch.setattr("shutil.which", lambda name: None)
        assert "not on PATH" in "\n".join(d._check_sandbox())

    def test_firecracker_e2b_missing_key_flagged(self, monkeypatch):
        monkeypatch.setattr(
            config, "get_sandbox",
            lambda: {"backend": "firecracker", "provider": "e2b"},
        )
        monkeypatch.setattr("shutil.which", lambda name: None)
        monkeypatch.delenv("E2B_API_KEY", raising=False)
        assert "E2B_API_KEY unset" in "\n".join(d._check_sandbox())
