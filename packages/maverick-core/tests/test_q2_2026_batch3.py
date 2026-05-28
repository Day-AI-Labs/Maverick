"""Q2 2026 batch 3: HuggingFace TGI provider, Chroma vector store,
Bluesky/Mastodon channel adapters."""
from __future__ import annotations

import importlib.util
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------- TGI provider ----------

class _FakeOpenAIClient:
    def __init__(self, api_key=None, base_url=None):
        self.api_key = api_key
        self.base_url = base_url


def _install_fake_openai(monkeypatch):
    fake = types.ModuleType("openai")
    fake.OpenAI = _FakeOpenAIClient
    fake.AsyncOpenAI = _FakeOpenAIClient
    monkeypatch.setitem(sys.modules, "openai", fake)


def test_tgi_provider_default_url(monkeypatch):
    _install_fake_openai(monkeypatch)
    monkeypatch.delenv("TGI_BASE_URL", raising=False)
    monkeypatch.delenv("TGI_API_KEY", raising=False)
    from maverick.providers.tgi_provider import TGIClient
    client = TGIClient()
    assert "8080" in client._sync.base_url
    assert client._sync.base_url.endswith("/v1")


def test_tgi_provider_env_overrides(monkeypatch):
    _install_fake_openai(monkeypatch)
    monkeypatch.setenv("TGI_BASE_URL", "http://my-tgi.example.com:9999")
    monkeypatch.setenv("TGI_API_KEY", "secret-token")
    from maverick.providers.tgi_provider import TGIClient
    client = TGIClient()
    # /v1 suffix appended automatically when missing.
    assert client._sync.base_url == "http://my-tgi.example.com:9999/v1"
    assert client._sync.api_key == "secret-token"


def test_tgi_provider_v1_suffix_idempotent(monkeypatch):
    _install_fake_openai(monkeypatch)
    monkeypatch.setenv("TGI_BASE_URL", "http://my-tgi.example.com/v1")
    from maverick.providers.tgi_provider import TGIClient
    client = TGIClient()
    # Already had /v1; don't double-suffix.
    assert client._sync.base_url == "http://my-tgi.example.com/v1"


def test_tgi_provider_in_registry():
    from maverick.providers import KNOWN_PROVIDERS, _canonical
    assert "tgi" in KNOWN_PROVIDERS
    assert _canonical("hf-tgi") == "tgi"
    assert _canonical("huggingface-tgi") == "tgi"


def test_tgi_provider_dispatches(monkeypatch):
    _install_fake_openai(monkeypatch)
    monkeypatch.delenv("TGI_BASE_URL", raising=False)
    from maverick.providers import get_provider_client
    from maverick.providers.tgi_provider import TGIClient
    client = get_provider_client("tgi")
    assert isinstance(client, TGIClient)
    # Alias also dispatches.
    client2 = get_provider_client("hf-tgi")
    assert isinstance(client2, TGIClient)


# ---------- Chroma vector store ----------

_HAS_CHROMA = importlib.util.find_spec("chromadb") is not None


@pytest.mark.skipif(not _HAS_CHROMA, reason="chromadb not installed")
def test_chroma_store_round_trip(tmp_path):
    from maverick.vector_store import ChromaStore
    store = ChromaStore(collection="t1", path=tmp_path / "vs")
    store.add(
        ["the user prefers dark mode", "morning is best for cold calls"],
        ids=["fact-1", "fact-2"],
        metadatas=[{"topic": "ui"}, {"topic": "sales"}],
    )
    assert store.count() == 2
    hits = store.query("UI preference", top_k=1)
    assert len(hits) == 1
    assert hits[0]["id"] in {"fact-1", "fact-2"}


@pytest.mark.skipif(not _HAS_CHROMA, reason="chromadb not installed")
def test_chroma_store_delete_and_reset(tmp_path):
    from maverick.vector_store import ChromaStore
    store = ChromaStore(collection="t2", path=tmp_path / "vs")
    store.add(["a", "b", "c"], ids=["i1", "i2", "i3"])
    store.delete(["i2"])
    assert store.count() == 2
    store.reset()
    assert store.count() == 0


def test_chroma_store_missing_dep_raises_importable_error(tmp_path, monkeypatch):
    """When chromadb isn't installed, instantiation raises a useful error."""
    if _HAS_CHROMA:
        # Hide it.
        monkeypatch.setitem(sys.modules, "chromadb", None)
    # Force reimport so the lazy check trips.
    import maverick.vector_store.chroma_store as cs
    importlib.reload(cs)
    if _HAS_CHROMA:
        # If chromadb is really installed, setting sys.modules to None
        # turns `import chromadb` into ImportError. So our error path
        # should still fire.
        with pytest.raises(ImportError, match="maverick-agent\\[chroma\\]"):
            cs.ChromaStore(path=tmp_path)
    else:
        with pytest.raises(ImportError, match="maverick-agent\\[chroma\\]"):
            cs.ChromaStore(path=tmp_path)


