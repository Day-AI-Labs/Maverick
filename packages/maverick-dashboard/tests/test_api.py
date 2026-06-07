"""REST API endpoint tests.

v0.1.6: the BackgroundTask runner is now `maverick.runner.run_goal_in_thread`
with signature ``(goal_id, max_dollars, max_wall_seconds, max_depth)``,
so the create_returns_pending monkeypatch takes 4 positional args (was 1).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from maverick_dashboard.app import app

# Same-origin default: mutating /api/v1 requests in no-token (loopback) mode
# must carry a matching Origin, the CSRF contract the dashboard enforces
# centrally (see app.py bearer_auth). These functional tests simulate a
# legitimate same-origin caller; the missing/forged-Origin cases are covered
# by test_security.py. GET/HEAD/OPTIONS skip the check, so this is a no-op for
# read tests.
client = TestClient(app, headers={"Origin": "http://testserver"})


@pytest.fixture(autouse=True)
def _isolated_world(tmp_path, monkeypatch):
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    yield


class TestGoals:
    def test_create_requires_api_key(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        resp = client.post("/api/v1/goals", json={"title": "hi"})
        assert resp.status_code == 400
        assert "ANTHROPIC_API_KEY" in resp.json()["detail"]

    def test_create_returns_pending(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")
        # Patch the shared runner so we don't actually call Anthropic.
        # The new signature is (goal_id, max_dollars, max_wall_seconds, max_depth).
        import maverick.runner as runner_mod
        called = []
        def fake_run(goal_id, max_dollars=2.0, max_wall_seconds=1800.0, max_depth=3):
            called.append((goal_id, max_dollars, max_wall_seconds, max_depth))
        monkeypatch.setattr(runner_mod, "run_goal_in_thread", fake_run)
        resp = client.post("/api/v1/goals", json={
            "title": "test goal", "description": "x", "max_dollars": 1.0,
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "pending"
        assert data["title"] == "test goal"
        assert len(called) == 1
        assert called[0][0] == data["id"]
        # Verify payload's max_dollars propagated (the fix from the council
        # security review).
        assert called[0][1] == 1.0


    def test_create_rejects_invalid_template_name(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")
        resp = client.post("/api/v1/goals", json={
            "title": "test goal",
            "template": "../escape_secret",
        })
        assert resp.status_code == 400
        assert "invalid template name" in resp.json()["detail"]
    def test_create_clamps_max_dollars(self, monkeypatch):
        """Pydantic Field bounds reject values outside [0, 100]."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")
        resp = client.post("/api/v1/goals", json={
            "title": "big spend", "max_dollars": 10_000.0,
        })
        # 422 = Pydantic validation error
        assert resp.status_code == 422

    def test_list_returns_array(self):
        resp = client.get("/api/v1/goals")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_get_unknown_404(self):
        resp = client.get("/api/v1/goals/999999")
        assert resp.status_code == 404

    def test_events_for_unknown_404(self):
        resp = client.get("/api/v1/goals/999999/events")
        assert resp.status_code == 404


class TestAnswer:
    """POST /api/v1/goals/{id}/answer now takes a JSON body (v0.1.6)."""

    def test_answer_unknown_question_404(self, tmp_path, monkeypatch):
        from maverick import world_model
        monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
        w = world_model.WorldModel(tmp_path / "world.db")
        gid = w.create_goal("test", "")
        resp = client.post(
            f"/api/v1/goals/{gid}/answer",
            json={"question_id": 9999, "answer": "x"},
        )
        assert resp.status_code == 404

    def test_answer_missing_body_422(self, tmp_path, monkeypatch):
        from maverick import world_model
        monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
        w = world_model.WorldModel(tmp_path / "world.db")
        gid = w.create_goal("test", "")
        # No body -> Pydantic validation 422 (was query-string-only before).
        resp = client.post(f"/api/v1/goals/{gid}/answer")
        assert resp.status_code == 422


