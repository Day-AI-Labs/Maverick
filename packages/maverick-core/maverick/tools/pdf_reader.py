"""PDF reader tool.

Extracts text from PDFs with page-range slicing. Tries pdfplumber
first (better table handling), falls back to pypdf. Both are in the
``[pdf]`` optional extra.

Reads from local paths or http(s) URLs.
"""
from __future__ import annotations

import io
import logging
import os
from pathlib import Path
from typing import Any

from . import Tool

log = logging.getLogger(__name__)


_PDF_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "source": {
            "type": "string",
            "description": "Local file path or http(s) URL.",
        },
        "pages": {
            "type": "string",
            "description": "Page range (e.g. '1-5', '3', '10-'); 1-indexed. Default: all.",
        },
        "include_tables": {
            "type": "boolean",
            "description": "Try to extract tables as markdown (pdfplumber path).",
        },
        "max_chars": {
            "type": "integer",
            "description": "Truncate output (default 100_000).",
        },
    },
    "required": ["source"],
}


def _parse_pages(spec: str, total: int) -> list[int]:
    """Parse '1-5', '3', '10-' into a list of 0-indexed page indices."""
    spec = (spec or "").strip()
    if not spec:
        return list(range(total))
    out: set[int] = set()
    try:
        for chunk in spec.split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            if "-" in chunk:
                a, _, b = chunk.partition("-")
                # Clamp both ends to [1, total] BEFORE building the range so a
                # spec like '1-99999999' can't construct a ~10^8-element loop.
                start = max(1, int(a)) if a else 1
                end = min(total, int(b)) if b else total
                for n in range(start, end + 1):
                    out.add(n - 1)
            else:
                n = int(chunk)
                if 1 <= n <= total:
                    out.add(n - 1)
    except ValueError:
        # Non-numeric spec (e.g. 'a-b'): fall back to all pages rather than
        # letting ValueError escape the tool.
        return list(range(total))
    return sorted(out)


def _load_bytes(source: str) -> bytes | None:
    """Get PDF bytes from a workspace-local path or safe URL."""
    if source.startswith(("http://", "https://")):
        try:
            import httpx  # noqa: F401  (presence check; safe_get imports it)
        except ImportError:
            return None
        from ._ssrf import BlockedHost, safe_client
        # Combine both defenses: safe_client pins the connection to the
        # validated public IP (SSRF / DNS-rebinding), AND we stream with a
        # hard byte ceiling so a model-supplied URL can't exhaust memory with
        # a multi-GB / endless body.
        _MAX = 100 * 1024 * 1024  # 100 MiB
        try:
            with safe_client(source, timeout=30.0) as client:
                with client.stream("GET", source) as resp:
                    resp.raise_for_status()
                    clen = resp.headers.get("content-length")
                    if clen is not None and clen.isdigit() and int(clen) > _MAX:
                        log.warning("pdf fetch refused: %s bytes > cap", clen)
                        return None
                    buf = bytearray()
                    for chunk in resp.iter_bytes():
                        buf += chunk
                        if len(buf) > _MAX:
                            log.warning("pdf fetch refused: body exceeded cap")
                            return None
                    return bytes(buf)
        except BlockedHost as e:
            log.warning("pdf fetch refused: %s", e)
            return None
        except Exception as e:
            log.warning("pdf fetch failed: %s", e)
            return None

    workdir = Path.cwd().resolve()
    p = Path(os.path.expanduser(source))
    if not p.is_absolute():
        p = (workdir / p).resolve()
    else:
        p = p.resolve()
    try:
        p.relative_to(workdir)
    except ValueError:
        return None
    if not p.exists() or not p.is_file():
        return None
    return p.read_bytes()


