"""Tests for the SSH sandbox backend (pure monkeypatch, no real ssh)."""
from __future__ import annotations

import shlex
import shutil
import subprocess
from pathlib import Path

import pytest
from maverick.sandbox import build_sandbox
from maverick.sandbox.ssh import SSHBackend


def _patch_ssh_ok(monkeypatch, run_recorder=None):
    """Make shutil.which find ssh and the verify probe succeed."""
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/ssh")

    def _fake_run(args, **kwargs):
        if run_recorder is not None:
            run_recorder.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", _fake_run)


def test_verify_ssh_probe_runs_on_construction(monkeypatch):
    calls = []
    _patch_ssh_ok(monkeypatch, calls)

    SSHBackend(host="me@example.com", ssh_args=["-i", "key"])

    probe = calls[0][0]
    assert probe[0] == "ssh"
    assert "BatchMode=yes" in probe
    assert "ConnectTimeout=10" in probe
    # Host-key policy pinned on the probe (default accept-new).
    assert "StrictHostKeyChecking=accept-new" in probe
    assert probe[-2:] == ["me@example.com", "true"]
    # ssh_args are threaded into the probe before host.
    assert "-i" in probe and "key" in probe


def test_verify_ssh_missing_binary_raises(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError, match="ssh binary not found"):
        SSHBackend(host="me@example.com")


def test_verify_ssh_failed_probe_raises(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/ssh")

    def _fake_run(args, **kwargs):
        return subprocess.CompletedProcess(args, 255, stdout=b"", stderr=b"perm denied")

    monkeypatch.setattr(subprocess, "run", _fake_run)

    with pytest.raises(RuntimeError, match="ssh to me@example.com failed: perm denied"):
        SSHBackend(host="me@example.com")


def test_exec_builds_mkdir_cd_and_quotes_command(monkeypatch):
    calls = []
    _patch_ssh_ok(monkeypatch)
    backend = SSHBackend(host="me@example.com", workdir="/home/me/ws", ssh_args=["-p", "2222"])

    def _exec_run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, stdout="hi", stderr="warn")

    monkeypatch.setattr(subprocess, "run", _exec_run)

    result = backend.exec("echo $HOME")

    args, kwargs = calls[0]
    assert args[0] == "ssh"
    # ssh hardening opts precede ssh_args, which precede the host.
    assert "BatchMode=yes" in args
    assert "StrictHostKeyChecking=accept-new" in args
    p_idx = args.index("-p")
    assert args[p_idx:p_idx + 2] == ["-p", "2222"]  # ssh_args threaded before host
    host = args[-2]
    remote = args[-1]
    assert host == "me@example.com"
    quoted = shlex.quote("/home/me/ws")
    # cmd runs as a single quoted arg inside sh -c so it can't escape the cd.
    inner = shlex.quote("echo $HOME")
    assert remote == f"mkdir -p {quoted} && cd {quoted} && sh -c {inner}"
    assert kwargs["capture_output"] is True
    assert kwargs["text"] is True
    assert result.stdout == "hi"
    assert result.stderr == "warn"
    assert result.exit_code == 0


def test_exec_cmd_injection_stays_single_arg(monkeypatch):
    """A cmd that tries to break out of the cd guard with a leading `;` must
    stay a single quoted argument to `sh -c`, not splice into the remote
    shell as a second statement that runs outside the workspace."""
    calls = []
    _patch_ssh_ok(monkeypatch)
    backend = SSHBackend(host="me@example.com", workdir="/home/me/ws")

    def _exec_run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", _exec_run)

    evil = "; rm -rf /"
    backend.exec(evil)

    remote = calls[0][0][-1]
    quoted = shlex.quote("/home/me/ws")
    # The whole evil string is one quoted arg to `sh -c` -- it never appears
    # as a bare `; rm -rf /` spliced after the cd.
    assert remote == f"mkdir -p {quoted} && cd {quoted} && sh -c {shlex.quote(evil)}"
    assert remote.endswith(shlex.quote(evil))


def test_exec_uses_default_timeout_then_override(monkeypatch):
    seen = []
    _patch_ssh_ok(monkeypatch)
    backend = SSHBackend(host="me@example.com", timeout=42.0)

    def _exec_run(args, **kwargs):
        seen.append(kwargs.get("timeout"))
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", _exec_run)

    backend.exec("ls")
    backend.exec("ls", timeout=7)

    assert seen == [42.0, 7]


def test_exec_timeout_returns_124(monkeypatch):
    _patch_ssh_ok(monkeypatch)
    backend = SSHBackend(host="me@example.com", timeout=3.0)

    def _exec_run(args, **kwargs):
        raise subprocess.TimeoutExpired(args, kwargs.get("timeout", 0), output=b"partial")

    monkeypatch.setattr(subprocess, "run", _exec_run)

    result = backend.exec("sleep 99")

    assert result.exit_code == 124
    assert result.stderr == "TIMEOUT after 3.0s"
    assert result.stdout == "partial"


def test_factory_selects_ssh_backend(monkeypatch):
    calls = []
    _patch_ssh_ok(monkeypatch, calls)

    from maverick import config as config_mod

    monkeypatch.setattr(config_mod, "get_sandbox", lambda: {"backend": "ssh", "timeout": 99})
    monkeypatch.setattr(config_mod, "load_config", lambda: {
        "sandbox": {
            "backend": "ssh",
            "host": "me@example.com",
            "workdir": "/remote/ws",
            "ssh_args": ["-i", "key"],
        }
    })

    backend = build_sandbox()

    assert isinstance(backend, SSHBackend)
    assert backend.host == "me@example.com"
    assert backend.workdir == Path("/remote/ws")
    assert backend.timeout == 99.0
    assert backend.ssh_args == ["-i", "key"]


def test_factory_ssh_without_host_raises(monkeypatch):
    from maverick import config as config_mod

    monkeypatch.setattr(config_mod, "get_sandbox", lambda: {"backend": "ssh"})
    monkeypatch.setattr(config_mod, "load_config", lambda: {"sandbox": {"backend": "ssh"}})

    with pytest.raises(ValueError, match="backend=ssh requires"):
        build_sandbox()
