"""Self-Harness: learn a MODEL-SPECIFIC harness addendum from failure traces.

Implements the loop from *"Self-Harness: Harnesses That Improve Themselves"*
(arXiv 2606.09498) on top of Maverick's existing governance spine, rather than
as a new ungoverned optimizer:

  MINE     recurring failure *signatures* from one model's reflexion traces
  PROPOSE  a minimal operating-guidance line targeting each signature
  VALIDATE the proposal on held-in AND held-out cases -- accept only when it
           does not regress either split and helps at least one (the paper's
           rule: reject a pure trade of one split for another)
  GATE     feed the validated change through ``self_improvement.consider()`` on
           the ``prompt`` rung -- so it inherits evidence/causal gating, the
           calibration-freeze interlock, capability non-escalation, reversibility,
           and the signed learning audit, exactly like every other learned rung.

Why this shape. The paper credits its gains to treating the harness as a
*model-specific, learnable* artifact. Maverick already learns *behaviors*
(skills, insights) that are recalled as context; this adds a learned, per-model
**operating-guidance addendum** that is recalled into the system prompt at build
time (:func:`recall_addendum`) -- never a mutation of the kernel templates. So
it sits inside the same "behavior recalled as context, snapshot + rollback"
safety model: an addendum is a file entry, removing it is the rollback handle.

The LLM proposer is an injected seam (:data:`ProposeFn`); a deterministic
fallback composes a guidance line from the signature so the loop runs and is
unit-testable without a provider. Validation likewise takes injected scorers --
a live A/B needs a real model, exactly as ``learning_rollout`` takes injected
constraints. OFF by default (``[self_harness] enable`` / ``MAVERICK_SELF_HARNESS``).
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .paths import data_dir

log = logging.getLogger(__name__)

# Keep an addendum short: it rides in EVERY system prompt for that model, so a
# runaway block would tax cache + context on every turn. A handful of crisp
# lines is the whole point ("minimal" in the paper).
_MAX_ADDENDUM_CHARS = 1500
_MAX_LINES_PER_MODEL = 8
# DoS backstop for mining: greedy clustering is worst-case O(n^2), so an
# unbounded trace list could hang a pass. Generous -- the runner feeds at most
# ``limit`` (500) recent traces, so this never trips in normal use; it only
# bounds a pathological direct caller. See mine_failures.
_MAX_MINE_TRACES = 4000
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def enabled() -> bool:
    """Whether the self-harness loop is active. OFF by default (kernel rule 1).

    Turn on with ``MAVERICK_SELF_HARNESS=1`` or ``[self_harness] enable = true``.
    When off, :func:`recall_addendum` returns ``""`` (the prompt is unchanged)
    and :func:`run_self_harness` is a no-op."""
    if os.environ.get("MAVERICK_SELF_HARNESS", "").strip().lower() in {
            "1", "true", "yes", "on"}:
        return True
    try:
        from .config import load_config
        return bool((load_config().get("self_harness") or {}).get("enable", False))
    except Exception:  # pragma: no cover -- config never blocks a run
        return False


def _store_path() -> Path:
    return data_dir("harness") / "addenda.json"


# ---- store (the learned, per-model addenda) -------------------------------

def load_addenda(path: Path | None = None) -> dict[str, str]:
    """The accepted ``{model_id: addendum_text}`` map (empty on any error)."""
    p = path if path is not None else _store_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            # Accept ONLY string values: a tampered/corrupt store with a numeric
            # or null value must not coerce to "123"/"None" and get recalled into
            # a prompt as literal garbage.
            return {str(k): v for k, v in data.items()
                    if isinstance(v, str) and v.strip()}
    except (FileNotFoundError, ValueError, OSError):
        pass
    return {}


def _write_addenda(addenda: dict[str, str], path: Path | None = None) -> None:
    # Route through atomic_write_text: a UNIQUE temp + os.replace + chmod 0600
    # that CLEANS THE TEMP UP on any failure. A hand-rolled fixed "<name>.tmp"
    # instead would (a) leave a stale .tmp behind whenever os.replace fails
    # (disk full / read-only FS / target is a dir) and (b) let an UNLOCKED
    # rollback racing a locked apply collide on the shared temp -- one
    # os.replace moving the temp out from under the other. The store itself
    # stays atomic either way, but the stray temp is real. (Found by the
    # fault-injection battery.)
    from .file_lock import atomic_write_text
    p = path if path is not None else _store_path()
    atomic_write_text(p, json.dumps(addenda, indent=2, sort_keys=True), mode=0o600)


def recall_addendum(model_id: str | None, path: Path | None = None) -> str:
    """The learned operating-guidance block for ``model_id`` (``""`` if none /
    disabled). Recalled into the system prompt by the agent at build time."""
    if not model_id or not enabled():
        return ""
    return load_addenda(path).get(str(model_id), "")


def _bullets(block: str) -> list[str]:
    return [ln[2:].strip() for ln in (block or "").splitlines()
            if ln.startswith("- ")]


def _norm_line(s: str) -> str:
    """Canonical form for delta-merge equality: case-folded, whitespace-collapsed,
    trailing punctuation stripped. Two lines with the same normal form are the
    SAME guidance reworded only trivially (e.g. an LLM proposer returning
    "Verify the token." then later "verify the token") -- they should refresh,
    not occupy two of the bounded slots. Deliberately EXACT-after-normalization,
    not fuzzy: templated per-class lines differ by a single token, and a fuzzy
    threshold would wrongly merge distinct failure classes."""
    return " ".join(str(s or "").split()).casefold().rstrip(".,;:!? ")


def list_learned(path: Path | None = None) -> dict[str, list[str]]:
    """The learned guidance lines per model, for operator inspection.

    Returns ``{model_id: [line, ...]}`` parsed from the stored addenda -- the
    same lines :func:`recall_addendum` injects, minus the framing header. Note
    this reads the STORE regardless of :func:`enabled`; the recall path is what
    gates on the toggle, so an operator can still inspect/roll back what was
    learned while the feature is paused."""
    out: dict[str, list[str]] = {}
    for model_id, block in load_addenda(path).items():
        lines = _bullets(block)
        if lines:
            out[model_id] = lines
    return out


def forget_addendum(model_id: str, *, line: str | None = None,
                    path: Path | None = None) -> bool:
    """Operator rollback: remove a model's learned addendum, or a single line.

    The user-facing undo handle for self-harness learning. The removal is
    serialized + atomic like every other store write, and is itself audited so
    the rollback leaves a trail. Returns ``True`` if something was removed,
    ``False`` if there was nothing matching to remove."""
    p = path if path is not None else _store_path()
    from .file_lock import cross_process_lock
    removed = False
    with _lock, cross_process_lock(p):
        before = load_addenda(p)
        if model_id not in before:
            return False
        after = dict(before)
        if line is None:
            del after[model_id]
            removed = True
        else:
            existing = _bullets(before[model_id])
            kept = [ln for ln in existing if ln != line]
            removed = len(kept) != len(existing)
            if not removed:
                return False
            if kept:
                header = "Operating guidance learned for this model:"
                after[model_id] = header + "\n" + "\n".join(f"- {ln}" for ln in kept)
            else:
                del after[model_id]
        _write_addenda(after, p)
    try:
        from .audit import EventKind, record
        record(EventKind.LEARNING_UPDATE, agent="self_harness", model_id=model_id,
               rung="prompt", line=line or "*", phase="forget")
    except Exception:  # pragma: no cover -- audit best-effort
        pass
    return removed


# ---- MINE -----------------------------------------------------------------

@dataclass(frozen=True)
class FailureSignature:
    """A recurring failure pattern for one model -- the weakness to target."""
    model_id: str
    failure_class: str
    signature: str              # short human description of the recurring failure
    support: int                # how many traces back it
    examples: tuple[str, ...]   # representative (sanitized) goal texts


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall((text or "").lower()))


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _is_minable(r: object, model_id: str) -> bool:
    """Whether a single reflexion is eligible to be mined for ``model_id``:
    a dict, tagged with this exact model, and UNSCOPED (no channel/user_id).
    The single source of truth for the mining-eligibility guard so the CLI's
    eligible count can never drift from what :func:`mine_failures` actually
    considers."""
    return (isinstance(r, dict)
            and str(r.get("model_id") or "") == str(model_id)
            and r.get("channel") is None and r.get("user_id") is None)


def count_eligible(reflexions: list[dict], *, model_id: str) -> int:
    """How many of ``reflexions`` are eligible to be mined for ``model_id``.

    A reflexion is eligible only if it is tagged with this model AND unscoped
    (the trace-poisoning guard drops scoped/remote-user failures). The operator
    CLI uses this to explain why scanning N reflexions mined nothing: "scanned
    N" can far exceed the eligible count when failures are scoped or belong to a
    different model, and a bare "no weaknesses" otherwise reads as "this model
    never fails" rather than "those failures were excluded by design"."""
    return sum(1 for r in (reflexions or []) if _is_minable(r, model_id))


