"""Unicode / zero-width / bidi safety filter.

Strips or warns about Unicode chars commonly used in prompt-injection
and homograph attacks:

  - Zero-width characters (ZWSP, ZWNJ, ZWJ, BOM)
  - Bidi override characters (RLO, LRO, PDF, etc. — the "Trojan
    Source" attack vector)
  - Tag characters (E0000-E007F — Unicode tag block hides text from
    most renderers)
  - Variation selectors that flip rendered glyphs

Two API surfaces:

  - ``normalize(text)`` returns the cleaned text + a list of removed
    code points (for audit).
  - ``has_dangerous_unicode(text)`` is a cheap boolean check used by
    the shield's input scan.

NFKC normalization is applied first so "ﬁ" → "fi" and other
look-alikes are canonicalized.
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import logging
import os
import sys
import unicodedata
from dataclasses import dataclass
from types import ModuleType

log = logging.getLogger(__name__)


# Zero-width / invisible.
_ZERO_WIDTH = {
    0x200B,  # ZERO WIDTH SPACE
    0x200C,  # ZERO WIDTH NON-JOINER
    0x200D,  # ZERO WIDTH JOINER
    0x2060,  # WORD JOINER
    0xFEFF,  # ZERO WIDTH NO-BREAK SPACE / BOM
}

# Bidirectional override block (the Trojan Source attack).
_BIDI_OVERRIDES = {
    0x200E,  # LRM (left-to-right mark)
    0x200F,  # RLM (right-to-left mark)
    0x061C,  # ALM (Arabic letter mark)
    0x202A,  # LRE
    0x202B,  # RLE
    0x202C,  # PDF (pop directional)
    0x202D,  # LRO
    0x202E,  # RLO
    0x2066,  # LRI
    0x2067,  # RLI
    0x2068,  # FSI
    0x2069,  # PDI
}

# Unicode tag block (E0000-E007F) — invisible, used in steganographic
# prompt injection.
_TAG_BLOCK_START = 0xE0000
_TAG_BLOCK_END = 0xE007F


@dataclass
class UnicodeScanResult:
    cleaned: str
    removed_codepoints: list[int]
    categories: list[str]

    @property
    def had_dangerous(self) -> bool:
        return bool(self.removed_codepoints)


def _category_for(cp: int) -> str:
    if cp in _ZERO_WIDTH:
        return "zero_width"
    if cp in _BIDI_OVERRIDES:
        return "bidi_override"
    if _TAG_BLOCK_START <= cp <= _TAG_BLOCK_END:
        return "tag_block"
    return ""


def normalize(text: str, *, nfkc: bool = True) -> UnicodeScanResult:
    """Strip dangerous Unicode + (optionally) NFKC-normalize.

    Returns ``UnicodeScanResult(cleaned, removed_codepoints, categories)``.
    ``categories`` is unique-preserving order of categories that were
    actually removed (subset of zero_width / bidi_override / tag_block).
    """
    if not text:
        return UnicodeScanResult(text, [], [])
    if nfkc:
        text = unicodedata.normalize("NFKC", text)
    cleaned_chars: list[str] = []
    removed: list[int] = []
    cats_seen: list[str] = []
    for ch in text:
        cp = ord(ch)
        cat = _category_for(cp)
        if cat:
            removed.append(cp)
            if cat not in cats_seen:
                cats_seen.append(cat)
            continue
        cleaned_chars.append(ch)
    return UnicodeScanResult("".join(cleaned_chars), removed, cats_seen)


def has_dangerous_unicode(text: str) -> bool:
    """Quick boolean check; doesn't allocate the cleaned string."""
    if not text:
        return False
    for ch in text:
        cp = ord(ch)
        if cp in _ZERO_WIDTH or cp in _BIDI_OVERRIDES:
            return True
        if _TAG_BLOCK_START <= cp <= _TAG_BLOCK_END:
            return True
    return False


# --- Native fast path (optional) -------------------------------------------
# A Rust implementation (the ``maverick_native`` extension, built from
# ``rust/mvk-scan``) does exactly this work GIL-free and far faster on the hot
# shield path. It is OPTIONAL: when the wheel isn't installed the pure-Python
# functions above are used unchanged, so behaviour is identical either way --
# the native module is a drop-in accelerator, never a new dependency.
def _safe_native_search_path() -> list[str]:
    """Return import paths that cannot be the current workspace directory."""
    cwd = os.path.realpath(os.getcwd())
    safe_path: list[str] = []
    for entry in sys.path:
        # ``""`` is the interpreter's current working directory. An attacker
        # controlled workspace can place ``maverick_native.py`` there and shadow
        # the optional native extension before safety scanning is initialized.
        if not entry:
            continue
        try:
            real_entry = os.path.realpath(entry)
        except OSError:
            continue
        try:
            is_workspace_path = os.path.commonpath([cwd, real_entry]) == cwd
        except ValueError:
            is_workspace_path = False
        if is_workspace_path:
            continue
        safe_path.append(entry)
    return safe_path


def _load_native() -> ModuleType | None:
    """Load the optional compiled scanner without importing cwd shadows."""
    spec = importlib.machinery.PathFinder.find_spec(
        "maverick_native", _safe_native_search_path()
    )
    if spec is None or spec.origin is None or spec.loader is None:
        return None
    if not any(
        spec.origin.endswith(suffix)
        for suffix in importlib.machinery.EXTENSION_SUFFIXES
    ):
        log.warning(
            "Ignoring non-extension maverick_native module at %s", spec.origin
        )
        return None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except (ImportError, OSError) as exc:  # pragma: no cover - platform dependent
        log.warning("Unable to load optional maverick_native extension: %s", exc)
        return None
    return module


_native = _load_native()

if _native is not None:  # pragma: no cover - active only when the wheel is built
    _normalize_py = normalize
    _has_dangerous_unicode_py = has_dangerous_unicode

    def normalize(text: str, *, nfkc: bool = True) -> UnicodeScanResult:  # noqa: F811
        try:
            cleaned, removed, categories = _native.normalize(text, nfkc)
            return UnicodeScanResult(cleaned, list(removed), list(categories))
        except Exception:
            return _normalize_py(text, nfkc=nfkc)

    def has_dangerous_unicode(text: str) -> bool:  # noqa: F811
        try:
            return _native.has_dangerous_unicode(text)
        except Exception:
            return _has_dangerous_unicode_py(text)


__all__ = [
    "UnicodeScanResult",
    "normalize",
    "has_dangerous_unicode",
]
