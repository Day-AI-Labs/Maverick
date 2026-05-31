"""Kubernetes sandbox backend.

Spawns a transient ``kubectl run --rm -i --restart=Never`` pod per
``exec()`` call, mounts the workspace via an emptyDir + ``kubectl
cp`` (or, when ``workdir`` is None, runs without a mount), captures
stdout/stderr/exit-code, and deletes the pod on exit.

Why kubectl-driven instead of the official Python client?
  - The Python client adds 50+ MB of generated code + grpcio + a
    handful of transitive deps. ``kubectl`` is one binary the user
    already has if they're running on K8s.
  - The exec semantics map 1:1 with our other sandboxes (Docker,
    Podman, Devcontainer); the abstraction is "spawn a fresh
    container per command", not "manage long-lived pods".

Config::

    [sandbox]
    backend = "kubernetes"
    image = "python:3.12-slim"
    namespace = "default"
    context = "minikube"        # optional kubeconfig context
    workdir = "/workspaces/repo"
    timeout = 120
    allow_network = false        # adds NetworkPolicy-deny annotation hint

Loud-fallback: missing kubectl binary or ``kubectl version`` failure
raises ``RuntimeError`` at construction so the wizard's smoke test
catches it before the agent runs.
"""
from __future__ import annotations

import logging
import shlex
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .local import ExecResult

log = logging.getLogger(__name__)


@dataclass
class KubernetesBackend:
    image: str = "python:3.12-slim"
    namespace: str = "default"
    context: str | None = None
    workdir: Path = Path("/workspaces/repo")
    timeout: float = 120.0
    allow_network: bool = False
    extra_kubectl_args: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.workdir = Path(self.workdir)
        self._verify_kubectl()

    def _kubectl_prefix(self) -> list[str]:
        args = ["kubectl"]
        if self.context:
            args.extend(["--context", self.context])
        args.extend(["-n", self.namespace])
        args.extend(self.extra_kubectl_args)
        return args

    def _verify_kubectl(self) -> None:
        try:
            subprocess.run(
                ["kubectl", "version", "--client", "--output=yaml"],
                capture_output=True, timeout=5, check=True,
            )
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            raise RuntimeError(
                "kubectl not available — required for kubernetes backend. "
                "Install kubectl or change [sandbox] backend in "
                "~/.maverick/config.toml."
            ) from e

    def exec(self, cmd: str, timeout: float | None = None) -> ExecResult:
        effective = self.timeout if timeout is None else timeout
        pod_name = f"maverick-sb-{uuid.uuid4().hex[:12]}"

        wrapped = (
            f"mkdir -p {shlex.quote(str(self.workdir))} && "
            f"cd {shlex.quote(str(self.workdir))} && {cmd}"
        )

        if not self.allow_network:
            return ExecResult(
                stdout="",
                stderr=(
                    "networking is disabled for kubernetes backend (allow_network=false), "
                    "but kubectl backend cannot enforce no-network safely"
                ),
                exit_code=2,
            )

        # `kubectl run` creates the pod, runs it, deletes it (--rm).
        # restart=Never is required for --rm semantics; --quiet
        # suppresses pod-create noise so stdout stays clean.
        args = [
            *self._kubectl_prefix(),
            "run", pod_name,
            "--rm", "-i", "--restart=Never", "--quiet",
            f"--image={self.image}",
            "--",
            "sh", "-c", wrapped,
        ]

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
            # Best-effort cleanup; ignore errors (incl. a hung kubectl
            # that would otherwise raise over the TIMEOUT result).
            try:
                subprocess.run(
                    [*self._kubectl_prefix(), "delete", "pod", pod_name,
                     "--ignore-not-found=true", "--grace-period=0", "--force"],
                    capture_output=True, timeout=10,
                )
            except Exception:
                pass
            stdout = e.stdout or ""
            if isinstance(stdout, bytes):
                stdout = stdout.decode("utf-8", errors="replace")
            return ExecResult(
                stdout=stdout[-8000:],
                stderr=f"TIMEOUT after {effective}s",
                exit_code=124,
            )


__all__ = ["KubernetesBackend"]
