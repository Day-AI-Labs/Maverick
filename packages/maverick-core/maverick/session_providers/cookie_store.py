"""Session cookie storage.

Stores per-provider session blobs as JSON files under
``~/.maverick/sessions/<provider>.json`` with mode 0o600.

The user's filesystem is the trust boundary. We do NOT fake encryption
on top of plain JSON -- if an attacker can read this file they can also
read ~/.maverick/.env which holds raw API keys. chmod 600 is honest
about what we actually protect against (other users on the same host).
"""
from __future__ import annotations

import json
import os
import stat
import time
from pathlib import Path

DEFAULT_DIR = Path.home() / ".maverick" / "sessions"


def _session_dir() -> Path:
    # Re-resolved per call so tests can monkeypatch HOME.
    return Path.home() / ".maverick" / "sessions"


def _path_for(provider: str) -> Path:
    safe = provider.replace("/", "_").replace("..", "_")
    return _session_dir() / f"{safe}.json"


def save_session(provider: str, blob: dict) -> Path:
    """Persist ``blob`` for ``provider``. Returns the file path."""
    if not isinstance(blob, dict):
        raise TypeError(f"blob must be dict, got {type(blob).__name__}")
    path = _path_for(provider)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Mark parent dir 0o700 so other users can't enumerate session files.
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    record = {"saved_at": time.time(), **blob}
    # Write atomically: write to tmp + chmod + rename. Avoids leaving a
    # half-written file with mode 644 visible to other users mid-write.
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record, indent=2))
    os.chmod(tmp, 0o600)
    tmp.replace(path)
    return path


def load_session(provider: str) -> dict | None:
    """Read the blob for ``provider``, or None if no session is stored.

    Raises PermissionError if the file isn't mode 0o600 -- a stricter
    perms enforcement prevents silently using a session that may have
    been world-readable.
    """
    path = _path_for(provider)
    if not path.exists():
        return None
    # POSIX mode bits are meaningless on Windows: NTFS reports 0o666 for
    # every file regardless of the chmod above, so enforcing 0o600 here made
    # EVERY load_session() raise on Windows (session import was wholly broken
    # on the desktop installer's primary platform). On Windows the protection
    # is the per-user profile ACL on ~/.maverick, not the POSIX bit, so skip
    # the check there; keep it strict on POSIX.
    if os.name != "nt":
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & 0o077:
            raise PermissionError(
                f"{path} has mode {oct(mode)} -- expected 0600. "
                "Run: chmod 600 " + str(path)
            )
    return json.loads(path.read_text())


def clear_session(provider: str) -> bool:
    """Delete the stored session. Returns True if a file was removed."""
    path = _path_for(provider)
    if path.exists():
        path.unlink()
        return True
    return False


def list_sessions() -> list[str]:
    """Names of providers with a stored session, sorted."""
    d = _session_dir()
    if not d.exists():
        return []
    return sorted(p.stem for p in d.glob("*.json") if not p.name.endswith(".tmp"))
