"""Per-role credit tracking — the routing consumer of CSCA."""
from __future__ import annotations

from maverick import role_stats


def test_record_and_average(tmp_path):
    p = tmp_path / "role_stats.json"
    role_stats.record("researcher", 0.6, path=p)
    role_stats.record("researcher", 0.4, path=p)
    role_stats.record("writer", -0.2, path=p)
    top = role_stats.top_roles(min_runs=1, path=p)
    assert top[0][0] == "researcher"
    assert abs(top[0][1] - 0.5) < 1e-9  # (0.6+0.4)/2
    # writer present but ranked below (negative avg)
    assert ("writer", -0.2) in top


def test_record_credit_maps_names_to_roles(tmp_path):
    p = tmp_path / "role_stats.json"
    cmap = {"researcher-1": 0.8, "coder-2": 0.1}
    name_to_role = {"researcher-1": "researcher", "coder-2": "coder"}
    role_stats.record_credit(cmap, name_to_role, path=p)
    top = dict(role_stats.top_roles(min_runs=1, path=p))
    assert top["researcher"] == 0.8 and top["coder"] == 0.1


def test_min_runs_filters_thin_history(tmp_path):
    p = tmp_path / "role_stats.json"
    role_stats.record("rare", 0.9, path=p)  # only 1 run
    assert role_stats.top_roles(min_runs=2, path=p) == []


def test_guidance_requires_credit_enabled(tmp_path, monkeypatch):
    p = tmp_path / "role_stats.json"
    role_stats.record("researcher", 0.7, path=p)
    role_stats.record("researcher", 0.7, path=p)
    # Off by default -> no guidance even with positive history.
    monkeypatch.delenv("MAVERICK_CREDIT", raising=False)
    monkeypatch.setattr("maverick.credit._settings", lambda: dict(__import__("maverick").credit._DEFAULTS))
    assert role_stats.guidance(path=p) is None
    # Enabled -> guidance names the high-credit role.
    monkeypatch.setenv("MAVERICK_CREDIT", "1")
    g = role_stats.guidance(path=p)
    assert g and "researcher" in g


def test_guidance_none_when_no_positive_roles(tmp_path, monkeypatch):
    p = tmp_path / "role_stats.json"
    role_stats.record("writer", -0.5, path=p)
    role_stats.record("writer", -0.3, path=p)
    monkeypatch.setenv("MAVERICK_CREDIT", "1")
    assert role_stats.guidance(path=p) is None
