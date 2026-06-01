"""Issue #467: observability/logging hygiene.

  - JSON formatter must not ship caller-attached `extra=` secrets verbatim:
    redact secret-named keys, scrub inline secrets in string values.
  - goal-context contextvars must reset to the PRIOR value (token-based), so
    concurrent/nested goals don't mislabel each other's log lines.
"""
from __future__ import annotations

import json
import logging

from maverick.logging_config import (
    JsonFormatter,
    _goal_id_var,
    reset_goal_context,
    set_goal_context,
)


def _fmt(**extra):
    rec = logging.LogRecord("t", logging.INFO, __file__, 1, "msg", None, None)
    for k, v in extra.items():
        setattr(rec, k, v)
    return json.loads(JsonFormatter().format(rec))


# ---------- extra= leak ----------

def test_secret_named_key_redacted():
    out = _fmt(api_key="sk-ant-abcdefghij1234567890XYZ", count=42)
    assert out["api_key"] == "[REDACTED]"
    assert out["count"] == 42  # benign field preserved


def test_various_secret_named_keys_redacted():
    out = _fmt(password="hunter2", auth_header="Bearer xyz", session_token="s",
               SECRET="x", normal_field="ok")
    for k in ("password", "auth_header", "session_token", "SECRET"):
        assert out[k] == "[REDACTED]", k
    assert out["normal_field"] == "ok"


def test_inline_secret_in_value_scrubbed():
    # Even a benign-named key gets its value scrubbed for inline secrets.
    out = _fmt(note="key is sk-ant-abcdefghij1234567890XYZ ok")
    assert "sk-ant-abcdefghij" not in out["note"]
    assert "[REDACTED" in out["note"]


def test_benign_values_untouched():
    out = _fmt(url="https://example.com/path", n=3, flag=True)
    assert out["url"] == "https://example.com/path"  # 'url' not treated as secret
    assert out["n"] == 3 and out["flag"] is True


# ---------- goal-context contextvar reset ----------

def test_nested_context_reset_restores_outer():
    assert _goal_id_var.get() is None
    outer = set_goal_context(goal_id=100)
    assert _goal_id_var.get() == 100
    inner = set_goal_context(goal_id=200)
    assert _goal_id_var.get() == 200
    reset_goal_context(inner)
    assert _goal_id_var.get() == 100  # restored to outer, NOT nulled
    reset_goal_context(outer)
    assert _goal_id_var.get() is None


def test_reset_tolerates_none_and_partial():
    # Should never raise on a None/partial token mapping.
    reset_goal_context(None)
    tok = set_goal_context(conversation_id=7)  # only conversation set
    reset_goal_context(tok)
    from maverick.logging_config import _conversation_id_var
    assert _conversation_id_var.get() is None
