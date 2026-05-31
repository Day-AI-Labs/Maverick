"""Firecracker microVM sandbox backend.

May-2026 research: plain Docker is "considered insufficient for
adversarial agents" (Northflank, 2026). Firecracker microVM is the
new 2026 baseline (Vercel Sandbox, E2B, Daytona all migrated). It
boots in ~125ms, gives kernel-level isolation, and constrains
network/disk by default.

This backend talks to a local Firecracker API socket (firecracker-go
is the canonical impl; the python client at github.com/firecracker-
microvm/firecracker-go-sdk has no direct python equivalent, so we
shell out to `firecracker` + `firectl`). For deployments that don't
have Firecracker installed (most desktops), the backend falls back
to a clear NotImplementedError at construction so the operator gets
an obvious error rather than a silent downgrade to local subprocess.

For E2B-hosted deployments (a managed Firecracker service), the
`provider="e2b"` mode talks to E2B's REST API instead of a local
socket. That path is the realistic config for VPS users who don't
want to operate Firecracker themselves.

Status (May 2026): SCAFFOLD. Full microVM lifecycle (kernel image,
rootfs, network bridge, balloon, snapshot/restore) is operator-side
work that varies per host distro; this module gives the agent loop
the same ``.exec(cmd) -> ExecResult`` interface and routes to either
a local firectl invocation or the E2B API.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .local import ExecResult

log = logging.getLogger(__name__)


@dataclass
class FirecrackerBackend:
    """Run agent commands inside a Firecracker microVM.

    Two modes:
      provider="local"  : talk to a local firectl + firecracker on PATH
      provider="e2b"    : POST to E2B's sandbox REST API
    """
    workdir: Path
    image: str = "ubuntu:24.04-maverick"
    timeout: float = 60.0
    provider: str = "local"
    api_key: str | None = None
    network: str = "egress-deny"   # egress-deny | egress-allow | bridge=<name>

    def __post_init__(self):
        if self.provider == "local":
            if not shutil.which("firecracker"):
                raise NotImplementedError(
                    "Firecracker backend requires the `firecracker` binary "
                    "on PATH. Install per "
                    "https://github.com/firecracker-microvm/firecracker/"
                    "blob/main/docs/getting-started.md or set "
                    "[sandbox] provider = \"e2b\" to use E2B's hosted "
                    "Firecracker service instead."
                )
        elif self.provider == "e2b":
            self.api_key = self.api_key or os.environ.get("E2B_API_KEY")
            if not self.api_key:
                raise ValueError(
                    "E2B Firecracker backend requires E2B_API_KEY"
                )
        else:
            raise ValueError(
                f"Firecracker provider must be 'local' or 'e2b', got {self.provider!r}"
            )

    def exec(self, cmd: str, timeout: float | None = None) -> ExecResult:
        # Wave 11: per-call timeout propagated to underlying providers
        # via a temporary self.timeout swap. Both _exec_e2b and
        # _exec_local read self.timeout; restore on exit.
        prior = self.timeout
        if timeout is not None:
            self.timeout = timeout
        try:
            if self.provider == "e2b":
                return self._exec_e2b(cmd)
            return self._exec_local(cmd)
        finally:
            self.timeout = prior


    def _e2b_network_config(self) -> dict:
        if self.network == "egress-deny":
            return {"egress": "deny"}
        if self.network == "egress-allow":
            return {"egress": "allow"}
        if self.network.startswith("bridge="):
            return {"bridge": self.network.split("=", 1)[1]}
        raise ValueError(
            "Firecracker network must be one of: "
            "'egress-deny', 'egress-allow', or 'bridge=<name>'"
        )

    def _exec_local(self, cmd: str) -> ExecResult:
        """Run inside a freshly-booted local microVM.

        Full impl: spin up a microVM with kernel+rootfs, copy workdir
        in via vsock, run cmd, capture stdio, tear down. The reference
        impl in `deploy/firecracker/` ships the kernel + rootfs build
        scripts; this module is the agent-side interface only.

        For now (scaffold): if `firectl` is installed, use it; else
        fall back to plain `docker run --read-only` and log the gap.
        """
        if shutil.which("firectl"):
            return self._firectl(cmd)
        # No firectl: an operator who configured `provider = "firecracker"`
        # asked for hard microVM isolation, so silently downgrading to a Docker
        # namespace boundary defeats that choice. Fail CLOSED by default; the
        # operator must explicitly opt into the weaker fallback with
        # MAVERICK_FIRECRACKER_STRICT=0 (previously the downgrade was the
        # default and only STRICT=1 failed closed, so the secure posture
        # depended on remembering to set an env var).
        if os.environ.get("MAVERICK_FIRECRACKER_STRICT", "1").strip().lower() not in {"0", "false", "no", "off"}:
            raise RuntimeError(
                "Firecracker local backend: firectl not on PATH, so microVM "
                "isolation is unavailable. Refusing to silently downgrade to "
                "Docker (which is a weaker boundary than you selected). Install "
                "firectl for microVM isolation, or set "
                "MAVERICK_FIRECRACKER_STRICT=0 to explicitly allow the Docker "
                "fallback."
            )
        # Operator explicitly opted into the downgrade (STRICT=0). Use a
        # hardened docker invocation and log so they know they're not getting
        # full microVM isolation.
        log.warning(
            "Firecracker local backend: firectl not on PATH and "
            "MAVERICK_FIRECRACKER_STRICT=0; falling back to a hardened "
            "`docker --network=none --read-only` for this run. Install "
            "firectl for full microVM isolation."
        )
        return self._docker_fallback(cmd)

    def _firectl(self, cmd: str) -> ExecResult:
        """Run a one-shot command via firectl. Scaffold."""
        # firectl invocation pattern (kernel + rootfs paths come from
        # ~/.maverick/firecracker/{kernel,rootfs}.img by convention).
        kernel = Path.home() / ".maverick" / "firecracker" / "kernel.img"
        rootfs = Path.home() / ".maverick" / "firecracker" / "rootfs.img"
        if not kernel.exists() or not rootfs.exists():
            return ExecResult(
                exit_code=127,
                stdout="",
                stderr=(
                    f"firecracker kernel/rootfs not found at "
                    f"{kernel} / {rootfs}. Run `maverick init --target=vps` "
                    "(future) or follow deploy/firecracker/README.md."
                ),
            )
        args = [
            "firectl",
            "--kernel", str(kernel),
            "--root-drive", str(rootfs),
            "--ncpus", "1",
            "--memory", "512",
        ]
        if self.network == "egress-deny":
            args += ["--no-network"]
        elif self.network.startswith("bridge="):
            args += ["--tap-device", self.network.split("=", 1)[1]]
        elif self.network != "egress-allow":
            return ExecResult(
                stdout="",
                stderr=(
                    "firecracker invalid network policy; expected "
                    "egress-deny|egress-allow|bridge=<name>"
                ),
                exit_code=126,
            )
        args += ["--", "/bin/sh", "-c", cmd]
        try:
            proc = subprocess.run(
                args, capture_output=True, text=True, timeout=self.timeout,
            )
        except subprocess.TimeoutExpired:
            return ExecResult(exit_code=124, stdout="", stderr="firecracker timeout")
        return ExecResult(
            exit_code=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )

    def _docker_fallback(self, cmd: str) -> ExecResult:
        """Best-effort sandbox when firectl isn't available.

        Applies the same containment the regular ``DockerBackend`` uses
        (``--cap-drop ALL`` + ``--security-opt no-new-privileges`` + a pids
        cap) so the fallback isn't *weaker* than the normal Docker path."""
        args = [
            "docker", "run", "--rm",
            "--network=none", "--read-only",
            "--tmpfs", "/tmp",
            # This fallback stands in for hard VM isolation, so it must be at
            # least as contained as the plain Docker backend: drop all caps,
            # block privilege escalation, and cap pids.
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--pids-limit", "512",
            "-v", f"{self.workdir}:/work:ro",
            "-w", "/work",
            "python:3.12-slim",
            "sh", "-c", cmd,
        ]
        try:
            proc = subprocess.run(
                args, capture_output=True, text=True, timeout=self.timeout,
            )
        except subprocess.TimeoutExpired:
            return ExecResult(exit_code=124, stdout="", stderr="docker timeout")
        return ExecResult(
            exit_code=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )

    def _exec_e2b(self, cmd: str) -> ExecResult:
        """Run on E2B's hosted Firecracker. Requires E2B_API_KEY."""
        try:
            import httpx
        except ImportError:
            return ExecResult(
                exit_code=127, stdout="",
                stderr=(
                    "E2B Firecracker requires httpx. Install: "
                    "pip install httpx"
                ),
            )
        # E2B API shape (May 2026): POST /sandboxes -> {id};
        # POST /sandboxes/{id}/processes {cmd} -> {stdout,stderr,exitCode}.
        # Full lifecycle (start/poll/tear down) is in the e2b SDK; this
        # scaffold uses the raw REST.
        try:
            with httpx.Client(timeout=self.timeout) as client:
                sb = client.post(
                    "https://api.e2b.dev/sandboxes",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={"template": self.image, "network": self._e2b_network_config()},
                )
                if sb.status_code >= 300:
                    return ExecResult(
                        exit_code=126, stdout="",
                        stderr=f"e2b sandbox create failed: {sb.status_code}",
                    )
                sb_id = sb.json().get("id")
                run = client.post(
                    f"https://api.e2b.dev/sandboxes/{sb_id}/processes",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={"cmd": cmd, "cwd": "/work"},
                )
                client.delete(
                    f"https://api.e2b.dev/sandboxes/{sb_id}",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                data = run.json() if run.status_code < 300 else {}
                return ExecResult(
                    exit_code=int(data.get("exitCode", 1)),
                    stdout=data.get("stdout", ""),
                    stderr=data.get("stderr", "")
                              or (f"http {run.status_code}" if run.status_code >= 300 else ""),
                )
        except Exception as e:
            return ExecResult(exit_code=125, stdout="", stderr=f"e2b error: {e}")
