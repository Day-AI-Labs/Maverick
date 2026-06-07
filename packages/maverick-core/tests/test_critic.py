"""Critic: graded structured critique (re-triage build)."""
from __future__ import annotations

from maverick.critic import Critic, CriticReview


def _critic_returning(text):
    return Critic(lambda prompt: text)


def test_parses_clean_json():
    c = _critic_returning(
        '{"confidence": 0.9, "recommendation": "accept", "issues": []}')
    r = c.review("some output")
    assert isinstance(r, CriticReview)
    assert r.confidence == 0.9
    assert r.recommendation == "accept"
    assert r.issues == []


def test_extracts_json_from_prose():
    c = _critic_returning(
        'Sure! Here is my review:\n{"confidence": 0.3, '
        '"recommendation": "reject", "issues": ["wrong", "incomplete"]}\nThanks.')
    r = c.review("x")
    assert r.recommendation == "reject"
    assert r.issues == ["wrong", "incomplete"]


def test_confidence_clamped():
    assert _critic_returning('{"confidence": 5}').review("x").confidence == 1.0
    assert _critic_returning('{"confidence": -2}').review("x").confidence == 0.0


def test_recommendation_inferred_from_confidence():
    # no recommendation field -> inferred from confidence buckets
    assert _critic_returning('{"confidence": 0.95}').review("x").recommendation == "accept"
    assert _critic_returning('{"confidence": 0.5}').review("x").recommendation == "revise"
    assert _critic_returning('{"confidence": 0.1}').review("x").recommendation == "reject"


def test_malformed_reply_safe_defaults():
    r = _critic_returning("totally not json").review("x")
    assert r.confidence == 0.0
    assert r.recommendation == "reject"
    assert r.issues == []


def test_issues_string_coerced_to_list():
    r = _critic_returning('{"confidence": 0.5, "issues": "single issue"}').review("x")
    assert r.issues == ["single issue"]


def test_prompt_includes_criteria():
    captured = {}
    Critic(lambda p: captured.setdefault("p", p) or '{"confidence":1}').review(
        "the work", criteria="must cite sources")
    assert "must cite sources" in captured["p"]
    assert "the work" in captured["p"]
