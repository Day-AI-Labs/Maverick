"""Audit-log Ed25519 signing.

Every audit event line is hashed together with the previous line's
hash (Merkle-style chain). The chain head is signed with an Ed25519
key whose pubkey is stored alongside.

This gives us tamper-evidence: if any historical line is altered,
the chain breaks at that point. The on-disk format stays NDJSON
(append-only), with two extra fields per row:

  - ``prev_hash``: hex-encoded SHA-256 of the previous row's signed bytes
  - ``hash``:      hex-encoded SHA-256 of this row's signed bytes
  - ``sig``:       hex-encoded Ed25519 signature of ``hash``

Key management:
  - First write: a new Ed25519 keypair is generated and saved at
    ``~/.maverick/audit/keys/<keyid>.{key,pub}`` (chmod 600 on the
    private key).
  - Subsequent writes load the most recent key.
  - ``verify_chain()`` walks a file and confirms every signature +
    chain link. Returns a list of any breaks for human review.

Optional [audit-signing] extra (cryptography>=42.0).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)


KEY_DIR = Path.home() / ".maverick" / "audit" / "keys"


_KEY_ID_RE = re.compile(r"^[0-9a-f]{16}$")

# Cross-file tip-ledger (#462/#443): a signed, chained ledger recording each
# completed day-file's tip hash + row count, so deleting or truncating a WHOLE
# day-file is detectable (per-file verify_chain only sees within one file).
ANCHOR_FILENAME = "anchors.ndjson"
ANCHOR_MARKER_FILENAME = ".anchors.required"
_DAY_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _is_valid_key_id(key_id: str) -> bool:
    """Key IDs are fixed-width lowercase hex fingerprints."""
    return bool(_KEY_ID_RE.fullmatch(key_id))


def _key_paths_for_id(key_id: str) -> tuple[Path, Path] | tuple[None, None]:
    """Return trusted key paths for key_id, or (None, None) if invalid."""
    if not _is_valid_key_id(key_id):
        return None, None
    pub_path = (KEY_DIR / f"{key_id}.pub").resolve()
    priv_path = (KEY_DIR / f"{key_id}.key").resolve()
    try:
        pub_path.relative_to(KEY_DIR.resolve())
        priv_path.relative_to(KEY_DIR.resolve())
    except ValueError:
        return None, None
    return pub_path, priv_path


@dataclass
class ChainBreak:
    line_no: int  # 1-indexed
    reason: str  # 'bad_hash' | 'bad_signature' | 'chain_mismatch' | 'malformed'
    detail: str


def _have_crypto() -> bool:
    try:
        from cryptography.hazmat.primitives.asymmetric import ed25519  # noqa: F401

        return True
    except ImportError:
        return False


def verify_ed25519(pubkey_hex: str, sig_hex: str, message: bytes) -> bool:
    """Return True iff ``sig_hex`` is a valid Ed25519 signature over
    ``message`` under ``pubkey_hex`` (both hex-encoded raw keys/sigs).

    Returns False on any verification failure or malformed input. Raises
    ImportError if ``cryptography`` is not installed -- callers that want
    fail-open behavior must guard with ``_have_crypto()`` first.
    """
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric import ed25519

    try:
        pub = ed25519.Ed25519PublicKey.from_public_bytes(bytes.fromhex(pubkey_hex))
        pub.verify(bytes.fromhex(sig_hex), message)
        return True
    except (InvalidSignature, ValueError):
        return False


def _generate_keypair() -> tuple[bytes, bytes, str]:
    """Return (private_key_bytes, public_key_bytes, key_id)."""
    if not _have_crypto():
        raise ImportError(
            "cryptography not installed. Run: pip install 'maverick-agent[audit-signing]'"
        )
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519

    priv = ed25519.Ed25519PrivateKey.generate()
    pub = priv.public_key()
    priv_bytes = priv.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_bytes = pub.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    key_id = hashlib.sha256(pub_bytes).hexdigest()[:16]
    return priv_bytes, pub_bytes, key_id


def _save_keypair(priv: bytes, pub: bytes, key_id: str) -> Path:
    KEY_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(KEY_DIR, 0o700)
    except OSError:
        pass
    priv_path = KEY_DIR / f"{key_id}.key"
    pub_path = KEY_DIR / f"{key_id}.pub"
    # Create the private signing key (the audit chain's trust anchor) with the
    # mode set AT creation. write_bytes() + a later chmod left a world-readable
    # window during which another local user could read -- and then forge with
    # -- the key. The dir chmod above is best-effort and may not apply.
    fd = os.open(str(priv_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, priv)
    finally:
        os.close(fd)
    pub_path.write_bytes(pub)
    try:
        os.chmod(priv_path, 0o600)
        os.chmod(pub_path, 0o644)
    except OSError:
        pass
    return priv_path


def _load_or_create_keypair() -> tuple[bytes, bytes, str]:
    """Load the most-recent keypair or generate one if none exists."""
    if KEY_DIR.exists():
        priv_files = sorted(KEY_DIR.glob("*.key"))
        if priv_files:
            latest = max(priv_files, key=lambda p: p.stat().st_mtime)
            key_id = latest.stem
            pub_path = KEY_DIR / f"{key_id}.pub"
            if pub_path.exists():
                return latest.read_bytes(), pub_path.read_bytes(), key_id
    priv, pub, key_id = _generate_keypair()
    _save_keypair(priv, pub, key_id)
    return priv, pub, key_id


class AuditSigner:
    """Sign + chain audit log lines.

    Wraps an NDJSON sink, adding ``prev_hash`` / ``hash`` / ``sig`` /
    ``key_id`` fields to each row before writing.

    Thread-safe. A single AuditSigner per file is assumed; cross-
    process concurrency would need an external lock (we don't bake
    that in to avoid adding flock/fcntl complexity for the common
    single-process case).
    """

    def __init__(self, audit_path: Path):
        self._lock = threading.Lock()
        self._path = audit_path
        self._priv_bytes, self._pub_bytes, self._key_id = _load_or_create_keypair()
        try:
            from cryptography.hazmat.primitives.asymmetric import ed25519
        except ImportError as e:
            raise ImportError(
                "cryptography not installed. Run: pip install 'maverick-agent[audit-signing]'"
            ) from e
        self._signer = ed25519.Ed25519PrivateKey.from_private_bytes(self._priv_bytes)
        self._last_hash = self._resume_last_hash()

    def _resume_last_hash(self) -> str:
        """If the file has prior entries, find the latest hash to chain on.

        A torn final line (crash mid-write, no trailing newline) must NOT
        silently reset the chain to genesis (prev_hash=""), which would let
        an attacker truncate-and-reappend a self-consistent sub-chain that
        verifies clean. If the last non-empty line is unparseable, raise so
        the caller surfaces it instead of starting a fresh chain.
        """
        if not self._path.exists() or self._path.stat().st_size == 0:
            return ""
        with open(self._path, "rb") as f:
            last_line = b""
            for line in f:
                if line.strip():
                    last_line = line
        if not last_line:
            return ""
        try:
            data = json.loads(last_line)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"audit chain resume: last line of {self._path} is unparseable "
                "(torn write?); refusing to silently restart the chain"
            ) from e
        return str(data.get("hash") or "")

    def write(self, event: dict) -> bool:
        """Append a signed + chained event row. Returns True on success."""
        with self._lock:
            payload = dict(event)
            payload["prev_hash"] = self._last_hash
            payload["key_id"] = self._key_id
            row_bytes = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
            row_hash = hashlib.sha256(row_bytes).hexdigest()
            sig = self._signer.sign(bytes.fromhex(row_hash)).hex()
            payload["hash"] = row_hash
            payload["sig"] = sig
            line = json.dumps(payload, default=str) + "\n"
            try:
                from .writer import _file_append_lock

                self._path.parent.mkdir(parents=True, exist_ok=True)
                with open(self._path, "a", encoding="utf-8") as f:
                    # Cross-process advisory lock: serialize concurrent writers
                    # so an append above PIPE_BUF can't interleave a torn row
                    # into the signed chain. POSIX-only; no-op elsewhere.
                    with _file_append_lock(f):
                        f.write(line)
                        # fsync so a power loss can't lose committed audit rows
                        # (or leave a torn line that breaks chain resume). The
                        # audit log is the trust anchor; durability matters more
                        # than the small write cost here.
                        f.flush()
                        os.fsync(f.fileno())
                try:
                    os.chmod(self._path, 0o600)
                except OSError:
                    pass
                # Only advance the in-memory chain head AFTER the row is
                # durably on disk; otherwise a crash between write and this
                # line would chain the next row on a hash that isn't there.
                self._last_hash = row_hash
                return True
            except OSError as e:
                log.warning("audit signer: write failed: %s", e)
                return False

    @property
    def public_key_hex(self) -> str:
        return self._pub_bytes.hex()


def verify_chain(path: Path, pubkey_hex: str | None = None) -> list[ChainBreak]:
    """Walk every line; verify chain links + signatures.

    If ``pubkey_hex`` is None, the verifier looks up each row's
    ``key_id`` against ~/.maverick/audit/keys/<keyid>.pub.

    Returns a list of breaks. Empty list = chain intact.
    """
    if not _have_crypto():
        return [ChainBreak(0, "no_crypto", "cryptography not installed")]
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric import ed25519

    breaks: list[ChainBreak] = []
    if not path.exists():
        return [ChainBreak(0, "missing_file", str(path))]
    prev = ""
    pubkey_cache: dict[str, ed25519.Ed25519PublicKey] = {}

    def _load_pubkey(key_id: str):
        if key_id in pubkey_cache:
            return pubkey_cache[key_id]
        if pubkey_hex:
            obj = ed25519.Ed25519PublicKey.from_public_bytes(bytes.fromhex(pubkey_hex))
        else:
            # Trust a local .pub only when its private .key sibling also
            # exists — i.e. this host actually generated that keypair.
            # That closes the "attacker drops a lone forged <id>.pub and
            # re-signs rows" vector while still honoring legitimate key
            # rotation (which always writes both .key and .pub). For
            # third-party tamper-evidence, callers should pass the
            # trusted pubkey_hex explicitly.
            pub_path, priv_path = _key_paths_for_id(key_id)
            if pub_path is None or not pub_path.exists() or not priv_path.exists():
                return None
            obj = ed25519.Ed25519PublicKey.from_public_bytes(pub_path.read_bytes())
        pubkey_cache[key_id] = obj
        return obj

    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, start=1):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError as e:
                breaks.append(ChainBreak(n, "malformed", str(e)))
                continue
            row_hash = data.get("hash")
            sig = data.get("sig")
            row_prev = data.get("prev_hash", "")
            key_id = data.get("key_id", "")
            if not row_hash or not sig or not key_id:
                breaks.append(ChainBreak(n, "malformed", "missing hash/sig/key_id"))
                continue
            if row_prev != prev:
                breaks.append(
                    ChainBreak(
                        n,
                        "chain_mismatch",
                        f"row prev={row_prev[:12]}... expected {prev[:12] or '(empty)'}",
                    )
                )
            payload_for_hash = {k: v for k, v in data.items() if k not in ("hash", "sig")}
            expected_hash = hashlib.sha256(
                json.dumps(payload_for_hash, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest()
            if expected_hash != row_hash:
                breaks.append(ChainBreak(n, "bad_hash", "content rehash != row hash"))
            pub = _load_pubkey(key_id)
            if pub is None:
                breaks.append(ChainBreak(n, "no_pubkey", f"key_id {key_id!r}"))
            else:
                try:
                    pub.verify(bytes.fromhex(sig), bytes.fromhex(row_hash))
                except InvalidSignature:
                    breaks.append(ChainBreak(n, "bad_signature", "Ed25519 verify failed"))
                except ValueError as e:
                    # A tampered sig/hash that isn't valid hex must be
                    # flagged as a break, NOT crash the verifier (which
                    # would skip every later row — the opposite of what
                    # a tamper-evidence tool should do).
                    breaks.append(ChainBreak(n, "bad_signature", f"malformed sig/hash: {e}"))
            prev = row_hash
    return breaks


# ---- cross-file tip-ledger (#462/#443) -------------------------------------

def _file_tip_and_count(path: Path) -> tuple[str, int]:
    """Return ``(last_row_hash, non_empty_row_count)`` for a signed day-file."""
    tip = ""
    count = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            count += 1
            try:
                tip = str(json.loads(line).get("hash") or tip)
            except json.JSONDecodeError:
                pass
    return tip, count


def _day_files(audit_dir: Path) -> list[Path]:
    """Date-named day-files (YYYY-MM-DD.ndjson), excluding the anchor ledger."""
    return sorted(
        p for p in audit_dir.glob("*.ndjson") if _DAY_RE.fullmatch(p.stem)
    )


def _anchored_days(audit_dir: Path) -> set[str]:
    path = audit_dir / ANCHOR_FILENAME
    days: set[str] = set()
    if not path.exists():
        return days
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if d.get("kind") == "anchor" and d.get("day"):
                days.add(str(d["day"]))
    return days


def _anchor_marker_path(audit_dir: Path) -> Path:
    """Return the durable marker that records an expected anchor ledger.

    The marker prevents a deleted ``anchors.ndjson`` from being silently
    recreated from only the day-files that an attacker chose to leave behind.
    """
    return audit_dir / ANCHOR_MARKER_FILENAME


def _mark_anchor_ledger_required(audit_dir: Path) -> None:
    marker = _anchor_marker_path(audit_dir)
    if marker.exists():
        return
    try:
        audit_dir.mkdir(parents=True, exist_ok=True)
        marker.write_text(
            "anchors.ndjson is required for audit tamper-evidence\n",
            encoding="utf-8",
        )
    except OSError as e:  # pragma: no cover - best-effort marker
        log.warning("audit anchors: failed to write ledger marker: %s", e)


def _ensure_anchor_ledger(audit_dir: Path) -> bool:
    """Return whether it is safe to append to the anchor ledger.

    A missing ledger is acceptable before the first completed day is anchored.
    Once the marker records that the ledger has existed, however, a missing
    ledger is suspicious and must not be rebuilt from only the remaining
    day-files.
    """
    anchor_path = audit_dir / ANCHOR_FILENAME
    if anchor_path.exists():
        _mark_anchor_ledger_required(audit_dir)
        return True
    return not _anchor_marker_path(audit_dir).exists()


def _append_anchor(audit_dir: Path, day: str, tip_hash: str, row_count: int) -> bool:
    """Append one signed, chained anchor row to the tip-ledger."""
    if not _have_crypto():
        return False
    signer = AuditSigner(audit_dir / ANCHOR_FILENAME)
    ok = bool(
        signer.write({
            "kind": "anchor",
            "day": day,
            "tip_hash": tip_hash,
            "row_count": row_count,
            "ts": datetime.now(timezone.utc).isoformat(),
        })
    )
    if ok:
        _mark_anchor_ledger_required(audit_dir)
    return ok


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def ensure_anchors(audit_dir: Path) -> int:
    """Record a tip-ledger anchor for every COMPLETED day-file lacking one.

    Only completed days (< today, UTC) are anchored -- today's file is still
    growing. Already-anchored days are left alone: we never silently re-anchor
    over a tampered file (that's ``verify_anchors``' job to flag); a legitimate
    GDPR erase re-anchors its day explicitly via ``reanchor_day_after_erase``.
    Returns the number of anchors written.
    """
    if not _have_crypto():
        return 0
    if not _ensure_anchor_ledger(audit_dir):
        log.warning(
            "audit anchors: %s is missing but was previously required; refusing to rebuild",
            ANCHOR_FILENAME,
        )
        return 0
    today = _today_utc()
    anchored = _anchored_days(audit_dir)
    written = 0
    for day_file in _day_files(audit_dir):
        day = day_file.stem
        if day >= today or day in anchored:
            continue
        tip, count = _file_tip_and_count(day_file)
        if count and _append_anchor(audit_dir, day, tip, count):
            written += 1
    return written


def reanchor_day_after_erase(audit_dir: Path, day_file: Path) -> None:
    """After a GDPR erase rewrites a completed day-file (changing its tip),
    append a fresh superseding anchor so ``verify_anchors`` matches the new
    state. The prior anchor stays in the append-only ledger -- an auditable
    record that the day was modified."""
    if not _have_crypto():
        return
    day = day_file.stem
    if not _DAY_RE.fullmatch(day) or day >= _today_utc():
        return  # not a completed day-file
    tip, count = _file_tip_and_count(day_file)
    if count:
        _append_anchor(audit_dir, day, tip, count)


def verify_anchors(audit_dir: Path, pubkey_hex: str | None = None) -> list[ChainBreak]:
    """Cross-file tamper-evidence: confirm every anchored day-file still exists
    and matches its latest recorded tip hash + row count. Catches deletion or
    truncation of a whole day-file, which per-file ``verify_chain`` cannot.

    Verifies the anchor ledger's own signed chain first, then each day.
    Empty list = intact.
    """
    anchor_path = audit_dir / ANCHOR_FILENAME
    if not anchor_path.exists():
        has_completed_days = any(p.stem < _today_utc() for p in _day_files(audit_dir))
        if has_completed_days or _anchor_marker_path(audit_dir).exists():
            return [
                ChainBreak(
                    0,
                    "anchor_ledger_missing",
                    f"{ANCHOR_FILENAME} is missing; "
                    "cross-file audit tamper-evidence cannot be verified",
                )
            ]
        return []
    breaks = list(verify_chain(anchor_path, pubkey_hex))
    # The ledger is append-only; the last anchor for a day wins (supersession).
    latest: dict[str, dict] = {}
    with open(anchor_path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if d.get("kind") == "anchor" and d.get("day"):
                latest[str(d["day"])] = d
    for day, anc in sorted(latest.items()):
        day_file = audit_dir / f"{day}.ndjson"
        if not day_file.exists():
            breaks.append(ChainBreak(
                0, "anchored_file_deleted", f"{day}.ndjson is anchored but missing"))
            continue
        tip, count = _file_tip_and_count(day_file)
        if tip != anc.get("tip_hash"):
            breaks.append(ChainBreak(
                0, "anchor_tip_mismatch",
                f"{day}: tip {tip[:12]}... != anchored {str(anc.get('tip_hash'))[:12]}..."))
        if count != anc.get("row_count"):
            breaks.append(ChainBreak(
                0, "anchor_count_mismatch",
                f"{day}: {count} rows != anchored {anc.get('row_count')}"))
    return breaks


def reanchor_file(path: Path, *, force: bool = False, preverified: bool = False) -> int:
    """Re-chain + re-sign every row of a signed audit file, in place.

    A GDPR erase tombstones or removes rows but does NOT recompute the
    ``prev_hash``/``hash``/``sig`` chain, so ``verify_chain()`` then reports
    breaks that are indistinguishable from tampering. This rewrites the file,
    recomputing each row's chain fields under the current key so the chain
    verifies clean again, preserving row content and order. The caller writes
    a signed ``erase`` marker first so a verifier holding the trusted pubkey
    can see the cut was authorized.

    By default, re-anchoring first verifies the existing file and refuses to
    rewrite a broken chain. Callers that just performed an authorized erase
    may pass ``preverified=True`` only after verifying the original file before
    mutating it; this prevents a routine erase from laundering older tampering.

    ``force`` re-signs even rows that currently carry no signature (e.g. a
    file whose every signed row was tombstoned by the erase). Without it, a
    file with no signed rows is left untouched (returns -1) -- erasing an
    unsigned log has no chain to repair.

    Returns rows re-signed, 0 if no rewrite was needed (already consistent),
    or -1 if skipped (crypto unavailable, missing file, or unsigned without
    ``force``).

    Re-anchoring re-signs under the host key: it makes *authorized* erasure
    verifiable-clean. It is not extra protection against an attacker who
    already holds that key -- that is inherent to same-host key storage.
    """
    if not _have_crypto():
        return -1
    if not path.exists() or path.is_dir():
        return -1
    from cryptography.hazmat.primitives.asymmetric import ed25519

    try:
        with open(path, encoding="utf-8") as f:
            original = f.read()
    except OSError:
        return -1

    parsed: list[tuple[str, object]] = []
    any_signed = False
    for raw in original.splitlines():
        if not raw.strip():
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # Never drop data on a rewrite: preserve unparseable lines
            # verbatim (and out of the chain), mirroring verify_chain.
            parsed.append(("raw", raw))
            continue
        if data.get("sig") and data.get("hash") and data.get("key_id"):
            any_signed = True
        parsed.append(("json", data))

    if not any_signed and not force:
        return -1
    if not preverified:
        breaks = verify_chain(path)
        if breaks:
            log.warning(
                "audit reanchor: refusing to rewrite %s; chain is not clean (%s)",
                path,
                breaks[0],
            )
            return -1

    priv_bytes, _pub, key_id = _load_or_create_keypair()
    signer = ed25519.Ed25519PrivateKey.from_private_bytes(priv_bytes)

    out_lines: list[str] = []
    prev = ""
    resigned = 0
    for kind, val in parsed:
        if kind == "raw":
            out_lines.append(val)  # type: ignore[arg-type]
            continue
        assert isinstance(val, dict)
        # Strip the old chain fields, then rebuild them exactly as
        # AuditSigner.write does (hash over payload incl. prev_hash + key_id,
        # sort_keys=True; sig over the hash bytes).
        payload = {k: v for k, v in val.items() if k not in ("hash", "sig", "prev_hash", "key_id")}
        payload["prev_hash"] = prev
        payload["key_id"] = key_id
        row_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        payload["hash"] = row_hash
        payload["sig"] = signer.sign(bytes.fromhex(row_hash)).hex()
        out_lines.append(json.dumps(payload, default=str))
        prev = row_hash
        resigned += 1

    new_content = "".join(line + "\n" for line in out_lines)
    if new_content == original:
        return 0  # untouched rows under an unchanged key -> no rewrite

    tmp = path.with_suffix(".ndjson.reanchortmp")
    try:
        mode = path.stat().st_mode & 0o777
    except OSError:
        mode = 0o600
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(new_content)
            f.flush()
            os.fsync(f.fileno())
        tmp.replace(path)
        try:
            os.chmod(path, mode)
        except OSError:
            pass
    except OSError as e:
        log.warning("audit reanchor: %s: %s", path, e)
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        return -1
    return resigned


__all__ = [
    "AuditSigner",
    "verify_chain",
    "verify_ed25519",
    "ChainBreak",
    "KEY_DIR",
    "reanchor_file",
]
