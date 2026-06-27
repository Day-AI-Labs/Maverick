"""Execution backends.

Local (subprocess), Docker (throwaway containers), SSH (remote host
via system ssh binary). All implement ``.exec(cmd) -> ExecResult``
so the agent loop is backend-agnostic.

The agent never instantiates a backend directly -- always go through
``build_sandbox()`` so the [sandbox] config section is the single
source of truth.
"""
from __future__ import annotations

import importlib.util
import logging
import os
import shutil
from pathlib import Path

from .devcontainer import DevcontainerBackend
from .docker import DockerBackend
from .firecracker import FirecrackerBackend
from .kubernetes import KubernetesBackend
from .local import ExecResult, LocalBackend
from .podman import PodmanBackend
from .sdk import SDK_VERSION, SandboxV2
from .ssh import SSHBackend

__all__ = [
    "LocalBackend",
    "DockerBackend",
    "PodmanBackend",
    "DevcontainerBackend",
    "KubernetesBackend",
    "FirecrackerBackend",
    "SSHBackend",
    "ExecResult",
    "build_sandbox",
    "fs_is_host_visible",
    "SandboxPolicyError",
    "SDK_VERSION",
    "SandboxV2",
]

log = logging.getLogger(__name__)

Sandbox = (
    LocalBackend | DockerBackend | PodmanBackend | DevcontainerBackend
    | KubernetesBackend | FirecrackerBackend | SSHBackend
)


# Default container image per coding language. When ``[sandbox] image`` isn't
# set explicitly, build_sandbox picks one from the language hint (``[sandbox]
# language`` or the ``MAVERICK_LANGUAGE`` env var -- the same signal
# coding_mode threads through evaluate_candidate/run_failing_tests) so a
# Rust/Go/JS task lands in a container that can actually run ``cargo test`` /
# ``go test`` / the JS runner, instead of python:3.12-slim with no toolchain.
_DEFAULT_IMAGE = "python:3.12-slim"
_IMAGE_BY_LANGUAGE = {
    "python":     "python:3.12-slim",
    "py":         "python:3.12-slim",
    "rust":       "rust:1-slim",
    "go":         "golang:1-bookworm",
    "golang":     "golang:1-bookworm",
    "javascript": "node:22-bookworm-slim",
    "typescript": "node:22-bookworm-slim",
    "js":         "node:22-bookworm-slim",
    "ts":         "node:22-bookworm-slim",
    "node":       "node:22-bookworm-slim",
    "ruby":       "ruby:3-slim",
    "java":       "eclipse-temurin:21-jdk",
    "kotlin":     "eclipse-temurin:21-jdk",
}


_TRUE_CONFIG_VALUES = {"1", "true", "yes", "on"}
_FALSE_CONFIG_VALUES = {"0", "false", "no", "off", ""}


def _config_bool(value: object, default: bool = False) -> bool:
    """Parse hand-edited/interpolated config booleans without string truthiness.

    TOML booleans arrive as ``bool``, but quoted values and ``${ENV}``
    interpolation arrive as strings.  Using ``bool("false")`` would enable
    security-sensitive toggles such as Docker network/root access, so accept
    common boolean spellings explicitly and fall back to the supplied default
    for unrecognized values.
    """
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _TRUE_CONFIG_VALUES:
            return True
        if normalized in _FALSE_CONFIG_VALUES:
            return False
        log.warning("invalid sandbox boolean %r; using default %s", value, default)
        return default
    if isinstance(value, int):
        return bool(value)
    log.warning("invalid sandbox boolean %r; using default %s", value, default)
    return default


def _resolve_image(full_cfg: dict) -> str:
    """Pick the container image for the container-based backends.

    Precedence: explicit ``[sandbox] image`` > language toolchain default
    (from ``[sandbox] language`` or the ``MAVERICK_LANGUAGE`` env hint) >
    ``python:3.12-slim``. An unknown language falls back to the Python image
    rather than guessing, so behaviour is unchanged unless a language is set.
    """
    explicit = full_cfg.get("image")
    if explicit:
        return explicit
    lang_value = full_cfg.get("language") or os.environ.get("MAVERICK_LANGUAGE", "")
    if not isinstance(lang_value, str):
        return _DEFAULT_IMAGE
    lang = lang_value.strip().lower()
    return _IMAGE_BY_LANGUAGE.get(lang, _DEFAULT_IMAGE)


