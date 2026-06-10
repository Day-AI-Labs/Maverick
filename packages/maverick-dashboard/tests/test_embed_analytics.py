"""Embedded analytics web component: static JS route + demo page."""
from __future__ import annotations

from fastapi.testclient import TestClient
from maverick_dashboard.app import app

client = TestClient(app)


def test_component_js_served_with_correct_content_type():
    r = client.get("/static/maverick-analytics.js")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/javascript")
    body = r.text
    # a real self-contained custom element, not a framework loader
    assert 'customElements.define("maverick-analytics"' in body
    assert "extends HTMLElement" in body
    # it reads the existing endpoints and nothing else
    assert "/api/v1/spend" in body and "/api/v1/goals" in body
    # the same-origin + token caveats are documented in the file itself
    assert "HONEST LIMITS" in body
    assert "CORS" in body


def test_demo_page_embeds_component_and_documents_limits():
    r = client.get("/embed-demo")
    assert r.status_code == 200
    assert "<maverick-analytics>" in r.text
    assert 'src="/static/maverick-analytics.js"' in r.text
    # honest usage notes on the page, not just in the JS comment
    assert "Same-origin requirement" in r.text
    assert "Token exposure" in r.text


def test_component_js_is_inert_text_for_other_methods():
    # only GET serves it; mutating verbs are 405, not silently accepted
    assert client.post(
        "/static/maverick-analytics.js",
        headers={"Origin": "http://testserver"},
    ).status_code == 405
