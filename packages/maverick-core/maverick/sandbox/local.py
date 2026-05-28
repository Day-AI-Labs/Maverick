"""Local subprocess backend.

The Backend interface is intentionally tiny: every backend exposes `exec(cmd)`.
That's the abstraction Hermes' 7 backends collapse to. Start simple.
"""
from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# Names matching this pattern are stripped from the child shell's env.
# Catches STRIPE_API_KEY, PLAID_SECRET, CLOUDFLARE_API_TOKEN,
# AWS_SECRET_ACCESS_KEY / AWS_ACCESS_KEY_ID / AWS_SESSION_TOKEN,
# *_PASSWORD, *_CREDENTIAL, plus connection strings that embed creds
# (DATABASE_URL, SENTRY_DSN, MONGO_URI, REDIS_URL, *_OAUTH, *_BEARER).
_SECRET_ENV_RE = re.compile(
    r"(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|APIKEY|DSN|URI|URL|CONN|OAUTH|BEARER)",
    re.IGNORECASE,
)
# Stripped explicitly even though the pattern already covers them — kept
# as a readable record of the provider creds we never want in the shell.
_ALWAYS_STRIP_ENV = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "GITLAB_TOKEN",
)


def scrub_env(source: Optional[dict] = None) -> dict:
    """Return a copy of the environment with secrets removed.

    The default LocalBackend runs model-driven shell commands on the host,
    so a prompt-injected agent can ``printenv`` / ``echo $STRIPE_API_KEY``
    and the value lands in stdout -> back to the model -> out via any
    channel. The old code stripped only 5 named vars while the ~70-tool
    suite reads 40+ other secret vars; this strips by name pattern so new
    credentials are covered by default (deny-by-pattern, not an ad-hoc
    name list). Tools that legitimately need a credential run in-process
    (Python), not through this shell, so aggressive stripping is safe.
    """
    src = os.environ if source is None else source
    out: dict = {}
    for k, v in src.items():
        if k in _ALWAYS_STRIP_ENV or _SECRET_ENV_RE.search(k):
            continue
        out[k] = v
    return out


@dataclass
class ExecResult:
    stdout: str
    stderr: str
    exit_code: int

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


class LocalBackend:
    def __init__(self, workdir: Optional[Path] = None, timeout: float = 60.0):
        self.workdir = workdir or Path.cwd()
        self.timeout = timeout

    def exec(self, cmd: str, timeout: Optional[float] = None) -> ExecResult:
        # Wave 10: per-call `timeout` kwarg lets the test runner override
        # the default 60s (too short for real pytest on SWE-bench
        # instances). Falls back to self.timeout when unset, preserving
        # behaviour for shell-tool callers that pass no timeout.
        # May 26 council fix (long-tail audit): `text=True` returns str
        # on success but TimeoutExpired.stdout is bytes — without
        # explicit decode the result.stdout types diverge. Pin both
        # branches to str.
        try:
            from ..chaos import maybe_fail
            maybe_fail("sandbox_exec",
                       message=f"chaos: sandbox_exec on {cmd[:40]!r}")
        except ImportError:
            pass
        effective = self.timeout if timeout is None else timeout
        child_env = scrub_env()

        try:
            result = subprocess.run(
                cmd,
                shell=True,
                cwd=str(self.workdir),
                capture_output=True,
                text=True,
                timeout=effective,
                env=child_env,
            )
            return ExecResult(
                stdout=(result.stdout or "")[-8000:],
                stderr=(result.stderr or "")[-2000:],
                exit_code=result.returncode,
            )
        except subprocess.TimeoutExpired as e:
            raw_out = e.stdout or b""
            if isinstance(raw_out, bytes):
                raw_out = raw_out.decode("utf-8", errors="replace")
            return ExecResult(
                stdout=raw_out[-8000:],
                stderr=f"TIMEOUT after {effective}s",
                exit_code=124,
            )
