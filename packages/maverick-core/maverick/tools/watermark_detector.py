"""Watermark / hidden-text detector (roadmap: 2027 H1 safety — "watermark detector").

Scan text for invisible or deceptive watermarking: zero-width characters,
Unicode tag-block steganography (U+E0000..U+E007F), bidi controls, and
homoglyph substitution (Latin look-alikes from Cyrillic/Greek). Deterministic
and offline — no model. The agent calls this before trusting pasted content or
before publishing its own output, so a hidden channel can't smuggle data past
the shield.

ops:
  - scan(text)  — report each finding with its codepoints and a count.
"""
from __future__ import annotations

import unicodedata
from typing import Any

from . import Tool

# Zero-width + invisible formatting characters that carry no glyph.
_ZERO_WIDTH = {
    0x200B: "ZERO WIDTH SPACE",
    0x200C: "ZERO WIDTH NON-JOINER",
    0x200D: "ZERO WIDTH JOINER",
    0x2060: "WORD JOINER",
    0xFEFF: "ZERO WIDTH NO-BREAK SPACE (BOM)",
    0x00AD: "SOFT HYPHEN",
}
# Bidirectional overrides — used to visually reorder text (Trojan Source).
_BIDI = {
    0x202A, 0x202B, 0x202C, 0x202D, 0x202E,
    0x2066, 0x2067, 0x2068, 0x2069,
}
# A few common homoglyphs: confusable -> the ASCII letter it imitates.
_HOMOGLYPHS = {
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O",
    "Р": "P", "С": "C", "Т": "T", "Х": "X", "а": "a", "е": "e", "о": "o",
    "р": "p", "с": "c", "х": "x", "Α": "A", "Β": "B", "Ε": "E", "Ο": "O",
}


def _scan(text: str) -> str:
    findings: list[str] = []

    zw = [(i, ch) for i, ch in enumerate(text) if ord(ch) in _ZERO_WIDTH]
    if zw:
        names = sorted({_ZERO_WIDTH[ord(ch)] for _, ch in zw})
        findings.append(f"zero-width: {len(zw)} char(s) [{', '.join(names)}]")

    tags = [ch for ch in text if 0xE0000 <= ord(ch) <= 0xE007F]
    if tags:
        # The tag block mirrors ASCII; decode the smuggled payload.
        decoded = "".join(chr(ord(ch) - 0xE0000) for ch in tags if 0xE0020 <= ord(ch) <= 0xE007E)
        findings.append(f"unicode-tag steganography: {len(tags)} char(s); decoded={decoded!r}")

    bidi = [ch for ch in text if ord(ch) in _BIDI]
    if bidi:
        findings.append(f"bidi-control: {len(bidi)} char(s) (possible Trojan-Source reorder)")

    homo = sorted({ch for ch in text if ch in _HOMOGLYPHS})
    if homo:
        pairs = ", ".join(f"{c!r}->{_HOMOGLYPHS[c]!r}" for c in homo)
        findings.append(f"homoglyph: {len(homo)} distinct confusable(s) [{pairs}]")

    other_invis = [
        ch for ch in text
        if unicodedata.category(ch) == "Cf"
        and ord(ch) not in _ZERO_WIDTH
        and ord(ch) not in _BIDI
        and not (0xE0000 <= ord(ch) <= 0xE007F)
    ]
    if other_invis:
        findings.append(f"other-format-control: {len(other_invis)} char(s)")

    if not findings:
        return "CLEAN: no watermark or hidden-text markers found"
    return "WATERMARKED:\n- " + "\n- ".join(findings)


def _run(args: dict[str, Any]) -> str:
    if args.get("op") not in (None, "scan"):
        return f"ERROR: unknown op {args.get('op')!r}"
    text = args.get("text")
    if not isinstance(text, str) or not text:
        return "ERROR: text is required"
    return _scan(text)


_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "op": {"type": "string", "enum": ["scan"]},
        "text": {"type": "string", "description": "Text to scan for hidden watermarks"},
    },
    "required": ["text"],
}


def watermark_detector() -> Tool:
    return Tool(
        name="watermark_detector",
        description=(
            "Scan text for invisible/deceptive watermarking: zero-width chars, "
            "Unicode tag-block steganography (decodes the payload), bidi "
            "controls (Trojan Source), and homoglyph substitution. op=scan with "
            "'text'. Returns CLEAN or WATERMARKED with per-finding detail. "
            "Deterministic, offline, no model."
        ),
        input_schema=_SCHEMA,
        fn=_run,
        parallel_safe=True,
    )
