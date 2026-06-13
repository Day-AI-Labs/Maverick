"""Audio diarization + emotion (roadmap: 2028 H1 capabilities, "audio
diarization + emotion").

Honest scope — this is **heuristic segmentation, not trained diarization**:
speaker changes are detected by thresholding the cosine *distance* between
consecutive frame embeddings, and labels are reused by nearest segment
centroid. There is no clustering, no overlap handling, no VAD; expect it to
split on long pauses and to confuse similar voices. It is the cheap,
dependency-free 80% — swap in a real diarization pipeline when that matters.

Both analyses run over **injected** embedder seams, so the math is testable
offline with synthetic vectors:

* :func:`segment_speakers` / :func:`diarize` take frame embeddings
  (``frame_embed(audio) -> [vector, ...]``);
* :func:`classify_emotion` ranks emotion labels with the same CLAP-style
  pair (``audio_embed(bytes) -> vector``, ``text_embed(labels) -> vectors``)
  as tools/audio_understanding.

The default adapters reuse audio_understanding's CLAP loader and therefore
share its ``[clap]`` extra (``pip install 'maverick-agent[clap]'``) and
``MAVERICK_CLAP_MODEL`` knob.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .tools.audio_understanding import cosine, rank_labels

DEFAULT_EMOTION_LABELS = (
    "neutral speech", "happy speech", "sad speech", "angry speech",
    "fearful speech", "surprised speech",
)


@dataclass(frozen=True)
class SpeakerSegment:
    speaker: str          # heuristic label: S1, S2, ... (reused via centroid match)
    start: int            # frame index, inclusive
    end: int              # frame index, exclusive


def _mean(vectors: Sequence[Sequence[float]]) -> list[float]:
    n = len(vectors)
    return [sum(v[i] for v in vectors) / n for i in range(len(vectors[0]))]


def segment_speakers(
    frames: Sequence[Sequence[float]],
    *,
    threshold: float = 0.35,
) -> list[SpeakerSegment]:
    """Cosine-distance threshold segmentation over frame embeddings.

    A boundary is declared wherever ``1 - cosine(frame[i-1], frame[i])``
    exceeds ``threshold`` (higher threshold = fewer, longer segments). Each
    segment is labelled by its nearest earlier segment centroid when within
    the same threshold, else gets a fresh ``S<n>`` — so an A-B-A exchange
    comes back as S1, S2, S1.
    """
    frames = [list(map(float, f)) for f in frames]
    if not frames:
        return []
    bounds = [0]
    for i in range(1, len(frames)):
        if 1.0 - cosine(frames[i - 1], frames[i]) > threshold:
            bounds.append(i)
    bounds.append(len(frames))

    segments: list[SpeakerSegment] = []
    centroids: list[tuple[str, list[float]]] = []
    for start, end in zip(bounds, bounds[1:], strict=False):
        centroid = _mean(frames[start:end])
        label = next(
            (known for known, vec in centroids
             if 1.0 - cosine(centroid, vec) <= threshold),
            None,
        )
        if label is None:
            label = f"S{len(centroids) + 1}"
            centroids.append((label, centroid))
        segments.append(SpeakerSegment(speaker=label, start=start, end=end))
    return segments


def diarize(audio: bytes, *, frame_embed, threshold: float = 0.35) -> list[SpeakerSegment]:
    """Frame-embed an audio blob and segment it by speaker change.

    ``frame_embed(audio) -> [vector, ...]`` is the injected seam; for a real
    backend see :func:`clap_frame_embed`.
    """
    return segment_speakers(frame_embed(audio), threshold=threshold)


def classify_emotion(
    audio: bytes,
    *,
    audio_embed=None,
    text_embed=None,
    labels: Sequence[str] = DEFAULT_EMOTION_LABELS,
) -> list[tuple[str, float]]:
    """Zero-shot emotion ranking, best label first.

    Same CLAP-style seam as tools/audio_understanding: cosine-rank
    ``labels`` (free text — richer prompts like "a person shouting in
    anger" work too) against the clip embedding. Heuristic, not a trained
    emotion classifier.
    """
    label_list = [str(label) for label in labels]
    if not label_list:
        raise ValueError("labels must be non-empty")
    if audio_embed is None or text_embed is None:
        from .tools.audio_understanding import clap_audio_embed, clap_text_embed
        audio_embed = audio_embed or clap_audio_embed
        text_embed = text_embed or clap_text_embed
    return rank_labels(audio_embed(audio), label_list, text_embed(label_list))


def clap_frame_embed(audio: bytes, *, frame_seconds: float = 2.0) -> list[list[float]]:
    """Real frame embedder sharing the [clap] extra: split a 16-bit PCM WAV
    into fixed windows and CLAP-embed each (raises the same actionable
    ImportError as audio_understanding when transformers/torch are absent)."""
    from .tools.audio_understanding import decode_wav, embed_waveform
    waveform, rate = decode_wav(audio)
    step = max(1, int(rate * frame_seconds))
    return [
        embed_waveform(waveform[i:i + step], rate)
        for i in range(0, len(waveform), step)
    ]