def mine_failures(
    reflexions: list[dict], *, model_id: str, min_support: int = 3,
    similarity: float = 0.3,
) -> list[FailureSignature]:
    """Cluster ONE model's failure traces into recurring signatures.

    Model-specific by design (the paper's key lever): only traces whose
    ``model_id`` matches are considered, so a weakness mined for one model never
    leaks into another's harness. Within a model, traces are grouped by
    ``failure_class`` then greedily clustered by goal-text Jaccard overlap; only
    clusters with ``>= min_support`` members survive (a one-off is noise, not a
    pattern). ``min_support < 1`` disables mining (returns nothing).

    SCOPE GUARD (trace-poisoning defense): only UNSCOPED failures -- ones with
    no ``channel`` and no ``user_id`` -- are mined. A scoped reflexion came from
    a remote user on some channel and may carry attacker-influenced goal/failure
    text; the addendum is recalled into EVERY future run of this model (across
    all channels/tenants), so admitting scoped text would let a hostile caller
    poison the harness cross-channel. This mirrors dreaming's unscoped-only
    promotion guard. A purely-local operator's runs are unscoped, so this costs
    nothing in the intended single-operator case."""
    if min_support < 1:
        return []
    mine = [r for r in (reflexions or []) if _is_minable(r, model_id)]
    # DoS backstop: greedy clustering is O(n*clusters) -- worst case O(n^2) when
    # every trace is a distinct goal. The runner already feeds only the most
    # recent ``limit`` (500) traces, but mine_failures is public; a direct caller
    # passing a huge list would otherwise hang the pass. Cap at a generous bound
    # (well above the runner's 500) and keep the most RECENT slice, so a runaway
    # input is bounded without affecting any realistic call. (Found by the
    # algorithmic-complexity battery.)
    if len(mine) > _MAX_MINE_TRACES:
        log.warning("self_harness: mining %d traces capped to %d (most recent)",
                    len(mine), _MAX_MINE_TRACES)
        mine = mine[-_MAX_MINE_TRACES:]
    # Canonicalize order so mining is DETERMINISTIC and permutation-invariant:
    # the greedy clustering and the by-class grouping both depend on iteration
    # order, so the same failures in a different log order would otherwise mine
    # different weaknesses -- non-reproducible learning from identical evidence.
    mine.sort(key=lambda r: (str(r.get("failure_class") or "error"),
                             str(r.get("goal_text") or ""),
                             str(r.get("failure_msg") or "")))
    by_class: dict[str, list[dict]] = {}
    for r in mine:
        by_class.setdefault(str(r.get("failure_class") or "error"), []).append(r)

    out: list[FailureSignature] = []
    for fclass, recs in by_class.items():
        clusters: list[list[dict]] = []
        # Cache each cluster HEAD's token set (parallel to ``clusters``). The
        # head's goal text never changes, so re-tokenizing it on every
        # comparison -- as a naive ``_tokens(cluster[0][...])`` in the inner loop
        # does -- is pure waste: it turned the greedy pass into a tokenize-bound
        # O(n^2) that took ~69s on 8k traces. Tokenize each head once instead.
        # Behaviour is identical: ``heads[i]`` is the token set of ``clusters[i]``'s
        # first member, exactly what the old code recomputed. (Found by the
        # algorithmic-complexity battery.)
        heads: list[set[str]] = []
        for r in recs:
            rt = _tokens(str(r.get("goal_text", "")))
            for i, htok in enumerate(heads):
                if _jaccard(rt, htok) >= similarity:
                    clusters[i].append(r)
                    break
            else:
                clusters.append([r])
                heads.append(rt)
        for cluster in clusters:
            if len(cluster) < min_support:
                continue
            examples = tuple(
                dict.fromkeys(  # de-dupe, preserve order
                    str(c.get("goal_text", "")).strip().splitlines()[0][:160]
                    for c in cluster if str(c.get("goal_text", "")).strip()
                )
            )[:3]
            out.append(FailureSignature(
                model_id=str(model_id), failure_class=fclass,
                signature=_summarize_signature(cluster),
                support=len(cluster), examples=examples,
            ))
    # Strongest weaknesses first.
    out.sort(key=lambda s: s.support, reverse=True)
    return out


