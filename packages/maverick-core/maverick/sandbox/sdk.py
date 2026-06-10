"""Sandbox SDK v2 — the formal backend contract (roadmap: 2028 H2 ecosystem).

v1 was duck typing: "anything with ``.exec(cmd) -> ExecResult``" — fine
in-tree, but a third party cannot ship a backend without forking, and a
subtly-wrong one (no timeout kwarg, wrong result shape) fails deep inside a
run. v2 makes the contract explicit and loadable:

* :class:`SandboxV2` — a ``runtime_checkable`` Protocol: ``workdir``,
  ``exec(cmd, timeout=None) -> ExecResult``-shaped result. Optional
  capabilities (``put_file``, ``close``) are *declared*, not guessed:
  :func:`capabilities` reports what a backend supports.
* :func:`conformance` — static checks a backend class/instance against the
  contract (presence, call signature, timeout kwarg) and returns the list of
  violations; ``[]`` means conformant. No command is executed.
* **Entry-point loading** — ``[sandbox] backend = "ep:<name>"`` resolves the
  ``maverick.sandboxes`` entry-point group, instantiates the factory with
  ``(workdir, timeout, **[sandbox] options)``, and **refuses** a
  non-conformant backend (a broken sandbox must never silently fall through
  to unsandboxed local execution).

``SDK_VERSION = 2``; in-tree backends conform as-is (v2 formalizes v1's
shape — no behavior change).
"""
from __future__ import annotations

import inspect
import logging
from typing import Any, Protocol, runtime_checkable

log = logging.getLogger(__name__)

SDK_VERSION = 2

# Optional capability methods a backend MAY provide; capabilities() reports
# which are present so callers feature-detect instead of try/except-ing.
_OPTIONAL = ("put_file", "close", "stop")


@runtime_checkable
class SandboxV2(Protocol):
    """The minimal contract every execution backend must satisfy."""

    workdir: Any

    def exec(self, cmd: str, timeout: float | None = None) -> Any: ...


def capabilities(backend: Any) -> set[str]:
    """The capability set a backend declares (by having the method)."""
    caps = {"exec"}
    for name in _OPTIONAL:
        if callable(getattr(backend, name, None)):
            caps.add(name)
    return caps


def conformance(backend: Any) -> list[str]:
    """Check ``backend`` (class or instance) against the v2 contract.

    Static only — nothing is executed. Returns violations; ``[]`` == OK.
    """
    problems: list[str] = []
    exec_fn = getattr(backend, "exec", None)
    if not callable(exec_fn):
        problems.append("missing exec(cmd, timeout=None)")
    else:
        try:
            sig = inspect.signature(exec_fn)
            params = [p for p in sig.parameters.values()
                      if p.name not in ("self", "cls")]
            names = [p.name for p in params]
            if not names:
                problems.append("exec() takes no command argument")
            accepts_timeout = (
                "timeout" in names
                or any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params)
            )
            if not accepts_timeout:
                problems.append(
                    "exec() must accept a per-call timeout kwarg "
                    "(timeout=None) — tools plumb longer caps for test runs")
        except (TypeError, ValueError):  # builtins/C callables
            problems.append("exec() signature is not introspectable")
    if not _declares_workdir(backend):
        problems.append("missing workdir attribute")
    return problems


def _declares_workdir(backend: Any) -> bool:
    """Instance attr, class attr/property, dataclass annotation, or an
    ``__init__(workdir=...)`` parameter all count as declaring ``workdir``
    (a class can't be probed for instance attributes without instantiating,
    which may need docker/ssh)."""
    if hasattr(backend, "workdir"):
        return True
    if "workdir" in getattr(backend, "__annotations__", {}):
        return True
    init = getattr(backend, "__init__", None)
    if callable(init):
        try:
            return "workdir" in inspect.signature(init).parameters
        except (TypeError, ValueError):
            return False
    return False


def load_entry_point_backend(name: str, *, workdir, timeout: float,
                             options: dict | None = None) -> Any:
    """Resolve + instantiate a third-party backend from ``maverick.sandboxes``.

    The factory is called ``factory(workdir=..., timeout=..., **options)``.
    A missing entry point or a non-conformant backend raises — a sandbox the
    operator explicitly selected must never silently degrade to something
    else (least of all unsandboxed local exec).
    """
    from importlib import metadata

    eps = metadata.entry_points()
    group = (eps.select(group="maverick.sandboxes")
             if hasattr(eps, "select") else eps.get("maverick.sandboxes", []))
    matches = [ep for ep in group if ep.name == name]
    if not matches:
        available = sorted(ep.name for ep in group)
        raise RuntimeError(
            f"sandbox entry point {name!r} not found "
            f"(installed: {available or 'none'}). Install the backend package "
            "or fix [sandbox] backend.")
    factory = matches[0].load()
    backend = factory(workdir=workdir, timeout=timeout, **(options or {}))
    problems = conformance(backend)
    if problems:
        raise RuntimeError(
            f"sandbox backend {name!r} does not conform to sandbox SDK v"
            f"{SDK_VERSION}: " + "; ".join(problems))
    log.info("loaded external sandbox %r (capabilities: %s)",
             name, sorted(capabilities(backend)))
    return backend


__all__ = ["SDK_VERSION", "SandboxV2", "capabilities", "conformance",
           "load_entry_point_backend"]
