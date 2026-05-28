"""Q3 2026 batch 17.

  - Browser fill_form action: batch-fills many inputs in one call,
    reports partial failures. Tested with a mocked session (no chromium).
"""
from __future__ import annotations

import maverick.tools.browser as browser_mod
from maverick.tools.browser import browser


class _FakePage:
    def __init__(self, fail=()):
        self.filled: list[tuple[str, str]] = []
        self._fail = set(fail)

    def fill(self, selector, value, timeout):
        if selector in self._fail:
            raise RuntimeError("element not found")
        self.filled.append((selector, value))


class _FakeSession:
    def __init__(self, page):
        self._page = page

    @property
    def page(self):
        return self._page

    def save_state(self):
        return True


def _use(monkeypatch, page):
    monkeypatch.setenv("MAVERICK_BROWSER_DISABLE", "0")
    monkeypatch.setattr(browser_mod, "_get_session", lambda: _FakeSession(page))


def test_fill_form_fills_all_fields(monkeypatch):
    page = _FakePage()
    _use(monkeypatch, page)
    out = browser_mod._run_browser_action({
        "action": "fill_form",
        "fields": {"#user": "alice", "#pass": "hunter2", "#email": "a@b.co"},
    })
    assert out == "filled 3/3 field(s)"
    assert page.filled == [("#user", "alice"), ("#pass", "hunter2"), ("#email", "a@b.co")]


def test_fill_form_preserves_order_and_coerces_values(monkeypatch):
    page = _FakePage()
    _use(monkeypatch, page)
    browser_mod._run_browser_action({
        "action": "fill_form",
        "fields": {"#a": 1, "#b": "two"},
    })
    assert page.filled == [("#a", "1"), ("#b", "two")]


def test_fill_form_reports_partial_failure(monkeypatch):
    page = _FakePage(fail={"#missing"})
    _use(monkeypatch, page)
    out = browser_mod._run_browser_action({
        "action": "fill_form",
        "fields": {"#ok": "x", "#missing": "y"},
    })
    assert out.startswith("filled 1/2 field(s)")
    assert "failed:" in out and "#missing" in out
    assert page.filled == [("#ok", "x")]


def test_fill_form_requires_fields(monkeypatch):
    page = _FakePage()
    _use(monkeypatch, page)
    assert "requires a non-empty" in browser_mod._run_browser_action(
        {"action": "fill_form"}).lower()
    assert "requires a non-empty" in browser_mod._run_browser_action(
        {"action": "fill_form", "fields": {}}).lower()


def test_fill_form_rejects_non_dict_fields(monkeypatch):
    page = _FakePage()
    _use(monkeypatch, page)
    out = browser_mod._run_browser_action(
        {"action": "fill_form", "fields": ["#a", "#b"]})
    assert out.startswith("ERROR")


def test_schema_includes_fill_form():
    schema = browser().input_schema
    assert "fill_form" in schema["properties"]["action"]["enum"]
    assert "fields" in schema["properties"]
