"""Cross-run sandbox pooling — opt-in reuse of a still-healthy backend.

``[sandbox] cross_run_pool = true`` (default **false**: zero behavior change)
lets a run park its sandbox at run end instead of dropping it, and lets
``build_sandbox`` hand that instance to the next run. The pool is bounded
(max 2 entries, TTL-evicted via an injected clock) and in-process — it serves
the long-lived ``maverick serve`` / embedder case where many runs share one
process; separate processes never share sandboxes.

Eligibility — the scrub contract
--------------------------------
A backend may only be pooled if handing it to the next run provably carries
**no state** from the previous one. What "scrubbed" means here, exactly:

  1. **Workspace wipe**: the parked handle's ``workdir`` is re-pointed to the
     *next* run's directory at acquire (and created). The previous run's
     workspace is never mounted again through this handle, and the handle
     keeps no other reference to it. (The old directory itself belongs to its
     run/operator; the pool does not delete operator files.)
  2. **Env reset**: eligible backends build the child environment fresh per
     exec via ``scrub_env()`` — nothing env-shaped survives on the instance.
  3. **No live guest**: eligible backends run a fresh ``docker/podman run
     --rm`` per exec, so no container/filesystem/process state exists between
     execs, let alone between runs. Docker's opt-in warm ``reuse_container``
     mode is deliberately excluded from pooling because its persistent guest is
     mounted to the workdir that existed when it was first created. Per-run
     ``timeout`` is re-applied at acquire.

Only :class:`DockerBackend` and :class:`PodmanBackend` satisfy all three
(what is actually reused is the verified daemon handle + image-pinned
configuration). Every other backend is excluded and **fails to fresh**:

  - ``LocalBackend`` — host execution; nothing to scrub, nothing isolated;
  - ``FirecrackerBackend`` — a warm e2b microVM keeps guest filesystem state
    that cannot be guaranteed wiped remotely (violates 3);
  - ``SSHBackend`` / ``KubernetesBackend`` / ``DevcontainerBackend`` — remote
    or project-bound state outside this process's control.

Keying
------
Entries are keyed by engine + **image digest** (resolved via ``<engine> image
inspect``; falls back to the tag string when the engine can't answer, in
which case a tag whose content moved would match — the digest lookup exists
precisely to avoid that) + every security-relevant constructor flag
(``allow_network``, ``allow_root``, ``pids_limit``, ``memory``, ``cpus``,
``runtime``). A config change therefore never receives a stale instance.

Wiring: ``build_sandbox`` consults :func:`acquire` behind the knob; the run
loop (integrator side) calls :func:`park_at_run_end` when a run finishes.
"""
from __future__ import annotations

import logging
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .docker import DockerBackend
from .local import scrub_env
from .podman import PodmanBackend

log = logging.getLogger(__name__)

POOL_MAX = 2
POOL_TTL_SECONDS = 600.0
_TRUE = {"1", "true", "yes", "on"}


def cross_run_pool_enabled(sandbox_cfg: dict | None = None) -> bool:
    """The ``[sandbox] cross_run_pool`` knob. Default OFF."""
    if sandbox_cfg is None:
        try:
            from ..config import load_config
            sandbox_cfg = (load_config() or {}).get("sandbox") or {}
        except Exception:  # pragma: no cover - config never blocks teardown
            return False
    raw = sandbox_cfg.get("cross_run_pool", False)
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() in _TRUE


def _engine_of(sandbox: object) -> str | None:
    """Pool-eligible engine name, or None (excluded -> caller fails to fresh).

    Podman first: it isn't a DockerBackend subclass today, but isinstance
    order documents the intent if that ever changes.
    """
    if isinstance(sandbox, PodmanBackend):
        return "podman"
    if isinstance(sandbox, DockerBackend):
        return "docker"
    return None


def _image_digest(engine: str, image: str) -> str:
    """Resolve the image's content digest (``.Id``); fall back to the tag."""
    try:
        proc = subprocess.run(
            [engine, "image", "inspect", "--format", "{{.Id}}", image],
            capture_output=True, text=True, timeout=10, env=scrub_env(),
        )
        digest = (proc.stdout or "").strip()
        if proc.returncode == 0 and digest:
            return digest
    except Exception as e:
        log.debug("sandbox pool: image digest lookup failed for %s: %s", image, e)
    return image


def _key(engine: str, image: str, *, allow_network: object, allow_root: object,
         pids_limit: object, memory: object, cpus: object,
         runtime: object) -> str:
    return "|".join([
        engine,
        _image_digest(engine, image),
        f"net={bool(allow_network)}",
        f"root={bool(allow_root)}",
        f"pids={pids_limit}",
        f"mem={memory}",
        f"cpus={cpus}",
        f"rt={runtime}",
    ])