def _summarize_signature(cluster: list[dict]) -> str:
    """A short, deterministic description of what keeps going wrong."""
    fclass = str(cluster[0].get("failure_class") or "error")
    # Most common short failure message in the cluster, if any.
    msgs = [str(c.get("failure_msg") or "").strip() for c in cluster]
    msgs = [m for m in msgs if m]
    # sorted() before max() so a tie in frequency breaks deterministically
    # (alphabetically) instead of by set iteration order.
    common = max(sorted(set(msgs)), key=msgs.count) if msgs else ""
    common = common.splitlines()[0][:120] if common else ""
    return f"{fclass}: {common}" if common else fclass


# ---- PROPOSE --------------------------------------------------------------

@dataclass(frozen=True)
class HarnessProposal:
    """A candidate operating-guidance line targeting one failure signature."""
    model_id: str
    signature: str
    addendum_line: str          # the minimal guidance to add
    rationale: str


# An injected proposer: given a signature, return a single short guidance line
# (the model proposing how to avoid its OWN recurring failure). Pure/seam.
ProposeFn = Callable[[FailureSignature], str]

def _sanitize_line(text: str) -> str:
    """Neutralize a proposed addendum line before it can enter a prompt.

    Defense-in-depth on top of the unscoped-only mining guard: the line still
    derives from trace text and (with an LLM proposer) from model output, so
    strip control chars, collapse all whitespace to single spaces (no multi-line
    break-out), and scrub secrets. The result is one bounded plain-prose line.

    Stripping is by UNICODE CATEGORY, not an ASCII regex: every control char
    (category ``Cc`` -- C0, the C1 0x80-0x9f block, and DEL) and every format
    char (``Cf`` -- zero-width ZWSP/ZWNJ/ZWJ, the BOM, and bidi overrides like
    RLO/LRO/isolates) is replaced with a space. An ASCII-only ``[\\x00-\\x1f\\x7f]``
    pass let the whole non-ASCII slice through, and this line lands in EVERY
    system prompt for the model AND in the signed audit + addenda.json a human
    reviews: a C1 byte injects a terminal escape when that log is cat'd, a
    zero-width char splits a trigger word past a downstream filter, and an RLO
    visually reverses the guidance an auditor reads. Zl/Zp/Zs separators are
    Unicode whitespace, so ``split()`` below already collapses them. (Found by
    the adversarial input-fuzzing battery.)"""
    raw = str(text or "")
    cleaned = "".join(
        " " if unicodedata.category(c) in {"Cc", "Cf"} else c for c in raw)
    line = " ".join(cleaned.split())  # collapse all whitespace incl. newlines
    try:
        from .secrets import scrub
        line = scrub(line)
    except Exception:  # pragma: no cover -- scrubbing must never break the loop
        pass
    return line.strip()


