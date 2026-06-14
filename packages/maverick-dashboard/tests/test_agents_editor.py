"""Per-client agent editor: roster + override REST endpoints and the page.

Mutating /api/v1 requests carry a same-origin Origin (the CSRF contract; see
test_api.py). The domains dir is redirected to a temp dir so overrides never
touch the real workspace, and the world DB is isolated per the usual pattern.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from maverick_dashboard.app import app

client = TestClient(app, headers={"Origin": "http://testserver"})


def _clean_builtin_name() -> str:
    from maverick.domain import builtin_dir, lint_profile, load_domains
    for name, prof in sorted(load_domains(builtin_dir()).items()):
        if not lint_profile(prof)[0]:
            return name
    raise AssertionError("no lint-error-clean built-in pack found")


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    monkeypatch.setenv("MAVERICK_DOMAINS_DIR", str(tmp_path / "domains"))
    yield


class TestRosterAndView:
    def test_page_renders_with_roster(self):
        r = client.get("/agents")
        assert r.status_code == 200
        assert "agents" in r.text.lower()

    def test_list_endpoint_includes_builtin(self):
        name = _clean_builtin_name()
        r = client.get("/api/v1/agents")
        assert r.status_code == 200
        assert name in {a["name"] for a in r.json()["agents"]}

    def test_get_agent_returns_merged_view(self):
        name = _clean_builtin_name()
        r = client.get(f"/api/v1/agents/{name}")
        assert r.status_code == 200
        body = r.json()
        assert body["name"] == name
        assert body["is_override"] is False
        assert body["overridden"] == []

    def test_get_unknown_agent_404(self):
        assert client.get("/api/v1/agents/no_such_pack").status_code == 404


class TestOverrideLifecycle:
    def test_save_override_persists_and_marks_provenance(self, tmp_path):
        name = _clean_builtin_name()
        r = client.post(f"/api/v1/agents/{name}/override",
                        json={"description": "Tuned for ACME."})
        assert r.status_code == 200
        assert r.json()["is_override"] is True
        assert "description" in r.json()["overridden"]
        assert (tmp_path / "domains" / f"{name}.toml").is_file()
        # A fresh GET reflects the override too.
        assert client.get(f"/api/v1/agents/{name}").json()["description"] == "Tuned for ACME."

    def test_workflow_edit_round_trips(self):
        name = _clean_builtin_name()
        steps = [{"name": "intake", "instruction": "Read the request.",
                  "tools": [], "gate": None}]
        r = client.post(f"/api/v1/agents/{name}/override", json={"workflow": steps})
        assert r.status_code == 200
        assert [s["name"] for s in r.json()["workflow"]] == ["intake"]

    def test_page_renders_workflow_as_editable_rows(self):
        name = _clean_builtin_name()
        client.post(f"/api/v1/agents/{name}/override", json={"workflow": [
            {"name": "intake", "instruction": "Read the request.", "tools": [], "gate": None},
            {"name": "review", "instruction": "Check it.", "tools": [], "gate": "approval"},
        ]})
        html = client.get(f"/agents?name={name}").text
        # The playbook renders as structured rows (not a raw JSON textarea),
        # with an add-step control and a clone template for new rows.
        assert 'class="wf-name"' in html
        assert 'value="intake"' in html and "Read the request." in html
        assert "Check it." in html
        assert "+ Add step" in html and 'id="wf-row-tpl"' in html
        assert 'name="workflow"' not in html   # the old JSON textarea is gone

    def test_invalid_override_rejected_422(self):
        # Empty allow_tools makes the merged pack fail lint -> rejected, not written.
        name = _clean_builtin_name()
        r = client.post(f"/api/v1/agents/{name}/override", json={"allow_tools": []})
        assert r.status_code == 422
        assert client.get(f"/api/v1/agents/{name}").json()["is_override"] is False

    def test_validate_endpoint_reports_without_writing(self):
        name = _clean_builtin_name()
        r = client.post(f"/api/v1/agents/{name}/validate", json={"allow_tools": []})
        assert r.status_code == 200
        assert r.json()["ok"] is False
        assert r.json()["errors"]
        assert client.get(f"/api/v1/agents/{name}").json()["is_override"] is False

    def test_delete_override_reverts(self):
        name = _clean_builtin_name()
        client.post(f"/api/v1/agents/{name}/override", json={"description": "temp"})
        assert client.get(f"/api/v1/agents/{name}").json()["is_override"] is True
        r = client.delete(f"/api/v1/agents/{name}/override")
        assert r.status_code == 200
        assert client.get(f"/api/v1/agents/{name}").json()["is_override"] is False


class TestPackEditingGate:
    def test_mutations_403_when_disabled(self, monkeypatch):
        import maverick.config as cfg
        monkeypatch.setattr(cfg, "get_features",
                            lambda: {"skills": True, "world_model": True,
                                     "streaming": True, "pack_editing": False})
        name = _clean_builtin_name()
        assert client.post(f"/api/v1/agents/{name}/override",
                           json={"description": "x"}).status_code == 403
        assert client.delete(f"/api/v1/agents/{name}/override").status_code == 403
        # Read-only access still works.
        assert client.get(f"/api/v1/agents/{name}").status_code == 200
