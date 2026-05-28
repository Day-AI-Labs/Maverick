"""Skill Store: catalog list + hash-pinned install endpoint + /store page.

The hash-pinned catalog install must work WITHOUT
MAVERICK_ALLOW_SKILL_INSTALL (that's the whole point — a consumer
clicks Install without touching an env var), while the free-text
/skills endpoint stays gated.
"""
from __future__ import annotations

from fastapi.testclient import TestClient


def _client():
    from maverick_dashboard.app import app
    return TestClient(app)


def _stub_catalog(monkeypatch, entries):
    import maverick.catalog as cat
    monkeypatch.setattr(cat, "load_catalog", lambda kind, indexes=None: entries)


def _entry(name="summarize-url", **over):
    import maverick.catalog as cat
    d = {
        "name": name, "version": "1.0.0", "summary": "x",
        "source": "gh:org/repo:SKILL.md", "sha256": "abc",
        "author": "org", "verified": True,
    }
    d.update(over)
    return cat.CatalogEntry.from_dict("skills", d)


# ---------- catalog list ----------

def test_catalog_list_unknown_kind_400(monkeypatch):
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    client = _client()
    r = client.get("/api/v1/catalog/widgets")
    assert r.status_code == 400


def test_catalog_list_returns_entries(monkeypatch):
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    _stub_catalog(monkeypatch, [_entry()])
    client = _client()
    r = client.get("/api/v1/catalog/skills")
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "skills"
    assert body["entries"][0]["name"] == "summarize-url"


def test_catalog_list_unreachable_returns_empty(monkeypatch):
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    _stub_catalog(monkeypatch, [])
    client = _client()
    r = client.get("/api/v1/catalog/skills")
    assert r.status_code == 200
    assert r.json()["entries"] == []


# ---------- catalog install (no env gate) ----------

def test_catalog_install_does_not_require_opt_in(monkeypatch):
    """The key property: install works WITHOUT MAVERICK_ALLOW_SKILL_INSTALL."""
    monkeypatch.delenv("MAVERICK_ALLOW_SKILL_INSTALL", raising=False)
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)

    import maverick.skills as sk
    from maverick.skills import Skill
    from pathlib import Path
    called = {}

    def _fake_install(name, *a, **kw):
        called["name"] = name
        return Skill(name=name, triggers=["t"], tools_needed=[], body="", path=Path("/x"))

    monkeypatch.setattr(sk, "install_from_catalog", _fake_install)
    client = _client()
    r = client.post(
        "/api/v1/catalog/skills/install",
        json={"name": "summarize-url"},
        headers={"Origin": "http://testserver"},
    )
    assert r.status_code == 201, r.text
    assert called["name"] == "summarize-url"
    assert r.json()["name"] == "summarize-url"


def test_catalog_install_hash_mismatch_400(monkeypatch):
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    import maverick.skills as sk

    def _raise(name, *a, **kw):
        raise ValueError("content hash mismatch for 'x'")

    monkeypatch.setattr(sk, "install_from_catalog", _raise)
    client = _client()
    r = client.post(
        "/api/v1/catalog/skills/install",
        json={"name": "x"},
        headers={"Origin": "http://testserver"},
    )
    assert r.status_code == 400
    assert "hash mismatch" in r.json()["detail"]


def test_free_text_skill_install_still_gated(monkeypatch):
    """Regression: the RCE-vector endpoint must STAY gated."""
    monkeypatch.delenv("MAVERICK_ALLOW_SKILL_INSTALL", raising=False)
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    client = _client()
    r = client.post(
        "/api/v1/skills",
        json={"source": "gh:attacker/repo"},
        headers={"Origin": "http://testserver"},
    )
    assert r.status_code == 403


# ---------- store page ----------

def test_store_page_renders_entries(monkeypatch, tmp_path):
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    _stub_catalog(monkeypatch, [_entry(summary="Summarise any URL")])
    client = _client()
    r = client.get("/store")
    assert r.status_code == 200
    assert "summarize-url" in r.text
    assert "Summarise any URL" in r.text
    assert "Install" in r.text
    assert 'href="/store"' in r.text  # nav link


def test_store_page_empty_state(monkeypatch, tmp_path):
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    _stub_catalog(monkeypatch, [])
    client = _client()
    r = client.get("/store")
    assert r.status_code == 200
    assert "No catalog entries" in r.text
