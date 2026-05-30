"""OpenAI-compatible providers must strip the API key.

Regression: a trailing newline (`echo $KEY > file`) or stray whitespace
otherwise 401s every call. OpenAIClient strips the resolved key, which
covers openrouter / deepseek / ollama / moonshot / xai / tgi / vllm --
they all pass their key through OpenAIClient.
"""
import pytest


def test_openai_client_strips_key():
    pytest.importorskip("openai")
    from maverick.providers.openai_provider import OpenAIClient
    client = OpenAIClient(api_key="sk-test-123\n  ")
    assert client._sync.api_key == "sk-test-123"
    assert client._async.api_key == "sk-test-123"


def test_openai_client_all_whitespace_key_becomes_none(monkeypatch):
    pytest.importorskip("openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    from maverick.providers.openai_provider import OpenAIClient
    # A whitespace-only key must not masquerade as a real one.
    client = OpenAIClient(api_key="   \n")
    assert client._sync.api_key in (None, "")
