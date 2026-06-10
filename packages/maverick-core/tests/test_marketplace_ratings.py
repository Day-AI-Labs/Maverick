"""Marketplace ratings: catalog rating fields, the local ledger, CLI surface."""
from __future__ import annotations

import pytest
from click.testing import CliRunner
from maverick.catalog import CatalogEntry
from maverick.marketplace_ratings import RatingsLedger, stars_bar


def test_catalog_entry_parses_ratings():
    e = CatalogEntry.from_dict("templates", {
        "name": "x", "source": "https://h/x.md", "rating": 4.4, "ratings_count": 12,
    })
    assert e.rating == 4.4 and e.ratings_count == 12
    assert e.to_dict()["rating"] == 4.4


def test_catalog_entry_rating_clamped_and_defensive():
    e = CatalogEntry.from_dict("templates", {"name": "x", "source": "s", "rating": 99})
    assert e.rating == 5.0
    bad = CatalogEntry.from_dict("templates", {"name": "x", "source": "s",
                                               "rating": "five", "ratings_count": "many"})
    assert bad.rating == 0.0 and bad.ratings_count == 0
    # Unrated entries don't emit rating keys.
    assert "rating" not in CatalogEntry.from_dict(
        "templates", {"name": "x", "source": "s"}).to_dict()


def test_ledger_rate_and_read(tmp_path):
    led = RatingsLedger(path=tmp_path / "r.json")
    led.rate("templates", "deploy-vps", 5, "great")
    mine = led.my_rating("templates", "deploy-vps")
    assert mine["stars"] == 5 and mine["comment"] == "great"
    assert led.my_rating("templates", "other") is None
    # Re-rating overwrites.
    led.rate("templates", "deploy-vps", 3)
    assert led.my_rating("templates", "deploy-vps")["stars"] == 3


def test_ledger_validation(tmp_path):
    led = RatingsLedger(path=tmp_path / "r.json")
    with pytest.raises(ValueError):
        led.rate("templates", "x", 0)
    with pytest.raises(ValueError):
        led.rate("templates", "x", 6)
    with pytest.raises(ValueError):
        led.rate("bogus-kind", "x", 3)
    with pytest.raises(ValueError):
        led.rate("templates", "  ", 3)


def test_ledger_export_for_submission(tmp_path):
    import json
    led = RatingsLedger(path=tmp_path / "r.json")
    led.rate("templates", "a", 4, "comment stays local")
    led.rate("skills", "b", 2)
    out = json.loads(led.export_for_submission())
    assert out == {"templates": {"a": 4}, "skills": {"b": 2}}


def test_stars_bar():
    assert stars_bar(4.4, 12) == "★★★★☆ (12)"
    assert stars_bar(5, 0) == "★★★★★"
    assert stars_bar(0, 0) == "unrated"


def test_cli_rate_and_export(tmp_path, monkeypatch):
    import maverick.marketplace_ratings as mr
    from maverick import cli as cli_mod
    real = mr.RatingsLedger
    monkeypatch.setattr(mr, "RatingsLedger",
                        lambda path=None: real(path=tmp_path / "r.json"))
    r = CliRunner().invoke(cli_mod.main, ["template", "rate", "deploy-vps", "4"])
    assert r.exit_code == 0, r.output
    assert "★★★★☆" in r.output
    r2 = CliRunner().invoke(cli_mod.main, ["template", "ratings-export"])
    assert '"deploy-vps": 4' in r2.output
    r3 = CliRunner().invoke(cli_mod.main, ["template", "rate", "x", "9"])
    assert r3.exit_code == 2
