"""Phase 5 — headless provisioning (`init --from-file`) + the runtime-protoc
opt-out for immutable/locked-down images."""
from __future__ import annotations

import stat

import pytest
from maverick import grpc_stubs

# ---- runtime-protoc opt-out -----------------------------------------------


def test_runtime_protoc_disabled_env(monkeypatch):
    monkeypatch.setenv("MAVERICK_NO_RUNTIME_PROTOC", "1")
    assert grpc_stubs.runtime_protoc_disabled() is True
    monkeypatch.setenv("MAVERICK_NO_RUNTIME_PROTOC", "0")
    assert grpc_stubs.runtime_protoc_disabled() is False


def test_guard_raises_when_disabled(monkeypatch):
    monkeypatch.setenv("MAVERICK_NO_RUNTIME_PROTOC", "1")
    with pytest.raises(RuntimeError, match="gen-stubs"):
        grpc_stubs.guard_runtime_generation("federation.proto")


def test_guard_noop_when_enabled(monkeypatch):
    monkeypatch.delenv("MAVERICK_NO_RUNTIME_PROTOC", raising=False)
    assert grpc_stubs.guard_runtime_generation("maverick.proto") is None


def test_cli_gen_stubs(monkeypatch):
    from click.testing import CliRunner
    from maverick.cli import main
    monkeypatch.setattr(grpc_stubs, "generate_all",
                        lambda: ["maverick.proto", "federation.proto"])
    r = CliRunner().invoke(main, ["gen-stubs"])
    assert r.exit_code == 0 and "maverick.proto" in r.output


# ---- headless provisioning -------------------------------------------------


def test_init_from_file_installs(monkeypatch, tmp_path):
    from click.testing import CliRunner
    from maverick.cli import main
    src = tmp_path / "client.toml"
    src.write_text('[client]\nid = "acme-corp"\nenforce = true\n')
    dst = tmp_path / "installed" / "config.toml"
    monkeypatch.setenv("MAVERICK_CONFIG", str(dst))

    r = CliRunner().invoke(main, ["init", "--from-file", str(src)])
    assert r.exit_code == 0 and "installed config" in r.output
    assert dst.read_text() == src.read_text()
    assert stat.S_IMODE(dst.stat().st_mode) == 0o600


def test_init_from_file_is_0600_at_creation_not_world_readable(monkeypatch, tmp_path):
    """Regression: the config must be created mode-0600 at creation time.

    The old shutil.copyfile path created the file world-readable (0644 & ~umask)
    and only chmod'd it AFTER the whole body -- which can carry inline provider
    api_keys -- was on disk, a window a co-located user could read. The file must
    be created via os.open with mode 0o600, and ~/.maverick tightened to 0700."""
    import os

    from click.testing import CliRunner
    from maverick.cli import main

    src = tmp_path / "prod.toml"
    src.write_text(
        '[providers.anthropic]\n'
        'api_key = "sk-do-not-leak"  # pragma: allowlist secret\n'
    )
    dst = tmp_path / "installed" / "config.toml"
    monkeypatch.setenv("MAVERICK_CONFIG", str(dst))

    seen: dict = {}
    real_open = os.open

    def spy_open(path, flags, mode=0o777):
        if str(path) == str(dst):
            seen["mode"] = mode
            seen["creat"] = bool(flags & os.O_CREAT)
        return real_open(path, flags, mode)

    monkeypatch.setattr(os, "open", spy_open)
    # A permissive umask would expose a copyfile/write_text path as 0644/0666;
    # mode-at-creation 0o600 is unaffected by it.
    old_umask = os.umask(0)
    try:
        r = CliRunner().invoke(main, ["init", "--from-file", str(src)])
    finally:
        os.umask(old_umask)

    assert r.exit_code == 0
    # Created via os.open(..., O_CREAT, 0o600) -- not copyfile.
    assert seen.get("creat") is True
    assert seen.get("mode") == 0o600
    # Final perms 0600, content byte-preserved, parent dir tightened to 0700.
    assert stat.S_IMODE(dst.stat().st_mode) == 0o600
    assert dst.read_text() == src.read_text()
    assert stat.S_IMODE(dst.parent.stat().st_mode) == 0o700


def test_init_from_file_missing(monkeypatch, tmp_path):
    from click.testing import CliRunner
    from maverick.cli import main
    monkeypatch.setenv("MAVERICK_CONFIG", str(tmp_path / "out.toml"))
    r = CliRunner().invoke(main, ["init", "--from-file", str(tmp_path / "nope.toml")])
    assert r.exit_code != 0


def test_init_from_file_bad_toml(monkeypatch, tmp_path):
    from click.testing import CliRunner
    from maverick.cli import main
    bad = tmp_path / "bad.toml"
    bad.write_text("this is = = not toml")
    monkeypatch.setenv("MAVERICK_CONFIG", str(tmp_path / "out.toml"))
    r = CliRunner().invoke(main, ["init", "--from-file", str(bad)])
    assert r.exit_code != 0 and "invalid TOML" in r.output
