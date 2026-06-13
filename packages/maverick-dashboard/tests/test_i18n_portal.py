"""i18n community portal: scaffold, validation, external-catalog loading."""
from __future__ import annotations

import json

from maverick_dashboard import i18n
from maverick_dashboard import i18n_portal as p


def test_scaffold_covers_every_reference_key():
    cat = p.scaffold("es")
    assert set(cat) == set(p.reference_keys())
    # seeded with the English text so a partial translation still validates
    assert cat["nav.goals"] == i18n.MESSAGES["nav.goals"]["en"]
    assert p.validate_catalog("es", cat) == []


def test_validate_flags_missing_and_unknown_keys():
    cat = p.scaffold("es")
    cat.pop("nav.goals")
    cat["nav.bogus"] = "x"
    problems = p.validate_catalog("es", cat)
    assert any("missing key: nav.goals" in x for x in problems)
    assert any("unknown key" in x and "nav.bogus" in x for x in problems)


def test_validate_flags_blank_and_bad_lang():
    cat = p.scaffold("es")
    cat["nav.goals"] = "   "
    assert any("non-empty string" in x for x in p.validate_catalog("es", cat))
    assert any("invalid language code" in x
               for x in p.validate_catalog("Spanish!", p.scaffold("es")))


def test_validate_flags_placeholder_mismatch(monkeypatch):
    # Reference key with a placeholder; a translation dropping it is rejected.
    monkeypatch.setitem(i18n.MESSAGES, "greet", {"en": "Hi {name}"})
    good = p.scaffold("es")
    good["greet"] = "Hola {name}"
    assert "greet" not in " ".join(p.validate_catalog("es", good))
    bad = dict(good)
    bad["greet"] = "Hola"
    assert any("placeholder mismatch" in x for x in p.validate_catalog("es", bad))


def test_pt_br_regional_code_valid():
    assert p.validate_catalog("pt-br", p.scaffold("pt-br")) == []


def test_load_external_catalogs(tmp_path):
    (tmp_path / "es.json").write_text(
        json.dumps(p.scaffold("es"), ensure_ascii=False), encoding="utf-8")
    loaded = p.load_external_catalogs(tmp_path)
    assert "es" in loaded
    assert loaded["es"]["nav.goals"] == i18n.MESSAGES["nav.goals"]["en"]


def test_invalid_external_catalog_skipped(tmp_path):
    (tmp_path / "xx.json").write_text("{ not json", encoding="utf-8")
    (tmp_path / "es.json").write_text(
        json.dumps({"nav.goals": "Objetivos"}), encoding="utf-8")  # incomplete
    loaded = p.load_external_catalogs(tmp_path)
    assert loaded == {}  # both skipped: one malformed, one incomplete


def test_merged_messages_adds_external_language(tmp_path):
    cat = p.scaffold("es")
    cat["nav.goals"] = "Objetivos"
    (tmp_path / "es.json").write_text(json.dumps(cat, ensure_ascii=False),
                                      encoding="utf-8")
    merged = p.merged_messages(tmp_path)
    assert merged["nav.goals"]["es"] == "Objetivos"
    # built-in languages untouched
    assert merged["nav.goals"]["en"] == i18n.MESSAGES["nav.goals"]["en"]
    # i18n.t reads the same {key: {lang: text}} shape merged_messages produces
    from maverick_dashboard.i18n import t
    assert t("nav.goals", "fr") == i18n.MESSAGES["nav.goals"]["fr"]


def test_available_languages(tmp_path):
    cat = p.scaffold("es")
    (tmp_path / "es.json").write_text(json.dumps(cat, ensure_ascii=False),
                                      encoding="utf-8")
    langs = p.available_languages(tmp_path)
    assert "en" in langs and "es" in langs
    assert langs == sorted(langs)


def test_no_portal_dir_is_empty(monkeypatch):
    monkeypatch.delenv("MAVERICK_I18N_DIR", raising=False)
    monkeypatch.setattr("maverick.config.load_config", dict)
    assert p.load_external_catalogs() == {}
    assert p.available_languages() == sorted(i18n.LANGS)
