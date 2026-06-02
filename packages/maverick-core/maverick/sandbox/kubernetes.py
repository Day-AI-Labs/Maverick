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

import json
import logging
import shlex
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .local import ExecResult, scrub_env

log = logging.getLogger(__name__)

# Deny-all NetworkPolicy the operator applies once per namespace so pods get no
# egress (and no ingress). Surfaced when allow_network=false, since a transient
# `kubectl run` pod can't enforce this on itself.
_DENY_ALL_NETWORKPOLICY = """\
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: maverick-deny-all
  namespace: {ns}
spec:
  podSelector: {{}}
  policyTypes: [Ingress, Egress]\
"""


@dataclass
class KubernetesBackend:
    image: str = "python:3.12-slim"
    namespace: str = "default"
    context: str | None = None
    workdir: Path = Path("/workspaces/repo")
    timeout: float = 120.0
    allow_network: bool = False
    extra_kubectl_args: list[str] = field(default_factory=list)
    # Containment for a possibly prompt-injected agent (mirrors docker/podman):
    # never run as uid 0, block privilege escalation, and bound RAM/CPU so a
    # runaway can't exhaust the node. Falsy memory/cpu disables that limit.
    run_as_user: int = 1000
    memory: str | None = "4g"
    cpus: str | None = None

    def __post_init__(self) -> None:
        self.workdir = Path(self.workdir)
        self._verify_kubectl()

    def _pod_overrides(self) -> dict:
        """A non-root, resource-bounded pod spec for ``kubectl run --overrides``.

        ``kubectl run`` otherwise emits a bare pod that runs as the image's
        default user (often root) with no resource limits. We pin a non-root
        securityContext + drop all capabilities + block privilege escalation,
        and set requests/limits so a runaway can't starve the node."""
        limits: dict[str, str] = {}
        if self.memory:
            limits["memory"] = str(self.memory)
        if self.cpus:
            limits["cpu"] = str(self.cpus)
        container: dict = {
            "name": "maverick",
            "securityContext": {
                "allowPrivilegeEscalation": False,
                "capabilities": {"drop": ["ALL"]},
            },
        }
        if limits:
            container["resources"] = {"limits": limits, "requests": limits}
        return {
            "spec": {
                "securityContext": {
                    "runAsNonRoot": True,
                    "runAsUser": int(self.run_as_user),
                },
                "containers": [container],
            }
        }

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
                capture_output=True, timeout=5, check=True, env=scrub_env(),
            )
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            raise RuntimeError(
                "kubectl not available — required for kubernetes backend. "
                "Install kubectl or change [sandbox] backend in "
                "~/.maverick/config.toml."
            ) from e

    def _delete_pod(self, pod_name: str) -> None:
        """Best-effort force-delete a pod; never raises.

        ``kubectl run --rm`` deletes the pod only on a clean exit. Any other
        outcome -- a timeout, a kubectl crash, the process being killed, or
        an unexpected exception mid-run -- can orphan the pod and leak
        cluster resources, so we always issue an explicit delete on the way
        out. ``--ignore-not-found`` makes the common (already-removed-by-rm)
        case a no-op.
        """
        try:
            subprocess.run(
                [*self._kubectl_prefix(), "delete", "pod", pod_name,
                 "--ignore-not-found=true", "--grace-period=0", "--force"],
                capture_output=True, timeout=10, env=scrub_env(),
            )
        except Exception:
            pass

    def exec(self, cmd: str, timeout: float | None = None) -> ExecResult:
        effective = self.timeout if timeout is None else timeout
        pod_name = f"maverick-sb-{uuid.uuid4().hex[:12]}"

        wrapped = (
            f"mkdir -p {shlex.quote(str(self.workdir))} && "
            f"cd {shlex.quote(str(self.workdir))} && {cmd}"
        )

        if not self.allow_network:
            # We can't make a single transient `kubectl run` pod enforce
            # no-egress on its own -- that needs a cluster-level NetworkPolicy
            # the operator applies once. Fail closed (don't silently run with
            # network) but emit the concrete deny-all policy to apply, making
            # good on the docstring's "NetworkPolicy-deny hint" promise.
            log.warning(
                "kubernetes backend: allow_network=false but a transient pod "
                "cannot self-enforce no-egress. Apply a deny-all NetworkPolicy "
                "to namespace %r once, then set allow_network=true:\n%s",
                self.namespace, _DENY_ALL_NETWORKPOLICY.format(ns=self.namespace),
            )
            return ExecResult(
                stdout="",
                stderr=(
                    "networking is disabled for kubernetes backend "
                    "(allow_network=false), but a transient kubectl pod cannot "
                    "enforce no-network on its own. Apply a deny-all "
                    "NetworkPolicy to the namespace (see logs) and set "
                    "allow_network=true."
                ),
                exit_code=2,
            )

        # `kubectl run` creates the pod, runs it, deletes it (--rm).
        # restart=Never is required for --rm semantics; --quiet
        # suppresses pod-create noise so stdout stays clean. --overrides pins
        # the non-root securityContext + resource limits onto the pod spec.
        args = [
            *self._kubectl_prefix(),
            "run", pod_name,
            "--rm", "-i", "--restart=Never", "--quiet",
            f"--image={self.image}",
            "--overrides", json.dumps(self._pod_overrides()),
            "--",
            "sh", "-c", wrapped,
        ]

        # Always force-delete the pod on the way out: --rm only fires on a
        # clean exit, so a timeout, a kubectl crash, or any other exception
        # would otherwise leak the pod. The finally runs the explicit delete
        # for every path (success, non-zero exit, timeout, unexpected error).
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
            stdout = e.stdout or ""
            if isinstance(stdout, bytes):
                stdout = stdout.decode("utf-8", errors="replace")
            return ExecResult(
                stdout=stdout[-8000:],
                stderr=f"TIMEOUT after {effective}s",
                exit_code=124,
            )
        finally:
            self._delete_pod(pod_name)


__all__ = ["KubernetesBackend"]
