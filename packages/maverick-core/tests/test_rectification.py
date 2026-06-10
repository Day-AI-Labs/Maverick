"""Right-to-rectification (GDPR Art. 16) over a real SQLite world model."""
from __future__ import annotations

import json

import pytest
from maverick import rectification as rf
from maverick.world_model import open_world

SUBJECT = "alice@example.com"
FIXED = "alice.cooper@example.com"


def _seed(tmp_path):
    """A world holding the subject in every covered field, plus controls."""
    w = open_world(tmp_path / "world.db")
    gid = w.create_goal(
        f"Email {SUBJECT} about the report",
        "The subject ALICE@EXAMPLE.COM appears uppercased here",
    )
    w.set_goal_status(gid, "done", result="sent to Alice@Example.Com today")
    control_gid = w.create_goal("Email bob@example.com", "nothing to rectify")
    conv = w.get_or_create_conversation("cli", "u1")
    w.append_turn(conv.id, "user", f"please contact {SUBJECT} first thing")
    w.append_turn(conv.id, "assistant", "done, no address mentioned")
    w.upsert_fact("contact:primary", SUBJECT)
    w.upsert_fact("contact:other", "carol@example.com")
    return w, gid, control_gid, conv.id


def test_find_occurrences_covers_all_fields_case_insensitively(tmp_path):
    w, gid, _control, _conv = _seed(tmp_path)
    with w:
        occ = rf.find_occurrences(w, SUBJECT)
    cells = {(o["table"], o["field"]) for o in occ}
    assert cells == {
        ("goals", "title"), ("goals", "description"), ("goals", "result"),
        ("turns", "content"), ("facts", "value"),
    }
    assert len(occ) == 5
    assert all(o["id"] for o in occ)
    title_hit = next(o for o in occ if o["field"] == "title")
    assert SUBJECT in title_hit["snippet"]
    desc_hit = next(o for o in occ if o["field"] == "description")
    assert "ALICE@EXAMPLE.COM" in desc_hit["snippet"]  # matched despite casing


def test_find_occurrences_snippet_radius_and_limit(tmp_path):
    with open_world(tmp_path / "world.db") as w:
        pad = "x" * 200
        w.create_goal(f"{pad}{SUBJECT}{pad}", f"also {SUBJECT}")
        occ = rf.find_occurrences(w, SUBJECT)
        title_hit = next(o for o in occ if o["field"] == "title")
        assert len(title_hit["snippet"]) == len(SUBJECT) + 2 * rf.SNIPPET_RADIUS
        assert SUBJECT in title_hit["snippet"]
        assert len(rf.find_occurrences(w, SUBJECT, limit=1)) == 1


def test_dry_run_is_default_and_changes_nothing(tmp_path):
    w, gid, _control, conv_id = _seed(tmp_path)
    with w:
        report = rf.rectify(w, SUBJECT, FIXED)
        assert report.dry_run is True
        assert report.matches == 5 and report.changed == 0
        assert report.by_table == {"goals": 3, "turns": 1, "facts": 1}

        goal = w.get_goal(gid)
        assert SUBJECT in goal.title and FIXED not in goal.title
        assert w.get_fact("contact:primary") == SUBJECT
        assert "DRY RUN" in rf.render(report)


def test_real_run_rewrites_every_occurrence_and_only_those(tmp_path):
    w, gid, control_gid, conv_id = _seed(tmp_path)
    with w:
        report = rf.rectify(w, SUBJECT, FIXED, dry_run=False)
        assert report.dry_run is False
        assert report.matches == 5 and report.changed == 5

        goal = w.get_goal(gid)
        assert goal.title == f"Email {FIXED} about the report"
        # Case-insensitive: the uppercase and mixed-case spellings were caught.
        assert goal.description == f"The subject {FIXED} appears uppercased here"
        assert goal.result == f"sent to {FIXED} today"

        turns = w.recent_turns(conv_id, limit=10)
        assert turns[0].content == f"please contact {FIXED} first thing"
        assert turns[1].content == "done, no address mentioned"  # untouched

        assert w.get_fact("contact:primary") == FIXED
        assert w.get_fact("contact:other") == "carol@example.com"  # untouched

        control = w.get_goal(control_gid)
        assert control.title == "Email bob@example.com"
        assert control.description == "nothing to rectify"

        # Idempotent: nothing left to match.
        assert rf.rectify(w, SUBJECT, FIXED).matches == 0
        assert "APPLIED" in rf.render(report)


def test_tables_filter_narrows_the_sweep(tmp_path):
    w, gid, _control, _conv = _seed(tmp_path)
    with w:
        report = rf.rectify(w, SUBJECT, FIXED, tables=["facts"], dry_run=False)
        assert report.by_table == {"facts": 1} and report.changed == 1
        assert w.get_fact("contact:primary") == FIXED
        assert SUBJECT in w.get_goal(gid).title  # goals were out of scope


def test_audit_trail_written_without_leaking_the_subject(tmp_path):
    w, _gid, _control, _conv = _seed(tmp_path)
    with w:
        rf.rectify(w, SUBJECT, FIXED, dry_run=False)
    # conftest pins HOME to tmp_path -> data_dir() == tmp_path/.maverick
    trail = tmp_path / ".maverick" / "rectifications.jsonl"
    assert trail.exists()
    raw = trail.read_text()
    assert SUBJECT not in raw and FIXED not in raw  # digests + counts only
    entry = json.loads(raw.splitlines()[0])
    assert entry["action"] == "rectify"
    assert entry["changed"] == 5
    assert entry["by_table"] == {"goals": 3, "turns": 1, "facts": 1}
    assert len(entry["subject_sha256_16"]) == 16


def test_dry_run_leaves_no_audit_trail(tmp_path):
    w, _gid, _control, _conv = _seed(tmp_path)
    with w:
        rf.rectify(w, SUBJECT, FIXED)  # dry run
    assert not (tmp_path / ".maverick" / "rectifications.jsonl").exists()


def test_empty_subject_and_replacement_rejected(tmp_path):
    with open_world(tmp_path / "world.db") as w:
        for bad in ("", "   ", None):
            with pytest.raises(ValueError):
                rf.rectify(w, bad, FIXED)
            with pytest.raises(ValueError):
                rf.find_occurrences(w, bad)
        for bad in ("", "   ", None):
            with pytest.raises(ValueError):
                rf.rectify(w, SUBJECT, bad)


def test_unknown_table_rejected(tmp_path):
    with open_world(tmp_path / "world.db") as w:
        with pytest.raises(ValueError):
            rf.rectify(w, SUBJECT, FIXED, tables=["conversations"])
