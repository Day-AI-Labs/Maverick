"""Q3 2026 batch 6: test_impact, youtube, notion, translate,
slack_bot tools."""
from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

# ---------- test_impact ----------

def _seed_repo(tmp_path):
    (tmp_path / "src" / "pkg").mkdir(parents=True)
    (tmp_path / "src" / "pkg" / "foo.py").write_text("def foo(): pass\n")
    (tmp_path / "src" / "pkg" / "bar.py").write_text("def bar(): pass\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_foo.py").write_text(
        "from src.pkg.foo import foo\n\ndef test_foo(): foo()\n"
    )
    (tmp_path / "tests" / "test_bar.py").write_text(
        "from src.pkg.bar import bar\n\ndef test_bar(): bar()\n"
    )
    (tmp_path / "tests" / "test_unrelated.py").write_text(
        "def test_x(): pass\n"
    )


def test_test_impact_requires_op():
    from maverick.tools.test_impact import test_impact
    assert "op is required" in test_impact().fn({})


def test_test_impact_analyze_files(tmp_path, monkeypatch):
    _seed_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    from maverick.tools.test_impact import test_impact
    out = test_impact().fn({
        "op": "analyze_files",
        "paths": ["src/pkg/foo.py"],
    })
    assert "test_foo.py" in out
    assert "test_bar.py" not in out
    assert "test_unrelated.py" not in out


def test_test_impact_parses_unified_diff(tmp_path, monkeypatch):
    _seed_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    diff = """diff --git a/src/pkg/bar.py b/src/pkg/bar.py
--- a/src/pkg/bar.py
+++ b/src/pkg/bar.py
@@ -1 +1 @@
-def bar(): pass
+def bar(): return 1
"""
    from maverick.tools.test_impact import test_impact
    out = test_impact().fn({
        "op": "analyze",
        "diff": diff,
    })
    assert "test_bar.py" in out
    assert "test_foo.py" not in out


def test_test_impact_empty_diff(tmp_path, monkeypatch):
    _seed_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    from maverick.tools.test_impact import test_impact
    out = test_impact().fn({
        "op": "analyze", "diff": "",
    })
    assert "no changed files" in out


def test_test_impact_no_test_dir(tmp_path, monkeypatch):
    (tmp_path / "src").mkdir()
    monkeypatch.chdir(tmp_path)
    from maverick.tools.test_impact import test_impact
    out = test_impact().fn({
        "op": "analyze_files",
        "paths": ["src/x.py"],
    })
    assert "no test directories" in out


# ---------- YouTube tool ----------

def test_youtube_requires_op():
    from maverick.tools.youtube import youtube
    assert "op is required" in youtube().fn({})


def test_youtube_missing_lib(monkeypatch):
    monkeypatch.setitem(sys.modules, "youtube_transcript_api", None)
    from maverick.tools.youtube import youtube
    out = youtube().fn({"op": "transcript", "video_id": "dQw4w9WgXcQ"})
    assert "youtube-transcript-api not installed" in out


def test_youtube_normalize_id():
    from maverick.tools.youtube import _normalize_id
    assert _normalize_id("dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert _normalize_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert _normalize_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42") == "dQw4w9WgXcQ"


def test_youtube_transcript_renders(monkeypatch):
    fake = types.ModuleType("youtube_transcript_api")

    class _API:
        @staticmethod
        def get_transcript(video_id, languages=None):
            return [
                {"text": "Never gonna", "start": 0.0, "duration": 1.0},
                {"text": "give you up", "start": 1.0, "duration": 1.0},
            ]

    fake.YouTubeTranscriptApi = _API
    monkeypatch.setitem(sys.modules, "youtube_transcript_api", fake)
    from maverick.tools.youtube import youtube
    out = youtube().fn({"op": "transcript", "video_id": "abc"})
    assert "Never gonna give you up" in out


def test_youtube_chapters_includes_timestamps(monkeypatch):
    fake = types.ModuleType("youtube_transcript_api")

    class _API:
        @staticmethod
        def get_transcript(video_id, languages=None):
            return [
                {"text": "intro", "start": 0.0, "duration": 1.0},
                # 10s gap forces a new chapter
                {"text": "verse one", "start": 11.0, "duration": 1.0},
            ]

    fake.YouTubeTranscriptApi = _API
    monkeypatch.setitem(sys.modules, "youtube_transcript_api", fake)
    from maverick.tools.youtube import youtube
    out = youtube().fn({"op": "chapters", "video_id": "abc"})
    assert "[00:00:00]" in out
    assert "[00:00:11]" in out


# ---------- Notion tool ----------

def test_notion_requires_op():
    from maverick.tools.notion import notion
    assert "op is required" in notion().fn({})


def test_notion_missing_token(monkeypatch):
    monkeypatch.delenv("NOTION_TOKEN", raising=False)
    fake = types.ModuleType("httpx")
    fake.Client = MagicMock()
    monkeypatch.setitem(sys.modules, "httpx", fake)
    from maverick.tools.notion import notion
    out = notion().fn({"op": "search", "query": "x"})
    assert "NOTION_TOKEN" in out


