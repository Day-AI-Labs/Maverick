"""Microsoft Teams tool (ROADMAP 2027 H2)."""
from __future__ import annotations

import httpx
from maverick.tools.teams_tool import _build_card, teams_tool


def test_build_card_plain():
    card = _build_card("hello world")
    assert card["@type"] == "MessageCard"
    assert card["text"] == "hello world"
    assert "title" not in card


def test_build_card_with_title():
    card = _build_card("body", "My Title")
    assert card["title"] == "My Title"
    assert card["summary"] == "My Title"


def test_send_posts_card(monkeypatch):
    captured = {}

    class _Resp:
        status_code = 200
        text = "1"

    def _fake_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        return _Resp()

    monkeypatch.setattr(httpx, "post", _fake_post)
    out = teams_tool().fn({"text": "deploy done", "title": "CI",
                           "webhook": "https://outlook.office.com/webhook/abc"})
    assert out == "posted to Teams"
    assert captured["json"]["text"] == "deploy done"
    assert captured["json"]["title"] == "CI"


def test_send_requires_webhook(monkeypatch):
    monkeypatch.delenv("TEAMS_WEBHOOK_URL", raising=False)
    out = teams_tool().fn({"text": "hi"})
    assert out.startswith("ERROR") and "webhook" in out


def test_send_rejects_non_https():
    out = teams_tool().fn({"text": "hi", "webhook": "http://outlook.office.com/x"})
    assert out.startswith("ERROR") and "https" in out


def test_send_rejects_private_host(monkeypatch):
    monkeypatch.delenv("MAVERICK_FETCH_ALLOW_PRIVATE", raising=False)
    out = teams_tool().fn({"text": "hi", "webhook": "https://127.0.0.1/webhook"})
    assert out.startswith("ERROR")


def test_send_requires_text():
    assert teams_tool().fn({"text": "", "webhook": "https://x.office.com/w"}).startswith("ERROR")
