"""Audit log writer. Append-only NDJSON with daily rotation.

The writer is fail-safe: any exception writing the audit log is logged
to the regular Python logger and swallowed. The agent kernel must never
crash because of an audit-path bug.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .events import AuditEvent, EventKind

log = logging.getLogger(__name__)


DEFAULT_AUDIT_DIR = Path.home() / ".maverick" / "audit"


def _resolve_signing(explicit: bool | None) -> bool:
    """Whether to sign + hash-chain audit rows. Opt-in.

    Precedence: explicit arg > MAVERICK_AUDIT_SIGN env > [audit] sign in
    config.toml > off. Resolved once at construction so the hot record()
    path never re-reads config.
    """
    if explicit is not None:
        return bool(explicit)
    if "MAVERICK_AUDIT_SIGN" in os.environ:
        from .._envparse import env_bool

        return env_bool("MAVERICK_AUDIT_SIGN", False)
    try:
        from ..config import load_config

        return bool(((load_config() or {}).get("audit") or {}).get("sign", False))
    except Exception:
        return False


class AuditLog:
    """Append-only NDJSON sink with per-day rotation.

    Single writer instance per process. Thread-safe.

    When signing is enabled (opt-in via ``sign=True`` /
    ``MAVERICK_AUDIT_SIGN`` / ``[audit] sign``), each row is routed
    through :class:`maverick.audit.signing.AuditSigner`, adding an
    Ed25519 ``prev_hash``/``hash``/``sig`` chain so tampering is
    detectable by ``maverick audit verify``. For third-party
    tamper-evidence the verifier must be given an externally-held
    pubkey: a co-located key only detects accidental/non-privileged
    edits, not an attacker who can also write the key dir.
    """

    def __init__(self, audit_dir: Path = DEFAULT_AUDIT_DIR, *, sign: bool | None = None):
        self.audit_dir = audit_dir
        self._lock = threading.Lock()
        self._current_path: Path | None = None
        self._current_day: str | None = None
        self._signing_enabled = _resolve_signing(sign)
        self._signer: Any = None
        self._signer_path: Path | None = None

    def _path_for(self, day_str: str) -> Path:
        return self.audit_dir / f"{day_str}.ndjson"

    def _ensure_dir(self) -> bool:
        try:
            self.audit_dir.mkdir(parents=True, exist_ok=True)
            try:
                os.chmod(self.audit_dir, 0o700)
            except OSError:
                pass
            return True
        except OSError as e:
            log.warning("audit: cannot create dir %s: %s", self.audit_dir, e)
            return False

    def _rotate_if_needed(self) -> Path | None:
        day_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._current_day == day_str and self._current_path is not None:
            return self._current_path
        if not self._ensure_dir():
            return None
        path = self._path_for(day_str)
        # Create the file with chmod 600 if it doesn't exist.
        if not path.exists():
            try:
                path.touch()
                os.chmod(path, 0o600)
            except OSError as e:
                log.warning("audit: cannot create %s: %s", path, e)
                return None
        self._current_path = path
        self._current_day = day_str
        return path

    def record(self, event: AuditEvent) -> bool:
        """Write one event. Returns True on success.

        String fields in the event payload are run through
        ``secret_detector.redact`` so API keys, OAuth tokens, JWTs, and
        ``.env`` fragments that leak via tool output never land on disk
        in plaintext. Redaction failure is non-fatal: the event still
        writes, but a warning logs.
        """
        with self._lock:
            path = self._rotate_if_needed()
            if path is None:
                return False
            try:
                payload = _redact_event(event.to_dict())
                signer = self._signer_for(path)
                if signer is not None:
                    # Sign the already-redacted payload so secrets never
                    # enter the signed bytes either.
                    return bool(signer.write(payload))
                line = json.dumps(payload, default=str) + "\n"
                with open(path, "a", encoding="utf-8") as f:
                    f.write(line)
                    # fsync so a crash / power loss can't lose a committed
                    # audit row (the signed path in signing.py already does
                    # this; match it so the unsigned log is just as durable).
                    f.flush()
                    os.fsync(f.fileno())
                return True
            except (OSError, TypeError, ValueError) as e:
                log.warning("audit: write failed: %s", e)
                return False

    def _signer_for(self, path: Path) -> Any:
        """Lazily build (and rotate with the day file) the AuditSigner.

        Falls back to unsigned writes if signing was requested but the
        crypto extra is missing — and disables further attempts so the
        warning logs once, not per record.
        """
        if not self._signing_enabled:
            return None
        if self._signer is None or self._signer_path != path:
            try:
                from .signing import AuditSigner

                self._signer = AuditSigner(path)
                self._signer_path = path
            except ImportError:
                log.warning(
                    "audit: signing enabled but 'cryptography' not installed; "
                    "writing UNSIGNED. Run: pip install 'maverick-agent[audit-signing]'"
                )
                self._signing_enabled = False
                return None
            except Exception as e:  # pragma: no cover - defensive
                log.warning("audit: signer init failed (%s); writing unsigned", e)
                self._signing_enabled = False
                return None
        return self._signer

    def reanchor_after_erase(self) -> int:
        """Refresh signed audit files after a GDPR erase.

        Erase helpers verify each signed file before mutating it and re-anchor
        only those modified files. This compatibility hook therefore only
        attempts safe/idempotent re-anchors: ``reanchor_file`` refuses to
        rewrite a chain that is not already clean unless the caller explicitly
        supplies proof that the pre-erase file was verified.

        No-op (returns 0) when signing is disabled -- an unsigned log has no
        chain to repair. Never raises: a re-anchor failure must not undo a
        completed erasure.
        """
        with self._lock:
            # Re-anchoring rewrites the day file, so the in-memory chain head
            # is now stale -- force a rebuild on the next write.
            self._signer = None
            self._signer_path = None
            if not self._signing_enabled:
                return 0
            try:
                from .signing import reanchor_file
            except Exception:  # pragma: no cover - crypto missing
                return 0
            total = 0
            if not self.audit_dir.exists():
                return 0
            for path in sorted(self.audit_dir.glob("*.ndjson")):
                try:
                    n = reanchor_file(path)
                except Exception as e:  # pragma: no cover - defensive
                    log.warning("audit: reanchor failed for %s: %s", path, e)
                    continue
                if n > 0:
                    total += n
            return total

    def tail(self, n: int = 50, day: str | None = None) -> list[dict[str, Any]]:
        """Return the last ``n`` events from ``day`` (default today)."""
        if day is None:
            day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        path = self._path_for(day)
        if not path.exists():
            return []
        try:
            with open(path, encoding="utf-8") as f:
                lines = f.readlines()
        except OSError:
            return []
        out: list[dict[str, Any]] = []
        for line in lines[-n:]:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out

    def grep(self, pattern: str, day: str | None = None) -> list[dict[str, Any]]:
        """Crude regex grep over the day's events."""
        import re

        try:
            rx = re.compile(pattern)
        except re.error as e:
            raise ValueError(f"invalid regex pattern {pattern!r}: {e}") from e
        if day is None:
            day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        path = self._path_for(day)
        if not path.exists():
            return []
        out: list[dict[str, Any]] = []
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    if rx.search(line):
                        try:
                            out.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
        except OSError:
            return []
        return out


