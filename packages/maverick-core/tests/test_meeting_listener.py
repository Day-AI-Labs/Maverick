"""ASR meeting listener (2027-H1): injected segment stream + injected clock;
deterministic heuristic action items, optional llm seam, 0600 artifact."""
from __future__ import annotations

import json
import os
import stat

from maverick.meeting_listener import (
    ActionItem,
    MeetingListener,
    MeetingSegment,
    extract_action_items,
)


def _clock(start=1000.0, step=10.0):
    state = {"t": start - step}

    def tick():
        state["t"] += step
        return state["t"]

    return tick


def _seg(text, speaker=None):
    return MeetingSegment(ts=0.0, speaker=speaker, text=text)


# ---- transcript + turns ----

def test_feed_accumulates_ordered_transcript_with_speakers():
    m = MeetingListener(clock=_clock())          # started at t=1000
    m.feed("hello all", speaker="Alice")         # t=1010
    m.feed("hi", speaker="Bob")                  # t=1020
    assert m.transcript() == "[10.0s] Alice: hello all\n[20.0s] Bob: hi"


def test_untagged_speaker_renders_placeholder_and_blank_text_ignored():
    m = MeetingListener(clock=_clock())
    m.feed("anonymous point")
    m.feed("   ")
    assert m.transcript() == "[10.0s] ?: anonymous point"
    assert len(m.segments) == 1


def test_speaker_turns_merge_consecutive_segments():
    m = MeetingListener(clock=_clock())
    for who in ("Alice", "Alice", "Bob", "Alice"):
        m.feed("text", speaker=who)
    assert m.speaker_turns() == [("Alice", 2), ("Bob", 1), ("Alice", 1)]
    assert m.speakers() == ["Alice", "Bob"]


def test_consume_stream_with_explicit_ts():
    m = MeetingListener(clock=_clock())
    m.consume([
        {"text": "first", "speaker": "Ann", "ts": 1001.0},
        {"text": "second", "ts": 1002.5},
    ])
    assert m.transcript() == "[1.0s] Ann: first\n[2.5s] ?: second"


# ---- action items (deterministic heuristic) ----

def test_assignment_patterns_extract_owner():
    items = extract_action_items([
        _seg("Alice will send the deck tomorrow", speaker="Bob"),
        _seg("Bob to follow up with legal", speaker="Alice"),
    ])
    assert items == [
        ActionItem(owner="Alice", text="Alice will send the deck tomorrow"),
        ActionItem(owner="Bob", text="Bob to follow up with legal"),
    ]


def test_imperative_and_marker_patterns_use_speaker_as_owner():
    items = extract_action_items([
        _seg("Schedule the retro for Friday", speaker="Carol"),
        _seg("action item: update the runbook", speaker="Dave"),
        _seg("let's review the budget", speaker="Erin"),
    ])
    assert [(i.owner, i.text) for i in items] == [
        ("Carol", "Schedule the retro for Friday"),
        ("Dave", "update the runbook"),
        ("Erin", "let's review the budget"),
    ]


def test_plain_statements_produce_no_action_items():
    items = extract_action_items([
        _seg("the weather is nice today", speaker="Ann"),
        _seg("Yesterday to me it seemed fine", speaker="Bob"),  # 'to' non-verb
        _seg("revenue will grow", speaker="Cat"),               # lowercase subject
    ])
    assert items == []


def test_duplicate_items_deduped_and_multi_sentence_split():
    items = extract_action_items([
        _seg("Send the notes. Send the notes. Alice will book the room",
             speaker="Bob"),
    ])
    assert [(i.owner, i.text) for i in items] == [
        ("Bob", "Send the notes"),
        ("Alice", "Alice will book the room"),
    ]


# ---- llm seam ----

def test_llm_seam_overrides_heuristic_and_failure_falls_back():
    m = MeetingListener(clock=_clock(), llm=lambda t: "Alice: ship the fix\n- recap notes")
    m.feed("Bob will write the summary", speaker="Ann")
    assert m.action_items() == [
        ActionItem(owner="Alice", text="ship the fix"),
        ActionItem(owner=None, text="recap notes"),
    ]

    def boom(transcript):
        raise RuntimeError("llm down")

    m2 = MeetingListener(clock=_clock(), llm=boom)
    m2.feed("Bob will write the summary", speaker="Ann")
    assert m2.action_items() == [
        ActionItem(owner="Bob", text="Bob will write the summary")]


# ---- summary + artifact ----

def test_summary_is_deterministic():
    m = MeetingListener(clock=_clock())
    m.feed("Alice will send the deck", speaker="Alice")   # t=1010
    m.feed("thanks", speaker="Bob")                       # t=1020
    assert m.summary() == ("2 segments from 2 speakers across 2 turns "
                           "over 20s; 1 action items")


def test_finalize_writes_0600_artifact_with_minutes(tmp_path, monkeypatch):
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path / "mhome"))
    m = MeetingListener(session_id="standup ../x", clock=_clock())
    m.feed("Alice will send the deck", speaker="Alice")
    path = m.finalize()                                   # ended t=1020
    assert path.parent == tmp_path / "mhome" / "meetings"
    # Sanitized to one path segment: separators replaced, so '..' is inert.
    assert path.name == "standup-..-x.json"
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    payload = json.loads(path.read_text())
    assert payload["duration_seconds"] == 20.0
    assert payload["speakers"] == ["Alice"]
    assert payload["action_items"] == [
        {"owner": "Alice", "text": "Alice will send the deck"}]
    assert "Alice: Alice will send the deck" in payload["transcript"]


def test_injected_clock_drives_started_and_duration(tmp_path, monkeypatch):
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path / "mhome"))
    m = MeetingListener(clock=_clock(start=50.0, step=5.0))
    m.feed("hi", speaker="A")
    payload = json.loads(m.finalize().read_text())
    assert payload["started"] == 50.0 and payload["ended"] == 60.0
    assert payload["duration_seconds"] == 10.0
    assert m.session_id == "meeting-50"
