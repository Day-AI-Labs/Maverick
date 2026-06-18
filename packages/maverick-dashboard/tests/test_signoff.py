"""Governed hand-off: record a sign-off on a gated deliverable, surface it on
the goal page, and export the deliverable as CSV for downstream loading."""
from __future__ import annotations

import csv
import io

from fastapi.testclient import TestClient
from maverick_dashboard.app import app

client = TestClient(app, headers={"Origin": "http://testserver"})

_TABLE = "| Week | Net |\n| --- | ---: |\n| W1 | 300 |\n| W2 | 100 |\n"


def _world(tmp_path, monkeypatch):
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    return world_model.WorldModel(tmp_path / "world.db")


def _forecast_goal(w):
    gid = w.create_goal("Refresh the cash forecast", "", domain="finance_cash13w")
    w.set_goal_status(gid, "done", result=_TABLE)
    return gid


class TestSignoffApi:
    def test_record_then_read_signoff(self, tmp_path, monkeypatch):
        w = _world(tmp_path, monkeypatch)
        gid = _forecast_goal(w)
        r = client.post(f"/api/v1/goals/{gid}/signoff",
                        json={"decision": "approved", "note": "ties out"})
        assert r.status_code == 200
        body = r.json()
        assert body["signoff"]["decision"] == "approved"
        assert body["gate"] == "review"
        # persisted + readable
        got = client.get(f"/api/v1/goals/{gid}/signoff").json()
        assert got["signoff"]["decision"] == "approved"
        assert got["signoff"]["note"] == "ties out"

    def test_signoff_on_ungated_goal_is_rejected(self, tmp_path, monkeypatch):
        w = _world(tmp_path, monkeypatch)
        gid = w.create_goal("generic", "")  # no domain -> no gate
        w.set_goal_status(gid, "done", result="just prose")
        r = client.post(f"/api/v1/goals/{gid}/signoff", json={"decision": "approved"})
        assert r.status_code == 400

    def test_bad_decision_is_422(self, tmp_path, monkeypatch):
        w = _world(tmp_path, monkeypatch)
        gid = _forecast_goal(w)
        r = client.post(f"/api/v1/goals/{gid}/signoff", json={"decision": "maybe"})
        assert r.status_code == 422

    def test_approval_fires_handoff_rejection_does_not(self, tmp_path, monkeypatch):
        import maverick.webhooks as webhooks
        w = _world(tmp_path, monkeypatch)
        calls = []
        monkeypatch.setattr(webhooks, "fire_deliverable_handoff",
                            lambda payload: calls.append(payload) or 1)

        gid = _forecast_goal(w)
        client.post(f"/api/v1/goals/{gid}/signoff", json={"decision": "approved"})
        assert len(calls) == 1
        assert calls[0]["goal_id"] == gid
        assert calls[0]["domain"] == "finance_cash13w"
        assert calls[0]["table"]["headers"] == ["Week", "Net"]  # parsed deliverable rides along
        assert calls[0]["result"] == ""  # no raw table text outside the reviewed artifact

        gid2 = _forecast_goal(w)
        client.post(f"/api/v1/goals/{gid2}/signoff", json={"decision": "rejected"})
        assert len(calls) == 1  # rejection does not hand off downstream

    def test_handoff_omits_unreviewed_raw_text_for_table(self, tmp_path, monkeypatch):
        import maverick.webhooks as webhooks
        w = _world(tmp_path, monkeypatch)
        calls = []
        monkeypatch.setattr(webhooks, "fire_deliverable_handoff",
                            lambda payload: calls.append(payload) or 1)

        raw = "HIDDEN_PREFACE\n" + _TABLE + "\nHIDDEN_TRAILER"
        gid = w.create_goal("Refresh the cash forecast", "", domain="finance_cash13w")
        w.set_goal_status(gid, "done", result=raw)

        r = client.post(f"/api/v1/goals/{gid}/signoff", json={"decision": "approved"})

        assert r.status_code == 200
        assert len(calls) == 1
        assert calls[0]["table"] == {
            "headers": ["Week", "Net"],
            "rows": [["W1", "300"], ["W2", "100"]],
        }
        assert calls[0]["result"] == ""
        assert "HIDDEN" not in str(calls[0])


