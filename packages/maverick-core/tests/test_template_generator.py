"""Tests for the template_generator tool. The generated skill must pass the
repo's own skill validator; the generated channel must be import-clean Python."""
from __future__ import annotations

from maverick.skills import validate_skill_file
from maverick.tools.template_generator import template_generator


def test_generated_skill_passes_validator(tmp_path):
    t = template_generator()
    out = t.fn({
        "op": "skill",
        "name": "Refund Helper",
        "triggers": ["process a refund", "issue a refund"],
        "tools_needed": ["stripe", "email"],
        "summary": "Issue a refund and notify the customer by email.",
    })
    assert out.startswith("---\nname: refund-helper")
    p = tmp_path / "SKILL.md"
    p.write_text(out, encoding="utf-8")
    result = validate_skill_file(p)
    assert result.ok, result.errors


def test_skill_requires_triggers_and_kebab_name():
    t = template_generator()
    assert t.fn({"op": "skill", "name": "x", "triggers": []}).startswith("ERROR")
    assert t.fn({"op": "skill", "name": "   ", "triggers": ["a"]}).startswith("ERROR")


def test_generated_channel_compiles_and_has_seams():
    t = template_generator()
    src = t.fn({"op": "channel", "name": "Pigeon Post", "transport": "webhook"})
    assert "class PigeonPostChannel(Channel):" in src
    for seam in ("async def start", "async def send", "async def stop"):
        assert seam in src
    # Import-clean Python: it must at least compile.
    compile(src, "<generated_channel>", "exec")
    assert "[channels.pigeon_post]" in src
    assert "PIGEON_POST_ALLOWED_USER_IDS" in src


def test_channel_validation():
    t = template_generator()
    assert t.fn({"op": "channel", "name": ""}).startswith("ERROR")
    assert t.fn({"op": "bogus", "name": "x"}).startswith("ERROR")


def test_registered():
    from maverick.tools import base_registry

    class _W:
        pass

    class _S:
        pass

    names = set(getattr(base_registry(world=_W(), sandbox=_S()), "_tools", {}).keys())
    assert "template_generator" in names
