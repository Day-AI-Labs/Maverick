"""template_generator: skill + channel scaffolds."""
from __future__ import annotations

from maverick.tools.template_generator import template_generator


def _gen(**kw):
    return template_generator().fn(kw)


def test_skill_frontmatter_and_slug():
    out = _gen(kind="skill", name="Summarize A URL",
               triggers=["tldr a page"], tools_needed=["http_fetch"])
    assert out.startswith("---\n")
    assert "name: summarize-a-url" in out
    assert 'triggers: ["tldr a page"]' in out
    assert 'tools_needed: ["http_fetch"]' in out
    assert "# Summarize A Url" in out


def test_skill_defaults_trigger_when_empty():
    out = _gen(kind="skill", name="do thing")
    assert 'triggers: ["use do-thing"]' in out


def test_channel_subclasses_base_and_stubs_methods():
    out = _gen(kind="channel", name="My Cool Net")
    assert "from .base import Channel" in out
    assert "class MyCoolNetChannel(Channel):" in out
    for m in ("async def start", "async def send", "async def stop"):
        assert m in out
    # The scaffold must be syntactically valid Python.
    compile(out, "<channel>", "exec")


def test_bad_kind_errors():
    assert _gen(kind="widget", name="x").startswith("ERROR")


def test_missing_name_errors():
    assert _gen(kind="skill").startswith("ERROR")


def test_punctuation_only_name_errors():
    assert _gen(kind="channel", name="!!!").startswith("ERROR")