class TestDeliverableExport:
    def test_forecast_exports_as_csv_after_approval(self, tmp_path, monkeypatch):
        w = _world(tmp_path, monkeypatch)
        gid = _forecast_goal(w)
        w.record_signoff(gid, "approved", decided_by="user:alice", note="ok")
        r = client.get(f"/api/v1/goals/{gid}/deliverable.csv")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/csv")
        body = r.text
        assert "Week,Net" in body
        assert "W1,300" in body

    def test_gated_table_export_requires_approved_signoff(self, tmp_path, monkeypatch):
        w = _world(tmp_path, monkeypatch)
        gid = w.create_goal("Prepare payment batch", "", domain="finance_ap")
        w.set_goal_status(gid, "done", result=_TABLE)

        r = client.get(f"/api/v1/goals/{gid}/deliverable.csv")
        assert r.status_code == 403

        w.record_signoff(gid, "rejected", decided_by="user:alice", note="hold")
        r = client.get(f"/api/v1/goals/{gid}/deliverable.csv")
        assert r.status_code == 403

        w.record_signoff(gid, "approved", decided_by="user:alice", note="ok")
        r = client.get(f"/api/v1/goals/{gid}/deliverable.csv")
        assert r.status_code == 200

    def test_export_neutralizes_spreadsheet_formulas(self, tmp_path, monkeypatch):
        w = _world(tmp_path, monkeypatch)
        gid = w.create_goal("Review AML alerts", "", domain="bank_aml_alerts")
        w.set_goal_status(
            gid,
            "done",
            result=(
                "| Alert | Formula | Safe |\n"
                "| --- | --- | --- |\n"
                "| =HYPERLINK(\"http://attacker.test\") | +SUM(1,2) | ordinary |\n"
                "| @SUM(1,2) | -2+3 | unchanged |\n"
            ),
        )
        # bank_aml_alerts is gated (review), so an approved sign-off is required
        # before the gated table can be exported.
        w.record_signoff(gid, "approved", decided_by="user:alice", note="ok")

        r = client.get(f"/api/v1/goals/{gid}/deliverable.csv")

        assert r.status_code == 200
        rows = list(csv.reader(io.StringIO(r.text)))
        assert rows[0] == ["Alert", "Formula", "Safe"]
        assert rows[1] == [
            "'=HYPERLINK(\"http://attacker.test\")",
            "'+SUM(1,2)",
            "ordinary",
        ]
        assert rows[2] == ["'@SUM(1,2)", "'-2+3", "unchanged"]

    def test_no_table_is_404(self, tmp_path, monkeypatch):
        w = _world(tmp_path, monkeypatch)
        gid = w.create_goal("Refresh forecast", "", domain="finance_cash13w")
        w.set_goal_status(gid, "done", result="No grid here, just narrative.")
        assert client.get(f"/api/v1/goals/{gid}/deliverable.csv").status_code == 404


class TestSignoffUi:
    def test_gated_done_goal_shows_signoff_controls(self, tmp_path, monkeypatch):
        w = _world(tmp_path, monkeypatch)
        gid = _forecast_goal(w)
        t = client.get(f"/chat/goal/{gid}").text
        assert 'id="signoff-approve"' in t
        assert 'id="signoff-reject"' in t

    def test_signed_off_goal_shows_decision_and_handoff(self, tmp_path, monkeypatch):
        w = _world(tmp_path, monkeypatch)
        gid = _forecast_goal(w)
        w.record_signoff(gid, "approved", decided_by="user:alice", note="ok")
        t = client.get(f"/chat/goal/{gid}").text
        assert 'id="signoff-approve"' not in t          # form replaced by the decision
        assert "approved" in t
        assert f"/api/v1/goals/{gid}/deliverable.csv" in t   # hand-off download offered

    def test_generic_goal_has_no_signoff_panel(self, tmp_path, monkeypatch):
        w = _world(tmp_path, monkeypatch)
        gid = w.create_goal("Summarize", "")
        w.set_goal_status(gid, "done", result="a summary")
        t = client.get(f"/chat/goal/{gid}").text
        assert 'class="signoff"' not in t
