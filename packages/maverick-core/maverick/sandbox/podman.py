"""Podman sandbox backend.

Daemonless alternative to Docker. Same surface: spawn a fresh
``podman run --rm`` per ``exec()`` with the workdir mounted, network
disabled by default.

Why ship this alongside Docker?
  - Podman is rootless out-of-the-box; common on locked-down CI hosts
    where Docker requires sudo/socket access.
  - Same CLI flags, near-zero porting cost.
  - Lets users keep one ``[sandbox]`` knob (``backend = "podman"``)
    and still get container isolation.

Config::

    [sandbox]
    backend = "podman"
    image = "python:3.12-slim"
    workdir = "/tmp/maverick"
    timeout = 60
    allow_network = false

Same loud-fallback contract as Docker: missing podman binary or
``podman version`` failure raises ``RuntimeError`` so the wizard's
smoke test catches it before the agent runs.
"""
from __future__ import annotations

import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .local import ExecResult


@dataclass
class PodmanBackend:
    workdir: Path
    image: str = "python:3.12-slim"
    timeout: float = 60.0
    allow_network: bool = False

    def __post_init__(self) -> None:
        self.workdir = Path(self.workdir)
        self.workdir.mkdir(parents=True, exist_ok=True)
        self._verify_podman()

    def _verify_podman(self) -> None:
        try:
            subprocess.run(
                ["podman", "version"],
                capture_output=True, timeout=5, check=True,
            )
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            raise RuntimeError(
                "Podman not available. Install podman, or change "
                "[sandbox] backend to 'local' / 'docker' in "
                "~/.maverick/config.toml."
            ) from e

    def exec(self, cmd: str, timeout: Optional[float] = None) -> ExecResult:
        effective = self.timeout if timeout is None else timeout
        container_name = f"maverick-sandbox-{uuid.uuid4().hex}"
        # `:Z` relabels the SELinux context for the mount so rootless
        # podman on Fedora / RHEL can read+write the workspace.
        args = [
            "podman", "run", "--rm",
            "--name", container_name,
            "-v", f"{self.workdir.resolve()}:/workspace:Z",
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
                timeout=effective,
            )
            return ExecResult(
                stdout=result.stdout[-8000:],
                stderr=result.stderr[-2000:],
                exit_code=result.returncode,
            )
        except subprocess.TimeoutExpired as e:
            subprocess.run(
                ["podman", "rm", "-f", container_name],
                capture_output=True,
                timeout=10,
            )
            stdout = e.stdout or ""
            if isinstance(stdout, bytes):
                stdout = stdout.decode("utf-8", errors="replace")
            return ExecResult(
                stdout=stdout[-8000:],
                stderr=f"TIMEOUT after {effective}s",
                exit_code=124,
            )
