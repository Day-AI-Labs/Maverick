"""Execution backends.

Local (subprocess), Docker (throwaway containers), SSH (remote host
via system ssh binary). All implement ``.exec(cmd) -> ExecResult``
so the agent loop is backend-agnostic.

The agent never instantiates a backend directly -- always go through
``build_sandbox()`` so the [sandbox] config section is the single
source of truth.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

from .docker import DockerBackend
from .firecracker import FirecrackerBackend
from .local import ExecResult, LocalBackend
from .podman import PodmanBackend
from .ssh import SSHBackend

__all__ = [
    "LocalBackend",
    "DockerBackend",
    "PodmanBackend",
    "FirecrackerBackend",
    "SSHBackend",
    "ExecResult",
    "build_sandbox",
]

Sandbox = Union[
    LocalBackend, DockerBackend, PodmanBackend, FirecrackerBackend, SSHBackend,
]


def build_sandbox(
    workdir: Optional[Union[str, Path]] = None,
    backend: Optional[str] = None,
) -> Sandbox:
    """Construct the configured sandbox backend.

    Reads ``[sandbox]`` from ``~/.maverick/config.toml``; either argument
    overrides the corresponding config value.
    """
    try:
        from ..config import get_sandbox
        cfg = get_sandbox()
        full_cfg = None
        try:
            from ..config import load_config
            full_cfg = load_config().get("sandbox", {})
        except Exception:
            full_cfg = {}
    except Exception:
        cfg = {}
        full_cfg = {}

    chosen = backend or cfg.get("backend", "local")
    wd = Path(workdir or cfg.get("workdir", str(Path.cwd()))).expanduser()
    timeout = float(cfg.get("timeout", 60))

    if chosen == "docker":
        image = full_cfg.get("image", "python:3.12-slim")
        return DockerBackend(workdir=wd, image=image, timeout=timeout)
    if chosen == "podman":
        image = full_cfg.get("image", "python:3.12-slim")
        return PodmanBackend(
            workdir=wd, image=image, timeout=timeout,
            allow_network=bool(full_cfg.get("allow_network", False)),
        )
    if chosen == "firecracker":
        return FirecrackerBackend(
            workdir=wd,
            image=full_cfg.get("image", "ubuntu:24.04-maverick"),
            timeout=timeout,
            provider=full_cfg.get("provider", "local"),
            api_key=full_cfg.get("api_key"),
            network=full_cfg.get("network", "egress-deny"),
        )
    if chosen == "ssh":
        host = full_cfg.get("host")
        if not host:
            raise ValueError(
                "sandbox backend=ssh requires [sandbox] host = \"user@example.com\""
            )
        return SSHBackend(
            host=host,
            workdir=Path(full_cfg.get("workdir", "~/maverick-workspace")),
            timeout=timeout,
            ssh_args=full_cfg.get("ssh_args", []),
        )
    return LocalBackend(workdir=wd, timeout=timeout)
