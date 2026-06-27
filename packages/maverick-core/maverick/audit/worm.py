"""Write-once (WORM) export of closed audit day-files.

The signed hash-chain + cross-file anchors make the audit log tamper-**evident**
(an alteration is *detectable*). WORM makes the historical records
**un-alterable in the first place**: each *closed* day-file is shipped to a
write-once target with a retention lock, so neither a privileged insider nor an
attacker with filesystem/root access can rewrite or delete the trail. Two
targets (``[audit.worm] provider``):

  - ``s3`` -- S3 (or S3-compatible) **Object-Lock** in ``COMPLIANCE`` (or
    ``GOVERNANCE``) mode with a retain-until date: the object cannot be
    overwritten or deleted until it expires, even by the account root under
    COMPLIANCE. Regulator-grade. The bucket must have Object-Lock + versioning
    enabled (a one-time operator setup), so every re-push is a new locked version.
  - ``local`` -- copy into a WORM directory as an immutable, mode-``0444``,
    versioned file. Best-effort on-box (an owner can still chmod it back), but
    tamper-**evident** via the manifest hash. Use ``s3`` for true WORM.

Only **closed** day-files (date < today, UTC) are shipped -- today's file is
still being appended. Idempotent: a manifest (``worm/manifest.ndjson``) records
each pushed file's sha256 + retain-until + locator, so re-runs skip unchanged
files. A closed file legitimately changes after ``audit seal`` / GDPR erase; on
the next push that new version is shipped (and, on S3, the prior version stays
independently locked). ``verify`` flags any closed file whose current bytes were
never shipped.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any

from ..paths import data_dir
from .signing import day_files

log = logging.getLogger(__name__)

_DEFAULT_RETENTION_DAYS = 2555  # ~7 years -- a common regulatory floor (SOX/HIPAA)
_MANIFEST_NAME = "manifest.ndjson"


class WormUnavailable(RuntimeError):
    """WORM export was requested but no usable target is configured/available."""


def _truthy(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _worm_cfg() -> dict[str, Any]:
    try:
        from ..config import load_config
        cfg = ((load_config() or {}).get("audit") or {}).get("worm") or {}
    # failure-policy: best_effort
    except Exception:  # pragma: no cover -- config never blocks a run
        return {}
    return cfg if isinstance(cfg, dict) else {}


def worm_enabled() -> bool:
    """Opt-in (default off): true when ``MAVERICK_AUDIT_WORM`` is truthy or
    ``[audit.worm] provider`` names a target."""
    env = os.environ.get("MAVERICK_AUDIT_WORM")
    if env is not None and env.strip() != "":
        return _truthy(env)
    return bool(_worm_cfg().get("provider"))


def _utcnow() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


# --- sinks ------------------------------------------------------------------

class LocalWormSink:
    """Copy each closed day-file into a WORM directory as an immutable, versioned,
    mode-0444 file. Best-effort on-box immutability; the manifest hash is the
    tamper-evidence. Each ``put`` writes a NEW file, never overwriting a prior
    version."""

    def __init__(self, directory: str | Path) -> None:
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)

    def put(self, name: str, data: bytes, *, retain_until: _dt.datetime) -> dict:
        # Version by push time (+ a uuid so a same-millisecond re-push after
        # seal/erase keeps the prior copy instead of clobbering it).
        dest = self._dir / f"{name}.{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}"
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, dest)
        try:
            os.chmod(dest, 0o444)
        except OSError:  # pragma: no cover -- exotic filesystem
            pass
        return {"target": "local", "path": str(dest),
                "retain_until": retain_until.isoformat()}

    def verify(self, locator: dict, expected_sha256: str) -> bool:
        if locator.get("target") != "local":
            return False
        try:
            path = Path(str(locator.get("path") or "")).resolve(strict=True)
            root = self._dir.resolve(strict=True)
            if root not in (path, *path.parents) or not path.is_file():
                return False
            if path.stat().st_mode & 0o222:
                return False
            return _sha256(path.read_bytes()) == expected_sha256
        except OSError:
            return False


class S3WormSink:
    """Ship each closed day-file to S3 (or compatible) with Object-Lock so it
    cannot be altered/deleted until ``retain_until``. Lazy boto3."""

    def __init__(self, *, bucket: str, prefix: str = "", mode: str = "COMPLIANCE",
                 region: str | None = None, endpoint_url: str | None = None) -> None:
        if not bucket:
            raise WormUnavailable("[audit.worm] provider = s3 requires a bucket")
        self._bucket = bucket
        self._prefix = prefix or ""
        self._mode = (mode or "COMPLIANCE").upper()
        if self._mode not in ("COMPLIANCE", "GOVERNANCE"):
            raise WormUnavailable(
                f"[audit.worm] mode must be COMPLIANCE or GOVERNANCE, got {mode!r}")
        self._region = region
        self._endpoint = endpoint_url
        self._client = None

    def _s3(self):
        if self._client is None:
            try:
                import boto3  # type: ignore
            except ImportError as e:  # pragma: no cover -- needs the extra
                raise WormUnavailable(
                    "S3 WORM export needs boto3 (pip install boto3)") from e
            self._client = boto3.client(
                "s3", region_name=self._region, endpoint_url=self._endpoint)
        return self._client

    def put(self, name: str, data: bytes, *, retain_until: _dt.datetime) -> dict:
        key = f"{self._prefix}{name}"
        resp = self._s3().put_object(
            Bucket=self._bucket, Key=key, Body=data,
            ObjectLockMode=self._mode,
            ObjectLockRetainUntilDate=retain_until,
            ChecksumAlgorithm="SHA256",
        )
        locator = {"target": "s3", "bucket": self._bucket, "key": key,
                   "mode": self._mode, "retain_until": retain_until.isoformat()}
        version_id = resp.get("VersionId") if isinstance(resp, dict) else None
        if version_id:
            locator["version_id"] = version_id
        return locator

    def verify(self, locator: dict, expected_sha256: str) -> bool:
        if locator.get("target") != "s3":
            return False
        bucket = str(locator.get("bucket") or "")
        key = str(locator.get("key") or "")
        if bucket != self._bucket or not key:
            return False
        kwargs = {"Bucket": bucket, "Key": key}
        version_id = locator.get("version_id")
        if version_id:
            kwargs["VersionId"] = str(version_id)
        try:
            obj = self._s3().get_object(**kwargs)
            body = obj.get("Body")
            data = body.read() if hasattr(body, "read") else body
            if not isinstance(data, bytes):
                return False
            return _sha256(data) == expected_sha256
        # failure-policy: fail_closed
        except Exception:
            return False


def build_sink(cfg: dict[str, Any] | None = None):
    """Construct the configured WORM sink, or raise :class:`WormUnavailable`."""
    cfg = cfg if cfg is not None else _worm_cfg()
    provider = str(cfg.get("provider") or "").strip().lower()
    if provider == "local":
        directory = cfg.get("dir") or str(data_dir("audit") / "worm" / "store")
        return LocalWormSink(directory)
    if provider in ("s3", "aws"):
        return S3WormSink(
            bucket=str(cfg.get("bucket") or ""),
            prefix=str(cfg.get("prefix") or ""),
            mode=str(cfg.get("mode") or "COMPLIANCE"),
            region=cfg.get("region"),
            endpoint_url=cfg.get("endpoint_url"),
        )
    raise WormUnavailable(
        "no WORM target configured; set [audit.worm] provider = s3 (or local)")


# --- manifest ---------------------------------------------------------------

def _manifest_path(audit_dir: Path) -> Path:
    return audit_dir / "worm" / _MANIFEST_NAME


def _load_manifest(audit_dir: Path) -> dict[str, dict]:
    """Latest manifest entry per day-file name (the manifest is append-only)."""
    path = _manifest_path(audit_dir)
    latest: dict[str, dict] = {}
    if not path.exists():
        return latest
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            name = rec.get("name")
            if isinstance(name, str):
                latest[name] = rec   # later lines win (append-only history)
    except OSError:  # pragma: no cover
        pass
    return latest



def _locator_verified(
    rec: dict, expected_sha256: str, sink: Any | None = None, audit_dir: Path | None = None
) -> bool:
    locator = rec.get("locator")
    if not isinstance(locator, dict):
        return False
    if sink is not None and hasattr(sink, "verify"):
        try:
            return bool(sink.verify(locator, expected_sha256))
        # failure-policy: fail_closed
        except Exception:
            return False
    target = locator.get("target")
    if target == "local":
        cfg = _worm_cfg()
        directory = None
        if str(cfg.get("provider") or "").strip().lower() == "local":
            directory = cfg.get("dir")
        if directory is None and audit_dir is not None:
            directory = audit_dir / "worm" / "store"
        if directory is None:
            return False
        return LocalWormSink(directory).verify(locator, expected_sha256)
    if target == "s3":
        try:
            cfg = dict(_worm_cfg())
            cfg.update({
                "provider": "s3",
                "bucket": locator.get("bucket"),
                "prefix": "",
                "mode": locator.get("mode") or cfg.get("mode") or "COMPLIANCE",
            })
            sink = build_sink(cfg)
            return bool(sink.verify(locator, expected_sha256))
        # failure-policy: fail_closed
        except Exception:
            return False
    return False

def _append_manifest(audit_dir: Path, rec: dict) -> None:
    path = _manifest_path(audit_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, sort_keys=True) + "\n")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _at_rest_sealing_active() -> bool:
    """True only when at-rest encryption is enabled AND sealing can actually run
    (crypto + key present). When sealing isn't possible (e.g. no key configured,
    as in CI) we can't expect closed day-files to be sealed, so the WORM
    plaintext gate stays inert rather than refusing every push."""
    try:
        from ..crypto_at_rest import at_rest_enabled, seal
        if not at_rest_enabled():
            return False
        seal(b"")  # cheap probe: raises EncryptionUnavailable if key/crypto absent
        return True
    # failure-policy: fail_closed
    except Exception:
        return False


# --- orchestration ----------------------------------------------------------

def push_closed_dayfiles(
    *,
    audit_dir: Path | None = None,
    today: str | None = None,
    sink: Any | None = None,
    retention_days: int | None = None,
    dry_run: bool = False,
) -> dict[str, str]:
    """Ship every closed (date < today), not-yet-shipped day-file to the WORM
    target. Returns a ``{filename: status}`` report. Idempotent: an unchanged,
    already-pushed file is skipped; a changed one is re-pushed (a new locked
    version). The current day-file and the anchor ledger are never shipped."""
    if audit_dir is None:
        audit_dir = data_dir("audit")
    today = today or _utcnow().strftime("%Y-%m-%d")
    cfg = _worm_cfg()
    if retention_days is None:
        try:
            retention_days = int(cfg.get("retention_days") or _DEFAULT_RETENTION_DAYS)
        except (TypeError, ValueError):
            retention_days = _DEFAULT_RETENTION_DAYS

    report: dict[str, str] = {}
    if not audit_dir.exists():
        return report
    closed = [p for p in day_files(audit_dir) if p.stem < today]
    if not closed:
        return report

    manifest = _load_manifest(audit_dir)
    if sink is None and not dry_run:
        sink = build_sink(cfg)   # raises WormUnavailable if unconfigured
    retain_until = _utcnow() + _dt.timedelta(days=retention_days)

    # Never ship PLAINTEXT audit data into an immutable WORM lock. A closed
    # day-file is sealed in-place by `audit seal`; WORM push is a separate
    # command with no enforced ordering, so pushing first would lock plaintext
    # (sensitive action detail) under a multi-year S3 Object-Lock COMPLIANCE
    # retention -- an exposure that can't be deleted and breaks GDPR erasability.
    # Refuse an unsealed file, but only when sealing is actually active (at-rest
    # enabled AND a key present): when sealing can't run (e.g. no key in CI) we
    # can't expect files to be sealed, so the gate stays inert.
    seal_required = _at_rest_sealing_active()
    from ..crypto_at_rest import is_sealed

    for p in closed:
        try:
            data = p.read_bytes()
        except OSError as e:
            report[p.name] = f"error ({e})"
            continue
        if seal_required and not is_sealed(data):
            report[p.name] = (
                "refused: unsealed plaintext -- run `maverick audit seal` before "
                "WORM push (at-rest encryption is on)"
            )
            continue
        digest = _sha256(data)
        prior = manifest.get(p.name)
        if prior and prior.get("sha256") == digest and _locator_verified(prior, digest, sink, audit_dir):
            report[p.name] = "already pushed"
            continue
        changed = prior is not None
        if dry_run:
            report[p.name] = "would re-push (changed)" if changed else "would push"
            continue
        try:
            locator = sink.put(p.name, data, retain_until=retain_until)
        # failure-policy: fail_soft_with_audit
        except Exception as e:  # surface sink failure per-file, keep going
            report[p.name] = f"error ({e})"
            continue
        _append_manifest(audit_dir, {
            "name": p.name, "sha256": digest,
            "pushed_at": _utcnow().isoformat(),
            "retain_until": retain_until.isoformat(),
            "locator": locator,
        })
        report[p.name] = "re-pushed (changed)" if changed else "pushed"
    return report


def verify(*, audit_dir: Path | None = None) -> dict[str, str]:
    """Check every closed local day-file against the WORM manifest. Status per
    file: ``ok`` (current bytes were shipped), ``changed since push`` (local bytes
    differ from the last shipped version -- re-push), or ``NOT pushed``."""
    if audit_dir is None:
        audit_dir = data_dir("audit")
    today = _utcnow().strftime("%Y-%m-%d")
    report: dict[str, str] = {}
    if not audit_dir.exists():
        return report
    manifest = _load_manifest(audit_dir)
    for p in day_files(audit_dir):
        if p.stem >= today:
            continue
        try:
            digest = _sha256(p.read_bytes())
        except OSError as e:
            report[p.name] = f"error ({e})"
            continue
        prior = manifest.get(p.name)
        if prior is None:
            report[p.name] = "NOT pushed"
        elif prior.get("sha256") == digest:
            report[p.name] = "ok" if _locator_verified(prior, digest, audit_dir=audit_dir) else "NOT durably present"
        else:
            report[p.name] = "changed since push"
    return report


__all__ = [
    "WormUnavailable", "LocalWormSink", "S3WormSink", "build_sink",
    "worm_enabled", "push_closed_dayfiles", "verify",
]
