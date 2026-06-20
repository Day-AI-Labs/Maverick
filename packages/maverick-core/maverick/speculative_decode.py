"""Cross-provider speculative drafting (roadmap: 2028 H2 — "speculative
decoding across providers").

HONEST SCOPE: this is APPLICATION-LEVEL speculative drafting, not logit-level
speculative decoding. True speculative decoding verifies draft tokens against
the target model's logits inside a single forward pass; hosted provider APIs
expose no such hook. This module approximates the same economics at the
prompt level, across any two providers the user configures:

  1. a cheap DRAFT model proposes a full continuation;
  2. the TARGET model VERIFIES/extends in ONE call — its prompt carries the
     draft with accept-verbatim-or-revise instructions, so an acceptable
     draft shifts target spend toward input tokens (cheap) instead of fresh
     output tokens (expensive), and a rejected draft still yields a correct
     answer in the same single target call;
  3. the realized accept-rate is tracked per ``(draft_model, target_model)``
     pair in a persisted ledger; once a pair has ``min_samples`` and its rate
     sits below ``floor``, the draft step is skipped and the target is called
     plain — speculation only continues where it pays for itself.

Models are never hardcoded here: defaults resolve through the role chain
(``maverick.llm.model_for_role`` — config ``[models]`` first, ``ROLE_MODELS``
as last resort), and both LLM calls are injected seams (``(prompt, model) ->
text``) so tests run offline and callers wire in ``maverick.llm.LLM`` —
or anything else — themselves.

Distinct from the existing speculation modules: ``speculative.py`` overlaps
asyncio coroutines, ``speculative_tools.py`` pre-warms the tool cache,
``speculative_best_of_n.py`` prunes weak attempts early. This module is about
approximating decode-time cost savings across providers.
"""
from __future__ import annotations

import difflib
import json
import logging
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .paths import data_dir

log = logging.getLogger(__name__)

# Injected LLM seam: (prompt, model_spec) -> completion text.
LLMCall = Callable[[str, str], str]

DEFAULT_LEDGER_PATH = data_dir("speculative_ledger.json")
# Role defaults only — the ROLES are named here, never model ids. "summarizer"
# is the kernel's established cheap tier; both resolve via config first.
DEFAULT_DRAFT_ROLE = "summarizer"
DEFAULT_TARGET_ROLE = "writer"
DEFAULT_FLOOR = 0.3
DEFAULT_MIN_SAMPLES = 5
DEFAULT_ACCEPT_THRESHOLD = 0.9

_VERIFY_INSTRUCTIONS = (
    "A draft answer to the task above is between the <draft> tags. "
    "If the draft is correct and complete, output it VERBATIM (you may extend "
    "it if it stops early). If it is wrong or low quality anywhere, ignore it "
    "and write the correct answer instead. Output only the final answer — "
    "no commentary about the draft."
)


def build_verify_prompt(prompt: str, draft: str) -> str:
    """The single target call: original task + draft + accept/revise rules."""
    return f"{prompt}\n\n{_VERIFY_INSTRUCTIONS}\n<draft>\n{draft}\n</draft>"


def _normalize(text: str) -> str:
    return " ".join((text or "").split())


def draft_accepted(draft: str, final: str, threshold: float = DEFAULT_ACCEPT_THRESHOLD) -> bool:
    """Did the target keep the draft? Verbatim/extended prefix, or near-identical.

    Whitespace-insensitive. ``final`` starting with the draft counts (the
    instructions allow extending a truncated draft); otherwise a difflib
    similarity ratio >= ``threshold`` counts as an accept-with-touch-ups.
    Deterministic — no model judges the judge.
    """
    d, f = _normalize(draft), _normalize(final)
    if not d or not f:
        return False
    if f.startswith(d):
        return True
    return difflib.SequenceMatcher(None, d, f).ratio() >= threshold


