"""The /start Get Started page: a live setup checklist that self-completes as
the workspace gets configured (provider -> built -> run/automated)."""
from __future__ import annotations

from fastapi.testclient import TestClient


def _client():
    from maverick_dashboard.app import app
    return TestClient(app, headers={"Origin": "http://testserver"})


def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path))
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    import maverick.templates as tpl
    monkeypatch.setattr(tpl, "USER_TEMPLATES", tmp_path / ".maverick" / "templates")
    import maverick.domain_edit as de
    monkeypatch.setattr(de, "list_agents", list)   # no overridden agents in a fresh ws
    from maverick_dashboard import app as app_mod
    app_mod._world_cache.clear()


def test_fresh_workspace_nothing_done(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    import maverick.config as config
    monkeypatch.setattr(config, "any_provider_configured", lambda: False)
    t = _client().get("/start").text
    assert "Connect a model provider" in t and "Build a workflow or agent" in t
    assert "0 of 3 done" in t and 'role="progressbar"' in t


def test_checklist_reflects_progress(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    import maverick.config as config
    monkeypatch.setattr(config, "any_provider_configured", lambda: True)  # step 1 done
    t = _client().get("/start").text
    assert "1 of 3 done" in t and "gs__step--done" in t


def test_nav_has_get_started(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    import maverick.config as config
    monkeypatch.setattr(config, "any_provider_configured", lambda: False)
    t = _client().get("/start").text
    assert '<span class="nav-label">Get started</span>' in t and 'href="/start"' in t


def test_run_step_uses_owner_scoped_goals(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    import maverick.config as config
    import maverick_dashboard.auth as auth
    from maverick import world_model
    from maverick.oidc import VerifiedPrincipal

    monkeypatch.setattr(config, "any_provider_configured", lambda: False)
    monkeypatch.setattr(auth, "oidc_enabled", lambda: True)

    def _verify(token, **_kw):
        return VerifiedPrincipal(
            sub=token,
            issuer="https://issuer.example",
            audience="maverick",
            claims={"sub": token},
        )

    monkeypatch.setattr(auth, "verify_oidc_token", _verify)
    world_model.WorldModel(tmp_path / "world.db").create_goal("bob-only", owner="user:bob")

    t = _client().get("/start", headers={"Authorization": "Bearer alice"}).text
    assert "0 of 3 done" in t
