"""Docker sandbox backend.

Each exec spawns a fresh container with the workspace mounted; the
container is removed on exit (``--rm``). Network is disabled by
default (``--network=none``); enable via ``allow_network=True`` if a
specific run needs it.

Why a fresh container per command? Simpler, no state leakage between
calls, mirrors how Hermes / OpenClaw approach ephemeral execution.
Long-lived container with ``docker exec`` is a future optimization.

Falls back loudly: if Docker isn't installed or the daemon isn't
running, ``DockerBackend.__init__`` raises ``RuntimeError`` so the
wizard's smoke test catches it before the agent runs.
"""
from __future__ import annotations

import shlex
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

from .local import ExecResult, container_user_args, scrub_env


def _kill_container(name: str, engine: str = "docker") -> str:
    """Reap an orphaned container by name; return a stderr note on failure.

    ``subprocess.run(timeout=...)`` only kills the local client process, so the
    daemon-side container survives the timeout. ``{engine} kill`` stops it and
    ``{engine} rm -f`` removes it; we retry the kill once in case the daemon was
    briefly busy. If both attempts fail we return a short ``; cleanup failed``
    note so the leak is visible rather than swallowed under a bare except.
    """
    last_err = ""
    for _ in range(2):
        try:
            subprocess.run(
                [engine, "kill", name],
                capture_output=True, timeout=10, env=scrub_env(),
            )
            subprocess.run(
                [engine, "rm", "-f", name],
                capture_output=True, timeout=10, env=scrub_env(),
            )
            return ""
        except Exception as e:  # daemon wedged / binary gone -- note + retry
            last_err = str(e) or e.__class__.__name__
    return f"; container cleanup failed ({last_err}); {name} may be orphaned"


