"""Regression tests for bug-hunt wave-6 fixes (core side)."""
from __future__ import annotations


class TestSecretDetectorBearer:
    def test_base64_bearer_detected(self):
        from maverick.safety.secret_detector import scan
        m = scan("Authorization: Bearer abcd+efgh/ijkl==mnopQRSTuvwx")
        assert any(x.name == "bearer_header" for x in m)


class TestPrivacyAnonStr:
    def test_string_false_disables(self, monkeypatch):
        import maverick.config as cfg
        from maverick import privacy
        monkeypatch.delenv("MAVERICK_ANON", raising=False)
        monkeypatch.setattr(cfg, "load_config",
                            lambda: {"privacy": {"anonymous": "false"}})
        assert privacy.anon_enabled() is False

    def test_string_true_enables(self, monkeypatch):
        import maverick.config as cfg
        from maverick import privacy
        monkeypatch.delenv("MAVERICK_ANON", raising=False)
        monkeypatch.setattr(cfg, "load_config",
                            lambda: {"privacy": {"anonymous": "true"}})
        assert privacy.anon_enabled() is True


class TestReasoningContentPreserved:
    def test_openai_response_reasoning_content_to_thinking(self):
        from maverick.providers.openai_provider import OpenAIClient

        class _Msg:
            content = "the answer"
            reasoning_content = "step-by-step CoT"
            tool_calls = None

        class _Choice:
            message = _Msg()
            finish_reason = "stop"

        class _Resp:
            choices = [_Choice()]
            usage = None

        out = OpenAIClient._from_response(_Resp(), None, model="deepseek-reasoner")
        assert out.thinking == "step-by-step CoT"
        assert out.text == "the answer"


class TestApplyPatchPathExtraction:
    def test_deletion_and_rename_paths_extracted(self):
        from maverick.tools.apply_patch import _files_in_patch
        # Deletion: target lives on `--- a/...`, `+++ /dev/null`.
        deletion = "--- a/secret.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-x\n"
        assert "secret.py" in _files_in_patch(deletion)
        assert "/dev/null" not in _files_in_patch(deletion)
        # Rename with a traversal target must be surfaced (so it gets checked).
        rename = (
            "diff --git a/a.py b/a.py\nrename from a.py\n"
            "rename to ../../etc/evil.py\n"
        )
        files = _files_in_patch(rename)
        assert "../../etc/evil.py" in files

    def test_modify_patch_not_double_counted(self):
        from maverick.tools.apply_patch import _files_in_patch
        modify = "--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-a\n+b\n"
        assert _files_in_patch(modify) == ["x.py"]


class TestRedisClientClosed:
    def test_client_closed_after_run(self, monkeypatch):
        import sys
        import types
        from unittest.mock import MagicMock
        fake_redis = types.ModuleType("redis")
        client = MagicMock()
        client.get.return_value = None
        fake_redis.Redis = MagicMock(return_value=client)
        fake_redis.Redis.from_url = MagicMock(return_value=client)
        monkeypatch.setitem(sys.modules, "redis", fake_redis)
        monkeypatch.setenv("REDIS_URL", "redis://x")
        from maverick.tools.redis_tool import redis_tool
        redis_tool().fn({"op": "get", "key": "k"})
        client.close.assert_called()  # no per-call connection-pool leak
