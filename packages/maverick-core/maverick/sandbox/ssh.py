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
    host_key_checking = "accept-new"   # accept-new | yes | no (default accept-new)
"""
from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from .local import ExecResult, scrub_env

# Connection options applied to BOTH the verify probe and every exec(): fail
# fast on an auth prompt / key change instead of blocking the agent loop on a
# hidden interactive prompt.
#  - BatchMode=yes      : never prompt for a password/passphrase (fail instead).
#  - ConnectTimeout=10  : don't hang forever on an unreachable host.
_BASE_SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]

# Host-key policy default. ``accept-new`` pins the key into known_hosts on
# first contact, then REJECTS a later key change (MITM) -- a real check,
# unlike the implicit "no checking" you get when ssh's StrictHostKeyChecking is
# left to its prompt default under BatchMode. We deliberately do NOT default to
# the strictest ``yes`` (would lock out users whose host isn't in known_hosts
# yet); operators can set ``host_key_checking = "yes"`` for that, or "no" to
# restore the old blind-accept behaviour.
_VALID_HOST_KEY_POLICIES = {"accept-new", "yes", "no"}


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
    # See _VALID_HOST_KEY_POLICIES. Safe-compatible default: accept-new.
    host_key_checking: str = "accept-new"

    def __post_init__(self) -> None:
        if isinstance(self.workdir, str):
            self.workdir = PurePosixPath(self.workdir)
        policy = (self.host_key_checking or "accept-new").strip().lower()
        if policy not in _VALID_HOST_KEY_POLICIES:
            policy = "accept-new"
        self.host_key_checking = policy
        self._verify_ssh()

    def _ssh_opts(self) -> list[str]:
        """BatchMode + ConnectTimeout + the configured host-key policy."""
        return [
            *_BASE_SSH_OPTS,
            "-o", f"StrictHostKeyChecking={self.host_key_checking}",
        ]

    def _verify_ssh(self) -> None:
        import shutil
        if not shutil.which("ssh"):
            raise RuntimeError(
                "ssh binary not found on PATH. Install openssh-client."
            )
        check = subprocess.run(
            ["ssh", *self._ssh_opts(), *self.ssh_args, self.host, "true"],
            capture_output=True, timeout=15, env=scrub_env(),
        )
        if check.returncode != 0:
            stderr = check.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(
                f"ssh to {self.host} failed: {stderr or 'unknown error'}. "
                "Check your SSH config / keys."
            )

    def exec(self, cmd: str, timeout: float | None = None) -> ExecResult:
        effective = self.timeout if timeout is None else timeout
        # Run cmd as a single quoted argument inside ``sh -c`` so a leading
        # ``;`` / ``&&`` / ``||`` / unbalanced quote can't escape the ``cd``
        # guard and run outside the workspace. The workdir itself is quoted too.
        wd = shlex.quote(str(self.workdir))
        remote = (
            f"mkdir -p {wd} && cd {wd} && sh -c {shlex.quote(cmd)}"
        )
        # Env hygiene: ssh forwards local env to the remote shell only via
        # SendEnv/SetEnv, neither of which we set -- so the remote never
        # inherits host secrets. We additionally scrub the LOCAL ssh client's
        # own env (env=scrub_env()) so a provider key can't leak through an
        # ssh feature that reads it (e.g. SSH_ASKPASS-style helpers).
        args = ["ssh", *self._ssh_opts(), *self.ssh_args, self.host, remote]
        try:
            result = subprocess.run(
                args, capture_output=True, text=True, timeout=effective,
                env=scrub_env(),
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
