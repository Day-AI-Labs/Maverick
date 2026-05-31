"""`maverick skill stats` / `maverick skill evict`: the curation surface.

Driven with click's CliRunner; skills + stats are seeded under the test's
isolated HOME (the autouse fixture points Path.home() at tmp_path).
"""
from __future__ import annotations

from click.testing import CliRunner

from maverick import skill_stats as ss
from maverick.cli import main
from maverick.skills import SKILLS_DIR


def _seed_skill(name: str, confidence: float = 1.0) -> None:
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    (SKILLS_DIR / f"{name}.md").write_text(
        f"---\nname: {name}\ndistilled_confidence: {confidence}\n"
        f"triggers:\n  - {name}\n---\n\n# Body\n\ndo {name}\n",
        encoding="utf-8",
    )


def test_curation_subcommands_registered():
    skill = main.commands["skill"]
    assert "stats" in skill.commands
    assert "evict" in skill.commands


def test_stats_empty_library():
    runner = CliRunner()
    result = runner.invoke(main, ["skill", "stats"])
    assert result.exit_code == 0, result.output
    assert "no skills yet" in result.output


def test_stats_shows_skill_and_track_record(tmp_path, monkeypatch):
    stats = tmp_path / "stats.json"
    monkeypatch.setattr(ss, "DEFAULT_PATH", stats)
    _seed_skill("deploy-app", confidence=0.9)
    for _ in range(4):
        ss.record_use(["deploy-app"], path=stats)
        ss.record_outcome(["deploy-app"], success=False, path=stats)

    runner = CliRunner()
    result = runner.invoke(main, ["skill", "stats"])
    assert result.exit_code == 0, result.output
    assert "deploy-app" in result.output
    assert "decay" in result.output


def test_evict_dry_run_lists_candidates(tmp_path, monkeypatch):
    stats = tmp_path / "stats.json"
    monkeypatch.setattr(ss, "DEFAULT_PATH", stats)
    _seed_skill("loser")
    for _ in range(6):
        ss.record_use(["loser"], path=stats)
        ss.record_outcome(["loser"], success=False, path=stats)

    runner = CliRunner()
    result = runner.invoke(main, ["skill", "evict"])
    assert result.exit_code == 0, result.output
    assert "loser" in result.output
    assert "--yes to remove" in result.output
    # Dry run: the skill file must still exist.
    assert (SKILLS_DIR / "loser.md").exists()


def test_evict_yes_removes(tmp_path, monkeypatch):
    stats = tmp_path / "stats.json"
    monkeypatch.setattr(ss, "DEFAULT_PATH", stats)
    _seed_skill("loser")
    _seed_skill("keeper")
    for _ in range(6):
        ss.record_use(["loser"], path=stats)
        ss.record_outcome(["loser"], success=False, path=stats)
        ss.record_use(["keeper"], path=stats)
        ss.record_outcome(["keeper"], success=True, path=stats)

    runner = CliRunner()
    result = runner.invoke(main, ["skill", "evict", "--yes"])
    assert result.exit_code == 0, result.output
    assert "removed: loser" in result.output
    assert not (SKILLS_DIR / "loser.md").exists()
    assert (SKILLS_DIR / "keeper.md").exists()


def test_evict_no_candidates(tmp_path, monkeypatch):
    stats = tmp_path / "stats.json"
    monkeypatch.setattr(ss, "DEFAULT_PATH", stats)
    _seed_skill("untried")
    runner = CliRunner()
    result = runner.invoke(main, ["skill", "evict"])
    assert result.exit_code == 0
    assert "no eviction candidates" in result.output
