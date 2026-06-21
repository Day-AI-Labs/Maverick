"""Cross-provider speculative drafting (ROADMAP 2028 H2) — offline tests."""
from __future__ import annotations

import json

import pytest
from maverick.speculative_decode import (
    AcceptanceLedger,
    build_verify_prompt,
    draft_accepted,
    speculative_complete,
)

DRAFT = "The answer is 42 because the question is unknowable."


@pytest.fixture()
def ledger(tmp_path):
    return AcceptanceLedger(tmp_path / "ledger.json")


def _calls(draft_text=DRAFT, target_fn=None):
    """Build recording (draft_call, target_call, record) seams."""
    record = {"draft": [], "target": []}

    def draft_call(prompt, model):
        record["draft"].append((prompt, model))
        return draft_text

    def target_call(prompt, model):
        record["target"].append((prompt, model))
        return target_fn(prompt) if target_fn else DRAFT  # echo = accept

    return draft_call, target_call, record


# ---------- acceptance detection ----------

def test_accepts_verbatim_and_extension():
    assert draft_accepted(DRAFT, DRAFT)
    assert draft_accepted(DRAFT, DRAFT + " And that is final.")
    assert draft_accepted("a  b\nc", "a b c")  # whitespace-insensitive


def test_rejects_rewrite_and_empty():
    assert not draft_accepted(DRAFT, "Completely different reasoning and answer text here.")
    assert not draft_accepted("", "anything")
    assert not draft_accepted(DRAFT, "")


def test_accepts_near_identical_touch_up():
    final = DRAFT.replace("unknowable", "unknowable.")
    assert draft_accepted(DRAFT, final, threshold=0.9)


# ---------- the draft-and-verify path ----------

def test_accept_path_records_and_returns_target_text(ledger):
    draft_call, target_call, record = _calls()
    res = speculative_complete(
        "What is the answer?", draft_call=draft_call, target_call=target_call,
        draft_model="cheap:d1", target_model="big:t1", ledger=ledger,
    )
    assert res.text == DRAFT and res.drafted and res.accepted
    assert res.draft_model == "cheap:d1" and res.target_model == "big:t1"
    # The single target call carried the draft + accept/revise instructions.
    verify_prompt = record["target"][0][0]
    assert verify_prompt == build_verify_prompt("What is the answer?", DRAFT)
    assert "<draft>" in verify_prompt and "VERBATIM" in verify_prompt
    assert record["draft"] == [("What is the answer?", "cheap:d1")]
    assert ledger.accept_rate("cheap:d1", "big:t1") == (1.0, 1)


def test_revise_path_records_rejection(ledger):
    draft_call, target_call, _ = _calls(
        target_fn=lambda p: "No: the real answer is entirely different and much longer than that.",
    )
    res = speculative_complete(
        "q", draft_call=draft_call, target_call=target_call,
        draft_model="d", target_model="t", ledger=ledger,
    )
    assert res.drafted and not res.accepted
    assert res.text.startswith("No: the real answer")
    rate, samples = ledger.accept_rate("d", "t")
    assert (rate, samples) == (0.0, 1)


def test_empty_draft_falls_back_and_counts_against_pair(ledger):
    draft_call, target_call, record = _calls(draft_text="   ")
    res = speculative_complete(
        "q", draft_call=draft_call, target_call=target_call,
        draft_model="d", target_model="t", ledger=ledger,
    )
    assert res.drafted and not res.accepted and res.text == DRAFT
    assert record["target"] == [("q", "t")]  # plain prompt, no <draft> wrapper
    assert ledger.accept_rate("d", "t") == (0.0, 1)


def test_draft_exception_falls_back_without_recording(ledger):
    def broken_draft(prompt, model):
        raise RuntimeError("provider down")

    _, target_call, record = _calls()
    res = speculative_complete(
        "q", draft_call=broken_draft, target_call=target_call,
        draft_model="d", target_model="t", ledger=ledger,
    )
    assert not res.drafted and res.text == DRAFT
    assert record["target"] == [("q", "t")]
    assert ledger.accept_rate("d", "t") == (1.0, 0)  # transport errors leave no mark


