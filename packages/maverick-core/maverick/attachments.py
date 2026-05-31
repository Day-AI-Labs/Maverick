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
"""
from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_ROOT = Path.home() / ".maverick" / "attachments"

# 25 MiB per file, 100 MiB per goal. Tunable via env so a VPS deployment
# can raise the cap without a code change.
MAX_FILE_BYTES = int(os.environ.get("MAVERICK_ATTACH_MAX_FILE_BYTES", 25 * 1024 * 1024))
MAX_GOAL_BYTES = int(os.environ.get("MAVERICK_ATTACH_MAX_GOAL_BYTES", 100 * 1024 * 1024))

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
    # SHA-prefix the on-disk name so two attachments with the same
    # filename don't collide and so a re-upload of the same bytes is a
    # no-op (idempotent).
    safe_name = filename.replace("/", "_").replace("\\", "_")
    dest = dest_dir / f"{sha256[:16]}-{safe_name}"
    if not dest.exists():
        dest.write_bytes(data)

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
