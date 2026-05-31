"""`maverick answer <id>` must not report success for a non-existent question.

A typo'd question id used to print 'answered #99999' and exit 0 (the UPDATE
silently matched zero rows). world.answer() now returns whether a row matched
so the CLI can flag the bad id.
"""
from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner
from maverick.cli import main
from maverick.world_model import open_world


def test_answer_nonexistent_question_errors(tmp_path: Path):
    db = tmp_path / "world.db"
    result = CliRunner().invoke(main, ["--db", str(db), "answer", "99999", "hello"])
    assert result.exit_code == 1
    assert "no such question" in result.output


def test_answer_existing_question_succeeds(tmp_path: Path):
    db = tmp_path / "world.db"
    w = open_world(db)
    gid = w.create_goal("g", "")
    qid = w.ask("Which one?", goal_id=gid)

    result = CliRunner().invoke(main, ["--db", str(db), "answer", str(qid), "this one"])
    assert result.exit_code == 0
    assert f"answered #{qid}" in result.output


def test_world_answer_returns_match_flag(tmp_path: Path):
    w = open_world(tmp_path / "world.db")
    gid = w.create_goal("g", "")
    qid = w.ask("Q?", goal_id=gid)
    assert w.answer(qid, "a") is True
    assert w.answer(999999, "a") is False
