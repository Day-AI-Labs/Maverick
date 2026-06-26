"""`maverick skills` group: bare list + stats + evict subcommands.

`skills` became a group (invoke_without_command) so the bare command still
lists, and `skills stats` / `skills evict` expose the #436 maintenance surface.
"""
from __future__ import annotations

import pytest
from click.testing import CliRunner
from maverick.cli import main
from maverick.skill import stats as skill_stats
from maverick.skills import SKILLS_DIR

SKILL_MD = (
    "---\n"
    "name: {name}\n"
    "triggers:\n"
    "  - do a thing\n"
    "---\n"
    "\n# What it does\n\nStuff.\n"
)


@pytest.fixture
def _skills_and_stats(tmp_path, monkeypatch):
    # The autouse home-isolation fixture points Path.home() at tmp, but
    # skill_stats.DEFAULT_PATH was bound at import; repoint it explicitly.
    monkeypatch.setattr(skill_stats, "DEFAULT_PATH", tmp_path / "stats.json")
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    (SKILLS_DIR / "good.md").write_text(SKILL_MD.format(name="good"), encoding="utf-8")
    (SKILLS_DIR / "bad.md").write_text(SKILL_MD.format(name="bad"), encoding="utf-8")
    return tmp_path


def test_bare_skills_lists(_skills_and_stats):
    result = CliRunner().invoke(main, ["skills"])
    assert result.exit_code == 0
    assert "good" in result.output and "bad" in result.output


def test_skills_stats_shows_track_record(_skills_and_stats):
    for _ in range(4):
        skill_stats.record_use(["good"])
        skill_stats.record_outcome(["good"], success=True)
    result = CliRunner().invoke(main, ["skills", "stats"])
    assert result.exit_code == 0
    assert "good: uses=4 wins=4" in result.output
    assert "bad: no usage recorded" in result.output


def test_skills_evict_dry_run_lists_without_removing(_skills_and_stats):
    for _ in range(6):
        skill_stats.record_use(["bad"])
        skill_stats.record_outcome(["bad"], success=False)
    result = CliRunner().invoke(main, ["skills", "evict"])
    assert result.exit_code == 0
    assert "candidate: bad" in result.output
    assert "dry-run" in result.output
    # Nothing deleted on a dry run.
    assert (SKILLS_DIR / "bad.md").exists()


def test_skills_evict_apply_removes(_skills_and_stats):
    for _ in range(6):
        skill_stats.record_use(["bad"])
        skill_stats.record_outcome(["bad"], success=False)
    result = CliRunner().invoke(main, ["skills", "evict", "--apply"])
    assert result.exit_code == 0
    assert "removed: bad" in result.output
    assert not (SKILLS_DIR / "bad.md").exists()
    assert (SKILLS_DIR / "good.md").exists()


def test_skills_evict_no_candidates(_skills_and_stats):
    result = CliRunner().invoke(main, ["skills", "evict"])
    assert result.exit_code == 0
    assert "no eviction candidates" in result.output
