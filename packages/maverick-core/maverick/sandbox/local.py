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

# Names matching this pattern are stripped from the child shell's env.
# Catches STRIPE_API_KEY, PLAID_SECRET, CLOUDFLARE_API_TOKEN,
# AWS_SECRET_ACCESS_KEY / AWS_ACCESS_KEY_ID / AWS_SESSION_TOKEN,
# *_PASSWORD, *_CREDENTIAL, header blobs that may carry auth values
# (MAVERICK_OTEL_HEADERS, OTEL_EXPORTER_OTLP_HEADERS), plus connection
# strings that embed creds (DATABASE_URL, SENTRY_DSN, MONGO_URI,
# REDIS_URL, *_OAUTH, *_BEARER).
_SECRET_ENV_RE = re.compile(
    r"(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD|PASSPHRASE|CREDENTIAL|APIKEY|DSN|URI|URL|CONN"
    r"|OAUTH|BEARER|HEADER|NETRC|COOKIE|AUTH)",
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
    # The SWE-bench gold patch: "GOLD_PATCH" matches no secret keyword in
    # _SECRET_ENV_RE, so without this a `printenv` in a non-opaque child leaks
    # the benchmark answer. shell.py only popped it for opaque runs.
    "MAVERICK_GOLD_PATCH",
)


# Git reads env-based config injection as an ATOMIC protocol: GIT_CONFIG_COUNT=N
# declares exactly N (GIT_CONFIG_KEY_i, GIT_CONFIG_VALUE_i) pairs. Used widely by
# CI/dev hosts (GitHub Actions, Codespaces, devcontainers) for url.insteadOf
# credential rewriting. Tracked separately because _SECRET_ENV_RE strips the
# KEY_* members (they match "KEY") but NOT COUNT/VALUE_*, which would leave git a
# dangling COUNT and abort every command with "missing config key
# GIT_CONFIG_KEY_0" (exit 128). The family must be kept all-or-nothing.
_GIT_CONFIG_INJECT_RE = re.compile(r"^GIT_CONFIG_(?:COUNT|KEY_\d+|VALUE_\d+)$")

_TRUE = {"1", "true", "yes", "on"}


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in _TRUE


def container_user_args(allow_root: bool = False) -> list[str]:
    """Return ``["--user", "uid:gid"]`` for non-root container execution.

    Containers default to running as root; against a writable host mount that
    lets a prompt-injected agent write root-owned files (or worse) on the host.
    Drop to the invoking user's uid/gid -- matching ``DevcontainerBackend`` --
    unless the operator opts back into root via ``[sandbox] allow_root = true``
    or ``MAVERICK_SANDBOX_ALLOW_ROOT`` (truthy).

    ``os.getuid``/``os.getgid`` are POSIX-only (absent on Windows); there is no
    uid/gid mapping to pin there, so fall back to no ``--user`` flag and let the
    container engine's own user handling apply.
    """
    if allow_root or _truthy(os.environ.get("MAVERICK_SANDBOX_ALLOW_ROOT")):
        return []
    getuid = getattr(os, "getuid", None)
    getgid = getattr(os, "getgid", None)
    if getuid is None or getgid is None:
        return []
    return ["--user", f"{getuid()}:{getgid()}"]


def scrub_env(source: dict | None = None) -> dict:
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
    # Keep git's COUNT/KEY_*/VALUE_* config-injection family all-or-nothing: if
    # the secret filter dropped any member (it strips KEY_* but not COUNT/VALUE_*),
    # the survivors form a corrupt injection that aborts every git command with
    # exit 128. Drop the whole family so git cleanly falls back to file config.
    git_family = {k for k in src if _GIT_CONFIG_INJECT_RE.match(k)}
    if git_family - out.keys():  # at least one member was scrubbed
        for k in git_family:
            out.pop(k, None)
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
    # Commands run as a host subprocess against the host filesystem, so files
    # this backend writes ARE visible to the calling (host) process. Container /
    # remote backends leave this False (no such attribute), so output-path
    # verification stays disabled for them. See ``sandbox.fs_is_host_visible``.
    host_visible_fs = True

    def __init__(self, workdir: Path | None = None, timeout: float = 60.0):
        self.workdir = workdir or Path.cwd()
        self.timeout = timeout

    def exec(self, cmd: str, timeout: float | None = None) -> ExecResult:
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
                # LocalBackend is the intentional unsandboxed host-exec path
                # (CLAUDE.md rule 4 allowlists shell only under sandbox/); env is
                # scrubbed and operators are warned to use a container backend.
                shell=True,  # nosec B602
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