@dataclass
class DockerBackend:
    workdir: Path
    image: str = "python:3.12-slim"
    timeout: float = 60.0
    allow_network: bool = False
    # Fork-bomb guard. Generous enough for real builds (pip/npm/pytest
    # spawn plenty of children) while still bounding a runaway agent.
    # Set to 0/None to disable (not recommended).
    pids_limit: int | None = 512
    # Bound host RAM so a runaway / prompt-injected process can't exhaust it
    # and trip the kernel OOM-killer (which can take down unrelated host
    # processes). CPU is left uncapped by default -- the per-exec ``timeout``
    # already bounds a busy-loop -- but ``cpus`` exposes the knob. A falsy
    # value ("" / None) disables either cap.
    memory: str | None = "4g"
    cpus: str | None = None
    # Run as the invoking user (uid:gid) by default instead of root, matching
    # DevcontainerBackend -- root in the container owns the writable
    # ``-v {workdir}:/workspace`` mount on the host. Set
    # ``[sandbox] allow_root = true`` (or MAVERICK_SANDBOX_ALLOW_ROOT) to keep
    # root for images that require it.
    allow_root: bool = False
    # Container runtime (``docker run --runtime``). None = Docker's default
    # (runc). Set to ``runsc`` for the **gVisor** application kernel, which
    # interposes a userspace kernel between the container and the host —
    # stronger isolation for a possibly prompt-injected agent than seccomp +
    # caps alone. The ``gvisor`` backend wires this in; the runtime must be
    # installed and registered with the Docker daemon.
    runtime: str | None = None
    # Warm-container reuse (the "sandbox pool" perf win): instead of a fresh
    # ``docker run --rm`` per command (a cold start every time), keep ONE
    # container alive and ``docker exec`` into it, so the 2nd..Nth command in a
    # run skip container startup. Opt-in (``[sandbox] reuse_container``); the
    # container is torn down on ``close()``. Default off -> run-per-command.
    reuse_container: bool = False

    def __post_init__(self) -> None:
        self.workdir = Path(self.workdir)
        self.workdir.mkdir(parents=True, exist_ok=True)
        self._warm_name: str | None = None
        self._verify_docker()

    def _verify_docker(self) -> None:
        try:
            subprocess.run(
                ["docker", "version"],
                capture_output=True, timeout=5, check=True,
            )
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            raise RuntimeError(
                "Docker not available. Install Docker Desktop / docker.io, or "
                "change [sandbox] backend to 'local' in ~/.maverick/config.toml."
            ) from e

    def _container_flags(self) -> list[str]:
        """The run/create flags shared by the cold and warm paths."""
        flags = [
            "-v", f"{self.workdir.resolve()}:/workspace",
            "-w", "/workspace",
            # Containment for a possibly prompt-injected agent: drop every
            # Linux capability and block privilege escalation (setuid/setgid
            # binaries can't gain more than they start with). Neither breaks
            # pip/npm/pytest, which need no capabilities.
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            *container_user_args(self.allow_root),
        ]
        if self.runtime:
            flags.extend(["--runtime", str(self.runtime)])
        if self.pids_limit:
            flags.extend(["--pids-limit", str(self.pids_limit)])
        if self.memory:
            # Pin --memory-swap to --memory so the cap can't be sidestepped via
            # swap (default: swap == 2x memory), keeping the RAM bound real.
            flags.extend(["--memory", str(self.memory),
                          "--memory-swap", str(self.memory)])
        if self.cpus:
            flags.extend(["--cpus", str(self.cpus)])
        if not self.allow_network:
            flags.extend(["--network", "none"])
        return flags

    def exec(self, cmd: str, timeout: float | None = None) -> ExecResult:
        # Wave 11: per-call `timeout` matches LocalBackend so the shell
        # tool can plumb a longer cap for pytest/npm test/etc. Falls
        # back to self.timeout (default 60 s).
        effective = self.timeout if timeout is None else timeout
        if self.reuse_container:
            return self._exec_warm(cmd, effective)
        container_name = f"maverick-sandbox-{uuid.uuid4().hex}"
        args = [
            "docker", "run", "--rm",
            "--name", container_name,
            *self._container_flags(),
        ]
        args.extend([self.image, "sh", "-c", cmd])

        try:
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=effective,
                env=scrub_env(),
            )
            return ExecResult(
                stdout=result.stdout[-8000:],
                stderr=result.stderr[-2000:],
                exit_code=result.returncode,
            )
        except subprocess.TimeoutExpired as e:
            # The timeout killed our local `docker run` client, not the daemon
            # container -- which keeps running (and holding the workspace mount)
            # until reaped. Force-remove it by name. Surface a cleanup failure
            # in stderr instead of swallowing it under a bare except: a leaked
            # container is a real condition the operator should see.
            cleanup_note = _kill_container(container_name)
            stdout = e.stdout or ""
            if isinstance(stdout, bytes):
                stdout = stdout.decode("utf-8", errors="replace")
            return ExecResult(
                stdout=stdout[-8000:],
                stderr=f"TIMEOUT after {effective}s{cleanup_note}",
                exit_code=124,
            )

    # -- warm-container reuse ("sandbox pool") ----------------------------

    def _ensure_warm(self) -> None:
        """Start the persistent container once; subsequent calls reuse it."""
        if self._warm_name is not None:
            return
        name = f"maverick-warm-{uuid.uuid4().hex}"
        args = ["docker", "run", "-d", "--name", name,
                *self._container_flags(),
                self.image, "sleep", "infinity"]
        subprocess.run(args, capture_output=True, text=True,
                       timeout=self.timeout, env=scrub_env())
        self._warm_name = name

    def _exec_warm(self, cmd: str, effective: float) -> ExecResult:
        self._ensure_warm()
        args = ["docker", "exec", self._warm_name, "sh", "-c",
                self._warm_command(cmd)]
        try:
            result = subprocess.run(args, capture_output=True, text=True,
                                    timeout=effective, env=scrub_env())
            return ExecResult(
                stdout=result.stdout[-8000:],
                stderr=result.stderr[-2000:],
                exit_code=result.returncode,
            )
        except subprocess.TimeoutExpired as e:
            # A timed-out `docker exec` can leave daemon-side children running
            # inside the warm container. Reap the container, just like the cold
            # path does, so no command can outlive its timeout/budget boundary.
            self.close()
            stdout = e.stdout or ""
            if isinstance(stdout, bytes):
                stdout = stdout.decode("utf-8", errors="replace")
            return ExecResult(stdout=stdout[-8000:],
                              stderr=f"TIMEOUT after {effective}s", exit_code=124)

    def _warm_command(self, cmd: str) -> str:
        """Run a command, then reap any processes it left behind.

        Warm containers intentionally keep filesystem/package state across
        execs, but shell background jobs must not survive a tool call. Docker
        does not provide a per-exec process cleanup primitive, so the wrapper
        runs the requested command in a child shell, preserves its exit status,
        then terminates every other container process except PID 1 and the
        wrapper itself. If the exec times out before reaching this cleanup,
        `_exec_warm` removes the whole container.
        """
        return "\n".join([
            f"sh -c {shlex.quote(cmd)} &",
            "child=$!",
            "wait $child",
            "rc=$?",
            "for proc in /proc/[0-9]*; do",
            "  pid=${proc##*/}",
            "  [ \"$pid\" = 1 ] && continue",
            "  [ \"$pid\" = \"$$\" ] && continue",
            "  kill -TERM \"$pid\" 2>/dev/null || true",
            "done",
            "sleep 0.2",
            "for proc in /proc/[0-9]*; do",
            "  pid=${proc##*/}",
            "  [ \"$pid\" = 1 ] && continue",
            "  [ \"$pid\" = \"$$\" ] && continue",
            "  kill -KILL \"$pid\" 2>/dev/null || true",
            "done",
            "exit $rc",
        ])

    def close(self) -> None:
        """Tear down the warm container (no-op when reuse is off / unused)."""
        if self._warm_name is None:
            return
        try:
            subprocess.run(["docker", "rm", "-f", self._warm_name],
                           capture_output=True, text=True, timeout=15,
                           env=scrub_env())
        except Exception:  # pragma: no cover -- best-effort teardown
            pass
        self._warm_name = None
