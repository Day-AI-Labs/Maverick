"""Docker sandbox backend.

Each exec spawns a fresh container with the workspace mounted; the
container is removed on exit (``--rm``). Network is disabled by
default (``--network=none``); enable via ``allow_network=True`` if a
specific run needs it.

Why a fresh container per command? Simpler, no state leakage between
calls, mirrors how Hermes / OpenClaw approach ephemeral execution.
Long-lived container with ``docker exec`` is a future optimization.

Falls back loudly: if Docker isn't installed or the daemon isn't
running, ``DockerBackend.__init__`` raises ``RuntimeError`` so the
wizard's smoke test catches it before the agent runs.
"""
from __future__ import annotations

import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

from .local import ExecResult


@dataclass
class DockerBackend:
    workdir: Path
    image: str = "python:3.12-slim"
    timeout: float = 60.0
    allow_network: bool = False
    # Fork-bomb guard. Generous enough for real builds (pip/npm/pytest
    # spawn plenty of children) while still bounding a runaway agent.
    # Set to 0/None to disable (not recommended).
    pids_limit: int | None = 512

    def __post_init__(self) -> None:
        self.workdir = Path(self.workdir)
        self.workdir.mkdir(parents=True, exist_ok=True)
        self._verify_docker()

    def _verify_docker(self) -> None:
        try:
            subprocess.run(
                ["docker", "version"],
                capture_output=True, timeout=5, check=True,
            )
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            raise RuntimeError(
                "Docker not available. Install Docker Desktop / docker.io, or "
                "change [sandbox] backend to 'local' in ~/.maverick/config.toml."
            ) from e

    def exec(self, cmd: str, timeout: float | None = None) -> ExecResult:
        # Wave 11: per-call `timeout` matches LocalBackend so the shell
        # tool can plumb a longer cap for pytest/npm test/etc. Falls
        # back to self.timeout (default 60 s).
        effective = self.timeout if timeout is None else timeout
        container_name = f"maverick-sandbox-{uuid.uuid4().hex}"
        args = [
            "docker", "run", "--rm",
            "--name", container_name,
            "-v", f"{self.workdir.resolve()}:/workspace",
            "-w", "/workspace",
            # Containment for a possibly prompt-injected agent: drop every
            # Linux capability and block privilege escalation (setuid/setgid
            # binaries can't gain more than they start with). Neither breaks
            # pip/npm/pytest, which need no capabilities.
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
        ]
        if self.pids_limit:
            args.extend(["--pids-limit", str(self.pids_limit)])
        if not self.allow_network:
            args.extend(["--network", "none"])
        args.extend([self.image, "sh", "-c", cmd])

        try:
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=effective,
            )
            return ExecResult(
                stdout=result.stdout[-8000:],
                stderr=result.stderr[-2000:],
                exit_code=result.returncode,
            )
        except subprocess.TimeoutExpired as e:
            # Best-effort cleanup. If the Docker daemon is itself wedged
            # (often the cause of the original timeout), `docker rm` can
            # also hang/raise; swallow it so the clean exit_code=124
            # TIMEOUT result below is what propagates, not an unhandled
            # exception in the agent loop. (Matches podman/kubernetes.)
            try:
                subprocess.run(
                    ["docker", "rm", "-f", container_name],
                    capture_output=True,
                    timeout=10,
                )
            except Exception:
                pass
            stdout = e.stdout or ""
            if isinstance(stdout, bytes):
                stdout = stdout.decode("utf-8", errors="replace")
            return ExecResult(
                stdout=stdout[-8000:],
                stderr=f"TIMEOUT after {effective}s",
                exit_code=124,
            )
