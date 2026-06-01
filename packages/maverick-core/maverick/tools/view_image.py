"""Image-understanding tool.

Sends an image to a vision-capable model and returns the description /
analysis. The tool itself is provider-agnostic: it picks the agent's
current LLM (or a configured override) and dispatches with a structured
image block.

Supports local file paths and http(s) URLs (which are passed through to
the provider where possible; otherwise downloaded and base64-encoded).
"""
from __future__ import annotations

import base64
import logging
import os
from pathlib import Path
from typing import Any

from . import Tool

log = logging.getLogger(__name__)


_VIEW_IMAGE_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "source": {
            "type": "string",
            "description": "Local image file path or http(s) URL (PNG/JPG/WebP/GIF).",
        },
        "prompt": {
            "type": "string",
            "description": "What to look for in the image. Default: 'Describe this image in detail.'",
        },
        "model": {
            "type": "string",
            "description": "Override vision model (provider:model). Defaults to MAVERICK_VISION_MODEL env or anthropic:claude-sonnet-4-6.",
        },
    },
    "required": ["source"],
}


_MIME_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}


def _guess_mime(source: str) -> str:
    ext = os.path.splitext(source)[1].lower()
    return _MIME_BY_EXT.get(ext, "image/jpeg")


def _load_image(source: str) -> tuple[bytes, str] | None:
    """Return (image_bytes, mime_type) for the source, or None on failure."""
    if source.startswith(("http://", "https://")):
        try:
            import httpx  # noqa: F401  (presence check; safe_get imports it)
        except ImportError:
            return None
        from ._ssrf import BlockedHost, safe_get
        try:
            # Pins the connection to the validated public IP (no rebinding).
            resp = safe_get(source, timeout=30.0)
            resp.raise_for_status()
            # Cap the in-memory body (then base64-encoded for the vision model):
            # a model-supplied URL to a multi-GB resource is an unbounded blowup.
            if len(resp.content) > 20 * 1024 * 1024:
                log.warning("image fetch refused: %d bytes > 20 MiB cap", len(resp.content))
                return None
            mime = (resp.headers.get("content-type") or _guess_mime(source)).split(";")[0].strip()
            return resp.content, mime
        except BlockedHost as e:
            log.warning("image fetch refused: %s", e)
            return None
        except Exception as e:
            log.warning("image fetch failed: %s", e)
            return None
    workdir = Path.cwd().resolve()
    path = Path(os.path.expanduser(source))
    if not path.is_absolute():
        path = (workdir / path).resolve()
    else:
        path = path.resolve()
    try:
        path.relative_to(workdir)
    except ValueError:
        return None
    if not path.exists() or not path.is_file():
        return None
    return path.read_bytes(), _guess_mime(source)


def _run_view_image(args: dict[str, Any]) -> str:
    source = (args.get("source") or "").strip()
    if not source:
        return "ERROR: source is required"
    prompt = (args.get("prompt") or "Describe this image in detail.").strip()
    model = (
        args.get("model")
        or os.environ.get("MAVERICK_VISION_MODEL")
        or "anthropic:claude-sonnet-4-6"
    )

    loaded = _load_image(source)
    if loaded is None:
        return f"ERROR: could not load image from {source!r}"
    image_bytes, mime = loaded

    # Anthropic format -- providers' adapters translate to OpenAI / Gemini
    # vision schemas in their `complete()` methods.
    image_block: dict[str, Any] = {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": mime,
            "data": base64.b64encode(image_bytes).decode("ascii"),
        },
    }
    messages = [{
        "role": "user",
        "content": [image_block, {"type": "text", "text": prompt}],
    }]

    try:
        from ..llm import LLM
    except ImportError as e:
        return f"ERROR: maverick.llm unavailable: {e}"

    try:
        llm = LLM(model=model)
        resp = llm.complete(
            system="You analyze images carefully and concisely.",
            messages=messages,
            max_tokens=1024,
        )
        return (resp.text or "").strip() or "(no description returned)"
    except Exception as e:
        return f"ERROR: vision call failed: {type(e).__name__}: {e}"


def view_image() -> Tool:
    """Factory: builds the view_image tool."""
    return Tool(
        name="view_image",
        description=(
            "Look at an image (local path or http(s) URL) and describe / "
            "analyze it. Provide a `prompt` to focus the analysis (e.g. "
            "'What's the error message?'). Picks the configured vision "
            "model automatically; override via `model` arg or "
            "MAVERICK_VISION_MODEL env var."
        ),
        input_schema=_VIEW_IMAGE_INPUT_SCHEMA,
        fn=_run_view_image,
    )
