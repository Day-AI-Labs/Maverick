"""Chrome i18n (fr/de/ja/zh) + accessibility font axis (dyslexia-friendly)."""
from __future__ import annotations

from fastapi.testclient import TestClient
from maverick_dashboard import i18n
from maverick_dashboard.app import app

client = TestClient(app)


def test_catalog_complete_for_all_languages():
    # Seed languages (community-contributed, intentionally partial) are
    # exempt from full coverage; t() falls back to English for their gaps.
    for key, entry in i18n.MESSAGES.items():
        for lang in i18n.LANGS:
            if lang in i18n.SEED_LANGS:
                continue
            assert entry.get(lang), f"{key} missing {lang}"


def test_t_fallbacks():
    assert i18n.t("nav.goals", "fr") == "Objectifs"
    assert i18n.t("nav.goals", "xx") == "Goals"   # unknown lang -> en
    assert i18n.t("nope.key", "fr") == "nope.key"  # unknown key -> key


def test_lang_resolution_param_cookie_header():
    class _Req:
        def __init__(self, q=None, c=None, h=None):
            self.query_params = {"lang": q} if q else {}
            self.cookies = {"mvk_lang": c} if c else {}
            self.headers = {"Accept-Language": h} if h else {}

    assert i18n.resolve_lang(_Req(q="ja")) == "ja"
    assert i18n.resolve_lang(_Req(c="de")) == "de"
    assert i18n.resolve_lang(_Req(h="zh-CN,zh;q=0.9")) == "zh"
    assert i18n.resolve_lang(_Req()) == "en"
    assert i18n.resolve_lang(_Req(q="xx", h="pt-BR")) == "en"


def test_lang_param_translates_chrome_and_sets_cookie():
    r = client.get("/", params={"lang": "fr"})
    assert r.status_code == 200
    assert 'lang="fr"' in r.text
    assert "mvk_lang=fr" in r.headers.get("set-cookie", "")
    r2 = client.get("/", params={"lang": "ja"})
    assert 'lang="ja"' in r2.text


def test_font_axis_cookie_and_body_class():
    r = client.get("/", params={"font": "dyslexic"})
    assert r.status_code == 200
    assert "font-dyslexic" in r.text
    assert "mvk_font=dyslexic" in r.headers.get("set-cookie", "")
    # Bogus values are ignored (no cookie, default class) -- fresh client so
    # the previous request's cookie doesn't mask the fallback.
    fresh = TestClient(app)
    r2 = fresh.get("/", params={"font": "comic"})
    assert "mvk_font" not in r2.headers.get("set-cookie", "")
    assert 'font-default' in r2.text


def test_font_and_theme_compose():
    r = client.get("/", params={"font": "dyslexic", "theme": "hicontrast"})
    assert "theme-hicontrast" in r.text and "font-dyslexic" in r.text
