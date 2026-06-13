"""Adaptive UI density (?density= / mvk_density) + pluggable operator themes."""
from __future__ import annotations

from fastapi.testclient import TestClient
from maverick_dashboard import themes as themes_mod
from maverick_dashboard.app import app, resolve_density

client = TestClient(app)


class _Req:
    def __init__(self, q=None, c=None):
        self.query_params = {"density": q} if q else {}
        self.cookies = {"mvk_density": c} if c else {}


# ----------------------------- density -----------------------------


def test_resolve_density_param_cookie_default():
    assert resolve_density(_Req(q="compact")) == "compact"
    assert resolve_density(_Req(c="compact")) == "compact"
    assert resolve_density(_Req(q="comfortable", c="compact")) == "comfortable"
    assert resolve_density(_Req()) == "comfortable"
    assert resolve_density(_Req(q="dense")) == "comfortable"  # bogus -> default


def test_resolve_density_config_fallback(monkeypatch):
    import maverick.config as cfg
    monkeypatch.setattr(cfg, "load_config", lambda: {"dashboard": {"density": "compact"}})
    assert resolve_density(_Req()) == "compact"


def test_density_param_sets_body_class_and_cookie():
    r = client.get("/", params={"density": "compact"})
    assert r.status_code == 200
    assert "density-compact" in r.text
    assert "mvk_density=compact" in r.headers.get("set-cookie", "")
    # Bogus values: no cookie, default class.
    fresh = TestClient(app)
    r2 = fresh.get("/", params={"density": "supertight"})
    assert "mvk_density" not in r2.headers.get("set-cookie", "")
    assert "density-comfortable" in r2.text


def test_compact_css_ships_in_base():
    r = client.get("/")
    assert "body.density-compact" in r.text
    assert 'id="density-select"' in r.text


# ----------------------------- pluggable themes -----------------------------

_GOOD = {"bg": "#101020", "panel": "#181830", "text": "#e0e0f0", "accent": "#7aa2f7"}


def _with_themes(monkeypatch, themes: dict):
    import maverick.config as cfg
    monkeypatch.setattr(cfg, "load_config", lambda: {"dashboard": {"themes": themes}})


def test_custom_themes_validation(monkeypatch):
    _with_themes(monkeypatch, {
        "midnight": _GOOD,
        "shorthex": {**_GOOD, "accent": "#fff"},                      # 3-digit hex OK
        "badhex": {**_GOOD, "bg": "red"},                             # not #hex
        "inject": {**_GOOD, "bg": "#fff; } body { background: url(x)"},  # CSS injection
        "dark": _GOOD,                                                # shadows builtin
        "Bad Name!": _GOOD,                                           # invalid slug
        "missing": {"bg": "#000", "panel": "#111", "text": "#fff"},   # no accent
        "extras": {**_GOOD, "sneaky": "#000"},                        # unknown key
    })
    out = themes_mod.custom_themes()
    assert set(out) == {"midnight", "shorthex"}


def test_theme_css_renders_validated_variables():
    css = themes_mod.theme_css({"midnight": _GOOD})
    assert css == ("body.theme-midnight { --bg: #101020; --panel: #181830; "
                   "--text: #e0e0f0; --accent: #7aa2f7; }")


def test_custom_theme_selectable_like_builtins(monkeypatch):
    _with_themes(monkeypatch, {"midnight": _GOOD})
    r = client.get("/", params={"theme": "midnight"})
    assert r.status_code == 200
    assert "theme-midnight" in r.text                       # body class
    assert "--bg: #101020" in r.text                        # CSS vars block
    assert 'value="midnight"' in r.text                     # switcher option
    assert "mvk_theme=midnight" in r.headers.get("set-cookie", "")


def test_unknown_theme_still_falls_back_to_dark(monkeypatch):
    _with_themes(monkeypatch, {"midnight": _GOOD})
    fresh = TestClient(app)
    r = fresh.get("/", params={"theme": "nope"})
    assert "theme-dark" in r.text
    assert "mvk_theme" not in r.headers.get("set-cookie", "")


def test_no_config_themes_is_default_off(monkeypatch):
    import maverick.config as cfg
    monkeypatch.setattr(cfg, "load_config", dict)
    assert themes_mod.custom_themes() == {}
    fresh = TestClient(app)
    r = fresh.get("/")
    assert "body.theme-midnight" not in r.text
