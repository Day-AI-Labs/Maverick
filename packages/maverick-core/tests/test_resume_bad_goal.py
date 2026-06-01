"""`maverick resume --goal-id <bad>` must exit non-zero, not silently succeed.

An explicit, non-existent --goal-id printed run_goal's "no such goal: N" and
exited 0 (a script couldn't tell it failed; export exits 2 for the same case).
"""
from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner
from maverick.cli import main


def test_resume_nonexistent_goal_exits_nonzero(tmp_path: Path):
    db = tmp_path / "world.db"
    result = CliRunner(env={"OPENAI_API_KEY": "sk-x"}).invoke(
        main, ["--db", str(db), "resume", "--goal-id", "99999"]
    )
    assert result.exit_code == 2
    assert "no such goal" in result.output


def test_resume_no_goal_is_graceful(tmp_path: Path):
    db = tmp_path / "world.db"
    result = CliRunner(env={"OPENAI_API_KEY": "sk-x"}).invoke(
        main, ["--db", str(db), "resume"]
    )
    # Nothing to resume is not an error.
    assert result.exit_code == 0
    assert "no active or blocked goal" in result.output
