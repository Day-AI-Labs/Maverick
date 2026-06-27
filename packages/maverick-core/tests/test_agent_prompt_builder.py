"""Characterization tests for the first extracted PromptBuilder seam.

``agent.select_base_template`` was lifted out of ``Agent._build_system`` as the
first side-effect-free collaborator in the god-module decomposition. These pin
its branch behavior so the extraction is provably byte-identical to the inline
code it replaced (the orchestrator/worker/coding-mode selection).
"""
from __future__ import annotations

from maverick.agent import (
    ORCHESTRATOR_SYSTEM_TEMPLATE,
    WORKER_SYSTEM_TEMPLATE,
    apply_global_overlays,
    apply_role_overlays,
    select_base_template,
)


def test_orchestrator_template_when_not_coding():
    out = select_base_template(
        role="orchestrator", depth=0, max_depth=5, coding_enabled=False)
    assert out == ORCHESTRATOR_SYSTEM_TEMPLATE.format(max_depth=5)


def test_worker_template_for_other_roles():
    out = select_base_template(
        role="researcher", depth=2, max_depth=5, coding_enabled=False)
    assert out == WORKER_SYSTEM_TEMPLATE.format(
        role="researcher", depth=2, max_depth=5)


def test_coding_mode_overrides_role():
    from maverick.coding_mode import CODER_CODING_MODE_TEMPLATE
    out = select_base_template(
        role="orchestrator", depth=0, max_depth=5, coding_enabled=True)
    assert out == CODER_CODING_MODE_TEMPLATE.format(
        role="orchestrator", depth=0, max_depth=5)
    # Coding mode overrides the role -> NOT the prose orchestrator template.
    assert out != ORCHESTRATOR_SYSTEM_TEMPLATE.format(max_depth=5)


def test_coding_mode_worker_is_also_coder():
    from maverick.coding_mode import CODER_CODING_MODE_TEMPLATE
    out = select_base_template(
        role="coder", depth=1, max_depth=3, coding_enabled=True)
    assert out == CODER_CODING_MODE_TEMPLATE.format(
        role="coder", depth=1, max_depth=3)


# ---- apply_global_overlays (second PromptBuilder collaborator) ----

def test_overlays_append_persona_style_habits_in_order(monkeypatch):
    monkeypatch.setattr("maverick.persona.render_persona_prompt", lambda: "P")
    monkeypatch.setattr("maverick.styles.render_active_style_prompt", lambda: "S")
    monkeypatch.setattr("maverick.data_engine.enabled", lambda: True)
    monkeypatch.setattr("maverick.procedural_memory.recall_prompt", lambda: "H")
    # base + persona + style + habits, in that exact order.
    assert apply_global_overlays("BASE") == "BASEPSH"


def test_overlays_skip_empty_and_disabled(monkeypatch):
    monkeypatch.setattr("maverick.persona.render_persona_prompt", lambda: "")
    monkeypatch.setattr("maverick.styles.render_active_style_prompt", lambda: "")
    monkeypatch.setattr("maverick.data_engine.enabled", lambda: False)
    assert apply_global_overlays("BASE") == "BASE"


def test_overlays_fail_open_on_error(monkeypatch):
    def boom():
        raise RuntimeError("overlay source down")
    monkeypatch.setattr("maverick.persona.render_persona_prompt", boom)
    monkeypatch.setattr("maverick.styles.render_active_style_prompt", lambda: "S")
    monkeypatch.setattr("maverick.data_engine.enabled", lambda: False)
    # Persona raises -> that overlay is skipped; style still applies; no raise.
    assert apply_global_overlays("BASE") == "BASES"


def test_overlays_habits_skipped_when_data_engine_off(monkeypatch):
    monkeypatch.setattr("maverick.persona.render_persona_prompt", lambda: "")
    monkeypatch.setattr("maverick.styles.render_active_style_prompt", lambda: "")
    monkeypatch.setattr("maverick.data_engine.enabled", lambda: False)
    # recall_prompt must NOT be consulted when the data engine is off.
    monkeypatch.setattr(
        "maverick.procedural_memory.recall_prompt",
        lambda: (_ for _ in ()).throw(AssertionError("should not be called")),
    )
    assert apply_global_overlays("BASE") == "BASE"


# ---- apply_role_overlays (third PromptBuilder collaborator) ----

def test_role_overlays_append_addendum_then_domain(monkeypatch):
    monkeypatch.setattr("maverick.role_edit.role_addendum", lambda role: "ADD")
    out = apply_role_overlays("BASE", role="coder", domain_persona="DOM")
    # role addendum first, then domain persona, each blank-line separated.
    assert out == "BASE\n\nADD\n\nDOM"


def test_role_overlays_no_addendum_no_domain(monkeypatch):
    monkeypatch.setattr("maverick.role_edit.role_addendum", lambda role: "")
    assert apply_role_overlays("BASE", role="coder", domain_persona=None) == "BASE"


def test_role_overlays_addendum_fails_open(monkeypatch):
    def boom(role):
        raise RuntimeError("role editor down")
    monkeypatch.setattr("maverick.role_edit.role_addendum", boom)
    # Addendum raises -> skipped; domain persona still applies; no raise.
    out = apply_role_overlays("BASE", role="coder", domain_persona="DOM")
    assert out == "BASE\n\nDOM"


def test_role_overlays_addendum_keyed_on_role(monkeypatch):
    seen = {}
    def _addendum(role):
        seen["role"] = role
        return ""
    monkeypatch.setattr("maverick.role_edit.role_addendum", _addendum)
    apply_role_overlays("BASE", role="analyst", domain_persona=None)
    assert seen["role"] == "analyst"
