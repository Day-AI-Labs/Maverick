"""Optional OCR fallback for the computer-use screenshot action.

Off by default; appends an <ocr> block when MAVERICK_COMPUTER_OCR is set
and OCR yields text. Fail-open when OCR deps are absent. Tests mock the
screenshot + OCR so they need neither mss/pillow/tesseract nor a display.
"""
from __future__ import annotations

from maverick.tools import computer


def test_ocr_disabled_by_default(monkeypatch):
    monkeypatch.delenv("MAVERICK_COMPUTER_OCR", raising=False)
    monkeypatch.setattr(computer, "_screenshot_png_b64", lambda: "FAKEB64")
    out = computer._run_computer_action({"action": "screenshot"})
    assert "<screenshot" in out
    assert "<ocr>" not in out


def test_ocr_appended_when_enabled(monkeypatch):
    monkeypatch.setenv("MAVERICK_COMPUTER_OCR", "1")
    monkeypatch.setattr(computer, "_screenshot_png_b64", lambda: "FAKEB64")
    monkeypatch.setattr(computer, "_ocr_png_b64", lambda b64: "Login\nSubmit")
    out = computer._run_computer_action({"action": "screenshot"})
    assert "<screenshot" in out
    assert "<ocr>Login\nSubmit</ocr>" in out


def test_ocr_enabled_but_no_text_omits_block(monkeypatch):
    monkeypatch.setenv("MAVERICK_COMPUTER_OCR", "on")
    monkeypatch.setattr(computer, "_screenshot_png_b64", lambda: "FAKEB64")
    monkeypatch.setattr(computer, "_ocr_png_b64", lambda b64: "")
    out = computer._run_computer_action({"action": "screenshot"})
    assert "<ocr>" not in out


def test_ocr_helper_fail_open_without_deps():
    # pytesseract isn't installed in the test env -> ImportError -> "".
    assert computer._ocr_png_b64("not-even-valid-b64") == ""
