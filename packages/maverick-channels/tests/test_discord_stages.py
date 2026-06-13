"""Discord Stages session: utterance assembly, etiquette, reply routing."""

from __future__ import annotations

import asyncio

from maverick_channels.discord_stages import StageSeam, StageSession


def _seam(speaker=False):
    state = {"speaker": speaker, "requests": 0, "spoken": [], "texted": []}

    async def request_speaker():
        state["requests"] += 1

    async def speak(text):
        state["spoken"].append(text)

    async def send_text(text):
        state["texted"].append(text)

    return state, StageSeam(
        request_speaker=request_speaker,
        is_speaker=lambda: state["speaker"],
        speak=speak,
        send_text=send_text,
    )


def _session(seam, *, wake=None, handler=None, allowed_user_ids=None):
    async def default_handler(msg):
        return f"echo:{msg.text}"

    return StageSession(
        handler=handler or default_handler,
        seam=seam,
        transcriber=lambda audio: audio.decode("utf-8"),
        wake_word=wake,
        allowed_user_ids=allowed_user_ids or {"u1", "u2"},
    )


def test_stage_session_requires_explicit_allowlist(monkeypatch):
    monkeypatch.delenv("DISCORD_ALLOWED_USER_IDS", raising=False)
    _state, seam = _seam(speaker=True)

    async def handler(msg):
        return f"echo:{msg.text}"

    try:
        StageSession(
            handler=handler,
            seam=seam,
            transcriber=lambda audio: audio.decode("utf-8"),
        )
    except ValueError as exc:
        assert "DISCORD_ALLOWED_USER_IDS" in str(exc)
    else:  # pragma: no cover - defensive assertion message
        raise AssertionError("StageSession accepted an empty allowlist")


def test_stage_session_can_read_allowlist_from_env(monkeypatch):
    monkeypatch.setenv("DISCORD_ALLOWED_USER_IDS", "u1")
    state, seam = _seam(speaker=True)
    s = StageSession(
        handler=lambda msg: _async_text(f"echo:{msg.text}"),
        seam=seam,
        transcriber=lambda audio: audio.decode("utf-8"),
    )

    out = asyncio.run(_drive(s, [("u1", b"hello", True)]))

    assert out == ["echo:hello"]
    assert state["spoken"] == ["echo:hello"]


def test_unauthorized_speaker_is_ignored_before_transcription():
    state, seam = _seam(speaker=True)
    calls = {"handler": 0, "transcriber": 0}

    async def handler(msg):
        calls["handler"] += 1
        return f"echo:{msg.text}"

    def transcriber(audio):
        calls["transcriber"] += 1
        return audio.decode("utf-8")

    s = StageSession(
        handler=handler,
        seam=seam,
        transcriber=transcriber,
        wake_word="maverick",
        allowed_user_ids={"trusted-speaker"},
    )

    out = asyncio.run(
        _drive(
            s,
            [
                ("intruder-speaker", b"maverick spend budget", True),
            ],
        )
    )

    assert out == []
    assert calls == {"handler": 0, "transcriber": 0}
    assert state["spoken"] == []
    assert state["texted"] == []


async def _async_text(text):
    return text


def test_utterance_assembled_across_segments():
    state, seam = _seam(speaker=True)
    s = _session(seam)
    out = asyncio.run(_drive(s, [("u1", b"deploy the", False), ("u1", b"staging site", True)]))
    assert out == ["echo:deploy the staging site"]
    assert state["spoken"] == ["echo:deploy the staging site"]


async def _drive(session, segments):
    replies = []
    for speaker, audio, final in segments:
        r = await session.on_audio_segment(speaker, audio, final=final)
        if r is not None:
            replies.append(r)
    return replies


def test_text_fallback_when_not_speaker():
    state, seam = _seam(speaker=False)
    s = _session(seam)
    asyncio.run(_drive(s, [("u1", b"hello there", True)]))
    assert state["texted"] == ["echo:hello there"]
    assert state["spoken"] == []


def test_wake_word_gates_responses():
    state, seam = _seam(speaker=True)
    s = _session(seam, wake="maverick")
    out = asyncio.run(
        _drive(
            s,
            [
                ("u1", b"just chatting amongst humans", True),
                ("u1", b"maverick summarize the call", True),
            ],
        )
    )
    assert out == ["echo:maverick summarize the call"]
    assert len(state["spoken"]) == 1


def test_speakers_buffered_independently():
    _state, seam = _seam(speaker=True)
    s = _session(seam)
    out = asyncio.run(
        _drive(
            s,
            [
                ("u1", b"alpha", False),
                ("u2", b"bravo", True),  # u2 finishes first
                ("u1", b"omega", True),
            ],
        )
    )
    assert out == ["echo:bravo", "echo:alpha omega"]


def test_never_self_promotes():
    state, seam = _seam(speaker=False)
    s = _session(seam)
    ok = asyncio.run(s.ensure_speaker_requested())
    assert ok is False  # still not a speaker (moderator decides)
    assert state["requests"] == 1  # but the request was made


def test_handler_failure_degrades_politely():
    async def boom(msg):
        raise RuntimeError("kaput")

    state, seam = _seam(speaker=False)
    s = _session(seam, handler=boom)
    asyncio.run(_drive(s, [("u1", b"do thing", True)]))
    assert state["texted"] == ["Sorry — that request failed."]


def test_tts_failure_falls_back_to_text():
    state, seam = _seam(speaker=True)

    async def bad_speak(text):
        raise RuntimeError("voice ws dropped")

    seam.speak = bad_speak
    s = _session(seam)
    asyncio.run(_drive(s, [("u1", b"hi", True)]))
    assert state["texted"] == ["echo:hi"]


def test_utterance_bounded():
    import maverick_channels.discord_stages as ds

    state, seam = _seam(speaker=True)
    s = _session(seam)
    big = b"x" * (ds.MAX_UTTERANCE_CHARS + 500)
    out = asyncio.run(_drive(s, [("u1", big, True)]))
    assert len(out[0]) <= len("echo:") + ds.MAX_UTTERANCE_CHARS