# Failure-class-grounded guidance for the deterministic proposer. arXiv
# 2603.23994 warns the STARTING ARTIFACT bounds what the loop can ever learn, so
# a generic "slow down and verify" line is a weak seed. These per-class lines
# are specific AND -- unlike the generic fallback -- do NOT embed the
# trace-derived signature text into the prompt, so they need no sanitization.
_CLASS_GUIDANCE: dict[str, str] = {
    "timeout": "this kind of goal has timed out before; budget the work, prefer "
               "incremental/streaming steps, and check for long-running "
               "operations before you start.",
    "auth": "this kind of goal has failed on authentication before; verify "
            "credentials and token freshness (refresh if near expiry) before the call.",
    "parse": "this kind of goal has failed on parsing before; validate the "
             "response shape before parsing and handle malformed or partial data.",
    "tool_error": "this kind of goal has hit a tool error before; check the "
                  "tool's preconditions and arguments and read its error output "
                  "before retrying.",
    "shield": "this kind of goal has been blocked by the safety shield before; "
              "stay within policy and avoid the action that tripped it.",
    "max_steps": "this kind of goal has run out of steps before; plan the fewest "
                 "steps to the result and avoid exploratory detours.",
    "budget": "this kind of goal has exhausted its budget before; do the cheapest "
              "sufficient work first and avoid redundant tool calls.",
    "agent_error": "this kind of goal has failed mid-run before; re-read the "
                   "error, confirm preconditions, and take the smallest safe "
                   "next step rather than retrying blindly.",
}


