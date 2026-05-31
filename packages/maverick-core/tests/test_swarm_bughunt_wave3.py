"""Regression tests for bug-hunt wave-3 fixes."""
from __future__ import annotations

import pytest


class TestRedditPrefixStrip:
    def test_subreddit_name_not_char_stripped(self, monkeypatch):
        # lstrip("r/") turned subreddit "rust" into "ust". removeprefix fixes it.
        from maverick.tools import reddit_tool
        captured = {}

        def fake_get(url, params=None):
            captured["url"] = url
            return 200, {"data": {"children": []}}

        monkeypatch.setattr(reddit_tool, "_get", fake_get)
        reddit_tool._op_subreddit({"name": "rust"})
        assert "/r/rust/" in captured["url"], captured["url"]

    def test_post_id_not_char_stripped(self, monkeypatch):
        from maverick.tools import reddit_tool
        captured = {}
        monkeypatch.setattr(
            reddit_tool, "_get",
            lambda url, params=None: (captured.setdefault("url", url), (200, {}))[1],
        )
        # "t3_t3abc" -> removeprefix strips one "t3_" -> "t3abc"; lstrip would
        # have eaten leading t/3/_ chars too. Use an id starting with stripped chars.
        reddit_tool._op_post({"post_id": "tango123"})
        assert "/comments/tango123." in captured["url"], captured["url"]


class TestLambdaConfirmGate:
    def test_stringy_false_does_not_fire_invoke(self):
        from maverick.tools.lambda_tool import _op_invoke
        # confirm="false" is truthy as a bare string; as_bool must read it as
        # False so the live invoke is NOT fired (returns the dry-run preview).
        out = _op_invoke({"function_name": "f", "confirm": "false"})
        assert "DRY RUN" in out


class TestPersonaStyleCasing:
    def test_style_case_insensitive(self, monkeypatch):
        from maverick import persona
        # Pick a real style key, upper-cased, and confirm it still applies.
        key = next(iter(persona.STYLES))
        monkeypatch.setattr(
            persona, "load_persona",
            lambda: {"name": "", "style": key.upper(), "addendum": ""},
        )
        rendered = persona.render_persona_prompt()
        assert persona.STYLES[key] in rendered


class TestTemplateBudgetParse:
    def test_malformed_budget_does_not_crash(self):
        from maverick.templates import _parse_frontmatter
        meta = _parse_frontmatter("budget_dollars: 1.2.3\n")
        # The bad value must not raise; it is kept as a string, not float().
        assert meta.get("budget_dollars") == "1.2.3"

    def test_valid_budget_still_coerced(self):
        from maverick.templates import _parse_frontmatter
        meta = _parse_frontmatter("budget_dollars: 2.5\n")
        assert meta.get("budget_dollars") == 2.5


class TestElasticsearchSeg:
    def test_path_traversal_encoded(self):
        from maverick.tools.elasticsearch_tool import _seg
        assert _seg("../../_cluster/settings") == "..%2F..%2F_cluster%2Fsettings"
        assert _seg("my-index") == "my-index"


class TestReplayExportSanitize:
    def test_pii_and_secrets_redacted(self):
        from maverick.replay_export import _sanitize
        text = 'contact john@example.com key=sk-ant-abcdefghij0123456789XYZ'
        out = _sanitize(text)
        assert "john@example.com" not in out
        assert "sk-ant-abcdefghij0123456789XYZ" not in out
