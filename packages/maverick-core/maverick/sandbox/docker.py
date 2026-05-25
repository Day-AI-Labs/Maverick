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
from dataclasses import dataclass
from pathlib import Path

from .local import ExecResult


@dataclass
class DockerBackend:
    workdir: Path
    image: str = "python:3.12-slim"
    timeout: float = 60.0
    allow_network: bool = False

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

    def exec(self, cmd: str) -> ExecResult:
        args = [
            "docker", "run", "--rm",
            "-v", f"{self.workdir.resolve()}:/workspace",
            "-w", "/workspace",
        ]
        if not self.allow_network:
            args.extend(["--network", "none"])
        args.extend([self.image, "sh", "-c", cmd])

        try:
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
            return ExecResult(
                stdout=result.stdout[-8000:],
                stderr=result.stderr[-2000:],
                exit_code=result.returncode,
            )
        except subprocess.TimeoutExpired as e:
            return ExecResult(
                stdout=(e.stdout or b"").decode("utf-8", errors="replace")[-8000:],
                stderr=f"TIMEOUT after {self.timeout}s",
                exit_code=124,
            )
