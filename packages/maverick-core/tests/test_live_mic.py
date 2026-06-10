"""Speech-to-action live mic (2027-H1): scripted chunk source + fake
transcriber; grammar matching reuses voice_command_grammar. Offline."""
from __future__ import annotations

import sys

import pytest
from maverick.live_mic import MicEvent, match_utterance, run_live_mic, whisper_transcriber

_GRAMMAR = [
    {"intent": "pause", "pattern": "pause goal {id}"},
    {"intent": "set_budget", "pattern": "set budget to {amount} dollars"},
    {"intent": "halt", "pattern": "stop everything"},
]


def _scripted(*utterances: str):
    """A chunk source + transcriber pair: chunk N transcribes to utterance N."""
    chunks = [f"chunk-{i}".encode() for i in range(len(utterances))]
    table = dict(zip(chunks, utterances))
    return chunks, lambda chunk: table[chunk]


def test_dispatches_matched_intent_with_slots():
    chunks, transcriber = _scripted("pause goal 12")
    seen: list[tuple[str, dict]] = []
    events = run_live_mic(chunks, transcriber, _GRAMMAR,
                          lambda i, s: seen.append((i, s)))
    assert seen == [("pause", {"id": "12"})]
    assert events == [MicEvent("pause goal 12", "pause", {"id": "12"}, "dispatched")]


def test_silence_chunks_produce_no_events():
    chunks, transcriber = _scripted("", "   ", "stop everything")
    events = run_live_mic(chunks, transcriber, _GRAMMAR, lambda i, s: None)
    assert [e.status for e in events] == ["dispatched"]


def test_no_match_recorded_but_not_dispatched():
    chunks, transcriber = _scripted("make me a sandwich")
    fired = []
    events = run_live_mic(chunks, transcriber, _GRAMMAR, lambda i, s: fired.append(i))
    assert fired == []
    assert events[0].intent is None and events[0].status == "no_match"


def test_risky_intent_without_confirm_hook_fails_closed():
    chunks, transcriber = _scripted("stop everything")
    fired = []
    events = run_live_mic(chunks, transcriber, _GRAMMAR, lambda i, s: fired.append(i),
                          risky_intents={"halt"})
    assert fired == [] and events[0].status == "denied"


def test_risky_intent_confirmed_true_dispatches():
    chunks, transcriber = _scripted("stop everything")
    fired = []
    events = run_live_mic(chunks, transcriber, _GRAMMAR, lambda i, s: fired.append(i),
                          risky_intents={"halt"}, confirm=lambda i, s: True)
    assert fired == ["halt"] and events[0].status == "dispatched"


def test_risky_intent_stringy_confirm_is_denied():
    # as_bool semantics: only a real True authorises; "yes"/1 fail closed.
    for verdict in ("yes", "true", 1):
        chunks, transcriber = _scripted("stop everything")
        events = run_live_mic(chunks, transcriber, _GRAMMAR, lambda i, s: None,
                              risky_intents={"halt"},
                              confirm=lambda i, s: verdict)
        assert events[0].status == "denied"


def test_action_error_recorded_and_loop_continues():
    chunks, transcriber = _scripted("pause goal 1", "pause goal 2")

    def boom(intent, slots):
        if slots["id"] == "1":
            raise RuntimeError("kaboom")

    events = run_live_mic(chunks, transcriber, _GRAMMAR, boom)
    assert [e.status for e in events] == ["error", "dispatched"]


def test_events_keep_utterance_order():
    chunks, transcriber = _scripted(
        "pause goal 1", "gibberish", "set budget to 5 dollars")
    events = run_live_mic(chunks, transcriber, _GRAMMAR, lambda i, s: None)
    assert [(e.intent, e.status) for e in events] == [
        ("pause", "dispatched"), (None, "no_match"), ("set_budget", "dispatched"),
    ]


def test_match_utterance_reuses_grammar_semantics():
    # Loose whitespace + case-insensitivity come from voice_command_grammar.
    intent, slots = match_utterance(_GRAMMAR, "  SET   budget  to  5  dollars ")
    assert intent == "set_budget" and slots == {"amount": "5"}
    assert match_utterance(_GRAMMAR, "nope") is None


def test_match_utterance_rejects_bad_grammar():
    with pytest.raises(ValueError, match="duplicate slot"):
        match_utterance([{"intent": "x", "pattern": "{a} {a}"}], "1 2")
    with pytest.raises(ValueError, match="intent"):
        match_utterance([{"pattern": "hi"}], "hi")


def test_whisper_transcriber_actionable_when_voice_extra_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    with pytest.raises(ImportError, match=r"maverick-agent\[voice\]"):
        whisper_transcriber()
