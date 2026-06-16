"""LLM-creative hypothesis generation: build a prompt, parse the reply into clean
action names, and survive a flaky model -- all without a provider key.
"""
from __future__ import annotations

from maverick import llm_hypothesizer as lh
from maverick.data_engine import FailureClass


def _fc(action="shell", effect=-0.5):
    return FailureClass(action=action, count=5, mean_outcome=0.2, causal_effect=effect,
                        ci_low=effect - 0.1, ci_high=effect + 0.3, trustworthy=True,
                        exemplars=())


def test_build_prompt_mentions_the_harmful_action():
    p = lh.build_prompt(_fc("rm_rf"), n=3)
    assert "rm_rf" in p and "-0.50" in p and "up to 3" in p


def test_parse_strips_bullets_numbering_and_prose():
    text = (
        "1. read_first\n"
        "- dry_run\n"
        "* `validate_plan`\n"
        "This whole line is prose and should be dropped because it is long\n"
        "read_first\n"          # duplicate
        "batch_apply"
    )
    assert lh.parse_interventions(text, n=10) == [
        "read_first", "dry_run", "validate_plan", "batch_apply"]


def test_parse_respects_the_cap():
    assert lh.parse_interventions("a\nb\nc\nd\ne", n=2) == ["a", "b"]


def test_generate_interventions_uses_injected_complete():
    captured = {}

    def complete(prompt):
        captured["prompt"] = prompt
        return "alt_one\nalt_two"

    out = lh.generate_interventions(_fc("shell"), complete, n=5)
    assert out == ["alt_one", "alt_two"]
    assert "shell" in captured["prompt"]


def test_generate_survives_a_flaky_model():
    def complete(prompt):
        raise RuntimeError("provider down")
    assert lh.generate_interventions(_fc(), complete) == []
