"""Local subprocess backend.

The Backend interface is intentionally tiny: every backend exposes `exec(cmd)`.
That's the abstraction Hermes' 7 backends collapse to. Start simple.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


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
        effective = self.timeout if timeout is None else timeout
        child_env = os.environ.copy()
        for key in (
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY",
            "GITHUB_TOKEN",
            "GH_TOKEN",
        ):
            child_env.pop(key, None)

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