def _default_propose(sig: FailureSignature) -> str:
    """Deterministic fallback proposer (no LLM): a failure-class-grounded
    guidance line, templated so the loop runs and is testable without a
    provider. Specific by class; falls back to a generic (sanitized) line for an
    unknown class."""
    specific = _CLASS_GUIDANCE.get(sig.failure_class)
    if specific:
        return f"When a goal resembles your past {sig.failure_class} failures, {specific}"
    return (f"When a goal resembles your past {sig.failure_class} failures "
            f"({sig.signature}), slow down and verify the precondition that "
            f"tripped you before acting.")


def llm_proposer(llm, *, budget=None, model: str | None = None,
                 max_tokens: int = 200) -> ProposeFn:
    """Build a REFLECTIVE proposer backed by an LLM -- the GEPA/RPT shape
    (arXiv 2507.19457, 2605.21781): read the mined failure signature + example
    goals and write ONE minimal operating-guidance line. Injected exactly like
    any other ``propose_fn``; the model is NOT hard-coded (kernel rule 2) --
    pass ``model`` or let the ``llm``'s own resolved model stand.

    Fails OPEN to :func:`_default_propose` on any provider error, empty output,
    or non-finite result, so a flaky model never blocks or skips a pass. The
    returned line still flows through ``propose_addendum``'s ``_sanitize_line``
    + length gate, so an attacker-influenced model cannot smuggle control chars,
    secrets, or multi-line break-outs past the existing defenses."""
    def _propose(sig: FailureSignature) -> str:
        try:
            system = (
                "You tune a coding agent's operating guidance. Given a recurring "
                "failure pattern for ONE model, write a single short imperative "
                "guidance line (<=200 characters, no preamble, no markdown, no "
                "newlines) that, added to that model's system prompt, would help "
                "it avoid this class of failure. Be specific and minimal.")
            examples = "\n".join(f"- {e}" for e in sig.examples[:3]) or "(none)"
            user = (f"Model: {sig.model_id}\nFailure class: {sig.failure_class}\n"
                    f"Signature: {sig.signature}\nExample goals that failed:\n"
                    f"{examples}\n\nGuidance line:")
            resp = llm.complete(system, [{"role": "user", "content": user}],
                                budget=budget, max_tokens=max_tokens, model=model)
            text = (getattr(resp, "text", "") or "")
            line = next((s.strip() for s in text.splitlines() if s.strip()), "")
            line = line.lstrip("-*•> ").strip().strip('"').strip()
            if line:
                return line
        except Exception as e:  # pragma: no cover -- fail open to deterministic
            log.warning("self_harness: llm proposer failed (%s); using fallback", e)
        return _default_propose(sig)
    return _propose


def propose_addendum(sig: FailureSignature, *, propose_fn: ProposeFn | None = None,
                     ) -> HarnessProposal | None:
    """Produce a MINIMAL guidance line for ``sig`` via the injected proposer
    (or the deterministic fallback). Returns ``None`` if the proposal is empty
    or too long to be 'minimal'."""
    fn = propose_fn or _default_propose
    try:
        line = fn(sig) or ""
    except Exception as e:  # pragma: no cover -- a bad proposer can't crash the loop
        log.warning("self_harness: proposer failed for %s (%s)", sig.signature, e)
        return None
    line = _sanitize_line(line)  # control chars + multi-line + secrets neutralized
    if not line or len(line) > 280:
        return None
    return HarnessProposal(
        model_id=sig.model_id, signature=sig.signature,
        addendum_line=line,
        rationale=f"targets {sig.support} '{sig.failure_class}' failures",
    )