_LOCAL_WARNING_EMITTED = False


def fs_is_host_visible(sandbox: object | None) -> bool:
    """Whether files the sandbox writes are visible to THIS (host) process.

    True when there is no sandbox (commands fall back to a host subprocess) or
    the backend runs against the host filesystem (``LocalBackend``, which sets
    ``host_visible_fs = True``). Container / remote backends (docker, podman,
    kubernetes, firecracker, ssh, modal) execute in a separate filesystem
    namespace, so a host-side ``Path.exists()`` on an output path is meaningless
    there -- callers should report the path rather than stat it. Unknown
    backends default to NOT host-visible, the conservative choice: a tool then
    states it can't verify instead of emitting a false "output missing" warning.
    """
    if sandbox is None:
        return True
    return bool(getattr(sandbox, "host_visible_fs", False))


class SandboxPolicyError(RuntimeError):
    """Raised when the configured sandbox backend violates deployment policy
    (e.g. the unsandboxed ``local`` backend under enterprise/require-container)."""


def _config_truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _container_backend_required(full_cfg: dict | None = None) -> bool:
    """Whether a container sandbox backend is mandatory (so ``local`` is refused).

    True when ``MAVERICK_REQUIRE_CONTAINER_BACKEND`` is set, ``[sandbox]
    require_container = true``, or enterprise mode is on. Off by default so
    single-tenant/dev installs keep the (warned) local backend.
    """
    if _config_truthy_env("MAVERICK_REQUIRE_CONTAINER_BACKEND"):
        return True
    if full_cfg and _config_bool(full_cfg.get("require_container"), False):
        return True
    try:
        from ..enterprise import enterprise_enabled
        return bool(enterprise_enabled())
    except Exception:  # pragma: no cover -- never block startup on a lookup error
        return False


def _resolve_local_under_policy(chosen: str, full_cfg: dict | None) -> str:
    """Container-default under enterprise: when ``chosen == "local"`` but a
    container backend is required (enterprise mode / require-container), upgrade
    ``local`` to an available container backend (docker, then podman) instead of
    running ``shell=True`` on the host. Only when NO container runtime is
    installed do we refuse, fail-closed -- we never silently fall back to the
    unsandboxed host. Returns ``chosen`` unchanged when the policy is inactive or
    the backend isn't ``local``."""
    if chosen != "local" or not _container_backend_required(full_cfg):
        return chosen
    auto = _default_container_backend()
    if auto is None:
        raise SandboxPolicyError(
            "refusing the unsandboxed 'local' sandbox backend: enterprise / "
            "require-container policy is active but [sandbox] backend = "
            "\"local\" runs shell=True on the host with no isolation, and no "
            "container runtime (docker / podman) was found to default to. "
            "Install docker or podman, or set [sandbox] backend to a "
            "container backend (gvisor / kubernetes / firecracker)."
        )
    log.warning(
        "enterprise/require-container policy is active and [sandbox] backend is "
        "'local' (no host isolation); defaulting to the available '%s' container "
        "backend. Pin [sandbox] backend explicitly to silence this.", auto,
    )
    return auto


def _default_container_backend() -> str | None:
    """The container backend to default to when ``local`` is refused: the first
    of ``docker`` / ``podman`` whose CLI is on PATH, or ``None`` if neither is
    installed (caller then fails closed rather than running on the host)."""
    for backend in ("docker", "podman"):
        if shutil.which(backend):
            return backend
    return None


def _warn_local_unsandboxed() -> None:
    """Warn (once per process) that the agent will run model-generated shell
    directly on the host with no container isolation.

    The local backend executes ``shell=True`` commands on this machine, so a
    prompt-injected agent gets host code execution. The Shield is the only
    screen, and it is fail-open (optional dependency) -- escalate the message
    when it isn't installed. Suppress with MAVERICK_SUPPRESS_SANDBOX_WARNING=1
    (e.g. when the operator has deliberately accepted host execution, or for
    quiet test runs). The wizard already defaults real installs to a container
    backend when one is available; this catches CLI / embedder / hand-edited
    configs that land on the unisolated default.
    """
    global _LOCAL_WARNING_EMITTED
    if _LOCAL_WARNING_EMITTED:
        return
    if os.environ.get("MAVERICK_SUPPRESS_SANDBOX_WARNING") == "1":
        _LOCAL_WARNING_EMITTED = True
        return
    _LOCAL_WARNING_EMITTED = True
    shield_present = importlib.util.find_spec("maverick_shield") is not None
    msg = (
        "sandbox backend is 'local': model-generated shell runs directly on "
        "this host with NO container isolation. A prompt-injected agent can "
        "execute arbitrary code here. For untrusted goals, set [sandbox] "
        "backend = \"docker\" (or podman) in ~/.maverick/config.toml."
    )
    if not shield_present:
        msg += (
            " maverick-shield is NOT installed, so tool calls are not screened "
            "either (fail-open). This is the least-protected configuration."
        )
    log.warning("%s Silence with MAVERICK_SUPPRESS_SANDBOX_WARNING=1.", msg)


