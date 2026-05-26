"""Voice channel (Vapi) construction smoke tests.

We can't actually run the FastAPI server in a unit test without the
fastapi extra installed, and we can't make real Vapi calls from CI.
These tests verify the channel constructs correctly + rejects bad
config, similar to test_sms_signature.
"""
from __future__ import annotations

import pytest


def _have_deps() -> bool:
    try:
        import fastapi  # noqa: F401
        import httpx  # noqa: F401
        return True
    except ImportError:
        return False


@pytest.mark.skipif(not _have_deps(), reason="fastapi+httpx not installed")
def test_voice_channel_requires_api_key():
    from maverick_channels.voice import VoiceChannel

    async def _noop(_):
        return ""

    with pytest.raises(ValueError, match="VAPI_API_KEY"):
        VoiceChannel(handler=_noop, api_key=None)


@pytest.mark.skipif(not _have_deps(), reason="fastapi+httpx not installed")
def test_voice_channel_constructs_with_api_key():
    from maverick_channels.voice import VoiceChannel

    async def _noop(_):
        return ""

    chan = VoiceChannel(
        handler=_noop,
        api_key="vapi-test-key",
        phone_number="+14155551234",
        port=8770,
        assistant_id="asst_xyz",
    )
    # FastAPI route is wired.
    routes = [r.path for r in chan._app.routes if hasattr(r, "path")]
    assert "/webhook/voice" in routes
    assert chan.provider == "vapi"


@pytest.mark.skipif(not _have_deps(), reason="fastapi+httpx not installed")
def test_voice_channel_picks_up_env(monkeypatch):
    from maverick_channels.voice import VoiceChannel

    async def _noop(_):
        return ""

    monkeypatch.setenv("VAPI_API_KEY", "from-env")
    chan = VoiceChannel(handler=_noop)
    assert chan.api_key == "from-env"