# ---- VALIDATE -------------------------------------------------------------

@dataclass(frozen=True)
class ValidationResult:
    accepted: bool
    held_in_delta: float
    held_out_delta: float
    reason: str
    # Raw held-out A/B (the unseen-split generalization signal) + case count, so
    # the gate's evidence check judges the honest baseline-vs-candidate numbers.
    baseline_score: float = 0.0
    candidate_score: float = 0.0
    samples: int = 0


# (addendum_text, cases) -> success_rate in [0,1]. Injected: a live A/B needs a
# real model, exactly like learning_rollout's constraints are injected.
ScoreFn = Callable[[str, list[str]], float]


def validate_proposal(
    proposal: HarnessProposal, *, held_in: list[str], held_out: list[str],
    score_with: ScoreFn, score_without: ScoreFn,
) -> ValidationResult:
    """The Self-Harness acceptance test: a harness edit must not regress EITHER
    split and must help at least one (reject pure trades).

    ``held_in`` are the mined cases the edit was written against; ``held_out``
    are unseen cases that guard against overfitting the edit to its own examples
    (the paper's central failure mode). ``score_with``/``score_without`` return
    a success rate for the prompt WITH vs WITHOUT the candidate line."""
    add = proposal.addendum_line
    in_with, in_without = score_with(add, held_in), score_without(add, held_in)
    out_with, out_without = score_with(add, held_out), score_without(add, held_out)
    n = len(held_in) + len(held_out)
    # A score is a success RATE in [0,1]. A buggy/hostile scorer returning a
    # non-finite (NaN/inf) or out-of-range value must NOT drive a promotion: an
    # inf candidate would otherwise sail past the gate's "candidate >= baseline"
    # evidence check. Reject up front. (Found by the 1000-round fuzz campaign.)
    scores = (in_with, in_without, out_with, out_without)
    if not all(isinstance(s, (int, float)) and math.isfinite(s) and 0.0 <= s <= 1.0
               for s in scores):
        return ValidationResult(False, 0.0, 0.0,
                                "scorer returned a non-finite or out-of-range value",
                                baseline_score=0.0, candidate_score=0.0, samples=n)
    in_delta, out_delta = in_with - in_without, out_with - out_without
    # The gate sees the unseen split as the honest baseline/candidate evidence.
    base = dict(baseline_score=out_without, candidate_score=out_with, samples=n)
    # Non-negative on both, strictly positive on at least one.
    if in_delta < 0 or out_delta < 0:
        return ValidationResult(False, in_delta, out_delta,
                                "regressed a split (held-in or held-out)", **base)
    if in_delta <= 0 and out_delta <= 0:
        return ValidationResult(False, in_delta, out_delta,
                                "no improvement on either split", **base)
    return ValidationResult(True, in_delta, out_delta, "validated", **base)


# ---- APPLY / ROLLBACK (the reversible handle the gate requires) -----------

def _compose_addendum(model_id: str, existing: str, line: str) -> str:
    """Append ``line`` to a model's addendum block, bounded + deduped."""
    header = "Operating guidance learned for this model:"
    lines = []
    for raw in (existing or "").splitlines():
        ln = raw.strip()
        if not ln or ln.startswith("Operating guidance"):
            continue
        if ln.startswith("- "):
            ln = ln[2:].strip()
        lines.append(ln)
    # Delta-merge (ACE anti-collapse, arXiv 2510.04618): drop any existing line
    # that normalizes to the SAME guidance as the new one, then append the new
    # one last (newest). This refreshes an exact OR trivially-reworded re-promote
    # to newest (renewed relevance) rather than leaving it where this pass's
    # other new lines would evict it under the newest-wins cap -- which left a
    # promoted line absent from the store (found by the 100k soak) -- and stops a
    # case/whitespace variant from consuming a second of the bounded slots and
    # evicting DISTINCT guidance (the "context collapse / brevity bias" mode).
    # Normalized-EXACT, not fuzzy: templated per-class lines differ by one token,
    # so a similarity threshold would wrongly merge distinct failure classes.
    nl = _norm_line(line)
    lines = [ln for ln in lines if _norm_line(ln) != nl]
    lines.append(line)
    lines = lines[-_MAX_LINES_PER_MODEL:]

    # Enforce the char budget by dropping WHOLE OLDEST bullets, not by slicing
    # the rendered block. A trailing ``block[:_MAX_ADDENDUM_CHARS]`` cut the
    # NEWEST bullets off the end (inverting the newest-wins cap) and could sever
    # a bullet mid-line -- corrupting the last stored line so a later re-promote
    # of it no longer dedups. Lines are <=280 chars, so ~6 max-length lines
    # already overflow 1500: this is reachable, not theoretical. Drop from the
    # front (oldest) until it fits; keep at least the single newest line.
    # (Found by the stateful sequence battery.)
    def _render(ls: list[str]) -> str:
        return header + "\n" + "\n".join(f"- {x}" for x in ls) if ls else header

    while len(lines) > 1 and len(_render(lines)) > _MAX_ADDENDUM_CHARS:
        lines.pop(0)
    # Last-resort guard for a single pathological line wider than the buffer
    # (can't happen under the 280-char propose cap, but stays defensive).
    return _render(lines)[:_MAX_ADDENDUM_CHARS]


