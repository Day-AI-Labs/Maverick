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
import weakref
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .events import AuditEvent, EventKind, is_valid_day

log = logging.getLogger(__name__)


DEFAULT_AUDIT_DIR = Path.home() / ".maverick" / "audit"

# Every live AuditLog registers here so an erase can drop the stale in-memory
# chain head on *any* writer pointed at the erased dir -- not just the default
# singleton. A WeakSet so GC'd logs fall out on their own.
_live_logs: weakref.WeakSet[AuditLog] = weakref.WeakSet()
_live_logs_lock = threading.Lock()


class _file_append_lock:
    """Advisory cross-process exclusive lock for the duration of an append.

    Two processes appending to the same day-file can interleave torn records
    once a line exceeds ``PIPE_BUF`` (single-``write`` atomicity no longer
    holds), corrupting NDJSON and -- when signing -- the hash chain. An
    advisory ``flock`` on the open file handle serializes concurrent writers.

    POSIX-only: on platforms without ``fcntl`` (e.g. Windows) this degrades to
    a no-op -- the in-process ``threading.Lock`` still covers same-process
    concurrency; cross-process append safety is simply not available there.
    """

    def __init__(self, fileobj: Any):
        self._fileobj = fileobj
        self._locked = False

    def __enter__(self) -> _file_append_lock:
        try:
            import fcntl
        except ImportError:  # non-POSIX (e.g. Windows): no advisory lock
            return self
        try:
            fcntl.flock(self._fileobj.fileno(), fcntl.LOCK_EX)
            self._locked = True
        except OSError as e:  # pragma: no cover - exotic FS without flock
            log.warning("audit: advisory flock unavailable (%s); appending unlocked", e)
        return self

    def __exit__(self, *exc: Any) -> None:
        if not self._locked:
            return
        try:
            import fcntl

            fcntl.flock(self._fileobj.fileno(), fcntl.LOCK_UN)
        except (ImportError, OSError):  # pragma: no cover - best-effort unlock
            pass


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

    def __init__(self, audit_dir: Path | None = None, *, sign: bool | None = None):
        # Resolve the dir at construction (not as a default arg, which would
        # freeze the path at import time). With no explicit dir, route through
        # the tenant-aware helper: the no-tenant default is the legacy
        # ``~/.maverick/audit`` and an active tenant gets its own audit chain
        # under ``~/.maverick/tenants/<t>/audit``.
        if audit_dir is None:
            from ..paths import data_dir

            audit_dir = data_dir("audit")
        self.audit_dir = audit_dir
        self._lock = threading.Lock()
        self._current_path: Path | None = None
        self._current_day: str | None = None
        self._signing_enabled = _resolve_signing(sign)
        self._signer: Any = None
        self._signer_path: Path | None = None
        with _live_logs_lock:
            _live_logs.add(self)

    def _path_for(self, day_str: str) -> Path:
        # ``day_str`` becomes a path component; refuse anything that isn't a
        # bare YYYY-MM-DD so a crafted ``day`` (e.g. ``../../etc/passwd``)
        # can't escape the audit dir. ``_rotate_if_needed`` only ever passes a
        # strftime value, so the write path is unaffected.
        if not is_valid_day(day_str):
            raise ValueError(f"invalid audit day {day_str!r}: expected YYYY-MM-DD")
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
        if self._signing_enabled:
            # Rollover (or first write this process): any now-complete prior
            # day-files get a signed tip-ledger anchor so deleting a whole
            # day-file is detectable. Best-effort -- anchoring must never block
            # an audit write.
            try:
                from .signing import ensure_anchors
                ensure_anchors(self.audit_dir)
            except Exception as e:  # pragma: no cover - defensive
                log.debug("audit: ensure_anchors failed: %s", e)
        return path

    def record(self, event: AuditEvent) -> bool:
        """Write one event. Returns True on success.

        String fields in the event payload are run through
        ``secret_detector.redact`` so API keys, OAuth tokens, JWTs, and
        ``.env`` fragments that leak via tool output never land on disk
        in plaintext. When anonymous mode is enabled, the already-secret-
        redacted payload is additionally passed through Maverick's privacy
        anonymizer before it is serialized or signed. Redaction failure is
        non-fatal: the event still writes, but a warning logs.
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
                    # Cross-process advisory lock so two processes appending the
                    # same day-file can't interleave torn records above PIPE_BUF.
                    with _file_append_lock(f):
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

    def reset_signer_for_dir(self, audit_dir: Path) -> None:
        """Drop the cached signer if it targets ``audit_dir``.

        An erase re-anchors the day file on disk, but the live signer still
        holds the pre-erase ``_last_hash`` in memory, so the next in-process
        ``record()`` would chain onto a hash no longer in the file ->
        immediate ``chain_mismatch``. Clearing the cached signer forces the
        next write to rebuild it and re-read the new chain tail via
        ``_resume_last_hash``. No-op if this log writes elsewhere.
        """
        try:
            same = self.audit_dir.resolve() == audit_dir.resolve()
        except OSError:
            same = self.audit_dir == audit_dir
        if not same:
            return
        with self._lock:
            self._signer = None
            self._signer_path = None

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
    """Walk an audit event dict and redact secrets plus anonymous-mode PII.

    Lazy-imports the detectors so the audit module stays usable in
    environments where optional safety/privacy modules were stripped or
    vendored. Returns a new dict; never mutates the input.
    """
    try:
        from ..safety.secret_detector import redact
    except Exception:
        redact = None

    def _walk(v: Any, depth: int = 0) -> Any:
        # Depth cap: the payload carries arbitrary **kwargs (tool args/results)
        # that can be model/tool-controlled and deeply nested; without a guard a
        # deep value raises RecursionError inside the audit-write path.
        if depth > 64:
            return v if isinstance(v, (int, float, bool, type(None))) else str(v)
        if isinstance(v, str):
            if redact is None:
                return v
            redacted, _ = redact(v)
            return redacted
        if isinstance(v, dict):
            return {k: _walk(vv, depth + 1) for k, vv in v.items()}
        if isinstance(v, list):
            return [_walk(vv, depth + 1) for vv in v]
        return v

    redacted_payload = _walk(payload)
    try:
        from ..privacy import anon_enabled, anonymize_dict
        if anon_enabled():
            return anonymize_dict(redacted_payload)
    except Exception:
        pass
    return redacted_payload


_default: AuditLog | None = None
_defaults: dict[Path, AuditLog] = {}
_default_lock = threading.Lock()


def default_audit_log() -> AuditLog:
    """Return the default audit log for the active tenant context.

    ``AuditLog`` resolves its output directory at construction time, so the
    module-level shortcut must not share one tenant-dependent instance across
    all callers in a long-lived process. Cache one default writer per resolved
    audit directory instead: the no-tenant path keeps the legacy singleton
    semantics, while tenant-scoped calls get an independent writer and chain.
    """
    global _default
    from ..paths import data_dir

    audit_dir = data_dir("audit")
    shared_audit_dir = data_dir("audit", tenant=None)
    with _default_lock:
        if audit_dir == shared_audit_dir:
            # No active tenant: keep the legacy singleton semantics so callers
            # that ASSIGN ``writer._default`` (the dashboard grep endpoint, the
            # audit tests) keep overriding the writer that ``record()`` uses.
            # Reading the new per-dir cache here would ignore that override and
            # silently build a fresh empty writer at the real home dir.
            if _default is None:
                _default = AuditLog(audit_dir)
            _defaults[audit_dir] = _default
            return _default
        log_obj = _defaults.get(audit_dir)
        if log_obj is None:
            log_obj = AuditLog(audit_dir)
            _defaults[audit_dir] = log_obj
        return log_obj


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


def reset_signer_after_erase(audit_dir: Path) -> None:
    """Reset every live AuditLog whose cached signer targets ``audit_dir``.

    Called by the erase helpers right after they re-anchor a file so a
    same-process erase-then-``record()`` chains onto the rewritten tail
    instead of a stale in-memory ``_last_hash``. Covers the default singleton
    and any directly-constructed log via the live registry; never forces a
    singleton into being.
    """
    with _live_logs_lock:
        logs = list(_live_logs)
    for log_obj in logs:
        log_obj.reset_signer_for_dir(audit_dir)


__all__ = [
    "AuditLog",
    "DEFAULT_AUDIT_DIR",
    "default_audit_log",
    "record",
    "reanchor_after_erase",
    "EventKind",
]
