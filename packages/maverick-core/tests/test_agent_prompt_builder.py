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