def _degrade_to_local(chosen: str, full_cfg: dict, wd: Path, timeout: float):
    """Build the unsandboxed LocalBackend for an unrecognized backend name --
    or refuse it under the require-container policy.

    The top-of-``build_sandbox`` gate catches an explicit ``backend="local"``;
    this catches the *other* path to a host shell -- a typo'd / unsupported
    backend that matched no known backend and would otherwise silently degrade.
    Both must fail closed under enterprise / require-container, else a config
    typo (``"dcoker"``) quietly runs untrusted agent code on the host.
    """
    if _container_backend_required(full_cfg):
        raise SandboxPolicyError(
            f"refusing to fall back to the unsandboxed 'local' sandbox "
            f"backend: configured backend {chosen!r} matched no known backend "
            f"and enterprise / require-container policy is active. Fix the "
            f"[sandbox] backend value (known: docker, podman, gvisor, "
            f"devcontainer, kubernetes, firecracker, ssh)."
        )
    log.warning(
        "unrecognized sandbox backend %r; falling back to local with NO "
        "container isolation. Known backends: docker, podman, "
        "devcontainer, kubernetes, firecracker, ssh, local.",
        chosen,
    )
    _warn_local_unsandboxed()
    return LocalBackend(workdir=wd, timeout=timeout)


