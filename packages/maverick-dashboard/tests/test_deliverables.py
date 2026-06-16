"""The persona inbox: build_inbox shaping + the /deliverables page (runs grouped
by deliverable, scoped to a consumer role, gated-and-finished flagged for
sign-off)."""
from __future__ import annotations

from dataclasses import dataclass

from fastapi.testclient import TestClient
from maverick_dashboard.app import app
from maverick_dashboard.deliverables import build_inbox, persona_roles_for

client = TestClient(app, headers={"Origin": "http://testserver"})


@dataclass
class _Run:
    id: int
    title: str
    status: str
    updated_at: float


_FORECAST = {"domain": "finance_cash13w", "deliverable": "13-week cash forecast",
             "shape": "forecast", "consumers": ["fpa_analyst", "treasurer"],
             "cadence": "weekly", "gate": "review", "suite": "finance"}
_RISK = {"domain": "risk_x", "deliverable": "Risk assessment", "shape": "report",
         "consumers": ["risk_officer"], "cadence": "", "gate": "approval", "suite": None}


class TestBuildInbox:
    def test_collects_every_consumer_role(self):
        m = build_inbox([_FORECAST, _RISK], {})
        assert m["roles"] == ["fpa_analyst", "risk_officer", "treasurer"]

    def test_role_filter_scopes_to_consumers(self):
        m = build_inbox([_FORECAST, _RISK], {}, role="risk_officer")
        assert [it["domain"] for it in m["items"]] == ["risk_x"]
        assert m["role"] == "risk_officer"

    def test_finished_gated_run_is_awaiting_signoff(self):
        runs = {"finance_cash13w": [_Run(7, "Refresh forecast", "done", 100.0)]}
        m = build_inbox([_FORECAST], runs)
        assert len(m["awaiting"]) == 1
        assert m["awaiting"][0]["id"] == 7
        assert m["awaiting"][0]["deliverable"] == "13-week cash forecast"
        assert m["items"][0]["awaiting_count"] == 1

    def test_running_or_ungated_run_is_not_awaiting(self):
        # in-flight run: not finished -> not awaiting
        running = {"finance_cash13w": [_Run(8, "x", "running", 1.0)]}
        assert build_inbox([_FORECAST], running)["awaiting"] == []
        # finished but the pack declares no gate -> nothing to sign off
        ungated = dict(_FORECAST, gate=None)
        done = {"finance_cash13w": [_Run(9, "x", "done", 1.0)]}
        assert build_inbox([ungated], done)["awaiting"] == []

    def test_items_with_signoffs_float_to_top(self):
        runs = {"finance_cash13w": [_Run(1, "f", "done", 5.0)],  # awaiting
                "risk_x": [_Run(2, "r", "running", 6.0)]}        # not
        m = build_inbox([_RISK, _FORECAST], runs)  # risk first by input order
        assert m["items"][0]["domain"] == "finance_cash13w"     # floated up

    def test_signed_off_run_drops_out_of_awaiting(self):
        runs = {"finance_cash13w": [_Run(7, "Refresh forecast", "done", 100.0)]}
        # finished + gated, but reviewed -> no longer awaiting
        m = build_inbox([_FORECAST], runs, signoffs={7: "approved"})
        assert m["awaiting"] == []
        assert m["items"][0]["awaiting_count"] == 0
        assert m["items"][0]["runs"][0]["signoff"] == "approved"

    def test_mine_defaults_to_my_roles(self):
        # No explicit role + my roles -> only deliverables I consume, flagged.
        m = build_inbox([_FORECAST, _RISK], {}, mine={"risk_officer"})
        assert [it["domain"] for it in m["items"]] == ["risk_x"]
        assert m["showing_mine"] is True
        assert m["mine"] == ["risk_officer"]

    def test_explicit_role_overrides_mine(self):
        m = build_inbox([_FORECAST, _RISK], {}, role="fpa_analyst", mine={"risk_officer"})
        assert [it["domain"] for it in m["items"]] == ["finance_cash13w"]
        assert m["showing_mine"] is False     # an explicit chip wins over the default
        assert m["roles"] == ["fpa_analyst", "risk_officer", "treasurer"]  # all roles, for the filter


class TestPersonaRoles:
    def _cfg(self, monkeypatch, cfg):
        monkeypatch.setattr("maverick.config.load_config", lambda *a, **k: cfg)

    def test_principal_mapping_wins(self, monkeypatch):
        self._cfg(monkeypatch, {"personas": {"user:alice": ["fpa_analyst", "treasurer"],
                                             "default": ["viewer_role"]}})
        assert persona_roles_for("user:alice") == ["fpa_analyst", "treasurer"]

    def test_falls_back_to_default(self, monkeypatch):
        self._cfg(monkeypatch, {"personas": {"default": ["risk_officer"]}})
        assert persona_roles_for("user:nobody") == ["risk_officer"]
        assert persona_roles_for(None) == ["risk_officer"]  # no-auth single user

    def test_string_is_coerced_to_list(self, monkeypatch):
        self._cfg(monkeypatch, {"personas": {"default": "controller"}})
        assert persona_roles_for(None) == ["controller"]

    def test_no_binding_is_empty(self, monkeypatch):
        self._cfg(monkeypatch, {})
        assert persona_roles_for("user:alice") == []


class TestDeliverablesPage:
    def _world(self, tmp_path, monkeypatch):
        from maverick import world_model
        monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
        return world_model.WorldModel(tmp_path / "world.db")

    def test_page_renders_with_filter_chips(self, tmp_path, monkeypatch):
        self._world(tmp_path, monkeypatch)
        r = client.get("/deliverables")
        assert r.status_code == 200
        assert "Deliverables" in r.text
        # finance_cash13w ships a contract, so its consumers show as filter chips
        assert "fpa_analyst" in r.text
        assert "13-week cash forecast" in r.text

    def test_finished_forecast_shows_in_signoff_queue(self, tmp_path, monkeypatch):
        w = self._world(tmp_path, monkeypatch)
        gid = w.create_goal("Refresh the cash forecast", "", domain="finance_cash13w")
        w.set_goal_status(gid, "done", result="| Week | Net |\n| --- | --- |\n| W1 | 10 |\n")
        t = client.get("/deliverables").text
        assert "Awaiting sign-off" in t
        assert f'href="/chat/goal/{gid}"' in t   # Review links to the deliverable view

    def test_role_filter_narrows_and_can_empty(self, tmp_path, monkeypatch):
        self._world(tmp_path, monkeypatch)
        # a role nobody consumes -> empty state, not a 500
        r = client.get("/deliverables?role=nobody_consumes_this")
        assert r.status_code == 200
        assert "No deliverables for nobody_consumes_this" in r.text
        # the real consumer keeps the forecast visible
        assert "13-week cash forecast" in client.get("/deliverables?role=fpa_analyst").text

    def test_persona_identity_defaults_inbox_to_my_roles(self, tmp_path, monkeypatch):
        self._world(tmp_path, monkeypatch)
        # No-auth single user bound to a persona role -> inbox defaults to "mine".
        monkeypatch.setattr("maverick.config.load_config",
                            lambda *a, **k: {"personas": {"default": ["tax_analyst"]}})
        t = client.get("/deliverables").text
        assert "Showing deliverables for your role" in t
        assert "tax_analyst" in t
        # a tax_analyst deliverable shows; a forecast (fpa/treasurer) is filtered out
        assert "Tax provision" in t
        assert "13-week cash forecast" not in t
        # ?role=all widens back to everything
        t_all = client.get("/deliverables?role=all").text
        assert "13-week cash forecast" in t_all
