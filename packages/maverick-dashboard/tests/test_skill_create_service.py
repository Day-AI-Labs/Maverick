"""POST /api/v1/skills/create — author a skill from the dashboard form. Shares
the MAVERICK_ALLOW_SKILL_INSTALL opt-in with install; writes to the skills dir."""
from __future__ import annotations

from fastapi.testclient import TestClient
from maverick_dashboard.app import app

client = TestClient(app, headers={"Origin": "http://testserver"})

_GOOD = {
    "name": "Weekly Status Rollup",
    "instructions": "# What this does\n\nSummarize the week.\n\n# Steps\n1. Gather.\n2. Write.",
    "triggers": ["weekly status", "status rollup"],
    "tools_needed": ["read_file"],
}


def _skills_dir(tmp_path, monkeypatch):
    from maverick import skills
    monkeypatch.setattr(skills, "SKILLS_DIR", tmp_path / "skills")


def test_create_requires_opt_in(tmp_path, monkeypatch):
    _skills_dir(tmp_path, monkeypatch)
    monkeypatch.delenv("MAVERICK_ALLOW_SKILL_INSTALL", raising=False)
    r = client.post("/api/v1/skills/create", json=_GOOD)
    assert r.status_code == 403


def test_create_writes_skill_when_opted_in(tmp_path, monkeypatch):
    _skills_dir(tmp_path, monkeypatch)
    monkeypatch.setenv("MAVERICK_ALLOW_SKILL_INSTALL", "1")
    r = client.post("/api/v1/skills/create", json=_GOOD)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "weekly-status-rollup"          # kebab id
    assert "weekly status" in body["triggers"]
    assert (tmp_path / "skills" / "weekly-status-rollup.md").exists()


def test_create_rejects_missing_trigger(tmp_path, monkeypatch):
    _skills_dir(tmp_path, monkeypatch)
    monkeypatch.setenv("MAVERICK_ALLOW_SKILL_INSTALL", "1")
    bad = dict(_GOOD, triggers=[])
    r = client.post("/api/v1/skills/create", json=bad)
    assert r.status_code == 422


def test_create_rejects_too_many_triggers_at_schema(tmp_path, monkeypatch):
    _skills_dir(tmp_path, monkeypatch)
    monkeypatch.setenv("MAVERICK_ALLOW_SKILL_INSTALL", "1")
    from maverick.skills import MAX_SKILL_CREATE_ITEMS

    bad = dict(_GOOD, triggers=[f"trigger {i}" for i in range(MAX_SKILL_CREATE_ITEMS + 1)])
    r = client.post("/api/v1/skills/create", json=bad)
    assert r.status_code == 422


def test_create_rejects_oversized_tool_item_at_schema(tmp_path, monkeypatch):
    _skills_dir(tmp_path, monkeypatch)
    monkeypatch.setenv("MAVERICK_ALLOW_SKILL_INSTALL", "1")
    from maverick.skills import MAX_SKILL_CREATE_ITEM_CHARS

    bad = dict(_GOOD, tools_needed=["x" * (MAX_SKILL_CREATE_ITEM_CHARS + 1)])
    r = client.post("/api/v1/skills/create", json=bad)
    assert r.status_code == 422