def build_sandbox(
    workdir: str | Path | None = None,
    backend: str | None = None,
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

    # Normalize the backend selector: it comes from user-typed TOML (or a CLI
    # flag) and is matched case-sensitively against the literals below, so
    # "Docker" / " docker " would otherwise fall through to the unsandboxed
    # local backend -- silently giving NO container isolation to a user who
    # explicitly asked for it. Lowercase + strip so the configured backend
    # actually applies.
    chosen = str(backend or cfg.get("backend") or "local").strip().lower()
    # Enterprise gate (container-default under enterprise): when 'local' is
    # chosen but a container backend is required, upgrade to an available one or
    # fail closed. Extracted to keep build_sandbox under the complexity cap.
    chosen = _resolve_local_under_policy(chosen, full_cfg)
    wd = Path(workdir or cfg.get("workdir", str(Path.cwd()))).expanduser()
    # Coerce defensively: [sandbox] timeout is hand-editable, and a non-numeric
    # ("fast") or non-positive value would otherwise raise here and crash the
    # kernel at startup -- config.py's contract is to fall back to defaults on
    # bad config, not abort. Warn + default so a typo doesn't take the agent down.
    try:
        timeout = float(cfg.get("timeout", 60))
        if timeout <= 0:
            raise ValueError("non-positive")
    except (TypeError, ValueError):
        log.warning("invalid [sandbox] timeout %r; using 60s", cfg.get("timeout"))
        timeout = 60.0

    if chosen == "modal":
        # Ephemeral Modal cloud sandboxes ([modal] extra). The CF-Workers half
        # of the roadmap item is declined for shell semantics (see
        # sandbox/modal_backend.py docstring).
        from .modal_backend import ModalBackend
        return ModalBackend(
            workdir=wd, image=_resolve_image(full_cfg), timeout=timeout,
            cpu=full_cfg.get("cpus"), memory_mb=full_cfg.get("memory_mb"),
            allow_network=_config_bool(full_cfg.get("allow_network"), False),
        )

    if chosen.startswith("ep:"):
        # Sandbox SDK v2: a third-party backend from the maverick.sandboxes
        # entry-point group. Conformance-checked at load; raises (never
        # silently falls back to unsandboxed local) on a broken backend.
        from .sdk import load_entry_point_backend
        options = full_cfg.get("options") or {}
        return load_entry_point_backend(
            chosen[3:].strip(), workdir=wd, timeout=timeout,
            options=options if isinstance(options, dict) else {},
        )

    if chosen in ("docker", "gvisor"):
        image = _resolve_image(full_cfg)
        # gVisor is Docker with the runsc runtime; reuse every Docker knob and
        # just swap the runtime. A configured [sandbox] runtime overrides the
        # default so an operator can point gvisor at a custom runsc registration.
        runtime = full_cfg.get("runtime") or ("runsc" if chosen == "gvisor" else None)
        kwargs = dict(
            allow_network=_config_bool(full_cfg.get("allow_network"), False),
            pids_limit=full_cfg.get("pids_limit", 512),
            memory=full_cfg.get("memory", "4g"),
            cpus=full_cfg.get("cpus"),
            allow_root=_config_bool(full_cfg.get("allow_root"), False),
        )
        # Opt-in cross-run pooling (default OFF -> this block is dead and
        # behavior is byte-identical): reuse a parked, still-healthy backend
        # for the same engine + image digest + security flags. See pool.py
        # for the scrub contract. Docker's reuse_container is the WITHIN-run
        # warm knob and is not cross-run pool eligible because it keeps a live
        # container mounted to the run workdir.
        reuse_container = _config_bool(full_cfg.get("reuse_container"), False)
        if _config_bool(full_cfg.get("cross_run_pool"), False) and not reuse_container:
            from . import pool as _pool
            pooled = _pool.shared_pool().acquire(
                "docker", image, workdir=wd, timeout=timeout,
                runtime=runtime, **kwargs)
            if pooled is not None:
                return pooled
        return DockerBackend(
            workdir=wd, image=image, timeout=timeout, runtime=runtime,
            reuse_container=reuse_container, **kwargs,
        )
    if chosen == "podman":
        image = _resolve_image(full_cfg)
        kwargs = dict(
            allow_network=_config_bool(full_cfg.get("allow_network"), False),
            pids_limit=full_cfg.get("pids_limit", 512),
            memory=full_cfg.get("memory", "4g"),
            cpus=full_cfg.get("cpus"),
            allow_root=_config_bool(full_cfg.get("allow_root"), False),
        )
        if _config_bool(full_cfg.get("cross_run_pool"), False):
            from . import pool as _pool
            pooled = _pool.shared_pool().acquire(
                "podman", image, workdir=wd, timeout=timeout, **kwargs)
            if pooled is not None:
                return pooled
        return PodmanBackend(
            workdir=wd, image=image, timeout=timeout, **kwargs,
        )
    if chosen == "devcontainer":
        project_dir = Path(
            full_cfg.get("project_dir") or workdir or Path.cwd()
        ).expanduser()
        return DevcontainerBackend(
            project_dir=project_dir, timeout=timeout,
            allow_network=_config_bool(full_cfg.get("allow_network"), True),
            memory=full_cfg.get("memory", "4g"),
        )
    if chosen == "kubernetes":
        return KubernetesBackend(
            image=_resolve_image(full_cfg),
            namespace=full_cfg.get("namespace", "default"),
            context=full_cfg.get("context"),
            workdir=Path(full_cfg.get("workdir", "/workspaces/repo")),
            timeout=timeout,
            allow_network=_config_bool(full_cfg.get("allow_network"), False),
            extra_kubectl_args=full_cfg.get("extra_kubectl_args") or [],
            run_as_user=int(full_cfg.get("run_as_user", 1000)),
            memory=full_cfg.get("memory", "4g"),
            cpus=full_cfg.get("cpus"),
        )
    if chosen == "firecracker":
        return FirecrackerBackend(
            workdir=wd,
            image=full_cfg.get("image", "ubuntu:24.04-maverick"),
            timeout=timeout,
            provider=full_cfg.get("provider", "local"),
            api_key=full_cfg.get("api_key"),
            network=full_cfg.get("network", "egress-deny"),
            # Warm microVM reuse between execs (e2b provider only; see
            # FirecrackerBackend docstring). Default OFF.
            warm=_config_bool(full_cfg.get("warm"), False),
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
            host_key_checking=full_cfg.get("host_key_checking", "accept-new"),
        )
    if chosen != "local":
        # Matched no known backend: route through the helper, which fail-closes
        # under require-container instead of silently degrading to a host shell.
        return _degrade_to_local(chosen, full_cfg, wd, timeout)
    _warn_local_unsandboxed()
    return LocalBackend(workdir=wd, timeout=timeout)