def _rollback_handle(path: Path | None = None) -> Callable[[], None]:
    """A thunk restoring the addendum store to its CURRENT state -- the
    reversible handle the gate requires. Captured before any write, so it is a
    valid undo whether or not the change is ultimately applied."""
    p = path if path is not None else _store_path()
    before = load_addenda(p)

    def _rollback() -> None:
        _write_addenda(before, p)

    return _rollback


# Serializes the store's load-modify-save so concurrent passes (the runner, a
# manual CLI, parallel per-model passes) can't clobber each other. The whole
# read-compose-write is one critical section -- an in-process lock plus a
# cross-process flock -- because without it two writers that both read the old
# store both write back, losing one's addendum (8 concurrent promotions
# collapsed to 1 in a forced-interleaving probe).
_lock = threading.Lock()


def _apply_addendum(proposal: HarnessProposal, path: Path | None = None) -> None:
    """Write the accepted line into the model's addendum block (atomically)."""
    p = path if path is not None else _store_path()
    from .file_lock import cross_process_lock
    with _lock, cross_process_lock(p):
        before = load_addenda(p)
        after = dict(before)
        after[proposal.model_id] = _compose_addendum(
            proposal.model_id, before.get(proposal.model_id, ""),
            proposal.addendum_line)
        _write_addenda(after, p)


# ---- DRIVE (mine -> propose -> validate -> gate) --------------------------

@dataclass
class SelfHarnessReport:
    model_id: str
    mined: int = 0
    proposed: int = 0
    validated: int = 0
    promoted: int = 0
    skipped: list[str] = field(default_factory=list)
    applied_lines: list[str] = field(default_factory=list)