# ---------- Bluesky channel ----------

@pytest.mark.asyncio
async def test_bluesky_start_requires_credentials():
    from maverick_channels.bluesky import BlueskyChannel

    async def handler(msg):
        return ""

    ch = BlueskyChannel(handler=handler, handle="", password="", allowed_user_ids={"did:plc:ok"})
    with pytest.raises(RuntimeError, match="BLUESKY_HANDLE"):
        await ch.start()


@pytest.mark.asyncio
async def test_bluesky_session_created_and_cached():
    from maverick_channels.bluesky import BlueskyChannel

    fake_resp = MagicMock()
    fake_resp.json = MagicMock(return_value={
        "accessJwt": "tok-123",
        "did": "did:plc:abc",
        "handle": "user.bsky.social",
    })
    fake_resp.raise_for_status = MagicMock()

    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)
    fake_client.post = AsyncMock(return_value=fake_resp)

    with patch("httpx.AsyncClient", return_value=fake_client):

        async def handler(msg):
            return ""

        ch = BlueskyChannel(
            handler=handler, handle="me.bsky.social", password="app-pass",
            allowed_user_ids={"did:plc:ok"},
        )
        sess = await ch._ensure_session()
        assert sess["accessJwt"] == "tok-123"
        # Second call hits the cache, no extra POST.
        sess2 = await ch._ensure_session()
        assert sess2["accessJwt"] == "tok-123"
        assert fake_client.post.call_count == 1


# ---------- Mastodon channel ----------

@pytest.mark.asyncio
async def test_mastodon_requires_token():
    from maverick_channels.mastodon import MastodonChannel

    async def handler(msg):
        return ""

    ch = MastodonChannel(handler=handler, access_token="", allowed_user_ids={"ok@example"})
    with pytest.raises(RuntimeError, match="MASTODON_ACCESS_TOKEN"):
        await ch._poll_once()


def test_mastodon_strip_html():
    from maverick_channels.mastodon import _strip_html
    html = "<p>Hello <a href='x'>world</a>!</p>"
    assert _strip_html(html) == "Hello world!"


@pytest.mark.asyncio
async def test_mastodon_poll_uses_since_id():
    from maverick_channels.mastodon import MastodonChannel

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.raise_for_status = MagicMock()
    fake_resp.json = MagicMock(return_value=[
        {"id": "100", "status": {"content": "<p>hi</p>", "id": "200"},
         "account": {"acct": "user@example"}},
    ])
    captured = {}

    async def fake_get(url, headers=None, params=None):
        captured["params"] = params
        return fake_resp

    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)
    fake_client.get = AsyncMock(side_effect=fake_get)

    with patch("httpx.AsyncClient", return_value=fake_client):
        async def handler(msg):
            return ""

        ch = MastodonChannel(
            handler=handler, access_token="tok",
            instance="mastodon.test",
            allowed_user_ids={"user@example"},
        )
        first = await ch._poll_once()
        assert len(first) == 1
        # First call: no since_id.
        assert "since_id" not in captured["params"]

        second_resp = MagicMock()
        second_resp.status_code = 200
        second_resp.raise_for_status = MagicMock()
        second_resp.json = MagicMock(return_value=[])
        async def fake_get2(url, headers=None, params=None):
            captured["params"] = params
            return second_resp
        fake_client.get = AsyncMock(side_effect=fake_get2)
        await ch._poll_once()
        # Second call: since_id = "100".
        assert captured["params"].get("since_id") == "100"


# ---------- Wizard catalog ----------

def test_wizard_catalog_includes_tgi():
    from maverick_installer import models
    assert "tgi" in models.PROVIDERS
    assert models.PROVIDERS["tgi"]["status"] == "ready"


def test_bluesky_requires_allowlist():
    from maverick_channels.bluesky import BlueskyChannel

    async def handler(msg):
        return ""

    with pytest.raises(ValueError, match="BLUESKY_ALLOWED_USER_IDS"):
        BlueskyChannel(handler=handler, handle="me", password="pass", allowed_user_ids=set())


def test_mastodon_requires_allowlist():
    from maverick_channels.mastodon import MastodonChannel

    async def handler(msg):
        return ""

    with pytest.raises(ValueError, match="MASTODON_ALLOWED_USER_IDS"):
        MastodonChannel(handler=handler, access_token="tok", allowed_user_ids=set())
