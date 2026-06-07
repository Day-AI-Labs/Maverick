"""Oversight control plane policy engine: ALLOW / DENY / REQUIRE_HUMAN.

Pure decision logic (no I/O), so every clause + the strictest-wins precedence is
unit-tested directly. Risk facts used: ``shell`` is high-risk, ``read_file`` is
low-risk (see ``safety.tool_risk``).
"""
from __future__ import annotations

from maverick.governance import Decision, Policy, evaluate


def test_empty_policy_allows():
    v = evaluate("read_file", policy=Policy())
    assert v.decision is Decision.ALLOW and v.allowed and v.rule == "default"


def test_deny_actions():
    v = evaluate("delete_file", policy=Policy(deny_actions=frozenset({"delete_file"})))
    assert v.decision is Decision.DENY and v.rule == "deny_actions"


def test_deny_min_risk_floor():
    pol = Policy(deny_min_risk="high")
    assert evaluate("shell", policy=pol).decision is Decision.DENY        # high
    assert evaluate("read_file", policy=pol).decision is Decision.ALLOW   # low


def test_require_human_actions():
    v = evaluate("send_email",
                 policy=Policy(require_human_actions=frozenset({"send_email"})))
    assert v.decision is Decision.REQUIRE_HUMAN and v.needs_human


def test_require_human_min_risk_floor():
    pol = Policy(require_human_min_risk="high")
    assert evaluate("shell", policy=pol).decision is Decision.REQUIRE_HUMAN
    assert evaluate("read_file", policy=pol).decision is Decision.ALLOW


def test_risk_override_param():
    # An action classified low can be forced high by the caller.
    pol = Policy(require_human_min_risk="high")
    assert evaluate("read_file", risk="high", policy=pol).decision is Decision.REQUIRE_HUMAN


def test_capability_denial_takes_precedence():
    from maverick.capability import Capability
    cap = Capability(principal="p", deny_tools=frozenset({"shell"}))
    v = evaluate("shell", capability=cap,
                 policy=Policy(require_human_actions=frozenset({"shell"})))
    assert v.decision is Decision.DENY and v.rule == "capability"


def test_deny_beats_require_human():
    pol = Policy(deny_actions=frozenset({"x"}),
                 require_human_actions=frozenset({"x"}))
    assert evaluate("x", policy=pol).decision is Decision.DENY


def test_from_config(monkeypatch):
    monkeypatch.setattr("maverick.config.load_config", lambda *a, **k: {
        "governance": {
            "deny_actions": ["delete_file"],
            "require_human_actions": ["send_email"],
            "require_human_min_risk": "high",
        },
    })
    pol = Policy.from_config()
    assert "delete_file" in pol.deny_actions
    assert "send_email" in pol.require_human_actions
    assert pol.require_human_min_risk == "high"
    assert not pol.is_empty()


def test_from_config_empty_is_default_allow(monkeypatch):
    monkeypatch.setattr("maverick.config.load_config", lambda *a, **k: {})
    pol = Policy.from_config()
    assert pol.is_empty()
    assert evaluate("shell", policy=pol).decision is Decision.ALLOW
