"""OCR tool — extract text from images.

Wraps the local ``tesseract`` binary (preferred — fast, no network)
with an optional fallback to the Hugging Face Inference API for
users who don't want to install a system dep.

ops:
  - extract(path, lang)       — local image (png/jpg/tiff/pdf/...)
  - extract_url(url, lang)    — fetch image first, then OCR

Lang defaults to ``eng``; ``eng+deu`` etc. for multi-language docs.

Requires tesseract on PATH for the default backend; fail-loud with
the install hint when missing. Set ``OCR_BACKEND=hf`` (and the
``HUGGINGFACE_API_TOKEN`` env) to route through the HF
``microsoft/trocr-base-printed`` (or any other HF OCR model) instead.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from . import Tool


def _scrub() -> dict:
    """Child env with secrets stripped (shared tools.scrub_child_env)."""
    from . import scrub_child_env
    return scrub_child_env()
log = logging.getLogger(__name__)


_OCR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "op": {"type": "string", "enum": ["extract", "extract_url"]},
        "path": {"type": "string"},
        "url": {"type": "string"},
        "lang": {"type": "string", "description": "Tesseract lang code (default 'eng')."},
        "backend": {
            "type": "string",
            "enum": ["tesseract", "hf"],
            "description": "Override default backend.",
        },
        "hf_model": {
            "type": "string",
            "description": "HF model id (backend=hf only).",
        },
    },
    "required": ["op"],
}


def _default_backend(explicit: str) -> str:
    if explicit:
        return explicit
    env = (os.environ.get("OCR_BACKEND") or "").strip().lower()
    return env or "tesseract"


def _tesseract_present() -> bool:
    return shutil.which("tesseract") is not None


def _run_tesseract(path: str, lang: str) -> str:
    if not _tesseract_present():
        return (
            "ERROR: tesseract not on PATH. Install (apt: tesseract-ocr; "
            "brew: tesseract) or set OCR_BACKEND=hf."
        )
    try:
        # `-` for stdout, suppress info noise on stderr.
        r = subprocess.run(
            ["tesseract", path, "-", "-l", lang, "--psm", "3"],
            capture_output=True, text=True, timeout=120, env=_scrub(),
        )
    except subprocess.TimeoutExpired:
        return "ERROR: tesseract TIMEOUT"
    if r.returncode != 0:
        return f"ERROR: tesseract ({r.returncode}): {(r.stderr or '').strip()[:300]}"
    text = (r.stdout or "").strip()
    return text if text else "(empty OCR result)"


def _run_hf(path: str, model: str) -> str:
    import httpx
    tok = os.environ.get("HUGGINGFACE_API_TOKEN", "").strip()
    if not tok:
        return "ERROR: backend=hf requires HUGGINGFACE_API_TOKEN."
    try:
        with open(path, "rb") as f:
            blob = f.read()
    except OSError as e:
        return f"ERROR: read {path}: {e}"
    r = httpx.post(
        f"https://api-inference.huggingface.co/models/{model}",
        headers={
            "Authorization": f"Bearer {tok}",
            "Content-Type": "application/octet-stream",
        },
        content=blob, timeout=60.0,
    )
    if r.status_code >= 400:
        return f"ERROR: HF OCR ({r.status_code}): {r.text[:300]}"
    try:
        data = r.json()
    except ValueError:
        return r.text[:3000]
    # TrOCR-style: list[{generated_text}]; some models return dicts.
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data[0].get("generated_text", str(data[0]))[:3000]
    if isinstance(data, dict):
        return data.get("generated_text", str(data))[:3000]
    return str(data)[:3000]


def _op_extract(path: str, lang: str, backend: str, hf_model: str) -> str:
    if not path:
        return "ERROR: extract requires path"
    workdir = Path.cwd().resolve()
    candidate = Path(path)
    candidate = (workdir / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
    try:
        candidate.relative_to(workdir)
    except ValueError:
        return f"ERROR: path escapes workspace: {path}"
    if not candidate.exists():
        return f"ERROR: file not found: {path}"
    if backend == "hf":
        return _run_hf(str(candidate), hf_model or "microsoft/trocr-base-printed")
    return _run_tesseract(str(candidate), lang or "eng")


def _op_extract_url(url: str, lang: str, backend: str, hf_model: str) -> str:
    if not url:
        return "ERROR: extract_url requires url"
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return f"ERROR: invalid URL: {url!r}"
    from ._ssrf import BlockedHost, safe_get
    try:
        # Pins the connection to the validated public IP (no rebinding window).
        r = safe_get(url, timeout=30.0)
    except BlockedHost as e:
        return (
            f"ERROR: refusing to fetch {parsed.hostname!r}: {e}. "
            "Set MAVERICK_FETCH_ALLOW_PRIVATE=1 to override."
        )
    except Exception as e:
        return f"ERROR: fetch failed: {type(e).__name__}: {e}"
    if r.status_code >= 400:
        return f"ERROR: image fetch {r.status_code}: {url}"
    # Pick a sensible extension from content-type for tesseract.
    ct = r.headers.get("content-type", "").split(";")[0].strip().lower()
    ext = {
        "image/png": ".png", "image/jpeg": ".jpg",
        "image/jpg": ".jpg", "image/tiff": ".tiff",
        "image/webp": ".webp", "application/pdf": ".pdf",
    }.get(ct, ".png")
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False, dir=Path.cwd()) as f:
        f.write(r.content)
        tmp = f.name
    try:
        return _op_extract(tmp, lang, backend, hf_model)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _run(args: dict[str, Any]) -> str:
    op = args.get("op")
    if not op:
        return "ERROR: op is required"
    backend = _default_backend((args.get("backend") or "").strip().lower())
    if backend not in ("tesseract", "hf"):
        backend = "tesseract"
    if backend == "hf":
        try:
            import httpx  # noqa: F401
        except ImportError:
            return "ERROR: httpx not installed (backend=hf). Run: pip install 'maverick-agent[issue-trackers]'"
    lang = (args.get("lang") or "eng").strip()
    hf_model = (args.get("hf_model") or "").strip()
    try:
        if op == "extract":
            return _op_extract(
                (args.get("path") or "").strip(), lang, backend, hf_model,
            )
        if op == "extract_url":
            return _op_extract_url(
                (args.get("url") or "").strip(), lang, backend, hf_model,
            )
    except Exception as e:
        return f"ERROR: ocr failed: {type(e).__name__}: {e}"
    return f"ERROR: unknown op {op!r}"


def ocr() -> Tool:
    return Tool(
        name="ocr",
        description=(
            "Extract text from images. ops: extract (local path), "
            "extract_url (remote image). backend = tesseract "
            "(default; requires binary on PATH) | hf "
            "(HUGGINGFACE_API_TOKEN, default model "
            "microsoft/trocr-base-printed). lang accepts "
            "tesseract codes like 'eng' / 'eng+deu'."
        ),
        input_schema=_OCR_SCHEMA,
        fn=_run,
    )
