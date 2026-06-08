"""Encrypt closed audit day-files at rest (confidentiality for the audit log).

The audit log is *signed* for tamper-evidence (``signing.py``) but is otherwise
plaintext NDJSON on disk -- a confidentiality gap when the events carry sensitive
action detail. This seals **closed** day-files (any date strictly before today) in
place with AES-256-GCM, leaving the file name unchanged: a sealed segment just
holds the encrypted blob instead of NDJSON, detected on read by the seal magic
header. The **current** day-file is never sealed -- live append + the flock'd
signing writer keep operating on plaintext.

Reads stay transparent: :func:`segment_text` decrypts a sealed segment back to its
NDJSON text, so the readers (``export.iter_audit_events``) and the verifier
(``signing.verify_chain`` / the cross-file tip ledger) work on sealed and
plaintext segments alike -- and the hash-chain still verifies, because sealing
only encrypts the bytes, never the signed rows.

Exposed as ``maverick audit seal``; runs only when at-rest encryption is enabled.
"""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class SegmentReadError(RuntimeError):
    """An audit segment could not be read or decoded for verification."""


def segment_text(path: Path, *, fail_soft: bool = True) -> str:
    """Return an audit day-file's NDJSON text, transparently decrypting a sealed
    segment.

    Export readers use the default fail-soft mode and receive ``""`` on a
    read/decrypt error. Integrity verifiers must pass ``fail_soft=False`` so
    unreadable or undecryptable signed evidence fails closed instead of being
    mistaken for a valid empty chain.
    """
    try:
        raw = Path(path).read_bytes()
    except OSError as e:
        if fail_soft:
            return ""
        raise SegmentReadError(f"cannot read audit segment {path}: {e}") from e
    from ..crypto_at_rest import is_sealed, unseal
    if is_sealed(raw):
        try:
            return unseal(raw).decode("utf-8")
        except Exception as e:
            if fail_soft:
                return ""
            raise SegmentReadError(f"cannot decrypt sealed audit segment {path}: {e}") from e
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as e:
        if fail_soft:
            return ""
        raise SegmentReadError(f"cannot decode audit segment {path}: {e}") from e


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """Replace ``path`` with ``data`` atomically and privately (0600)."""
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".seal-", suffix=".tmp")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def seal_closed_segments(audit_dir: Path | None = None, *,
                         today: str | None = None,
                         dry_run: bool = False) -> dict[str, str]:
    """Seal every closed (date < today), not-yet-sealed day-file in place.

    Requires at-rest encryption to be enabled (raises
    :class:`maverick.crypto_at_rest.EncryptionUnavailable` otherwise, so it never
    leaves a half-state). Returns a ``{filename: status}`` report. The current
    day-file, the ``anchors.ndjson`` tip ledger, and already-sealed files are
    skipped.
    """
    import datetime as _dt

    from ..crypto_at_rest import EncryptionUnavailable, at_rest_enabled, is_sealed, seal
    if not at_rest_enabled():
        raise EncryptionUnavailable(
            "at-rest encryption is not enabled; set [encryption] at_rest = true "
            "(or MAVERICK_ENCRYPT_AT_REST=1) before sealing audit segments"
        )
    if audit_dir is None:
        from ..paths import data_dir
        audit_dir = data_dir("audit")
    today = today or _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")

    report: dict[str, str] = {}
    if not audit_dir.exists():
        return report
    for p in sorted(audit_dir.glob("*.ndjson")):
        if not _DAY_RE.fullmatch(p.stem):
            continue                              # not a date-named day-file
        if p.stem >= today:
            report[p.name] = "skipped (current)"  # live append stays plaintext
            continue
        try:
            raw = p.read_bytes()
        except OSError as e:
            report[p.name] = f"error ({e})"
            continue
        if is_sealed(raw):
            report[p.name] = "already sealed"
            continue
        if dry_run:
            report[p.name] = "would seal"
            continue
        _atomic_write_bytes(p, seal(raw))
        report[p.name] = "sealed"
    return report


__all__ = ["SegmentReadError", "segment_text", "seal_closed_segments"]
