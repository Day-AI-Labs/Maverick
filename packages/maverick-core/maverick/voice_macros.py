"""Voice macros — named multi-step command sequences for the voice surface.

A macro maps one trigger phrase ("morning routine") to an ordered list of
plain-text command steps (["status report", "what failed", ...]). Macros are
recorded/managed programmatically, persisted at ``data_dir("voice_macros.json")``
(atomic temp-file + ``os.replace`` write, ``chmod 0600``), and triggered by
matching the phrase in an incoming utterance.

Safety properties (deliberate, tested):

* **Steps are re-validated at trigger time.** Each step is re-parsed through
  the injected grammar ``parse`` seam when the macro runs; a step that no
  longer parses is *skipped*, never dispatched — a stored macro cannot
  smuggle an unparseable command past the grammar.
* **A macro never pre-authorizes.** Steps whose intent is mutating keep their
  confirm gates individually: the injected ``confirm`` seam is called once
  per risky step and only a literal ``True`` (``tools.as_bool``, fail-closed)
  lets that one step run. No confirm seam => every risky step is refused.
* **Bounded.** At most :data:`MAX_STEPS` steps are accepted at record time,
  and a hand-edited oversized file is truncated to the same bound at run time.

Pure functions over an injected ``dispatch(intent, slots) -> str`` seam; the
module never executes anything itself.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .paths import data_dir
from .tools import as_bool

log = logging.getLogger(__name__)

# Serializes a macro-store load-modify-save in-process; cross_process_lock in
# _locked() extends it across processes.
_MACROS_LOCK = threading.Lock()


def _locked(path: Path | None):
    from contextlib import ExitStack

    from .file_lock import cross_process_lock
    stack = ExitStack()
    stack.enter_context(_MACROS_LOCK)
    stack.enter_context(cross_process_lock(path if path is not None else macros_path()))
    return stack

MAX_STEPS = 16


def macros_path() -> Path:
    """Tenant-aware store location: ``<data>/voice_macros.json``."""
    return data_dir("voice_macros.json")


def _normalize_phrase(text: str) -> str:
    return " ".join(str(text or "").split()).rstrip("?!. ").lower()


def load_macros(path: Path | None = None) -> dict[str, list[str]]:
    """Load the macro store; fail-soft to ``{}`` on a missing/corrupt file."""
    p = path if path is not None else macros_path()
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        log.warning("voice_macros: cannot read %s: %s", p, e)
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, list[str]] = {}
    for name, steps in data.items():
        if isinstance(name, str) and isinstance(steps, list):
            out[name] = [str(s) for s in steps]
    return out


def save_macros(macros: dict[str, list[str]], path: Path | None = None) -> None:
    """Atomic, private write: unique temp file + ``chmod 0600`` + ``os.replace``."""
    p = path if path is not None else macros_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".voice_macros-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(macros, f, indent=2)
        os.chmod(tmp, 0o600)
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def record_macro(name: str, steps: list[str], path: Path | None = None) -> dict[str, list[str]]:
    """Add/replace a macro. Validates and persists; returns the new store.

    Raises ``ValueError`` for an empty name, no steps, more than
    :data:`MAX_STEPS` steps, or a blank/non-string step.
    """
    key = _normalize_phrase(name)
    if not key:
        raise ValueError("macro name must be a non-empty phrase")
    if not isinstance(steps, list) or not steps:
        raise ValueError("steps must be a non-empty list of command strings")
    if len(steps) > MAX_STEPS:
        raise ValueError(f"too many steps ({len(steps)} > {MAX_STEPS})")
    clean: list[str] = []
    for s in steps:
        if not isinstance(s, str) or not s.strip():
            raise ValueError("every step must be a non-empty string")
        clean.append(" ".join(s.split()))
    # Whole load-modify-save under the lock so a concurrent record/delete of
    # another macro can't clobber this one (last-writer-wins on the dict).
    with _locked(path):
        macros = load_macros(path)
        macros[key] = clean
        save_macros(macros, path)
    return macros


def delete_macro(name: str, path: Path | None = None) -> bool:
    """Remove a macro by name; True if it existed."""
    key = _normalize_phrase(name)
    with _locked(path):
        macros = load_macros(path)
        if key not in macros:
            return False
        del macros[key]
        save_macros(macros, path)
    return True


def match_trigger(utterance: str, macros: dict[str, list[str]]) -> str | None:
    """The macro name an utterance triggers, or None.

    Matches the bare phrase ("morning routine") or "run <phrase>" /
    "run the <phrase>", case/punctuation/whitespace-insensitive — the same
    looseness the live-mic grammar applies to other commands.
    """
    text = _normalize_phrase(utterance)
    if not text:
        return None
    candidates = [text]
    if text.startswith("run the "):
        candidates.append(text[len("run the "):])
    elif text.startswith("run "):
        candidates.append(text[len("run "):])
    for cand in candidates:
        if cand in macros:
            return cand
    return None


@dataclass
class StepResult:
    step: str
    status: str  # "ok" | "skipped" | "refused" | "error"
    detail: str = ""


@dataclass
class MacroRun:
    name: str
    results: list[StepResult] = field(default_factory=list)
    truncated: bool = False


def run_macro(
    name: str,
    *,
    parse: Callable[[str], tuple[str, dict] | None],
    dispatch: Callable[[str, dict], str],
    confirm: Callable[[str], object] | None = None,
    mutating_intents: frozenset[str] | None = None,
    macros: dict[str, list[str]] | None = None,
    path: Path | None = None,
) -> MacroRun:
    """Execute a stored macro through injected seams; returns per-step results.

    ``parse`` is the grammar (e.g. ``conversational_supervisor.parse_utterance``)
    — every step is re-validated through it NOW, at trigger time. ``dispatch``
    executes a parsed ``(intent, slots)``. Steps parsing to an intent in
    ``mutating_intents`` (default: the supervisor's set) are individually
    confirm-gated via ``as_bool(confirm(...))``; one approval covers one step,
    never the whole macro. A failing step is recorded and the macro continues.

    Raises ``KeyError`` for an unknown macro name.
    """
    if mutating_intents is None:
        from .conversational_supervisor import MUTATING_INTENTS
        mutating_intents = MUTATING_INTENTS
    store = macros if macros is not None else load_macros(path)
    key = _normalize_phrase(name)
    if key not in store:
        raise KeyError(f"no macro named {key!r}")
    steps = store[key]
    run = MacroRun(name=key)
    if len(steps) > MAX_STEPS:  # hand-edited store: enforce the bound anyway
        run.truncated = True
        steps = steps[:MAX_STEPS]
    for step in steps:
        parsed = parse(step)
        if parsed is None:
            run.results.append(StepResult(step, "skipped", "did not parse against the grammar"))
            continue
        intent, slots = parsed
        if intent in mutating_intents:
            if confirm is None:
                run.results.append(StepResult(step, "refused", "no confirm channel; risky step not run"))
                continue
            try:
                verdict = confirm(f"macro {key!r} step: {step}")
            except Exception as e:
                run.results.append(StepResult(step, "refused", f"confirm failed: {e}"))
                continue
            if not as_bool(verdict):
                run.results.append(StepResult(step, "refused", "not confirmed"))
                continue
        try:
            detail = dispatch(intent, slots)
        except Exception as e:
            run.results.append(StepResult(step, "error", str(e)))
            continue
        run.results.append(StepResult(step, "ok", str(detail)))
    return run


def trigger(
    utterance: str,
    *,
    parse: Callable[[str], tuple[str, dict] | None],
    dispatch: Callable[[str, dict], str],
    confirm: Callable[[str], object] | None = None,
    macros: dict[str, list[str]] | None = None,
    path: Path | None = None,
) -> MacroRun | None:
    """One-phrase entry point for the live-mic loop: if ``utterance`` matches
    a stored macro, run it (same seams as :func:`run_macro`); else None so the
    caller falls through to its normal grammar handling."""
    store = macros if macros is not None else load_macros(path)
    name = match_trigger(utterance, store)
    if name is None:
        return None
    return run_macro(
        name, parse=parse, dispatch=dispatch, confirm=confirm, macros=store,
    )


__all__ = [
    "MAX_STEPS",
    "macros_path",
    "load_macros",
    "save_macros",
    "record_macro",
    "delete_macro",
    "match_trigger",
    "StepResult",
    "MacroRun",
    "run_macro",
    "trigger",
]