def _redact_event(payload: dict[str, Any]) -> dict[str, Any]:
    """Walk an audit event dict and redact any embedded secrets in string values.

    Lazy-imports the detector so the audit module stays usable in
    environments where ``maverick.safety`` was stripped or vendored.
    Returns a new dict; never mutates the input.
    """
    try:
        from ..safety.secret_detector import redact
    except Exception:
        return payload

    def _walk(v: Any, depth: int = 0) -> Any:
        # Depth cap: the payload carries arbitrary **kwargs (tool args/results)
        # that can be model/tool-controlled and deeply nested; without a guard a
        # deep value raises RecursionError inside the audit-write path.
        if depth > 64:
            return v if isinstance(v, (int, float, bool, type(None))) else str(v)
        if isinstance(v, str):
            redacted, _ = redact(v)
            return redacted
        if isinstance(v, dict):
            return {k: _walk(vv, depth + 1) for k, vv in v.items()}
        if isinstance(v, list):
            return [_walk(vv, depth + 1) for vv in v]
        return v

    return _walk(payload)


_default: AuditLog | None = None
_default_lock = threading.Lock()


def default_audit_log() -> AuditLog:
    """Singleton AuditLog at ``~/.maverick/audit/``."""
    global _default
    with _default_lock:
        if _default is None:
            _default = AuditLog()
        return _default


def record(
    kind: str,
    *,
    agent: str = "system",
    goal_id: int | None = None,
    **payload: Any,
) -> bool:
    """Module-level shortcut for the default audit log."""
    event = AuditEvent(
        ts=time.time(),
        kind=kind,
        agent=agent,
        goal_id=goal_id,
        payload=payload,
    )
    return default_audit_log().record(event)


def reanchor_after_erase() -> int:
    """Re-anchor the default audit log's signed chain after a GDPR erase.

    Module-level shortcut for the singleton. Safe to call unconditionally:
    a no-op when signing is off.
    """
    return default_audit_log().reanchor_after_erase()


__all__ = [
    "AuditLog",
    "DEFAULT_AUDIT_DIR",
    "default_audit_log",
    "record",
    "reanchor_after_erase",
    "EventKind",
]
