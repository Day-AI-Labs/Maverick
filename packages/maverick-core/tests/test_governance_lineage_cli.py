"""`maverick governance lineage|impact` -- the governed-action audit trail CLI."""
from __future__ import annotations

import json

from click.testing import CliRunner


def test_lineage_and_impact_added_to_governance_group():
    # Must EXTEND the existing governance group, not replace it.
    from maverick.cli import main
    sub = set(main.commands["governance"].commands)
    assert {"show", "check", "lineage", "impact"} <= sub


def test_governance_lineage_shows_and_verifies(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from maverick import governed_actions as ga
    ga.record_tool_lineage(5, "write_file", {"p": "a"}, skills=("sk",), sources=("kb",))
    ga.record_tool_lineage(5, "shell", {"cmd": "x"}, skills=("sk",))
    from maverick.cli import main
    r = CliRunner().invoke(main, ["governance", "lineage", "5"])
    assert r.exit_code == 0, r.output
    assert "write_file" in r.output and "shell" in r.output and "VALID" in r.output


def test_governance_lineage_empty_goal(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from maverick.cli import main
    r = CliRunner().invoke(main, ["governance", "lineage", "999"])
    assert r.exit_code == 0 and "no recorded actions" in r.output


def test_governance_impact_text_and_json(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from maverick import governed_actions as ga
    ga.record_tool_lineage(7, "shell", {"cmd": "x"}, skills=("sk",), sources=("kb-9",))
    from maverick.cli import main
    text = CliRunner().invoke(main, ["governance", "impact", "sk", "--kind", "skill"])
    assert text.exit_code == 0 and "goal 7" in text.output
    js = CliRunner().invoke(main, ["governance", "impact", "kb-9", "--json"])
    assert js.exit_code == 0 and json.loads(js.output)[0]["goal_id"] == 7
