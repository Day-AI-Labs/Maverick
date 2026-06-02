import os
import subprocess

import pytest
from maverick.sandbox.docker import DockerBackend
from maverick.sandbox.podman import PodmanBackend


def _capture_run_argv(monkeypatch, Backend, verify_attr, tmp_path, **kw):
    """Run exec() once with subprocess.run mocked; return the run/exec argv."""
    monkeypatch.setattr(Backend, verify_attr, lambda self: None)
    cap: dict = {}

    class _R:
        stdout = ""
        stderr = ""
        returncode = 0

    monkeypatch.setattr(subprocess, "run", lambda args, **k: cap.update(args=args) or _R())
    Backend(workdir=tmp_path, **kw).exec("echo hi")
    return cap["args"]


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="POSIX-only uid/gid")
@pytest.mark.parametrize("Backend,verify", [
    (DockerBackend, "_verify_docker"),
    (PodmanBackend, "_verify_podman"),
])
def test_runs_non_root_by_default(monkeypatch, tmp_path, Backend, verify):
    monkeypatch.delenv("MAVERICK_SANDBOX_ALLOW_ROOT", raising=False)
    args = _capture_run_argv(monkeypatch, Backend, verify, tmp_path)
    assert "--user" in args
    assert args[args.index("--user") + 1] == f"{os.getuid()}:{os.getgid()}"


@pytest.mark.parametrize("Backend,verify", [
    (DockerBackend, "_verify_docker"),
    (PodmanBackend, "_verify_podman"),
])
def test_allow_root_field_drops_user_flag(monkeypatch, tmp_path, Backend, verify):
    monkeypatch.delenv("MAVERICK_SANDBOX_ALLOW_ROOT", raising=False)
    args = _capture_run_argv(monkeypatch, Backend, verify, tmp_path, allow_root=True)
    assert "--user" not in args


def test_allow_root_env_var_drops_user_flag(monkeypatch, tmp_path):
    monkeypatch.setenv("MAVERICK_SANDBOX_ALLOW_ROOT", "1")
    args = _capture_run_argv(monkeypatch, DockerBackend, "_verify_docker", tmp_path)
    assert "--user" not in args


def test_memory_swap_pinned_to_memory(monkeypatch, tmp_path):
    args = _capture_run_argv(monkeypatch, DockerBackend, "_verify_docker", tmp_path,
                             memory="2g")
    assert args[args.index("--memory") + 1] == "2g"
    assert args[args.index("--memory-swap") + 1] == "2g"


def test_timeout_cleanup_failure_surfaced(monkeypatch, tmp_path):
    """If reaping the orphaned container fails, the leak is reported in stderr
    rather than swallowed under a bare except."""
    monkeypatch.setattr(DockerBackend, "_verify_docker", lambda self: None)

    def _fake_run(args, **kwargs):
        if args[:2] == ["docker", "run"]:
            raise subprocess.TimeoutExpired(args, kwargs.get("timeout", 0), output=b"x")
        if args[:2] == ["docker", "kill"]:
            raise OSError("daemon wedged")
        raise AssertionError(f"unexpected: {args}")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    result = DockerBackend(workdir=tmp_path).exec("sleep 30", timeout=1)
    assert result.exit_code == 124
    assert result.stderr.startswith("TIMEOUT after 1s")
    assert "cleanup failed" in result.stderr


def test_timeout_forces_container_cleanup(monkeypatch, tmp_path):
    calls = []

    def _fake_run(args, **kwargs):
        calls.append(args)
        if args[:2] == ["docker", "version"]:
            return subprocess.CompletedProcess(args, 0, stdout="ok", stderr="")
        if args[:2] == ["docker", "run"]:
            raise subprocess.TimeoutExpired(args, kwargs.get("timeout", 0), output=b"partial")
        if args[:2] == ["docker", "kill"]:
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        if args[:3] == ["docker", "rm", "-f"]:
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        raise AssertionError(f"unexpected docker call: {args}")

    monkeypatch.setattr(subprocess, "run", _fake_run)

    backend = DockerBackend(workdir=tmp_path)
    result = backend.exec("sleep 30", timeout=1)

    assert result.exit_code == 124
    assert "TIMEOUT after 1s" == result.stderr
    assert result.stdout == "partial"

    run_args = next(args for args in calls if args[:2] == ["docker", "run"])
    rm_args = next(args for args in calls if args[:3] == ["docker", "rm", "-f"])
    assert "--name" in run_args
    container_name = run_args[run_args.index("--name") + 1]
    assert rm_args[3] == container_name


def test_build_sandbox_parses_string_false_docker_controls(monkeypatch, tmp_path):
    """Quoted/interpolated false must not enable Docker network or root."""
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join([
            "[sandbox]",
            'backend = "docker"',
            f'workdir = "{tmp_path}"',
            'allow_network = "${MAV_ALLOW_NETWORK}"',
            'allow_root = "false"',
        ])
    )
    monkeypatch.setenv("MAVERICK_CONFIG", str(config_path))
    monkeypatch.setenv("MAV_ALLOW_NETWORK", "false")
    monkeypatch.delenv("MAVERICK_SANDBOX_ALLOW_ROOT", raising=False)

    from maverick.sandbox import DockerBackend, build_sandbox

    monkeypatch.setattr(DockerBackend, "_verify_docker", lambda self: None)

    backend = build_sandbox()
    assert backend.allow_network is False
    assert backend.allow_root is False

    captured: dict = {}

    class _R:
        stdout = ""
        stderr = ""
        returncode = 0

    monkeypatch.setattr(
        subprocess, "run", lambda args, **kwargs: captured.update(args=args) or _R()
    )
    backend.exec("echo hi")

    assert "--network" in captured["args"]
    assert captured["args"][captured["args"].index("--network") + 1] == "none"
    if hasattr(os, "getuid"):
        assert "--user" in captured["args"]
        assert captured["args"][captured["args"].index("--user") + 1] == (
            f"{os.getuid()}:{os.getgid()}"
        )
