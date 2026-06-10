"""Voice macros — persistence, trigger matching, per-step gates, bounds."""
from __future__ import annotations

import json
import os
import stat

import pytest
from maverick.conversational_supervisor import parse_utterance
from maverick.voice_macros import (
    MAX_STEPS,
    delete_macro,
    load_macros,
    match_trigger,
    record_macro,
    run_macro,
    save_macros,
    trigger,
)


@pytest.fixture
def store(tmp_path):
    return tmp_path / "voice_macros.json"


# ----- persistence: atomic, private, validated -----

def test_record_and_load_roundtrip(store):
    record_macro("Morning Routine", ["status report", "what failed"], path=store)
    assert load_macros(store) == {"morning routine": ["status report", "what failed"]}


def test_store_file_is_0600_and_valid_json(store):
    record_macro("morning routine", ["status report"], path=store)
    mode = stat.S_IMODE(os.stat(store).st_mode)
    assert mode == 0o600
    assert json.loads(store.read_text()) == {"morning routine": ["status report"]}
    # No stray temp files left behind by the atomic write.
    assert [p.name for p in store.parent.iterdir()] == [store.name]


def test_load_missing_or_corrupt_fails_soft(store):
    assert load_macros(store) == {}
    store.write_text("{not json")
    assert load_macros(store) == {}
    store.write_text('["a list, not a dict"]')
    assert load_macros(store) == {}


@pytest.mark.parametrize("name,steps", [
    ("", ["status"]),
    ("   ", ["status"]),
    ("ok", []),
    ("ok", "status"),          # not a list
    ("ok", ["status", ""]),    # blank step
    ("ok", ["status", 42]),    # non-string step
])
def test_record_macro_validation(store, name, steps):
    with pytest.raises(ValueError):
        record_macro(name, steps, path=store)
    assert load_macros(store) == {}


def test_record_macro_enforces_max_steps(store):
    with pytest.raises(ValueError):
        record_macro("big", ["status"] * (MAX_STEPS + 1), path=store)
    record_macro("big", ["status"] * MAX_STEPS, path=store)  # at the bound: fine


def test_delete_macro(store):
    record_macro("morning routine", ["status"], path=store)
    assert delete_macro("Morning Routine!", path=store) is True
    assert delete_macro("morning routine", path=store) is False
    assert load_macros(store) == {}


# ----- trigger matching -----

def test_match_trigger_variants():
    macros = {"morning routine": ["status report"]}
    assert match_trigger("morning routine", macros) == "morning routine"
    assert match_trigger("  Morning   ROUTINE? ", macros) == "morning routine"
    assert match_trigger("run morning routine", macros) == "morning routine"
    assert match_trigger("run the morning routine", macros) == "morning routine"
    assert match_trigger("evening routine", macros) is None
    assert match_trigger("", macros) is None


# ----- execution through injected seams -----

def _dispatcher(log):
    def dispatch(intent, slots):
        log.append((intent, slots))
        return f"did {intent}"
    return dispatch


def test_run_macro_dispatches_parsed_steps_in_order(store):
    record_macro("morning routine", ["status report", "what failed"], path=store)
    calls = []
    run = run_macro(
        "morning routine", parse=parse_utterance, dispatch=_dispatcher(calls), path=store,
    )
    assert [r.status for r in run.results] == ["ok", "ok"]
    assert calls == [("status", {}), ("failures", {})]
    assert run.truncated is False


def test_unparseable_step_is_skipped_never_dispatched(store):
    record_macro(
        "sneaky", ["status report", "rm -rf / please", "what failed"], path=store,
    )
    calls = []
    run = run_macro("sneaky", parse=parse_utterance, dispatch=_dispatcher(calls), path=store)
    assert [r.status for r in run.results] == ["ok", "skipped", "ok"]
    assert ("status", {}) in calls and ("failures", {}) in calls
    assert len(calls) == 2  # the smuggled step never reached dispatch


def test_risky_steps_each_need_their_own_confirm(store):
    record_macro("cleanup", ["pause goal 1", "cancel goal 2"], path=store)
    calls = []
    verdicts = iter([True, False])
    asked = []

    def confirm(desc):
        asked.append(desc)
        return next(verdicts)

    run = run_macro(
        "cleanup", parse=parse_utterance, dispatch=_dispatcher(calls),
        confirm=confirm, path=store,
    )
    assert [r.status for r in run.results] == ["ok", "refused"]
    assert calls == [("pause", {"goal": "1"})]
    assert len(asked) == 2  # one approval covers ONE step, never the macro


def test_risky_steps_refused_without_confirm_seam(store):
    record_macro("cleanup", ["pause goal 1", "status report"], path=store)
    calls = []
    run = run_macro("cleanup", parse=parse_utterance, dispatch=_dispatcher(calls), path=store)
    assert [r.status for r in run.results] == ["refused", "ok"]
    assert calls == [("status", {})]


@pytest.mark.parametrize("verdict", ["yes", "true", 1, None])
def test_stringy_confirm_fails_closed(store, verdict):
    record_macro("cleanup", ["cancel goal 1"], path=store)
    calls = []
    run = run_macro(
        "cleanup", parse=parse_utterance, dispatch=_dispatcher(calls),
        confirm=lambda _d: verdict, path=store,
    )
    assert run.results[0].status == "refused"
    assert calls == []


def test_confirm_raising_refuses_that_step_only(store):
    record_macro("cleanup", ["cancel goal 1", "status report"], path=store)
    calls = []

    def confirm(_d):
        raise RuntimeError("channel down")

    run = run_macro(
        "cleanup", parse=parse_utterance, dispatch=_dispatcher(calls),
        confirm=confirm, path=store,
    )
    assert [r.status for r in run.results] == ["refused", "ok"]


def test_dispatch_error_recorded_and_macro_continues(store):
    record_macro("morning routine", ["status report", "what failed"], path=store)

    def dispatch(intent, _slots):
        if intent == "status":
            raise RuntimeError("world down")
        return "ok"

    run = run_macro("morning routine", parse=parse_utterance, dispatch=dispatch, path=store)
    assert [r.status for r in run.results] == ["error", "ok"]
    assert "world down" in run.results[0].detail


def test_hand_edited_oversized_macro_truncated_at_run_time(store):
    # Bypass record_macro's validation, as a hand edit would.
    save_macros({"big": ["status report"] * (MAX_STEPS + 10)}, path=store)
    calls = []
    run = run_macro("big", parse=parse_utterance, dispatch=_dispatcher(calls), path=store)
    assert run.truncated is True
    assert len(run.results) == MAX_STEPS
    assert len(calls) == MAX_STEPS


def test_run_macro_unknown_name_raises(store):
    with pytest.raises(KeyError):
        run_macro("nope", parse=parse_utterance, dispatch=lambda i, s: "", path=store)


# ----- one-phrase trigger entry point -----

def test_trigger_runs_matching_macro(store):
    record_macro("morning routine", ["status report"], path=store)
    calls = []
    run = trigger(
        "run the morning routine!", parse=parse_utterance,
        dispatch=_dispatcher(calls), path=store,
    )
    assert run is not None
    assert calls == [("status", {})]


def test_trigger_falls_through_on_no_match(store):
    record_macro("morning routine", ["status report"], path=store)
    out = trigger(
        "pause goal 5", parse=parse_utterance, dispatch=lambda i, s: "", path=store,
    )
    assert out is None  # caller's normal grammar handling takes over
