"""Cross-process serialization + atomic writes for small JSON/TOML state files.

Many modules persist a tiny state file with a *read-modify-write*: load the
whole dict, mutate one key, write it all back. Two correctness hazards recur:

  - **Torn read.** A bare ``write_text`` / ``open(..., "w")`` truncates the
    file in place; a concurrent reader sees a half-written file and its
    ``json.load`` raises -> the state is treated as empty or the caller
    crashes. ``atomic_write_text`` writes a *unique* temp file and ``os.replace``
    it into position, so a reader only ever sees the old or the new whole file.

  - **Lost update.** ``os.replace`` makes each write atomic but does NOT stop
    two processes from both loading the same totals and the second clobbering
    the first. A ``threading.Lock`` only serializes threads *within one
    process* — the dashboard, ``serve``, a cron ``dream``, and a webhook can be
    four separate processes against the same tenant data dir.
    ``cross_process_lock`` adds an advisory ``flock`` on a stable sidecar so the
    whole load-modify-save is serialized across processes too.

This mirrors the proven discipline in :mod:`maverick.quotas`
(``_cross_process_lock`` + unique ``mkstemp`` + ``os.replace``); it is factored
out here so the dozen other state stores can adopt it without copy-pasting the
``flock`` dance. POSIX-only locking that degrades to a no-op (the in-process
lock still applies) where ``fcntl``/``flock`` is unavailable.
"""
from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

__all__ = ["cross_process_lock", "atomic_write_text"]


@contextmanager
def cross_process_lock(target: str | Path):
    """Advisory exclusive lock serializing a read-modify-write of ``target``.

    Keyed on a stable ``<name>.lock`` sidecar next to the file — never the file
    itself, since ``os.replace`` swaps the target's inode out from under any
    handle held on it. POSIX-only; degrades to a no-op where ``fcntl``/``flock``
    is unavailable (callers should still hold their own in-process lock).
    """
    target = Path(target)
    lock_path = target.parent / (target.name + ".lock")
    fd = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
    except OSError:
        yield  # cannot create the lock file -> proceed best-effort
        return
    try:
        try:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX)
        except (ImportError, OSError):
            pass  # non-POSIX / exotic FS -> rely on the in-process lock
        yield
    finally:
        try:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_UN)
        except (ImportError, OSError):
            pass
        os.close(fd)


def atomic_write_text(path: str | Path, text: str, *, mode: int = 0o600,
                      encoding: str = "utf-8") -> None:
    """Write ``text`` to ``path`` atomically: a *unique* temp file in the same
    directory, then ``os.replace`` into position.

    A reader concurrent with the write sees either the old whole file or the new
    whole file — never a truncated one. The temp name is unique (``mkstemp``) so
    two concurrent writers don't collide on a shared ``.tmp`` (one ``os.replace``
    would otherwise move the temp out from under the other). The temp is cleaned
    up on any failure so a crashed write leaves no stray files.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}-",
                               suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