class TestAttachments:
    def test_upload_text_then_list(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MAVERICK_ATTACH_MAX_FILE_BYTES", "1000000")
        # Attachment bytes land on disk; route to tmp_path so tests don't
        # litter ~/.maverick.
        import maverick.attachments as att_mod
        monkeypatch.setattr(att_mod, "DEFAULT_ROOT", tmp_path / "att")

        from maverick.world_model import DEFAULT_DB, WorldModel
        wm = WorldModel(DEFAULT_DB)
        gid = wm.create_goal("attach", "")

        resp = client.post(
            f"/api/v1/goals/{gid}/attachments",
            files={"file": ("hello.txt", b"hello world", "text/plain")},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["filename"] == "hello.txt"
        assert data["mime"] == "text/plain"
        assert data["size_bytes"] == len(b"hello world")

        # List endpoint returns the same record.
        resp = client.get(f"/api/v1/goals/{gid}/attachments")
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert items[0]["filename"] == "hello.txt"

    def test_upload_rejects_disallowed_mime(self, tmp_path, monkeypatch):
        import maverick.attachments as att_mod
        monkeypatch.setattr(att_mod, "DEFAULT_ROOT", tmp_path / "att")
        from maverick.world_model import DEFAULT_DB, WorldModel
        wm = WorldModel(DEFAULT_DB)
        gid = wm.create_goal("attach", "")

        resp = client.post(
            f"/api/v1/goals/{gid}/attachments",
            files={"file": ("bad.exe", b"MZ\x00\x00",
                            "application/x-msdownload")},
        )
        assert resp.status_code == 400
        assert "mime type not allowed" in resp.json()["detail"]


    def test_upload_reads_with_size_cap(self, monkeypatch):
        import asyncio

        from maverick_dashboard import api as api_mod

        class _World:
            def get_goal(self, goal_id):
                return object()

            def list_attachments(self, goal_id):
                return []

            def add_attachment(self, **kwargs):
                return 1

        class _Stored:
            filename = "x.txt"
            mime = "text/plain"
            size_bytes = 1
            sha256 = "abc"
            path = "/tmp/x"

        class _File:
            filename = "x.txt"
            content_type = "text/plain"

            def __init__(self):
                self.read_sizes = []

            async def read(self, size=-1):
                self.read_sizes.append(size)
                return b"x"

        monkeypatch.setattr(api_mod, "_world", lambda: _World())

        called = {}

        def _store(goal_id, filename, mime, data, existing_total):
            called["data"] = data
            return _Stored()

        monkeypatch.setattr("maverick.attachments.store", _store)
        monkeypatch.setattr("maverick.attachments.MAX_FILE_BYTES", 7)

        f = _File()
        # upload_attachment now takes the Request first (for owner scoping); a
        # bare object has no .state.principal, so auth is treated as OFF here.
        out = asyncio.run(api_mod.upload_attachment(object(), 1, f))

        assert f.read_sizes == [8]
        assert called["data"] == b"x"
        assert out.size_bytes == 1

    def test_upload_to_unknown_goal_404(self):
        resp = client.post(
            "/api/v1/goals/99999/attachments",
            files={"file": ("x.txt", b"x", "text/plain")},
        )
        assert resp.status_code == 404


class TestFacts:
    def test_get_empty_initially(self):
        resp = client.get("/api/v1/facts")
        assert resp.status_code == 200
        assert resp.json() == {}

    def test_set_then_get(self):
        resp = client.post("/api/v1/facts", json={"key": "city", "value": "Lisbon"})
        assert resp.status_code == 204
        resp = client.get("/api/v1/facts")
        assert resp.json() == {"city": "Lisbon"}

    def test_upsert_overwrites(self):
        client.post("/api/v1/facts", json={"key": "city", "value": "Lisbon"})
        client.post("/api/v1/facts", json={"key": "city", "value": "Tokyo"})
        assert client.get("/api/v1/facts").json() == {"city": "Tokyo"}


class TestSkills:
    def test_list_returns_array(self):
        resp = client.get("/api/v1/skills")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_install_bare_path_rejected(self, monkeypatch):
        """REST callers can't POST {"source": "/etc/passwd"} (security fix)."""
        monkeypatch.setenv("MAVERICK_ALLOW_SKILL_INSTALL", "1")
        resp = client.post("/api/v1/skills", json={"source": "/etc/passwd"})
        assert resp.status_code == 400
        assert "not allowed" in resp.json()["detail"]

    def test_install_file_scheme_rejected(self, monkeypatch):
        monkeypatch.setenv("MAVERICK_ALLOW_SKILL_INSTALL", "1")
        resp = client.post("/api/v1/skills", json={"source": "file:///etc/passwd"})
        assert resp.status_code == 400

    def test_install_bad_gh_format_rejected(self, monkeypatch):
        monkeypatch.setenv("MAVERICK_ALLOW_SKILL_INSTALL", "1")
        resp = client.post("/api/v1/skills", json={"source": "gh:not-valid"})
        assert resp.status_code == 400

    def test_install_blocked_without_opt_in(self):
        """Without MAVERICK_ALLOW_SKILL_INSTALL=1, endpoint refuses (council fix)."""
        resp = client.post("/api/v1/skills", json={"source": "gh:any/repo"})
        assert resp.status_code == 403
        assert "MAVERICK_ALLOW_SKILL_INSTALL" in resp.json()["detail"]

    def test_remove_unknown_404(self):
        resp = client.delete("/api/v1/skills/does-not-exist")
        assert resp.status_code == 404


class TestSpend:
    def test_returns_total_and_episodes(self):
        resp = client.get("/api/v1/spend")
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "episodes" in data
        assert isinstance(data["episodes"], list)


class TestOpenAPI:
    def test_openapi_schema_served(self):
        resp = client.get("/openapi.json")
        assert resp.status_code == 200
        spec = resp.json()
        paths = spec.get("paths", {})
        for required in (
            "/api/v1/goals", "/api/v1/goals/{goal_id}", "/api/v1/facts",
            "/api/v1/skills", "/api/v1/spend",
        ):
            assert required in paths, f"missing {required}"

    def test_docs_served(self):
        resp = client.get("/docs")
        assert resp.status_code == 200

    def test_openapi_exempt_from_bearer_auth(self, monkeypatch):
        """OpenAPI tooling needs /openapi.json without a token."""
        monkeypatch.setenv("MAVERICK_DASHBOARD_TOKEN", "s3cr3t")
        resp = client.get("/openapi.json")
        assert resp.status_code == 200

    def test_docs_exempt_from_bearer_auth(self, monkeypatch):
        monkeypatch.setenv("MAVERICK_DASHBOARD_TOKEN", "s3cr3t")
        resp = client.get("/docs")
        assert resp.status_code == 200

    def test_api_endpoint_requires_bearer_when_token_set(self, monkeypatch):
        """Council test-coverage finding: /api/v1 was never tested with auth.

        Silent auth bypass on the API would be catastrophic; this test
        catches that regression class.
        """
        monkeypatch.setenv("MAVERICK_DASHBOARD_TOKEN", "s3cr3t")
        resp = client.get("/api/v1/goals")
        assert resp.status_code == 401

    def test_api_endpoint_with_bearer_succeeds(self, monkeypatch):
        monkeypatch.setenv("MAVERICK_DASHBOARD_TOKEN", "s3cr3t")
        resp = client.get(
            "/api/v1/goals",
            headers={"Authorization": "Bearer s3cr3t"},
        )
        assert resp.status_code == 200

    def test_api_endpoint_with_query_token_rejected(self, monkeypatch):
        """Council security pass: `?token=...` leaks via Referer/history.

        Removed; callers must send Authorization: Bearer.
        """
        monkeypatch.setenv("MAVERICK_DASHBOARD_TOKEN", "s3cr3t")
        resp = client.get("/api/v1/goals?token=s3cr3t")
        assert resp.status_code == 401

    def test_api_endpoint_with_wrong_bearer_rejected(self, monkeypatch):
        monkeypatch.setenv("MAVERICK_DASHBOARD_TOKEN", "s3cr3t")
        resp = client.get(
            "/api/v1/goals",
            headers={"Authorization": "Bearer wrong"},
        )
        assert resp.status_code == 401

    def test_livez_exempt_from_bearer_auth(self, monkeypatch):
        """Cheap liveness check must work without auth."""
        monkeypatch.setenv("MAVERICK_DASHBOARD_TOKEN", "s3cr3t")
        resp = client.get("/livez")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_healthz_deep_probe_returns_checks(self, monkeypatch):
        """Deep healthz probes DB, LLM key, runner."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")
        resp = client.get("/healthz")
        # Either ok or degraded -- the important property is that the
        # response includes per-check status.
        body = resp.json()
        assert "checks" in body
        assert "db" in body["checks"]
        assert "llm_key" in body["checks"]
        assert "runner" in body["checks"]

    def test_healthz_503_when_no_llm_key(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        resp = client.get("/healthz")
        assert resp.status_code == 503
        assert resp.json()["status"] == "degraded"
        assert "missing" in resp.json()["checks"]["llm_key"]


class TestMetrics:
    def test_healthz_redacts_exception_text_when_token_set(self, tmp_path, monkeypatch):
        """Wave 4 council security finding: on a VPS with
        MAVERICK_DASHBOARD_TOKEN set, /healthz must NOT leak the
        absolute DB path in error messages (it exposes the OS username).

        Issue #468 hardens this further: the auth-exempt payload now drops
        the whole ``checks`` block under a token (which also leaked
        ``llm_key`` and a live in-flight gauge), collapsing to just the
        status. So no DB path can appear at all.
        """
        monkeypatch.setenv("MAVERICK_DASHBOARD_TOKEN", "s3cr3t")
        # Point DEFAULT_DB at an unwritable path so the DB check fails.
        from maverick import world_model
        bad_path = tmp_path / "subdir-that-does-not-exist" / "world.db"
        monkeypatch.setattr(world_model, "DEFAULT_DB", bad_path)

        resp = client.get("/healthz")
        body = resp.json()
        # Minimal payload under a token: only the status, no checks block.
        assert "checks" not in body
        assert "subdir-that-does-not-exist" not in resp.text
        assert str(bad_path) not in resp.text

    def test_metrics_prometheus_format(self):
        resp = client.get("/metrics")
        assert resp.status_code == 200
        text = resp.text
        # Prometheus text format requires HELP + TYPE lines.
        assert "# HELP maverick_goals_total" in text
        assert "# TYPE maverick_goals_total counter" in text
        assert "# HELP maverick_cost_dollars_total" in text
        assert "# TYPE maverick_concurrent_goals gauge" in text
        assert "maverick_concurrent_goals" in text
        assert "maverick_max_concurrent_goals" in text