def run_self_harness(
    reflexions: list[dict], *, model_id: str,
    held_in: list[str] | None = None, held_out: list[str] | None = None,
    score_with: ScoreFn | None = None, score_without: ScoreFn | None = None,
    propose_fn: ProposeFn | None = None, controller=None,
    min_support: int = 3, path: Path | None = None,
) -> SelfHarnessReport:
    """One self-harness pass for ``model_id``: mine weaknesses, propose minimal
    edits, validate on held-in/held-out, and GATE each survivor through the
    self-improvement ladder before applying it.

    ``score_with``/``score_without`` (the live A/B) are injected; without them
    validation is skipped and the pass is a dry inspection (nothing is applied).
    Returns a :class:`SelfHarnessReport`. Never raises -- a learning pass must
    not perturb anything."""
    report = SelfHarnessReport(model_id=str(model_id))
    if not enabled():
        report.skipped.append("disabled")
        return report
    try:
        sigs = mine_failures(reflexions, model_id=model_id, min_support=min_support)
        report.mined = len(sigs)
        for sig in sigs:
            # The addendum block holds at most _MAX_LINES_PER_MODEL lines. Stop
            # once this pass has filled them: signatures are sorted STRONGEST
            # (highest support) first, so processing more would only let a weaker
            # line evict a stronger one under the newest-wins cap -- and would
            # gate + audit a promotion we'd immediately discard. Keep the
            # strongest weaknesses; report the rest as deferred.
            if report.promoted >= _MAX_LINES_PER_MODEL:
                report.skipped.append(f"addendum at capacity: {sig.signature}")
                continue
            proposal = propose_addendum(sig, propose_fn=propose_fn)
            if proposal is None:
                report.skipped.append(f"no proposal: {sig.signature}")
                continue
            report.proposed += 1

            if score_with is None or score_without is None:
                report.skipped.append(f"no scorer (dry): {proposal.addendum_line}")
                continue
            vr = validate_proposal(
                proposal, held_in=held_in or list(sig.examples),
                held_out=held_out or [], score_with=score_with,
                score_without=score_without)
            if not vr.accepted:
                report.skipped.append(f"rejected ({vr.reason}): {proposal.addendum_line}")
                continue
            report.validated += 1

            ok, why = _gate_and_apply(proposal, vr, controller=controller, path=path)
            if not ok:
                # Surface WHY the gate refused (e.g. "too few samples (3 < 5)",
                # frozen verifier, disabled controller) so an operator with a
                # small validation set or a drifting judge isn't left guessing.
                report.skipped.append(f"gate refused ({why}): {proposal.addendum_line}")
                continue
            report.promoted += 1
            report.applied_lines.append(proposal.addendum_line)
    except Exception as e:  # pragma: no cover -- learning never perturbs a run
        log.warning("self_harness: pass failed (%s)", e)
        report.skipped.append(f"error: {e}")
    return report


def _gate_and_apply(proposal: HarnessProposal, vr: ValidationResult, *,
                    controller=None, path: Path | None = None) -> tuple[bool, str]:
    """Judge the validated proposal through ``self_improvement.consider()`` on
    the ``prompt`` rung and apply it ONLY on a promoting verdict. Returns
    ``(ok, reason)`` -- ``reason`` names the blocking gate when refused.

    Promotion therefore requires the self-improvement controller to be engaged
    (``[self_improvement] enable``): self_harness mines/proposes/validates, but
    the *promotion decision* -- evidence floor, calibration-freeze interlock,
    reversibility -- belongs to the one governed gate every rung shares. The
    rollback handle is captured BEFORE any write, so the reversibility gate is
    satisfied and a refused candidate leaves the store untouched."""
    from . import self_improvement as si

    cand = si.Candidate(
        rung="prompt",
        summary=f"self-harness addendum [{proposal.model_id}]: {proposal.addendum_line}",
        baseline_score=vr.baseline_score,
        candidate_score=vr.candidate_score,
        samples=vr.samples,
        payload={"model_id": proposal.model_id, "line": proposal.addendum_line},
        rollback=_rollback_handle(path),
        provenance={"source": "self_harness", "signature": proposal.signature},
    )
    verdict = si.consider(cand, controller=controller)
    if not getattr(verdict, "ok", False):
        reason = getattr(verdict, "blocking_reason", "") or "refused"
        return False, reason  # gate refused -> nothing written
    _apply_addendum(proposal, path=path)
    try:
        from .audit import EventKind, record
        # Record the DIAGNOSTIC PROVENANCE alongside the line: which weakness it
        # targets (signature/rationale) and the unseen-split evidence that
        # promoted it (held-out delta over N samples). A reversible, signed
        # learning audit should answer "why was this learned?", not just "what"
        # -- the provenance a compliance review / rollback decision needs
        # (arXiv 2508.07407's evaluation-and-safety requirement).
        record(EventKind.LEARNING_UPDATE, agent="self_harness",
               model_id=proposal.model_id, rung="prompt",
               line=proposal.addendum_line, phase="apply",
               signature=proposal.signature, rationale=proposal.rationale,
               held_out_delta=round(vr.held_out_delta, 4), samples=vr.samples)
    except Exception:  # pragma: no cover -- audit best-effort
        pass
    return True, "promoted"


__all__ = [
    "enabled", "recall_addendum", "load_addenda",
    "list_learned", "forget_addendum",
    "FailureSignature", "mine_failures", "count_eligible",
    "HarnessProposal", "ProposeFn", "propose_addendum", "llm_proposer",
    "ValidationResult", "ScoreFn", "validate_proposal",
    "SelfHarnessReport", "run_self_harness",
]