class AcceptanceLedger:
    """Persisted accept/total counts per (draft_model, target_model) pair.

    A flat JSON map ``{"draft -> target": {"accepted": n, "total": n}}`` at
    ``~/.maverick/speculative_ledger.json`` (path injectable for tests).
    Reads fail soft to empty; writes are atomic (tmp + replace) and a write
    error never breaks the completion path.
    """

    def __init__(self, path: str | os.PathLike | None = None):
        self.path = Path(path) if path is not None else DEFAULT_LEDGER_PATH
        self._lock = threading.Lock()
        self._data = self._load()

    def _load(self) -> dict:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {}
        except (OSError, ValueError):
            return {}

    @staticmethod
    def _key(draft_model: str, target_model: str) -> str:
        return f"{draft_model} -> {target_model}"

    def record(self, draft_model: str, target_model: str, accepted: bool) -> None:
        with self._lock:
            row = self._data.setdefault(
                self._key(draft_model, target_model), {"accepted": 0, "total": 0},
            )
            row["total"] = int(row.get("total") or 0) + 1
            if accepted:
                row["accepted"] = int(row.get("accepted") or 0) + 1
            self._save()

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(self.path.name + ".tmp")
            tmp.write_text(json.dumps(self._data, sort_keys=True), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError as e:  # never let bookkeeping break a completion
            log.warning("speculative ledger save failed: %s", e)

    def accept_rate(self, draft_model: str, target_model: str) -> tuple[float, int]:
        """(rate, samples). No samples yet -> (1.0, 0): optimistic start."""
        with self._lock:
            row = self._data.get(self._key(draft_model, target_model)) or {}
        total = int(row.get("total") or 0)
        if total == 0:
            return 1.0, 0
        return int(row.get("accepted") or 0) / total, total


@dataclass
class SpeculativeResult:
    text: str                 # the answer (always from the target model)
    drafted: bool             # was a draft produced and verified
    accepted: bool            # did the target keep the draft
    draft: str = ""
    draft_model: str = ""
    target_model: str = ""
    accept_rate: float = 1.0  # the pair's ledger rate BEFORE this call


def _resolve_models(
    draft_model: str | None, target_model: str | None,
    draft_role: str, target_role: str,
) -> tuple[str, str]:
    if draft_model and target_model:
        return draft_model, target_model
    from .llm import model_for_role  # config [models] first; ROLE_MODELS last resort
    return (
        draft_model or model_for_role(draft_role),
        target_model or model_for_role(target_role),
    )


def speculative_complete(
    prompt: str,
    *,
    draft_call: LLMCall,
    target_call: LLMCall,
    draft_model: str | None = None,
    target_model: str | None = None,
    draft_role: str = DEFAULT_DRAFT_ROLE,
    target_role: str = DEFAULT_TARGET_ROLE,
    ledger: AcceptanceLedger | None = None,
    floor: float = DEFAULT_FLOOR,
    min_samples: int = DEFAULT_MIN_SAMPLES,
    accept_threshold: float = DEFAULT_ACCEPT_THRESHOLD,
) -> SpeculativeResult:
    """Draft with the cheap model, verify/extend with the target in one call.

    Falls back to a plain target call (no draft spend) when the pair's
    ledger accept-rate is below ``floor`` after ``min_samples``, or when the
    draft call fails or returns nothing. The answer is ALWAYS target-model
    output — a bad draft costs latency, never quality.
    """
    draft_model, target_model = _resolve_models(
        draft_model, target_model, draft_role, target_role,
    )
    led = ledger if ledger is not None else AcceptanceLedger()
    rate, samples = led.accept_rate(draft_model, target_model)

    if samples >= min_samples and rate < floor:
        # Speculation is losing for this pair: skip the draft entirely.
        return SpeculativeResult(
            text=target_call(prompt, target_model),
            drafted=False, accepted=False,
            draft_model=draft_model, target_model=target_model, accept_rate=rate,
        )

    try:
        draft = draft_call(prompt, draft_model)
    except Exception as e:
        # A transport/provider failure is not an accept-rate signal: fall back
        # to the plain call without recording.
        log.warning("speculative draft failed (%s); plain target call", type(e).__name__)
        return SpeculativeResult(
            text=target_call(prompt, target_model),
            drafted=False, accepted=False,
            draft_model=draft_model, target_model=target_model, accept_rate=rate,
        )

    if not (draft or "").strip():
        # The draft model produced nothing useful — that IS a pair signal.
        led.record(draft_model, target_model, False)
        return SpeculativeResult(
            text=target_call(prompt, target_model),
            drafted=True, accepted=False,
            draft_model=draft_model, target_model=target_model, accept_rate=rate,
        )

    final = target_call(build_verify_prompt(prompt, draft), target_model)
    accepted = draft_accepted(draft, final, accept_threshold)
    led.record(draft_model, target_model, accepted)
    return SpeculativeResult(
        text=final, drafted=True, accepted=accepted, draft=draft,
        draft_model=draft_model, target_model=target_model, accept_rate=rate,
    )


__all__ = [
    "LLMCall",
    "AcceptanceLedger",
    "SpeculativeResult",
    "speculative_complete",
    "build_verify_prompt",
    "draft_accepted",
    "DEFAULT_LEDGER_PATH",
    "DEFAULT_FLOOR",
    "DEFAULT_MIN_SAMPLES",
]