def test_notion_search_renders(monkeypatch):
    monkeypatch.setenv("NOTION_TOKEN", "ntn_xx")
    resp = MagicMock()
    resp.status_code = 200
    resp.json = MagicMock(return_value={"results": [{
        "object": "page", "id": "abcd1234efgh",
        "properties": {"title": {
            "type": "title",
            "title": [{"plain_text": "My Page"}],
        }},
    }]})

    fake_client = MagicMock()
    fake_client.post = MagicMock(return_value=resp)
    fake_client.__enter__ = MagicMock(return_value=fake_client)
    fake_client.__exit__ = MagicMock(return_value=False)
    fake_httpx = types.ModuleType("httpx")
    fake_httpx.Client = MagicMock(return_value=fake_client)
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)

    from maverick.tools.notion import notion
    out = notion().fn({"op": "search", "query": "page"})
    assert "My Page" in out


def test_notion_page_create_requires_args():
    from maverick.tools.notion import notion
    out = notion().fn({"op": "page_create"})
    assert "parent_id and title" in out


# ---------- Translate tool ----------

def test_translate_requires_text():
    from maverick.tools.translate import translate
    out = translate().fn({"op": "translate", "target": "es"})
    assert "text is required" in out


def test_translate_deepl_path(monkeypatch):
    monkeypatch.setenv("DEEPL_API_KEY", "abc:fx")
    resp = MagicMock()
    resp.status_code = 200
    resp.json = MagicMock(return_value={"translations": [
        {"text": "Hola mundo", "detected_source_language": "EN"},
    ]})

    fake_httpx = types.ModuleType("httpx")
    fake_httpx.post = MagicMock(return_value=resp)
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)

    from maverick.tools.translate import translate
    out = translate().fn({"op": "translate", "text": "hello world",
                          "target": "es"})
    assert "Hola mundo" in out
    assert "from=EN" in out
    url = fake_httpx.post.call_args.args[0]
    assert "api-free.deepl.com" in url


def test_translate_libre_fallback(monkeypatch):
    monkeypatch.delenv("DEEPL_API_KEY", raising=False)
    resp = MagicMock()
    resp.status_code = 200
    resp.json = MagicMock(return_value={"translatedText": "Bonjour"})

    fake_httpx = types.ModuleType("httpx")
    fake_httpx.post = MagicMock(return_value=resp)
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)

    from maverick.tools.translate import translate
    out = translate().fn({"op": "translate", "text": "hello", "target": "fr"})
    assert "Bonjour" in out


def test_translate_detect_libre(monkeypatch):
    monkeypatch.delenv("DEEPL_API_KEY", raising=False)
    resp = MagicMock()
    resp.status_code = 200
    resp.json = MagicMock(return_value=[
        {"language": "ja", "confidence": 0.99},
    ])
    fake_httpx = types.ModuleType("httpx")
    fake_httpx.post = MagicMock(return_value=resp)
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)
    from maverick.tools.translate import translate
    out = translate().fn({"op": "detect", "text": "こんにちは"})
    assert "ja" in out


# ---------- Slack bot tool ----------

def test_slack_bot_requires_op():
    from maverick.tools.slack_bot import slack_bot
    assert "op is required" in slack_bot().fn({})


def test_slack_bot_missing_token(monkeypatch):
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    fake = types.ModuleType("httpx")
    fake.post = MagicMock()
    monkeypatch.setitem(sys.modules, "httpx", fake)
    from maverick.tools.slack_bot import slack_bot
    out = slack_bot().fn({"op": "post", "channel": "#x", "text": "hi"})
    assert "SLACK_BOT_TOKEN" in out


def test_slack_bot_post_calls_api(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    resp = MagicMock()
    resp.json = MagicMock(return_value={
        "ok": True, "channel": "C12345", "ts": "1234.5678",
    })

    fake_httpx = types.ModuleType("httpx")
    fake_httpx.post = MagicMock(return_value=resp)
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)

    from maverick.tools.slack_bot import slack_bot
    out = slack_bot().fn({"op": "post", "channel": "C12345", "text": "hello"})
    assert "posted to C12345" in out
    # Verify auth header was set.
    headers = fake_httpx.post.call_args.kwargs["headers"]
    assert headers["Authorization"].startswith("Bearer xoxb-test")


def test_slack_bot_post_validates_args():
    from maverick.tools.slack_bot import slack_bot
    out = slack_bot().fn({"op": "post"})
    assert "post requires channel and text" in out


def test_slack_bot_history_renders(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    resp = MagicMock()
    resp.json = MagicMock(return_value={"ok": True, "messages": [
        {"ts": "1.0", "user": "U1", "text": "hi"},
        {"ts": "2.0", "user": "U2", "text": "yo"},
    ]})
    fake_httpx = types.ModuleType("httpx")
    fake_httpx.get = MagicMock(return_value=resp)
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)
    from maverick.tools.slack_bot import slack_bot
    out = slack_bot().fn({"op": "history", "channel": "C1"})
    assert "U1" in out and "hi" in out


# ---------- registration smoke ----------

def test_new_tools_register(tmp_path):
    from maverick.sandbox.local import LocalBackend
    from maverick.tools import base_registry

    class _W:
        def open_questions(self, gid):
            return []

    reg = base_registry(_W(), LocalBackend(workdir=tmp_path))
    names = {t.name for t in reg.all()}
    for n in ("test_impact", "youtube", "notion", "translate", "slack_bot"):
        assert n in names, f"{n} not registered"
