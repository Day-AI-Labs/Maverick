"""RTL language support: dir attribute, logical CSS, and the Arabic
community-seed catalog (genuinely translated subset, English fallback)."""
from __future__ import annotations

from fastapi.testclient import TestClient
from maverick_dashboard import i18n
from maverick_dashboard.app import app

client = TestClient(app)


def test_rtl_lang_set_covers_the_four_scripts():
    assert {"ar", "he", "fa", "ur"} <= set(i18n.RTL_LANGS)
    for code in ("ar", "he", "fa", "ur", "ar-EG"):
        assert i18n.dir_for(code) == "rtl"
    for code in ("en", "fr", "de", "ja", "zh", "", None):
        assert i18n.dir_for(code or "") == "ltr"


def test_arabic_page_carries_dir_rtl_and_lang():
    r = client.get("/goals", params={"lang": "ar"})
    assert r.status_code == 200
    assert 'lang="ar"' in r.text
    assert 'dir="rtl"' in r.text
    assert "mvk_lang=ar" in r.headers.get("set-cookie", "")


def test_ltr_languages_keep_dir_ltr():
    fresh = TestClient(app)
    r = fresh.get("/goals", params={"lang": "fr"})
    assert 'lang="fr"' in r.text and 'dir="ltr"' in r.text
    r2 = fresh.get("/goals", params={"lang": "en"})
    assert 'dir="ltr"' in r2.text


def test_rtl_cookie_persists_direction():
    fresh = TestClient(app)
    fresh.get("/", params={"lang": "ar"})  # sets the cookie
    r = fresh.get("/goals")                # no param: cookie drives it
    assert 'dir="rtl"' in r.text and 'lang="ar"' in r.text


def test_base_layout_uses_logical_properties():
    r = client.get("/")
    # the chrome CSS flips with dir instead of hard-coding left/right
    assert "inset-inline-start" in r.text
    assert "margin-inline-start" in r.text
    assert "text-align: start" in r.text


def test_lang_select_offers_arabic():
    r = client.get("/")
    assert 'value="ar"' in r.text
    assert "العربية" in r.text


def test_arabic_seed_is_partial_and_genuine():
    """ar is a community-seed catalog: a handful of real translations,
    English fallback for the rest — never machine-translated to completion."""
    assert "ar" in i18n.SEED_LANGS
    assert "ar" in i18n.LANGS
    # genuinely translated seed keys
    assert i18n.t("nav.goals", "ar") == "الأهداف"
    assert i18n.t("label.language", "ar") == "اللغة"
    assert i18n.t("action.search", "ar") == "بحث"
    # unseeded keys fall back to English, never blank
    assert i18n.t("label.theme", "ar") == "Theme"
    seeded = sum(1 for entry in i18n.MESSAGES.values() if entry.get("ar"))
    assert 0 < seeded < len(i18n.MESSAGES)  # partial by design


def test_arabic_seed_strings_render_in_chrome():
    r = client.get("/", params={"lang": "ar"})
    # the language-select aria-label uses t('label.language')
    assert "اللغة" in r.text
