"""ChatGPT session: agent runs must not be retained in the user's chat history
or fed to model training -- the prompts carry the user's private goals/data
(parity with claude_session's no-history behavior)."""
from __future__ import annotations

from maverick.session_providers.chatgpt_session import ChatGPTSessionClient


def test_history_and_training_disabled():
    # _build_request_body uses no instance state, so call it unbound to skip the
    # httpx-gated constructor.
    body = ChatGPTSessionClient._build_request_body(None, "my private goal", "gpt-4o")
    assert body["history_and_training_disabled"] is True


def test_prompt_and_model_forwarded():
    body = ChatGPTSessionClient._build_request_body(None, "hello world", "gpt-4o")
    assert body["messages"][0]["content"]["parts"] == ["hello world"]
    assert body["model"] == "gpt-4o"
