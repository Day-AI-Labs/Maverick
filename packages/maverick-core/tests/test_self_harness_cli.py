"""Operator CLI for the self-harness learned guidance: `maverick self-harness`.

The loop was invisible from the command line -- an operator could not see what
their agents had learned or roll any of it back. This pins the inspection/undo
surface: ``harness show`` (what was learned, per model), ``harness log`` (the
audit trail of learn/forget events), and ``harness forget`` (the rollback).

Every store/audit path is redirected under a tmp ``MAVERICK_HOME`` so the tests
never touch a real install.
"""
from __future__ import annotations

import json
import re

import pytest
from click.testing import CliRunner
from maverick import self_harness as sh
from maverick.cli import main


@pytest.fixture
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path))
    monkeypatch.setenv("MAVERICK_SELF_HARNESS", "1")
    return tmp_path


def _seed(model="claude-x", lines=("verify the precondition", "check inputs first")):
    block = "Operating guidance learned for this model:\n" + "\n".join(f"- {x}" for x in lines)
    sh._write_addenda({model: block}, sh._store_path())


def test_show_lists_learned_guidance(_home):
    _seed()
    r = CliRunner().invoke(main, ["self-harness", "show"])
    assert r.exit_code == 0, r.output
    assert "claude-x" in r.output
    assert "verify the precondition" in r.output and "check inputs first" in r.output


def test_show_json_is_machine_readable(_home):
    _seed()
    r = CliRunner().invoke(main, ["self-harness", "show", "--json"])
    assert r.exit_code == 0, r.output
    data = json.loads(r.output)
    assert data == {"claude-x": ["verify the precondition", "check inputs first"]}


def test_show_filters_by_model(_home):
    _seed("model-a", ["line a"])
    sh._write_addenda({**sh.load_addenda(sh._store_path()),
                       "model-b": "Operating guidance learned for this model:\n- line b"},
                      sh._store_path())
    r = CliRunner().invoke(main, ["self-harness", "show", "--model", "model-a"])
    assert "line a" in r.output and "line b" not in r.output


def test_show_warns_when_disabled(_home, monkeypatch):
    monkeypatch.delenv("MAVERICK_SELF_HARNESS")        # feature OFF
    _seed()
    r = CliRunner().invoke(main, ["self-harness", "show"])
    assert r.exit_code == 0
    assert "OFF" in r.output                            # operator is told it won't recall
    assert "verify the precondition" in r.output        # but can still inspect it


def test_show_empty(_home):
    r = CliRunner().invoke(main, ["self-harness", "show"])
    assert r.exit_code == 0 and "no learned guidance" in r.output


def test_forget_removes_all_for_model(_home):
    _seed()
    r = CliRunner().invoke(main, ["self-harness", "forget", "--model", "claude-x", "--yes"])
    assert r.exit_code == 0 and "removed" in r.output
    assert sh.list_learned() == {}


def test_forget_one_line_keeps_the_rest(_home):
    _seed()
    r = CliRunner().invoke(
        main, ["self-harness", "forget", "--model", "claude-x",
               "--line", "check inputs first", "--yes"])
    assert r.exit_code == 0 and "removed" in r.output
    assert sh.list_learned() == {"claude-x": ["verify the precondition"]}


def test_forget_aborts_without_confirmation(_home):
    _seed()
    r = CliRunner().invoke(main, ["self-harness", "forget", "--model", "claude-x"], input="n\n")
    assert "aborted" in r.output
    assert sh.list_learned() == {"claude-x": ["verify the precondition", "check inputs first"]}


def test_forget_nothing_to_remove(_home):
    r = CliRunner().invoke(main, ["self-harness", "forget", "--model", "ghost", "--yes"])
    assert r.exit_code == 0 and "nothing to remove" in r.output


def test_log_smoke_and_records_forget(_home):
    _seed()
    # a forget is audited; the log surface should not error and ideally show it.
    CliRunner().invoke(main, ["self-harness", "forget", "--model", "claude-x", "--yes"])
    r = CliRunner().invoke(main, ["self-harness", "log"])
    assert r.exit_code == 0, r.output


def test_log_renders_human_readable_timestamp(_home):
    # The audit ts is an epoch float; the operator-facing log must render it as a
    # calendar timestamp, not a raw 1.78e9 float (which answers "when?" with noise).
    _seed()
    CliRunner().invoke(main, ["self-harness", "forget", "--model", "claude-x", "--yes"])
    r = CliRunner().invoke(main, ["self-harness", "log"])
    assert r.exit_code == 0, r.output
    assert re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", r.output), r.output
    assert not re.search(r"\b1[0-9]{9}\.\d", r.output), r.output  # no raw epoch float