# ---------- the accept-rate floor ----------

def test_floor_skips_drafting_for_losing_pair(ledger):
    for _ in range(5):
        ledger.record("d", "t", False)  # 0/5 accepted

    def never_draft(prompt, model):
        raise AssertionError("draft model must not be called below the floor")

    _, target_call, record = _calls()
    res = speculative_complete(
        "q", draft_call=never_draft, target_call=target_call,
        draft_model="d", target_model="t", ledger=ledger,
        floor=0.3, min_samples=5,
    )
    assert not res.drafted and res.text == DRAFT
    assert res.accept_rate == 0.0
    assert record["target"] == [("q", "t")]


def test_below_min_samples_keeps_drafting(ledger):
    for _ in range(4):
        ledger.record("d", "t", False)  # 0/4: not enough evidence yet
    draft_call, target_call, record = _calls()
    res = speculative_complete(
        "q", draft_call=draft_call, target_call=target_call,
        draft_model="d", target_model="t", ledger=ledger,
        floor=0.3, min_samples=5,
    )
    assert res.drafted
    assert len(record["draft"]) == 1


def test_healthy_pair_keeps_drafting(ledger):
    for _ in range(10):
        ledger.record("d", "t", True)
    draft_call, target_call, _ = _calls()
    res = speculative_complete(
        "q", draft_call=draft_call, target_call=target_call,
        draft_model="d", target_model="t", ledger=ledger,
    )
    assert res.drafted and res.accept_rate == 1.0


# ---------- ledger persistence ----------

def test_ledger_roundtrip(tmp_path):
    path = tmp_path / "ledger.json"
    led = AcceptanceLedger(path)
    led.record("d", "t", True)
    led.record("d", "t", False)
    led.record("x", "y", True)
    reloaded = AcceptanceLedger(path)
    assert reloaded.accept_rate("d", "t") == (0.5, 2)
    assert reloaded.accept_rate("x", "y") == (1.0, 1)
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["d -> t"] == {"accepted": 1, "total": 2}


def test_ledger_corrupt_file_fails_soft(tmp_path):
    path = tmp_path / "ledger.json"
    path.write_text("{not json", encoding="utf-8")
    led = AcceptanceLedger(path)
    assert led.accept_rate("d", "t") == (1.0, 0)
    led.record("d", "t", True)  # and it can recover by writing fresh
    assert AcceptanceLedger(path).accept_rate("d", "t") == (1.0, 1)


# ---------- model resolution: roles, never hardcoded ----------

def test_models_resolve_via_role_chain(ledger, monkeypatch):
    """Default models come from model_for_role (config-first), not literals."""
    monkeypatch.setenv("MAVERICK_MODEL_OVERRIDE_SUMMARIZER", "prov:tiny-draft")
    monkeypatch.setenv("MAVERICK_MODEL_OVERRIDE_WRITER", "prov:big-target")
    draft_call, target_call, record = _calls()
    res = speculative_complete(
        "q", draft_call=draft_call, target_call=target_call, ledger=ledger,
    )
    assert res.draft_model == "prov:tiny-draft"
    assert res.target_model == "prov:big-target"
    assert record["draft"][0][1] == "prov:tiny-draft"
    assert record["target"][0][1] == "prov:big-target"


def test_explicit_models_win_without_touching_roles(ledger):
    draft_call, target_call, _ = _calls()
    res = speculative_complete(
        "q", draft_call=draft_call, target_call=target_call,
        draft_model="a:b", target_model="c:d", ledger=ledger,
    )
    assert (res.draft_model, res.target_model) == ("a:b", "c:d")


def test_record_is_concurrency_safe(tmp_path):
    """Separate ledgers at one path (≈ separate processes) must accumulate
    accept/total counts, not clobber each other."""
    import threading

    p = tmp_path / "ledger.json"
    n, per = 8, 25

    def worker():
        led = AcceptanceLedger(p)
        for _ in range(per):
            led.record("draft", "target", True)

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    final = AcceptanceLedger(p)
    rate, samples = final.accept_rate("draft", "target")
    assert samples == n * per
    assert rate == 1.0
    assert list(tmp_path.glob("*.tmp")) == []