def _extract_with_pdfplumber(data: bytes, pages: str | None, include_tables: bool) -> str | None:
    try:
        import pdfplumber  # type: ignore
    except ImportError:
        return None
    out: list[str] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        total = len(pdf.pages)
        page_indices = _parse_pages(pages or "", total)
        for idx in page_indices:
            page = pdf.pages[idx]
            text = (page.extract_text() or "").strip()
            block = f"=== Page {idx + 1} of {total} ===\n{text}"
            if include_tables:
                tables = page.extract_tables() or []
                for ti, table in enumerate(tables, 1):
                    if not table:
                        continue
                    md = _table_to_markdown(table)
                    block += f"\n\n[Table {ti}]\n{md}"
            out.append(block)
    return "\n\n".join(out)


def _extract_with_pypdf(data: bytes, pages: str | None) -> str | None:
    try:
        import pypdf  # type: ignore
    except ImportError:
        try:
            import PyPDF2 as pypdf  # type: ignore
        except ImportError:
            return None
    reader = pypdf.PdfReader(io.BytesIO(data))
    total = len(reader.pages)
    page_indices = _parse_pages(pages or "", total)
    out: list[str] = []
    for idx in page_indices:
        text = (reader.pages[idx].extract_text() or "").strip()
        out.append(f"=== Page {idx + 1} of {total} ===\n{text}")
    return "\n\n".join(out)


def _table_to_markdown(rows: list[list]) -> str:
    if not rows:
        return ""
    header = rows[0]
    body = rows[1:]
    md = "| " + " | ".join(str(c or "") for c in header) + " |\n"
    md += "|" + "|".join("---" for _ in header) + "|\n"
    for r in body:
        md += "| " + " | ".join(str(c or "") for c in r) + " |\n"
    return md


def extract_text_from_bytes(data: bytes, *, pages: str = "",
                            include_tables: bool = False) -> str | None:
    """Extract text from PDF bytes (pdfplumber, pypdf fallback).

    Also the **parser-isolation child entry** (``parser_isolation.PARSERS
    ["pdf_text"]``): with ``[security] isolate_parsers`` on, hostile PDF bytes
    are parsed in a scrubbed child process so a memory-safety bug in the
    C-backed parsers can't touch the kernel. Returns None when no parser
    extra is installed.
    """
    text = _extract_with_pdfplumber(data, pages, include_tables)
    if text is None:
        text = _extract_with_pypdf(data, pages)
    return text


def _run_read_pdf(args: dict[str, Any]) -> str:
    source = (args.get("source") or "").strip()
    if not source:
        return "ERROR: source is required"
    pages = args.get("pages") or ""
    include_tables = bool(args.get("include_tables"))
    max_chars = int(args.get("max_chars") or 100_000)

    data = _load_bytes(source)
    if data is None:
        return f"ERROR: could not read PDF from {source!r}"

    from ..parser_isolation import parse_isolated, should_isolate
    text = None
    if should_isolate():
        try:
            text = parse_isolated("pdf_text", data, pages=pages,
                                  include_tables=include_tables)
        except (RuntimeError, ValueError) as e:
            # the child died on hostile bytes / timed out: refuse rather than
            # re-parsing the same bytes in-process (that defeats the isolation)
            return f"ERROR: isolated PDF parse failed: {e}"
    else:
        text = extract_text_from_bytes(data, pages=pages,
                                       include_tables=include_tables)
    if text is None:
        return (
            "ERROR: no PDF parser available. Run: "
            "pip install 'maverick-agent[pdf]'"
        )

    if len(text) > max_chars:
        text = text[:max_chars] + f"\n\n[... truncated at {max_chars} chars]"
    return text


def read_pdf() -> Tool:
    """Factory: builds the read_pdf tool."""
    return Tool(
        name="read_pdf",
        description=(
            "Read text from a PDF (local path or http(s) URL). Supports "
            "pages='1-5,8,10-' for ranges, include_tables=true to extract "
            "tables as markdown. Tries pdfplumber first, falls back to "
            "pypdf. Install with: pip install 'maverick-agent[pdf]'."
        ),
        input_schema=_PDF_INPUT_SCHEMA,
        fn=_run_read_pdf,
    )
