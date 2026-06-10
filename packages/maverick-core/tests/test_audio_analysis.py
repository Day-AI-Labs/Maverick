"""Audio diarization + emotion (2028-H1): synthetic frame embeddings exercise
the cosine-distance segmentation; emotion ranking uses fake CLAP-style
embedders. Offline; no model is ever loaded."""
from __future__ import annotations

import sys

import pytest
from maverick.audio_analysis import (
    DEFAULT_EMOTION_LABELS,
    SpeakerSegment,
    clap_frame_embed,
    classify_emotion,
    diarize,
    segment_speakers,
)

_A = [1.0, 0.0, 0.0]
_B = [0.0, 1.0, 0.0]


def test_constant_frames_single_segment():
    segs = segment_speakers([_A, _A, _A, _A])
    assert segs == [SpeakerSegment(speaker="S1", start=0, end=4)]


def test_abrupt_change_splits_at_boundary():
    segs = segment_speakers([_A, _A, _B, _B, _B])
    assert segs == [
        SpeakerSegment(speaker="S1", start=0, end=2),
        SpeakerSegment(speaker="S2", start=2, end=5),
    ]


def test_returning_speaker_reuses_label():
    segs = segment_speakers([_A, _A, _B, _B, _A, _A])
    assert [s.speaker for s in segs] == ["S1", "S2", "S1"]
    assert segs[2] == SpeakerSegment(speaker="S1", start=4, end=6)


def test_threshold_knob_merges_or_splits():
    drift = [[1.0, 0.0], [0.9, 0.1], [0.8, 0.2]]  # gentle drift
    assert len(segment_speakers(drift, threshold=0.5)) == 1
    assert len(segment_speakers(drift, threshold=0.001)) == 3


def test_empty_and_single_frame():
    assert segment_speakers([]) == []
    assert segment_speakers([_A]) == [SpeakerSegment(speaker="S1", start=0, end=1)]


def test_zero_vectors_treated_as_change():
    # cosine(zero, x) = 0 -> distance 1 -> boundary; never a crash.
    segs = segment_speakers([_A, [0.0, 0.0, 0.0], _A])
    assert [s.speaker for s in segs] == ["S1", "S2", "S1"]


def test_diarize_runs_injected_frame_embedder():
    calls = []

    def frame_embed(audio):
        calls.append(audio)
        return [_A, _B]

    segs = diarize(b"wav-bytes", frame_embed=frame_embed, threshold=0.2)
    assert calls == [b"wav-bytes"]
    assert [s.speaker for s in segs] == ["S1", "S2"]


# ---- emotion ----

def _text_embed(labels):
    # Map each label to a distinct one-hot axis, deterministically.
    return [[1.0 if i == j else 0.0 for j in range(len(labels))]
            for i in range(len(labels))]


def test_emotion_nearest_label_wins():
    n = len(DEFAULT_EMOTION_LABELS)
    angry_axis = list(DEFAULT_EMOTION_LABELS).index("angry speech")
    audio_vec = [0.9 if i == angry_axis else 0.05 for i in range(n)]
    ranked = classify_emotion(
        b"clip", audio_embed=lambda b: audio_vec, text_embed=_text_embed)
    assert ranked[0][0] == "angry speech" and ranked[0][1] > ranked[1][1]
    assert len(ranked) == n


def test_emotion_custom_labels_and_validation():
    ranked = classify_emotion(
        b"clip", audio_embed=lambda b: [1.0, 0.0], text_embed=_text_embed,
        labels=("calm", "tense"))
    assert [label for label, _ in ranked] == ["calm", "tense"]
    with pytest.raises(ValueError, match="non-empty"):
        classify_emotion(b"clip", audio_embed=lambda b: [1.0],
                         text_embed=_text_embed, labels=())


def test_emotion_default_adapter_needs_clap_extra(monkeypatch):
    monkeypatch.setitem(sys.modules, "transformers", None)
    monkeypatch.setitem(sys.modules, "torch", None)
    import maverick.tools.audio_understanding as au
    monkeypatch.setattr(au, "_clap", None)
    with pytest.raises(ImportError, match=r"maverick-agent\[clap\]"):
        classify_emotion(b"clip")


def test_clap_frame_embed_shares_clap_extra(monkeypatch):
    monkeypatch.setitem(sys.modules, "transformers", None)
    monkeypatch.setitem(sys.modules, "torch", None)
    import maverick.tools.audio_understanding as au
    monkeypatch.setattr(au, "_clap", None)
    import io
    import wave
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x40" * 8)
    with pytest.raises(ImportError, match=r"maverick-agent\[clap\]"):
        clap_frame_embed(buf.getvalue())
