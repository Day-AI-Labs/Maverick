"""Attachment storage for goal inputs (files + images).

Stores bytes under ``~/.maverick/attachments/<goal_id>/<sha256>`` and
records the metadata in the world model. Enforces:
  - max per-file size (default 25 MiB, env-configurable)
  - max total per-goal size (default 100 MiB)
  - mime-type allowlist (text + image families by default)

The agent has a ``list_attachments`` tool that returns the on-disk paths
so the existing ``read_file`` tool can pick them up. Images are also
delivered to the orchestrator as Anthropic vision content blocks (see
``content_blocks_for_goal``) so the agent can SEE them, not just read
their bytes.

**S3-backed attachments** (opt-in): with ``[attachments] s3_bucket`` (or
``MAVERICK_ATTACH_S3_BUCKET``) set, every stored attachment is also mirrored
to ``s3://<bucket>/<prefix><goal_id>/<name>`` — the durable/shared copy for
multi-host deployments — and :func:`s3_fetch` pulls a missing attachment back
down on a worker that doesn't have the local file. Local disk remains the
source the tools read; the mirror is best-effort fail-open (an S3 outage
must never reject an upload). Uses boto3 (the ``[s3]`` extra), imported
lazily; works against any S3-compatible endpoint via ``AWS_ENDPOINT_URL``.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from .paths import data_dir

log = logging.getLogger(__name__)

DEFAULT_ROOT = data_dir("attachments")

# 25 MiB per file, 100 MiB per goal. Tunable via env so a VPS deployment
# can raise the cap without a code change.
def _env_int(name: str, default: int) -> int:
    # A non-numeric value used to raise ValueError at import time, killing the
    # attachment path with an opaque traceback instead of using the default.
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


MAX_FILE_BYTES = _env_int("MAVERICK_ATTACH_MAX_FILE_BYTES", 25 * 1024 * 1024)
MAX_GOAL_BYTES = _env_int("MAVERICK_ATTACH_MAX_GOAL_BYTES", 100 * 1024 * 1024)

# Mime allowlist. Text + image families. PDF allowed (anthropic vision
# supports it directly). Active deny for executables and archives.
ALLOWED_MIME_PREFIXES = (
    "text/",
    "image/",
    "application/pdf",
    "application/json",
    "application/xml",
    "application/x-yaml",
)
ALLOWED_IMAGE_MIMES = frozenset({
    "image/jpeg", "image/png", "image/gif", "image/webp",
})


class AttachmentRejected(ValueError):
    """Raised when an attachment violates a size / type / quota rule."""


@dataclass(frozen=True)
class Stored:
    filename: str
    mime: str
    size_bytes: int
    sha256: str
    path: Path


def _root_for_goal(goal_id: int, root: Path | None = None) -> Path:
    base = root or DEFAULT_ROOT
    return base / str(goal_id)


# ---- S3 mirror (opt-in) -----------------------------------------------------

def _s3_settings() -> tuple[str, str]:
    """(bucket, key_prefix); bucket == "" when the mirror is off."""
    bucket = os.environ.get("MAVERICK_ATTACH_S3_BUCKET", "").strip()
    prefix = os.environ.get("MAVERICK_ATTACH_S3_PREFIX", "").strip()
    if not bucket:
        try:
            from .config import load_config
            cfg = (load_config() or {}).get("attachments") or {}
            bucket = str(cfg.get("s3_bucket") or "").strip()
            prefix = prefix or str(cfg.get("s3_prefix") or "").strip()
        except Exception:  # pragma: no cover -- config never blocks an upload
            pass
    if prefix and not prefix.endswith("/"):
        prefix += "/"
    return bucket, prefix


def s3_mirror_enabled() -> bool:
    return bool(_s3_settings()[0])


def _s3_client():
    import boto3  # the [s3] extra; lazy so the default path never imports it
    kwargs = {}
    endpoint = os.environ.get("AWS_ENDPOINT_URL", "").strip()
    if endpoint:
        kwargs["endpoint_url"] = endpoint
    region = os.environ.get("AWS_REGION", "").strip()
    if region:
        kwargs["region_name"] = region
    return boto3.client("s3", **kwargs)


def _s3_key(goal_id: int, name: str) -> str:
    bucket, prefix = _s3_settings()
    assert bucket
    return f"{prefix}{goal_id}/{name}"


def _s3_mirror(goal_id: int, dest: Path, mime: str) -> None:
    """Best-effort upload of a stored attachment. Never raises."""
    try:
        client = _s3_client()
        bucket, _ = _s3_settings()
        client.put_object(
            Bucket=bucket,
            Key=_s3_key(goal_id, dest.name),
            Body=dest.read_bytes(),
            ContentType=mime or "application/octet-stream",
        )
    except Exception as e:  # noqa: BLE001 -- mirror is fail-open by design
        log.warning("attachment S3 mirror failed (local copy kept): %s", e)


def _validate_attachment_name(name: str) -> None:
    """Reject names that cannot be stored under one goal attachment dir."""
    windows_name = PureWindowsPath(name)
    if (
        not name
        or name.startswith(".")
        or "/" in name
        or "\\" in name
        or Path(name).is_absolute()
        or windows_name.is_absolute()
        or windows_name.drive
    ):
        raise AttachmentRejected(f"invalid attachment name: {name!r}")
    if any(ord(c) < 0x20 or ord(c) == 0x7f for c in name):
        raise AttachmentRejected(f"control character in attachment name: {name!r}")


def s3_fetch(goal_id: int, name: str, *, root: Path | None = None) -> Path | None:
    """Pull one mirrored attachment down to the local store.

    For a worker host that doesn't have the local file (the uploader ran
    elsewhere). ``name`` is the on-disk name (``<sha16>-<filename>``). Returns
    the local path, or None when the mirror is off / the object is missing.
    """
    if not s3_mirror_enabled():
        return None
    _validate_attachment_name(name)
    dest_dir = _root_for_goal(goal_id, root)
    dest = dest_dir / name
    if dest.exists():
        return dest
    try:
        client = _s3_client()
        bucket, _ = _s3_settings()
        obj = client.get_object(Bucket=bucket, Key=_s3_key(goal_id, name))
        content_length = obj.get("ContentLength")
        if content_length is not None and int(content_length) > MAX_FILE_BYTES:
            raise AttachmentRejected(
                f"file too large: {content_length} bytes (limit {MAX_FILE_BYTES})"
            )
        data = obj["Body"].read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            raise AttachmentRejected(
                f"file too large: {len(data)} bytes (limit {MAX_FILE_BYTES})"
            )
    except AttachmentRejected:
        raise
    except Exception as e:  # noqa: BLE001 -- absent object / S3 down -> None
        log.warning("attachment S3 fetch failed: %s", e)
        return None
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(dest_dir, 0o700)
    except OSError:
        pass
    dest.write_bytes(data)
    try:
        os.chmod(dest, 0o600)
    except OSError:
        pass
    return dest


def store(
    goal_id: int,
    filename: str,
    mime: str,
    data: bytes,
    *,
    existing_total: int = 0,
    root: Path | None = None,
) -> Stored:
    """Validate + persist a single attachment. Returns the on-disk record.

    ``existing_total`` is the sum of ``size_bytes`` for prior attachments
    on this goal; the caller passes it in so the per-goal cap is enforced
    even when uploads arrive across requests.
    """
    if not filename:
        raise AttachmentRejected("filename is required")
    if "/" in filename or "\\" in filename or filename.startswith("."):
        raise AttachmentRejected(f"invalid filename: {filename!r}")
    if any(ord(c) < 0x20 or ord(c) == 0x7f for c in filename):
        # A null byte truncates the path at the C layer in downstream
        # consumers; other control chars enable log/terminal injection.
        # Real filenames never contain them.
        raise AttachmentRejected(f"control character in filename: {filename!r}")
    if not mime:
        raise AttachmentRejected("mime type is required")
    if not any(mime.startswith(p) for p in ALLOWED_MIME_PREFIXES):
        raise AttachmentRejected(f"mime type not allowed: {mime}")

    size = len(data)
    if size == 0:
        raise AttachmentRejected("empty file")
    if size > MAX_FILE_BYTES:
        raise AttachmentRejected(
            f"file too large: {size} bytes (limit {MAX_FILE_BYTES})"
        )
    if existing_total + size > MAX_GOAL_BYTES:
        raise AttachmentRejected(
            f"per-goal attachment quota exceeded: "
            f"{existing_total + size} > {MAX_GOAL_BYTES}"
        )

    sha256 = hashlib.sha256(data).hexdigest()
    dest_dir = _root_for_goal(goal_id, root)
    dest_dir.mkdir(parents=True, exist_ok=True)
    # Attachment bytes can be private (uploaded docs, screenshots). The
    # default umask often leaves them world-readable on a shared host, so
    # lock the goal dir + file to the owner.
    try:
        os.chmod(dest_dir, 0o700)
    except OSError:
        pass
    # SHA-prefix the on-disk name so two attachments with the same
    # filename don't collide and so a re-upload of the same bytes is a
    # no-op (idempotent).
    safe_name = filename.replace("/", "_").replace("\\", "_")
    dest = dest_dir / f"{sha256[:16]}-{safe_name}"
    if not dest.exists():
        dest.write_bytes(data)
        try:
            os.chmod(dest, 0o600)
        except OSError:
            pass
        if s3_mirror_enabled():
            _s3_mirror(goal_id, dest, mime)

    return Stored(
        filename=filename,
        mime=mime,
        size_bytes=size,
        sha256=sha256,
        path=dest,
    )


def content_blocks_for_goal(world, goal_id: int) -> list[dict]:
    """Build Anthropic content blocks for image attachments on a goal.

    Text/PDF attachments are NOT auto-embedded -- the agent uses
    `list_attachments` + `read_file` for those (so token usage is opt-in).
    Images, however, need to be sent as vision blocks for the agent to
    see them, so we embed every accepted image at run-time.
    """
    blocks: list[dict] = []
    for a in world.list_attachments(goal_id):
        if a.mime not in ALLOWED_IMAGE_MIMES:
            continue
        try:
            b = Path(a.path).read_bytes()
        except OSError:
            continue
        blocks.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": a.mime,
                "data": base64.b64encode(b).decode("ascii"),
            },
        })
    return blocks
