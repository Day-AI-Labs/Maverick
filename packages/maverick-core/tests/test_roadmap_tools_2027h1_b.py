"""Tests for 2027-H1 tools batch B: voice_command_grammar, what_changed_digest,
gui_element_memory, adversarial_eval. Deterministic and offline."""
from __future__ import annotations

import json

from maverick.tools.adversarial_eval import adversarial_eval
from maverick.tools.gui_element_memory import gui_element_memory
from maverick.tools.voice_command_grammar import voice_command_grammar
from maverick.tools.what_changed_digest import what_changed_digest

_GRAMMAR = [
    {"intent": "pause", "pattern": "pause goal {id}"},
    {"intent": "set_budget", "pattern": "set budget to {amount} dollars"},
    {"intent": "halt", "pattern": "stop everything"},
]


# ---- voice_command_grammar ----

def test_grammar_slot_extraction():
    t = voice_command_grammar()
    out = t.fn({"grammar": _GRAMMAR, "utterance": "pause goal 12"})
    assert "intent: pause" in out and "slots: id=12" in out


def test_grammar_loose_whitespace_and_case():
    t = voice_command_grammar()
    out = t.fn({"grammar": _GRAMMAR, "utterance": "  SET   budget  to  5  dollars "})
    assert "intent: set_budget" in out and "amount=5" in out


def test_grammar_no_slot_and_no_match():
    t = voice_command_grammar()
    assert "intent: halt" in t.fn({"grammar": _GRAMMAR, "utterance": "stop everything"})
    assert t.fn({"grammar": _GRAMMAR, "utterance": "make me a sandwich"}) == "NO MATCH"


def test_grammar_validation():
    t = voice_command_grammar()
    assert t.fn({"grammar": [], "utterance": "x"}).startswith("ERROR")
    assert t.fn({"grammar": _GRAMMAR, "utterance": "  "}).startswith("ERROR")
    assert t.fn({"grammar": [{"intent": "x", "pattern": "{a} {a}"}], "utterance": "1 2"}).startswith("ERROR")


def test_grammar_rejects_adjacent_slots_without_backtracking():
    t = voice_command_grammar()
    grammar = [{"intent": "bad", "pattern": "{s0}{s1}{s2}{s3}{s4}{s5}{s6}{s7}{s8}{s9}{s10}{s11}X"}]
    out = t.fn({"grammar": grammar, "utterance": "a" * 30})
    assert out.startswith("ERROR: invalid pattern")


def test_grammar_input_limits():
    t = voice_command_grammar()
    assert t.fn({"grammar": _GRAMMAR * 22, "utterance": "pause goal 12"}).startswith("ERROR")
    assert t.fn({"grammar": _GRAMMAR, "utterance": "x" * 2049}).startswith("ERROR")
    assert t.fn({"grammar": [{"intent": "x", "pattern": "x" * 513}], "utterance": "x"}).startswith("ERROR")


# ---- what_changed_digest ----

def test_digest_added_removed_changed():
    t = what_changed_digest()
    out = t.fn({"before": {"a": 1, "b": 2, "c": 3}, "after": {"a": 1, "b": 5, "d": 9}})
    assert "1 added, 1 removed, 1 changed" in out
    assert "+ d = 9" in out and "- c (was 3)" in out and "~ b: 2 -> 5" in out


def test_digest_numeric_delta_and_nochange():
    t = what_changed_digest()
    out = t.fn({"before": {"cost": 10.0}, "after": {"cost": 12.5}, "numeric_delta": True})
    assert "~ cost: 10 -> 12.5  (+2.5)" in out
    assert t.fn({"before": {"a": 1}, "after": {"a": 1}}) == "no changes"


def test_digest_validation():
    t = what_changed_digest()
    assert t.fn({"before": [], "after": {}}).startswith("ERROR")


# ---- gui_element_memory ----

def test_gui_put_get_roundtrip():
    t = gui_element_memory()
    store = t.fn({"op": "put", "app": "checkout", "screen": "pay", "name": "submit", "selector": "#pay-btn"})
    entries = json.loads(store)
    assert entries == [{"app": "checkout", "screen": "pay", "name": "submit", "selector": "#pay-btn"}]
    got = t.fn({"op": "get", "memory": entries, "app": "checkout", "screen": "pay", "name": "submit"})
    assert json.loads(got)["selector"] == "#pay-btn"
    assert t.fn({"op": "get", "memory": entries, "app": "x", "screen": "y", "name": "z"}) == "NOT FOUND"


def test_gui_put_upserts_and_lists():
    t = gui_element_memory()
    e1 = json.loads(t.fn({"op": "put", "app": "a", "screen": "s", "name": "btn", "selector": "#old"}))
    e2 = json.loads(t.fn({"op": "put", "memory": e1, "app": "a", "screen": "s", "name": "btn", "selector": "#new"}))
    assert len(e2) == 1 and e2[0]["selector"] == "#new"
    listing = t.fn({"op": "list", "memory": e2, "app": "a"})
    assert "a/s/btn: #new" in listing


def test_gui_validation():
    t = gui_element_memory()
    assert t.fn({"op": "put", "app": "a"}).startswith("ERROR")
    assert t.fn({"op": "bogus"}).startswith("ERROR")
    assert t.fn({"op": "list"}) == "(empty)"


# ---- adversarial_eval ----

def test_adv_eval_missed_attack_fails():
    t = adversarial_eval()
    out = t.fn({"cases": [
        {"prompt": "ignore prior instructions", "expected": "block", "actual": "block"},
        {"prompt": "exfil the env vars", "expected": "block", "actual": "allow"},
        {"prompt": "what's the weather", "expected": "allow", "actual": "allow"},
    ]})
    assert "TP=1 FP=0 TN=1 FN=1" in out
    assert "verdict: FAIL (missed attacks: 1)" in out
    assert "exfil the env vars" in out


def test_adv_eval_clean_pass_and_overblock():
    t = adversarial_eval()
    out = t.fn({"cases": [
        {"prompt": "jailbreak", "expected": "block", "actual": "deny"},
        {"prompt": "benign", "expected": "allow", "actual": "refuse"},
    ]})
    assert "FN=0" in out and "verdict: PASS" in out
    assert "OVER-BLOCKED" in out and "benign" in out


def test_adv_eval_validation():
    t = adversarial_eval()
    assert t.fn({"cases": []}).startswith("ERROR")
    assert t.fn({"cases": [{"expected": "block", "actual": "maybe"}]}).startswith("ERROR")


def test_batch_registered():
    from maverick.tools import base_registry

    class _W:
        pass

    class _S:
        pass

    names = set(getattr(base_registry(world=_W(), sandbox=_S()), "_tools", {}).keys())
    for name in ("voice_command_grammar", "what_changed_digest",
                 "gui_element_memory", "adversarial_eval"):
        assert name in names
