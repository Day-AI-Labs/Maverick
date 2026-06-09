"""watermark_detector: hidden-text / steganography scan."""
from __future__ import annotations

from maverick.tools.watermark_detector import watermark_detector


def _scan(text):
    return watermark_detector().fn({"op": "scan", "text": text})


def test_clean_plain_text():
    assert _scan("hello world, perfectly ordinary text.").startswith("CLEAN")


def test_zero_width_detected():
    out = _scan("he​llo")
    assert out.startswith("WATERMARKED") and "zero-width" in out


def test_unicode_tag_steganography_decoded():
    payload = "hi" + "".join(chr(0xE0000 + ord(c)) for c in "SECRET")
    out = _scan(payload)
    assert "unicode-tag" in out and "SECRET" in out


def test_bidi_control_flagged():
    out = _scan("amount = 100‮ drowssap")
    assert "bidi-control" in out


def test_homoglyph_detected():
    out = _scan("pаypal")  # Cyrillic 'а'
    assert "homoglyph" in out


def test_missing_text_errors():
    assert watermark_detector().fn({"op": "scan"}).startswith("ERROR")
