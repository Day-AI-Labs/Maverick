"""Image describers -- turn an uploaded image / process diagram into text the
knowledge layer can index.

A describer is any ``callable(path: str) -> str``. ``build_ocr_describer`` uses
the optional ``vision`` extra (pytesseract + Pillow) to OCR the text out of a
diagram. A richer vision-LLM describer (which captions the image, not just its
text) can be supplied by the caller instead -- the KnowledgeBase only needs the
callable, so the model/dependency choice stays with the operator.
"""
from __future__ import annotations


def build_ocr_describer():
    """An OCR describer (pytesseract + Pillow).

    Needs the ``vision`` extra: ``pip install maverick-knowledge[vision]`` (plus
    the system ``tesseract`` binary). Returns ``callable(path) -> str``."""
    try:
        import pytesseract
        from PIL import Image
    except ModuleNotFoundError as e:
        raise RuntimeError(
            "OCR needs the 'vision' extra: pip install maverick-knowledge[vision]"
        ) from e

    def describe(path: str) -> str:
        text = (pytesseract.image_to_string(Image.open(path)) or "").strip()
        return f"[diagram/image OCR: {path}]\n{text}" if text else ""

    return describe
