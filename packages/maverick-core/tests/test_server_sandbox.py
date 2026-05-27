from __future__ import annotations

from pathlib import Path


def test_build_from_config_uses_configured_sandbox_backend(monkeypatch, tmp_path):
    from maverick import server as server_mod

    class _FakeWorld:
        pass

    class _FakeLLM:
        pass

    calls = {}

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(server_mod, "load_config", lambda: {
        "sandbox": {"backend": "docker", "workdir": str(tmp_path)},
        "channels": {},
    })
    monkeypatch.setattr(server_mod, "WorldModel", _FakeWorld)
    monkeypatch.setattr(server_mod, "LLM", _FakeLLM)

    def _fake_build_sandbox(*, workdir=None, backend=None):
        calls["workdir"] = workdir
        calls["backend"] = backend

        class _Sandbox:
            pass

        return _Sandbox()

    monkeypatch.setattr(server_mod, "build_sandbox", _fake_build_sandbox)

    try:
        server_mod.build_from_config()
    except RuntimeError as e:
        assert "No channels enabled" in str(e)

    assert calls["backend"] == "docker"
    assert Path(calls["workdir"]) == tmp_path
