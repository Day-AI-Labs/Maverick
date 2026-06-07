"""Extract plain text from uploaded documents, dispatched by extension.

text / markdown / HTML need no extra deps (HTML via stdlib ``html.parser``).
PDF and DOCX use the ``parsers`` extra (pypdf / python-docx), imported lazily so
the package imports clean without them.
"""
from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._skip = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip and data.strip():
            self.parts.append(data.strip())


def _html_to_text(raw: str) -> str:
    p = _TextExtractor()
    p.feed(raw)
    return " ".join(p.parts)


IMAGE_EXTS = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".tif",
})


def is_image(path: str | Path) -> bool:
    """True if ``path`` looks like an image (by extension). Images can't be read
    as UTF-8 -- they need an image_describer (OCR or a vision model) to become
    text, which the KnowledgeBase routes them through."""
    return Path(path).suffix.lower() in IMAGE_EXTS


def extract_text(path: str | Path) -> str:
    """Return the document's text. Raises only when an optional parser extra is
    required (PDF/DOCX) but not installed, or for an image (route via a describer)."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in (".html", ".htm"):
        return _html_to_text(path.read_text(encoding="utf-8", errors="replace"))
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ModuleNotFoundError as e:
            raise RuntimeError(
                "PDF parsing needs the 'parsers' extra: "
                "pip install maverick-knowledge[parsers]"
            ) from e
        reader = PdfReader(str(path))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    if suffix == ".docx":
        try:
            import docx  # python-docx
        except ModuleNotFoundError as e:
            raise RuntimeError(
                "DOCX parsing needs the 'parsers' extra: "
                "pip install maverick-knowledge[parsers]"
            ) from e
        return "\n".join(p.text for p in docx.Document(str(path)).paragraphs)
    if is_image(path):
        raise RuntimeError(
            "images need an image_describer (OCR or a vision model); the "
            "KnowledgeBase routes them there before extract_text"
        )
    # text / markdown / unknown -> read as UTF-8 text.
    return path.read_text(encoding="utf-8", errors="replace")
