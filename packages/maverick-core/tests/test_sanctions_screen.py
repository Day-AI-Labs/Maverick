"""Sanctions screening (finance-agent-suite §2.6)."""
from __future__ import annotations

import maverick.tools.sanctions_screen as sanctions_mod
import pytest
from maverick.tools.sanctions_screen import load_list, normalize, sanctions_screen, screen

_SDN = ["Evil Corp LLC", "Bad Actor", "Sanctioned Holdings Ltd", "John Q Public"]


def test_normalize():
    assert normalize("  Evil Corp, LLC. ") == "evil corp llc"


def test_exact_match():
    r = screen("evil corp llc", _SDN)
    assert r["match"] is True
    assert r["hits"][0]["score"] == 1.0
    assert r["hits"][0]["name"] == "Evil Corp LLC"


def test_clear_when_no_match():
    r = screen("Totally Legit Inc", _SDN)
    assert r["match"] is False
    assert r["hits"] == []


def test_token_overlap_below_threshold_clears():
    # shares one token with "John Q Public" but not enough at 0.85
    assert screen("John Smith", _SDN, threshold=0.85)["match"] is False


def test_token_overlap_match_at_lower_threshold():
    r = screen("Sanctioned Holdings", _SDN, threshold=0.6)
    assert r["match"] is True
    assert any("Sanctioned Holdings" in h["name"] for h in r["hits"])


def test_screen_rejects_unsafe_thresholds():
    for threshold in (-1, 0, 1.1):
        with pytest.raises(ValueError):
            screen("Totally Legit Inc", _SDN, threshold=threshold)


def test_tool_rejects_negative_threshold_without_leaking_list(tmp_path, monkeypatch):
    p = tmp_path / "sdn.txt"
    p.write_text("Secret Watchlist One\nSecret Watchlist Two\n", encoding="utf-8")
    monkeypatch.setattr(sanctions_mod, "_list_path", lambda: p)

    out = sanctions_screen().fn({"name": "Totally Legit Inc", "threshold": -1})

    assert out.startswith("ERROR: threshold")
    assert "Secret Watchlist" not in out


def test_load_list_newline(tmp_path):
    p = tmp_path / "sdn.txt"
    p.write_text("Evil Corp LLC\nBad Actor\n\n", encoding="utf-8")
    assert load_list(p) == ["Evil Corp LLC", "Bad Actor"]


def test_load_list_json(tmp_path):
    p = tmp_path / "sdn.json"
    p.write_text('{"names": ["A Co", "B Co"]}', encoding="utf-8")
    assert load_list(p) == ["A Co", "B Co"]


def test_load_list_missing(tmp_path):
    assert load_list(tmp_path / "nope.txt") == []


def test_tool_requires_name():
    assert sanctions_screen().fn({"name": ""}).startswith("ERROR")


def test_tool_errors_without_list(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    out = sanctions_screen().fn({"name": "Anyone"})
    assert out.startswith("ERROR") and "sanctions list" in out
