"""Trained-classifier scoring seam for the cheap-probe tier.

The Constitutional-v2 cheap probe (:mod:`maverick_shield.cascade`) is purely
heuristic: hand-tuned regex/unicode signals. That is a strong recall floor but
there was no way to put a *trained* classifier into the first pass -- the gap
between "heuristic shield" and "trained safety model".

This adds that seam **safely**. A model is a set of linear weights over the
probe's own named features, loaded from a plain JSON artifact -- no pickle, so
loading an operator-supplied model can't execute code (unacceptable in a safety
component). An operator trains a logistic-regression / linear classifier offline
on labelled jailbreak data and exports::

    {"bias": -1.2, "weights": {"regex_hit": 2.3, "non_ascii_ratio": 1.1, ...},
     "threshold": 0.5}

``LinearProbeModel.score(text)`` returns a calibrated probability in ``[0, 1]``.
The cascade ensembles it with the heuristic by taking the MAX, so adding a model
can only *raise* recall, never weaken the existing floor. Default OFF: with no
``[shield] probe_model`` / ``MAVERICK_SHIELD_PROBE_MODEL`` configured, the probe
behaves exactly as before.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

log = logging.getLogger(__name__)

# Reuse the cheap probe's signal regexes so a trained model scores over the same
# features the heuristic sees (kept import-light: compiled here, mirrors cascade).
_RX_REGEX = None  # lazily bound from cascade to avoid an import cycle at import time
_TAG_RE = re.compile(r"[\U000E0000-\U000E007F]")
_INVISIBLE_RE = re.compile("[\u200b-\u200f\u202a-\u202e\u2060-\u206f]")
_B64_RE = re.compile(r"[A-Za-z0-9+/]{200,}={0,2}")
_HEX_RE = re.compile(r"\\x[0-9a-fA-F]{2}.{0,10}\\x[0-9a-fA-F]{2}")


def _probe_regex():
    global _RX_REGEX
    if _RX_REGEX is None:
        from .cascade import _PROBE_REGEX
        _RX_REGEX = _PROBE_REGEX
    return _RX_REGEX


def probe_features(text: str) -> dict[str, float]:
    """Numeric features for a text, the model's input vector.

    Binary signals mirror the heuristic probe; ``non_ascii_ratio`` and
    ``log_length`` give the model continuous signal the heuristic discretizes.
    Stable feature names are the model's contract."""
    if not text:
        return {}
    n = len(text)
    non_ascii = sum(1 for c in text if ord(c) > 127)
    return {
        "regex_hit": 1.0 if _probe_regex().search(text.lower()) else 0.0,
        "unicode_tag": 1.0 if _TAG_RE.search(text) else 0.0,
        "zero_width": 1.0 if _INVISIBLE_RE.search(text) else 0.0,
        "base64_blob": 1.0 if _B64_RE.search(text) else 0.0,
        "hex_escape": 1.0 if _HEX_RE.search(text) else 0.0,
        "non_ascii_ratio": non_ascii / max(n, 1),
        "log_length": math.log10(n + 1),
    }


def _sigmoid(z: float) -> float:
    # Numerically stable logistic.
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    ez = math.exp(z)
    return ez / (1.0 + ez)


@runtime_checkable
class ProbeModel(Protocol):
    """Anything that scores a text's jailbreak likelihood in ``[0, 1]``."""

    def score(self, text: str) -> float: ...


@dataclass(frozen=True)
class LinearProbeModel:
    """A linear/logistic classifier over :func:`probe_features`.

    ``score = sigmoid(bias + Σ weights[f] * feature[f])``. Unknown feature
    names in ``weights`` are ignored; missing features count as 0. ``threshold``
    is advisory metadata (the cascade uses the raw probability)."""

    bias: float = 0.0
    weights: dict[str, float] = None  # type: ignore[assignment]
    threshold: float = 0.5

    def score(self, text: str) -> float:
        feats = probe_features(text)
        z = float(self.bias)
        for name, w in (self.weights or {}).items():
            z += float(w) * feats.get(name, 0.0)
        return _sigmoid(z)

    @classmethod
    def from_dict(cls, data: dict) -> LinearProbeModel:
        if not isinstance(data, dict):
            raise ValueError("probe model must be a JSON object")
        weights = data.get("weights") or {}
        if not isinstance(weights, dict):
            raise ValueError("probe model 'weights' must be an object")
        # Coerce + validate numerics up front so scoring can't raise later.
        clean = {str(k): float(v) for k, v in weights.items()}
        return cls(
            bias=float(data.get("bias", 0.0)),
            weights=clean,
            threshold=float(data.get("threshold", 0.5)),
        )


def load_probe_model(path: str | Path) -> LinearProbeModel | None:
    """Load a JSON linear-model artifact. Returns ``None`` (fail-open) on a
    missing path or malformed file -- a broken model must not break scanning."""
    try:
        p = Path(path).expanduser()
        if not p.exists():
            log.warning("shield probe_model: no file at %s", p)
            return None
        return LinearProbeModel.from_dict(json.loads(p.read_text(encoding="utf-8")))
    except Exception as e:  # noqa: BLE001 -- never let a bad model break the shield
        log.warning("shield probe_model: failed to load %s: %s", path, e)
        return None


_cache_lock = threading.Lock()
_cached: tuple[str, LinearProbeModel | None] | None = None


def configured_probe_model() -> LinearProbeModel | None:
    """The operator-configured probe model, or ``None`` when unset.

    Path from ``MAVERICK_SHIELD_PROBE_MODEL`` or ``[shield] probe_model``.
    Cached by path so repeated scans don't re-read the file; never raises."""
    global _cached
    path = os.environ.get("MAVERICK_SHIELD_PROBE_MODEL", "").strip()
    if not path:
        try:
            from maverick.config import load_config
            path = str((load_config() or {}).get("shield", {}).get("probe_model", "")).strip()
        except Exception:  # pragma: no cover -- config/core optional in shield
            path = ""
    if not path:
        return None
    with _cache_lock:
        if _cached is not None and _cached[0] == path:
            return _cached[1]
        model = load_probe_model(path)
        _cached = (path, model)
        return model


def _reset_cache() -> None:
    """Test hook: drop the cached model so a new path/file is re-read."""
    global _cached
    with _cache_lock:
        _cached = None


__all__ = [
    "ProbeModel", "LinearProbeModel", "probe_features",
    "load_probe_model", "configured_probe_model",
]
