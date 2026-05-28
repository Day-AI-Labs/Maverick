"""Devcontainer sandbox backend.

Reads the project's ``.devcontainer/devcontainer.json`` (or
``devcontainer.json`` at repo root) and runs commands inside the
configured container image — so the agent operates in the same
environment the user's IDE / Codespaces / GitHub Actions devcontainer
spec describes.

Why ship this separately from Docker?
  - Users who already maintain a devcontainer spec want their AI
    agent to use the exact same toolchain.
  - VSCode + GitHub Codespaces standardize on this format; meeting
    users where they are.

Strategy:
  - Look up ``.devcontainer/devcontainer.json`` (preferred) or
    ``devcontainer.json``. JSONC (JSON with comments) is supported
    by stripping ``// ...`` lines + trailing commas.
  - Read ``image`` (required). ``dockerFile`` build is out of scope
    for v1 (delegate to a pre-built image; we'll surface a useful
    error if only dockerFile is set).
  - Read ``remoteUser`` (default ``root``), ``workspaceFolder``
    (default ``/workspaces/<repo-name>``), ``containerEnv``
    (env vars), ``forwardPorts`` (ignored — exec model).
  - ``runArgs`` are intentionally rejected in v1 to preserve sandbox
    isolation guarantees.
  - For each ``exec()``: ``docker run --rm`` with the parsed config.

Config::

    [sandbox]
    backend = "devcontainer"
    project_dir = "/path/to/your/repo"  # contains .devcontainer/
    timeout = 60
    allow_network = true                # devcontainers usually need net
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .local import ExecResult

log = logging.getLogger(__name__)


def _strip_jsonc(text: str) -> str:
    """Strip // line comments + /* block */ comments + trailing commas."""
    # Block comments
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    # Line comments (skip if inside a string — naive but works for
    # well-formed devcontainer.json which doesn't have //-in-strings).
    out_lines = []
    for line in text.splitlines():
        out_lines.append(re.sub(r"(?<!:)//.*$", "", line))
    text = "\n".join(out_lines)
    # Trailing commas before } or ]
    text = re.sub(r",(\s*[}\]])", r"\1", text)
    return text


@dataclass
class DevcontainerSpec:
    image: str
    remote_user: str = "root"
    workspace_folder: str = "/workspaces/repo"
    container_env: dict[str, str] = field(default_factory=dict)


def _find_devcontainer_json(project_dir: Path) -> Optional[Path]:
    candidates = [
        project_dir / ".devcontainer" / "devcontainer.json",
        project_dir / "devcontainer.json",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _parse_devcontainer(path: Path) -> DevcontainerSpec:
    raw = path.read_text(encoding="utf-8")
    try:
        data = json.loads(_strip_jsonc(raw))
    except json.JSONDecodeError as e:
        raise RuntimeError(f"failed to parse {path}: {e}") from e
    if not isinstance(data, dict):
        raise RuntimeError(f"{path}: top-level must be an object")
    image = data.get("image")
    if not image:
        if data.get("dockerFile") or data.get("build"):
            raise RuntimeError(
                f"{path}: only `image` is supported in v1 — "
                "your spec uses `dockerFile` or `build`. Build the "
                "image yourself + reference it via `image`."
            )
        raise RuntimeError(f"{path}: missing required `image` field")

    run_args = data.get("runArgs") or []
    if run_args:
        raise RuntimeError(
            f"{path}: `runArgs` is not supported for security reasons in v1. "
            "Configure sandbox options in Maverick config instead."
        )

    repo_name = path.parent.name
    if path.parent.name == ".devcontainer":
        repo_name = path.parent.parent.name
    return DevcontainerSpec(
        image=str(image),
        remote_user=str(data.get("remoteUser") or "root"),
        workspace_folder=str(
            data.get("workspaceFolder") or f"/workspaces/{repo_name}",
        ),
        container_env={
            str(k): str(v) for k, v in (data.get("containerEnv") or {}).items()
        },
    )


@dataclass
class DevcontainerBackend:
    project_dir: Path
    timeout: float = 60.0
    allow_network: bool = True
    spec_override: Optional[DevcontainerSpec] = None

    def __post_init__(self) -> None:
        self.project_dir = Path(self.project_dir).resolve()
        self._verify_docker()
        if self.spec_override is not None:
            self.spec = self.spec_override
        else:
            p = _find_devcontainer_json(self.project_dir)
            if p is None:
                raise RuntimeError(
                    f"no devcontainer.json found under {self.project_dir} "
                    "(looked at .devcontainer/devcontainer.json + ./devcontainer.json)"
                )
            self.spec = _parse_devcontainer(p)
            log.info("devcontainer: %s -> image=%s", p, self.spec.image)

    def _verify_docker(self) -> None:
        try:
            subprocess.run(
                ["docker", "version"],
                capture_output=True, timeout=5, check=True,
            )
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            raise RuntimeError(
                "Docker not available — required for devcontainer backend. "
                "Install Docker or change [sandbox] backend in ~/.maverick/config.toml."
            ) from e

    def exec(self, cmd: str, timeout: Optional[float] = None) -> ExecResult:
        effective = self.timeout if timeout is None else timeout
        container_name = f"maverick-devc-{uuid.uuid4().hex}"
        args = [
            "docker", "run", "--rm",
            "--name", container_name,
            "-v", f"{self.project_dir}:{self.spec.workspace_folder}",
            "-w", self.spec.workspace_folder,
        ]
        if self.spec.remote_user and self.spec.remote_user != "root":
            args.extend(["--user", self.spec.remote_user])
        for k, v in self.spec.container_env.items():
            args.extend(["-e", f"{k}={v}"])
        if not self.allow_network:
            args.extend(["--network", "none"])
        args.extend([self.spec.image, "sh", "-c", cmd])

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
            subprocess.run(
                ["docker", "rm", "-f", container_name],
                capture_output=True, timeout=10,
            )
            stdout = e.stdout or ""
            if isinstance(stdout, bytes):
                stdout = stdout.decode("utf-8", errors="replace")
            return ExecResult(
                stdout=stdout[-8000:],
                stderr=f"TIMEOUT after {effective}s",
                exit_code=124,
            )


__all__ = ["DevcontainerBackend", "DevcontainerSpec"]