def _key_of(sandbox: object) -> str | None:
    engine = _engine_of(sandbox)
    if engine is None:
        return None
    if isinstance(sandbox, DockerBackend) and sandbox.reuse_container:
        log.debug(
            "sandbox pool: DockerBackend with reuse_container is not "
            "pool-eligible; warm containers are per-run only"
        )
        return None
    return _key(
        engine,
        sandbox.image,  # type: ignore[attr-defined]
        allow_network=sandbox.allow_network,  # type: ignore[attr-defined]
        allow_root=sandbox.allow_root,  # type: ignore[attr-defined]
        pids_limit=sandbox.pids_limit,  # type: ignore[attr-defined]
        memory=sandbox.memory,  # type: ignore[attr-defined]
        cpus=sandbox.cpus,  # type: ignore[attr-defined]
        runtime=getattr(sandbox, "runtime", None),  # podman has no runtime knob
    )


def _healthy(sandbox: object) -> bool:
    """Re-verify the engine daemon before parking; an unhealthy handle is
    dropped (the next run's fresh construction will surface the real error)."""
    try:
        if isinstance(sandbox, PodmanBackend):
            sandbox._verify_podman()
        elif isinstance(sandbox, DockerBackend):
            sandbox._verify_docker()
        else:
            return False
        return True
    except Exception as e:
        log.info("sandbox pool: not parking unhealthy sandbox: %s", e)
        return False


@dataclass
class _Entry:
    key: str
    sandbox: object
    parked_at: float


class SandboxPool:
    """Bounded, TTL'd registry of parked sandbox handles. Thread-safe."""

    def __init__(self, max_entries: int = POOL_MAX, ttl: float = POOL_TTL_SECONDS,
                 clock: Callable[[], float] = time.monotonic):
        self.max_entries = max(1, int(max_entries))
        self.ttl = float(ttl)
        self.clock = clock
        self._entries: list[_Entry] = []
        self._lock = threading.Lock()

    def _prune_locked(self) -> None:
        now = self.clock()
        self._entries = [e for e in self._entries if now - e.parked_at < self.ttl]

    def park(self, sandbox: object) -> bool:
        """Park a sandbox at run end. False = excluded/unhealthy (fail to fresh)."""
        key = _key_of(sandbox)
        if key is None:
            log.debug("sandbox pool: %s is not pool-eligible; not parking",
                      type(sandbox).__name__)
            return False
        if not _healthy(sandbox):
            return False
        with self._lock:
            self._prune_locked()
            if any(e.sandbox is sandbox for e in self._entries):
                return True  # already parked; don't double-enter
            while len(self._entries) >= self.max_entries:
                evicted = self._entries.pop(0)
                log.debug("sandbox pool: evicting oldest entry (%s)", evicted.key)
            self._entries.append(_Entry(key=key, sandbox=sandbox,
                                        parked_at=self.clock()))
        return True

    def acquire(self, engine: str, image: str, *, workdir: Path | str,
                timeout: float, allow_network: object = False,
                allow_root: object = False, pids_limit: object = 512,
                memory: object = "4g", cpus: object = None,
                runtime: object = None) -> object | None:
        """Hand out a parked sandbox matching this exact configuration, scrubbed.

        Scrub (see module docstring): ``workdir`` re-pointed + created, and
        the new run's ``timeout`` applied. None = nothing suitable (caller
        builds fresh).
        """
        with self._lock:
            self._prune_locked()
            if not any(e.key.startswith(engine + "|") for e in self._entries):
                return None  # cheap out before any digest subprocess
        # Compute the digest key OUTSIDE the lock: _key -> _image_digest runs a
        # `docker/podman image inspect` (up to 10s) and must not stall every
        # other acquire()/park()/len() behind the global pool lock. park() is
        # symmetric -- it computes _key_of before locking. A second thread that
        # mutates _entries in this window is fine: the authoritative scan below
        # re-takes the lock.
        key = _key(engine, image, allow_network=allow_network,
                   allow_root=allow_root, pids_limit=pids_limit,
                   memory=memory, cpus=cpus, runtime=runtime)
        with self._lock:
            self._prune_locked()
            for i, entry in enumerate(self._entries):
                if entry.key == key:
                    self._entries.pop(i)
                    sandbox = entry.sandbox
                    break
            else:
                return None
        wd = Path(workdir)
        wd.mkdir(parents=True, exist_ok=True)
        sandbox.workdir = wd  # type: ignore[attr-defined]
        sandbox.timeout = float(timeout)  # type: ignore[attr-defined]
        log.info("sandbox pool: reusing parked %s sandbox for %s",
                 engine, wd)
        return sandbox

    def __len__(self) -> int:
        with self._lock:
            self._prune_locked()
            return len(self._entries)


_shared: SandboxPool | None = None
_shared_lock = threading.Lock()


def shared_pool() -> SandboxPool:
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = SandboxPool()
        return _shared


def reset_shared_pool() -> None:
    """Drop the process pool (tests)."""
    global _shared
    with _shared_lock:
        _shared = None


def park_at_run_end(sandbox: object) -> bool:
    """Integrator hook: call when a run finishes instead of dropping the sandbox.

    No-ops (returns False) unless ``[sandbox] cross_run_pool = true`` — with
    the knob off, run teardown is exactly what it was before this module
    existed.
    """
    if not cross_run_pool_enabled():
        return False
    return shared_pool().park(sandbox)


__all__ = [
    "POOL_MAX",
    "POOL_TTL_SECONDS",
    "SandboxPool",
    "shared_pool",
    "reset_shared_pool",
    "park_at_run_end",
    "cross_run_pool_enabled",
]
