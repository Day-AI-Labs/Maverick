"""Visual goal-templates marketplace (/templates, /api/v1/templates[,/suggested])
and the chat-form prefill it links to."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from maverick_dashboard.app import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path))
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    from maverick_dashboard import api as api_mod
    from maverick_dashboard import app as app_mod
    api_mod._world_cache.clear()
    app_mod._world_cache.clear()
    # Deterministic template catalog: a tmp user dir, no bundled repo templates.
    import maverick.templates as tpl_mod
    user_dir = tmp_path / "templates"
    user_dir.mkdir()
    monkeypatch.setattr(tpl_mod, "USER_TEMPLATES", user_dir)
    monkeypatch.setattr(tpl_mod, "_BUNDLED_CANDIDATES", [])
    yield user_dir


@pytest.fixture
def catalog(_isolated):
    (_isolated / "trip-plan.md").write_text(
        "---\ntitle: Plan a trip to {{ city }}\nparams:\n  - city\n---\n"
        "Plan a trip to {{ city }} under budget.",
        encoding="utf-8",
    )
    (_isolated / "research-report.md").write_text(
        "---\ntitle: Research a topic\n---\nResearch it deeply.",
        encoding="utf-8",
    )
    return _isolated


def test_templates_page_lists_catalog_with_ratings(catalog):
    from maverick.marketplace.ratings import RatingsLedger
    RatingsLedger().rate("templates", "trip-plan", 4)
    r = client.get("/templates")
    assert r.status_code == 200
    assert "trip-plan" in r.text and "research-report" in r.text
    assert "★★★★☆" in r.text       # rated template
    assert "unrated" in r.text      # the other one
    assert 'href="/templates"' in r.text  # nav link wired


def test_use_template_links_prefill_chat_not_autostart(catalog):
    r = client.get("/templates")
    # One-click use: a link to /chat with title+description query params.
    assert 'href="/chat?title=Plan%20a%20trip%20to%20%7B%7B%20city%20%7D%7D' in r.text
    assert "description=" in r.text
    # No goal was created by rendering the marketplace.
    from maverick_dashboard.app import _world
    assert _world().list_goals() == []


def test_templates_page_empty_state(_isolated):
    r = client.get("/templates")
    assert r.status_code == 200
    assert "No templates yet" in r.text


def test_templates_api(catalog):
    from maverick.marketplace.ratings import RatingsLedger
    RatingsLedger().rate("templates", "research-report", 5)
    body = client.get("/api/v1/templates").json()
    by_name = {e["name"]: e for e in body["templates"]}
    assert by_name["trip-plan"]["params"] == ["city"]
    assert by_name["trip-plan"]["stars"] is None
    assert by_name["research-report"]["stars"] == 5
    assert by_name["research-report"]["rating_bar"].startswith("★★★★★")


def test_suggested_api_ranks_for_this_user(catalog):
    from maverick_dashboard.app import _world
    w = _world()
    for _ in range(3):
        w.create_goal("research the market", "")
    body = client.get("/api/v1/templates/suggested").json()
    names = [e["name"] for e in body["suggested"]]
    assert names[0] == "research-report"
    assert body["suggested"][0]["score"] > 0
    # k caps the list.
    assert len(client.get("/api/v1/templates/suggested?k=1").json()["suggested"]) == 1


def test_chat_prefill_from_query_params(catalog):
    r = client.get("/chat", params={
        "title": 'Plan a "big" trip', "description": "Use <param> {{ city }}",
    })
    assert r.status_code == 200
    # Prefilled, HTML-escaped, and the details block is opened.
    assert 'value="Plan a &#34;big&#34; trip"' in r.text
    assert "Use &lt;param&gt; {{ city }}" in r.text
    assert "<details open>" in r.text
    # No prefill -> unchanged empty form.
    r2 = client.get("/chat")
    assert 'value=""' in r2.text and "<details>" in r2.text