def test_preview_explains_scoped_exclusion(_home):
    # All-scoped failures are excluded by the trace-poisoning guard, so preview
    # must say "0 eligible" + explain why, not a bare "no weaknesses" that reads
    # as "this model never fails".
    from maverick import reflexion
    for i in range(4):
        reflexion.record(goal_text=f"export ledger {i}", failure_class="timeout",
                         failure_msg="timed out", reflection="x",
                         model_id="claude-x", channel="slack:x", user_id="u1")
    r = CliRunner().invoke(main, ["self-harness", "preview", "--model", "claude-x"])
    assert r.exit_code == 0, r.output
    assert "0 eligible" in r.output
    assert "excluded by design" in r.output


def test_preview_counts_eligible_unscoped(_home):
    # Unscoped failures ARE eligible; if they just don't meet min-support, the
    # count reflects that (and no scoped-exclusion note is shown).
    from maverick import reflexion
    for i in range(4):
        reflexion.record(goal_text=f"export ledger {i}", failure_class="timeout",
                         failure_msg="timed out", reflection="x", model_id="claude-x")
    r = CliRunner().invoke(
        main, ["self-harness", "preview", "--model", "claude-x", "--min-support", "99"])
    assert r.exit_code == 0, r.output
    assert "4 eligible" in r.output
    assert "excluded by design" not in r.output


def test_preview_rejects_nonpositive_min_support(_home):
    # min_support < 1 disables mining; the command must say so loudly instead of
    # printing "No recurring weaknesses" (which reads as "your model has none").
    for bad in ("0", "-3"):
        r = CliRunner().invoke(main, ["self-harness", "preview", "--min-support", bad])
        assert r.exit_code != 0, r.output
        assert "min-support" in r.output.lower(), r.output


def _seed_with_meta(model, line, **prov):
    block = "Operating guidance learned for this model:\n- " + line
    sh._write_addenda({model: block}, sh._store_path())
    rec = {"model_id": model, "text": line, "learned_at": 1700000000.0,
           "updated_at": 1700000000.0, **prov}
    sh._write_line_meta({sh._line_id(model, line): rec}, sh._store_path())


def test_show_verbose_renders_provenance(_home):
    _seed_with_meta("claude-x", "verify the token first", signature="auth: 401 expired",
                    rationale="targets 4 'auth' failures", held_out_delta=0.2, samples=8)
    r = CliRunner().invoke(main, ["self-harness", "show", "--verbose"])
    assert r.exit_code == 0, r.output
    assert "auth: 401 expired" in r.output
    assert "held-out +0.2 over 8 samples" in r.output
    assert "2023-11" in r.output                         # learned date rendered


def test_retire_cli_removes_stale_line(_home):
    _seed_with_meta("claude-x", "stale line")             # dated 2023 -> stale
    r = CliRunner().invoke(
        main, ["self-harness", "retire", "--older-than-days", "1", "--yes"])
    assert r.exit_code == 0, r.output
    assert "retired 1 line" in r.output
    assert sh.recall_addendum("claude-x", sh._store_path()) == ""


def test_retire_cli_aborts_without_confirmation(_home):
    _seed_with_meta("claude-x", "stale line")
    r = CliRunner().invoke(
        main, ["self-harness", "retire", "--older-than-days", "1"], input="n\n")
    assert "aborted" in r.output
    assert "stale line" in sh.recall_addendum("claude-x", sh._store_path())


def test_show_verbose_renders_usage(_home):
    _seed_with_meta("claude-x", "verify the token first", signature="auth: 401",
                    held_out_delta=0.2, samples=8, last_recalled_at=1700500000.0)
    r = CliRunner().invoke(main, ["self-harness", "show", "--verbose"])
    assert r.exit_code == 0, r.output
    assert "last recalled" in r.output


def test_conflicts_cli_flags_contradictions(_home):
    block = ("Operating guidance learned for this model:\n"
             "- Prefer streaming for large exports\n"
             "- Avoid streaming for large exports")
    sh._write_addenda({"claude-x": block}, sh._store_path())
    r = CliRunner().invoke(main, ["self-harness", "conflicts"])
    assert r.exit_code == 0, r.output
    assert "possible conflict" in r.output
    assert "Prefer streaming" in r.output and "Avoid streaming" in r.output


def test_conflicts_cli_clean(_home):
    sh._write_addenda(
        {"claude-x": "Operating guidance learned for this model:\n- Verify the token first"},
        sh._store_path())
    r = CliRunner().invoke(main, ["self-harness", "conflicts"])
    assert r.exit_code == 0 and "no conflicting guidance" in r.output
