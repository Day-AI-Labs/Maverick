"""Voice biometric unlock — companion factor ONLY (roadmap: 2028 H2 UX).

Speaker verification for voice channels: enroll a speaker's voice profile,
then score later utterances against it and gate *convenience* actions on a
match. Three hard stances, stated up front because biometrics invite
overreach:

1. **Never a sole factor.** A voice match may *unlock convenience* (skip
   re-typing a PIN for low-risk actions); it must never be the only gate on a
   sensitive action — replay/synthesis attacks are practical, and the
   docstring-level contract is that callers combine it with an existing
   factor (allowlist + consent). ``VoiceGate.decide`` therefore returns
   ``companion_ok``, never "authenticated".
2. **Local only, deletable.** Profiles are embeddings (never raw audio) in a
   local 0600 store; ``delete_profile`` is first-class (biometric data is
   erasable by design).
3. **Opt-in.** ``[voice] biometric_unlock = true`` required; default off.

The embedding comes from an INJECTED ``embedder(audio_bytes) -> vector``
(e.g. a speaker-embedding model the operator provides); this module is the
pure enrollment/scoring/policy layer — cosine similarity against the
enrolled centroid with a configurable threshold.
"""
from __future__ import annotations

import json
import math
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

DEFAULT_THRESHOLD = 0.80
_MIN_ENROLL_SAMPLES = 3


def enabled() -> bool:
    if os.environ.get("MAVERICK_VOICE_UNLOCK", "").strip().lower() in {
        "1", "true", "yes", "on",
    }:
        return True
    try:
        from .config import load_config
        return bool(((load_config() or {}).get("voice") or {})
                    .get("biometric_unlock", False))
    except Exception:  # pragma: no cover
        return False


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


def _centroid(vecs: list[list[float]]) -> list[float]:
    n = len(vecs)
    return [sum(v[i] for v in vecs) / n for i in range(len(vecs[0]))]


@dataclass(frozen=True)
class GateDecision:
    companion_ok: bool        # the voice factor passed (NEVER sole auth)
    score: float
    reason: str


class VoiceGate:
    """Enrollment + scoring + policy over an injected speaker embedder."""

    def __init__(self, embedder, *, store_path: Path | None = None,
                 threshold: float = DEFAULT_THRESHOLD):
        self._embed = embedder
        self._threshold = float(threshold)
        if store_path is None:
            from .paths import data_dir
            store_path = data_dir("voice_profiles.json")
        self._path = Path(store_path)

    # -- store --------------------------------------------------------------

    def _load(self) -> dict:
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save(self, data: dict) -> None:
        parent = self._path.parent
        parent_existed = parent.exists()
        parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        if not parent_existed:
            try:
                os.chmod(parent, 0o700)
            except OSError:  # pragma: no cover
                pass

        fd, tmp_name = tempfile.mkstemp(
            dir=parent,
            prefix=f".{self._path.name}.",
            suffix=".tmp",
            text=True,
        )
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh)
            os.replace(tmp, self._path)
            try:
                os.chmod(self._path, 0o600)
            except OSError:  # pragma: no cover
                pass
        except Exception:
            try:
                tmp.unlink()
            except OSError:  # pragma: no cover
                pass
            raise

    # -- enrollment ----------------------------------------------------------

    def enroll(self, speaker: str, samples: list[bytes]) -> int:
        """Enroll from >= 3 utterances (a single sample over-fits noise).
        Stores ONLY the embedding centroid, never audio."""
        if len(samples) < _MIN_ENROLL_SAMPLES:
            raise ValueError(
                f"enrollment needs >= {_MIN_ENROLL_SAMPLES} samples, "
                f"got {len(samples)}")
        vecs = [list(map(float, self._embed(s))) for s in samples]
        if len({len(v) for v in vecs}) != 1:
            raise ValueError("embedder returned inconsistent dimensions")
        data = self._load()
        data[speaker] = {"centroid": _centroid(vecs), "enrolled_at": time.time(),
                         "samples": len(samples)}
        self._save(data)
        return len(vecs[0])

    def delete_profile(self, speaker: str) -> bool:
        """Erase a speaker's biometric profile (first-class by design)."""
        data = self._load()
        if speaker not in data:
            return False
        del data[speaker]
        self._save(data)
        return True

    def profiles(self) -> list[str]:
        return sorted(self._load())

    # -- verification ----------------------------------------------------------

    def score(self, speaker: str, audio: bytes) -> float | None:
        """Cosine similarity vs the enrolled centroid; None if unenrolled."""
        entry = self._load().get(speaker)
        if not entry:
            return None
        vec = list(map(float, self._embed(audio)))
        return _cosine(vec, entry["centroid"])

    def decide(self, speaker: str, audio: bytes) -> GateDecision:
        """The companion-factor decision. ``companion_ok`` is True only when
        the feature is enabled, the speaker is enrolled, and the score clears
        the threshold — and it NEVER means "authenticated" on its own."""
        if not enabled():
            return GateDecision(False, 0.0,
                                "voice unlock disabled ([voice] biometric_unlock)")
        s = self.score(speaker, audio)
        if s is None:
            return GateDecision(False, 0.0, f"{speaker!r} not enrolled")
        if s >= self._threshold:
            return GateDecision(True, round(s, 4),
                                "voice factor matched (companion factor only — "
                                "combine with an existing factor)")
        return GateDecision(False, round(s, 4),
                            f"score {s:.3f} below threshold {self._threshold}")


__all__ = ["VoiceGate", "GateDecision", "enabled", "DEFAULT_THRESHOLD"]
