"""Local subprocess backend.

The Backend interface is intentionally tiny: every backend exposes `exec(cmd)`.
That's the abstraction Hermes' 7 backends collapse to. Start simple.
"""
from __future__ import annotations

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

    def exec(self, cmd: str) -> ExecResult:
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                cwd=str(self.workdir),
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
