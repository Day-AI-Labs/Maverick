"""Streaming voice session — endpointing, barge-in, scripted offline replay."""
from __future__ import annotations

from maverick_channels.streaming_voice import (
    MAX_REPLY_HISTORY,
    MAX_UTTERANCE_CHARS,
    PlaybackSeams,
    ScriptedEvent,
    StreamingVoiceSession,
    run_scripted,
)


class FakeClock:
    def __init__(self, t: float = 100.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class FakePlayback:
    """Scriptable playback engine: tests flip ``speaking`` directly."""

    def __init__(self):
        self.speaking = False
        self.stops = 0

    def seams(self) -> PlaybackSeams:
        return PlaybackSeams(
            is_speaking=lambda: self.speaking,
            stop_speaking=self._stop,
        )

    def _stop(self) -> None:
        self.stops += 1
        self.speaking = False


def make_session(**kw):
    clock = kw.pop("clock", FakeClock())
    playback = kw.pop("playback", FakePlayback())
    heard = []
    session = StreamingVoiceSession(
        playback.seams(), clock=clock, on_utterance=heard.append, **kw,
    )
    return session, clock, playback, heard


# ----- endpointing -----

def test_final_closes_immediately():
    session, _clock, _pb, heard = make_session()
    session.feed_partial("pause goal")
    utt = session.feed_final("pause goal five")
    assert utt is not None and utt.text == "pause goal five"
    assert utt.final is True
    assert [u.text for u in heard] == ["pause goal five"]


def test_final_without_partials_still_closes():
    session, _clock, _pb, heard = make_session()
    utt = session.feed_final("yes")
    assert utt is not None and utt.text == "yes" and utt.final is True
    assert len(heard) == 1


def test_stability_timeout_closes_via_injected_clock():
    session, clock, _pb, heard = make_session(stability_timeout_s=1.0)
    session.feed_partial("what's running")
    assert session.poll() is None  # not stable yet
    clock.advance(0.5)
    assert session.poll() is None
    clock.advance(0.6)  # 1.1s since last change
    utt = session.poll()
    assert utt is not None and utt.text == "what's running"
    assert utt.final is False  # closed by endpointing, not an ASR final
    assert len(heard) == 1
    assert session.poll() is None  # nothing left open


def test_partial_updates_reset_stability_clock():
    session, clock, _pb, _heard = make_session(stability_timeout_s=1.0)
    session.feed_partial("what")
    clock.advance(0.8)
    session.feed_partial("what's running")  # changed -> clock resets
    clock.advance(0.8)
    assert session.poll() is None  # only 0.8s since the change
    clock.advance(0.3)
    assert session.poll() is not None


def test_unchanged_partial_does_not_reset_clock():
    session, clock, _pb, _heard = make_session(stability_timeout_s=1.0)
    session.feed_partial("hello")
    clock.advance(0.8)
    session.feed_partial("hello")  # identical hypothesis: no reset
    clock.advance(0.3)
    assert session.poll() is not None


def test_empty_final_falls_back_to_open_hypothesis():
    session, _clock, _pb, _heard = make_session()
    session.feed_partial("cancel goal two")
    utt = session.feed_final("")
    assert utt is not None and utt.text == "cancel goal two"


def test_empty_final_with_nothing_open_is_ignored():
    session, _clock, pb, heard = make_session()
    pb.speaking = True
    assert session.feed_final("") is None
    assert heard == []
    assert pb.stops == 0  # no speech onset, no barge-in


def test_empty_partials_never_open_or_barge_in():
    session, _clock, pb, _heard = make_session()
    pb.speaking = True
    session.feed_partial("")
    session.feed_partial("   ")
    assert pb.stops == 0
    assert session.poll() is None


def test_timestamps_come_from_injected_clock():
    clock = FakeClock(50.0)
    session, clock, _pb, _heard = make_session(clock=clock)
    session.feed_partial("hi")
    clock.advance(2.0)
    utt = session.feed_final("hi there")
    assert utt.started_at == 50.0
    assert utt.ended_at == 52.0


# ----- barge-in -----

def test_barge_in_halts_playback_and_marks_reply_interrupted():
    session, _clock, pb, _heard = make_session()
    reply = session.begin_reply("Here is a very long answer about the deploy.")
    pb.speaking = True
    session.feed_partial("wait")  # speech onset while bot is speaking
    assert pb.stops == 1
    assert pb.speaking is False
    assert reply.status == "interrupted"
    assert reply.partially_delivered is True
    # The interrupted reply's full text is preserved for redelivery.
    assert reply.text == "Here is a very long answer about the deploy."
    assert session.interrupted_replies == [reply]
    # The new utterance takes the floor and closes normally.
    utt = session.feed_final("wait stop that")
    assert utt.text == "wait stop that"


def test_no_barge_in_when_bot_is_silent():
    session, _clock, pb, _heard = make_session()
    reply = session.begin_reply("short answer")
    pb.speaking = True
    session.reply_finished()
    pb.speaking = False  # playback ran to completion
    session.feed_partial("next question")
    assert pb.stops == 0
    assert reply.status == "delivered"
    assert session.interrupted_replies == []


def test_barge_in_fires_once_per_utterance():
    session, _clock, pb, _heard = make_session()
    session.begin_reply("answer")
    pb.speaking = True
    session.feed_partial("hold")
    session.feed_partial("hold on")  # same utterance: no second stop
    assert pb.stops == 1


def test_unheralded_final_also_barges_in():
    session, _clock, pb, _heard = make_session()
    session.begin_reply("answer")
    pb.speaking = True
    utt = session.feed_final("stop")
    assert pb.stops == 1
    assert utt.text == "stop"
    assert session.interrupted_replies[0].text == "answer"


# ----- bounds -----

def test_hypothesis_is_bounded():
    session, _clock, _pb, _heard = make_session()
    session.feed_partial("x" * (MAX_UTTERANCE_CHARS + 5000))
    utt = session.feed_final("")
    assert len(utt.text) == MAX_UTTERANCE_CHARS


def test_reply_history_is_bounded():
    session, _clock, _pb, _heard = make_session()
    for i in range(MAX_REPLY_HISTORY + 10):
        session.begin_reply(f"reply {i}")
        session.reply_finished()
    assert len(session.replies) == MAX_REPLY_HISTORY


# ----- scripted end-to-end replay (fully offline) -----

def test_scripted_conversation_with_interruption():
    clock = FakeClock()
    pb = FakePlayback()
    session = StreamingVoiceSession(
        pb.seams(), clock=clock, stability_timeout_s=1.0,
    )
    script = [
        ScriptedEvent("partial", "what's"),
        ScriptedEvent("partial", "what's running"),
        ScriptedEvent("wait", seconds=1.5),  # endpointing closes utterance 1
    ]
    utterances = run_scripted(session, script, clock.advance)
    assert [u.text for u in utterances] == ["what's running"]

    # Bot starts answering; the user barges in mid-reply.
    session.begin_reply("Three goals are running: deploy, docs, and triage…")
    pb.speaking = True
    script2 = [
        ScriptedEvent("partial", "pause"),
        ScriptedEvent("final", "pause goal five"),
    ]
    utterances2 = run_scripted(session, script2, clock.advance)
    assert [u.text for u in utterances2] == ["pause goal five"]
    assert pb.stops == 1
    assert len(session.interrupted_replies) == 1
    assert session.interrupted_replies[0].text.startswith("Three goals")

    # The follow-up reply plays to completion this time.
    session.begin_reply("Paused goal 5.")
    pb.speaking = True
    session.reply_finished()
    assert session.replies[-1].status == "delivered"


def test_scripted_unknown_event_kind_raises():
    clock = FakeClock()
    pb = FakePlayback()
    session = StreamingVoiceSession(pb.seams(), clock=clock)
    try:
        run_scripted(session, [ScriptedEvent("noise", "x")], clock.advance)
    except ValueError as e:
        assert "unknown scripted event" in str(e)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError")
