import subprocess

from maverick.sandbox.docker import DockerBackend


def test_timeout_forces_container_cleanup(monkeypatch, tmp_path):
    calls = []

    def _fake_run(args, **kwargs):
        calls.append(args)
        if args[:2] == ["docker", "version"]:
            return subprocess.CompletedProcess(args, 0, stdout="ok", stderr="")
        if args[:2] == ["docker", "run"]:
            raise subprocess.TimeoutExpired(args, kwargs.get("timeout", 0), output=b"partial")
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
