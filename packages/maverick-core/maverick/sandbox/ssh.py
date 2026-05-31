"""SSH sandbox backend.

Executes commands on a remote host via the system ``ssh`` binary. No
Python dep (paramiko) -- we just shell out to ssh so users get the
same keys / config / agents they already have set up.

Config::

    [sandbox]
    backend = "ssh"
    host = "me@example.com"
    workdir = "/home/me/maverick-workspace"
    timeout = 60
    ssh_args = ["-i", "~/.ssh/maverick_key"]
"""
from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from .local import ExecResult


@dataclass
class SSHBackend:
    host: str
    # The workdir lives on the REMOTE host, which is POSIX -- use
    # PurePosixPath, never the platform Path: on a Windows client
    # ``str(Path("/home/me/ws"))`` becomes ``\home\me\ws`` and we would ship
    # a broken backslash path to the (Linux) remote.
    workdir: PurePosixPath = PurePosixPath("~/maverick-workspace")
    timeout: float = 60.0
    ssh_args: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if isinstance(self.workdir, str):
            self.workdir = PurePosixPath(self.workdir)
        self._verify_ssh()

    def _verify_ssh(self) -> None:
        import shutil
        if not shutil.which("ssh"):
            raise RuntimeError(
                "ssh binary not found on PATH. Install openssh-client."
            )
        check = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
             *self.ssh_args, self.host, "true"],
            capture_output=True, timeout=10,
        )
        if check.returncode != 0:
            stderr = check.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(
                f"ssh to {self.host} failed: {stderr or 'unknown error'}. "
                "Check your SSH config / keys."
            )

    def exec(self, cmd: str, timeout: float | None = None) -> ExecResult:
        effective = self.timeout if timeout is None else timeout
        remote = f"mkdir -p {shlex.quote(str(self.workdir))} && " \
                 f"cd {shlex.quote(str(self.workdir))} && {cmd}"
        args = ["ssh", *self.ssh_args, self.host, remote]
        try:
            result = subprocess.run(
                args, capture_output=True, text=True, timeout=effective,
            )
            return ExecResult(
                stdout=result.stdout[-8000:],
                stderr=result.stderr[-2000:],
                exit_code=result.returncode,
            )
        except subprocess.TimeoutExpired as e:
            return ExecResult(
                stdout=(e.stdout or b"").decode("utf-8", errors="replace")[-8000:],
                stderr=f"TIMEOUT after {effective}s",
                exit_code=124,
            )
