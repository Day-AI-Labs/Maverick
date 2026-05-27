"""Template tests."""
from __future__ import annotations

import pytest

from maverick.templates import Template, _substitute, load_template


TEMPLATE_BODY = """---
title: Research {{ topic }}
budget_dollars: 2.5
budget_wall_seconds: 1200
params:
  - topic
  - depth
---
Research {{ topic }} across {{ depth }} dimensions. Write to report.md.
"""


def test_parse_with_frontmatter():
    t = Template.parse(TEMPLATE_BODY, "research")
    assert t.title == "Research {{ topic }}"
    assert t.budget_dollars == 2.5
    assert t.budget_wall_seconds == 1200
    assert "topic" in t.params
    assert "depth" in t.params


def test_parse_without_frontmatter():
    t = Template.parse("just a body", "plain")
    assert t.title == "plain"
    assert t.body == "just a body"
    assert t.budget_dollars == 5.0


def test_render_substitutes_variables():
    t = Template.parse(TEMPLATE_BODY, "research")
    title, body = t.render(topic="AI agents", depth="4")
    assert title == "Research AI agents"
    assert "AI agents across 4 dimensions" in body


def test_render_missing_required_param():
    t = Template.parse(TEMPLATE_BODY, "research")
    with pytest.raises(ValueError, match="missing required params"):
        t.render(topic="x")  # forgot 'depth'


def test_render_extra_params_ignored():
    t = Template.parse(TEMPLATE_BODY, "research")
    title, body = t.render(topic="x", depth="y", unused="z")
    assert title == "Research x"


def test_substitute_leaves_unknown_vars_alone():
    out = _substitute("hello {{ name }}, {{ missing }}", {"name": "world"})
    assert "hello world" in out
    assert "{{ missing }}" in out


def test_load_template_rejects_path_traversal():
    with pytest.raises(ValueError, match="invalid template name"):
        load_template("../secret")


def test_load_template_rejects_absolute_path():
    with pytest.raises(ValueError, match="invalid template name"):
        load_template("/tmp/secret")
