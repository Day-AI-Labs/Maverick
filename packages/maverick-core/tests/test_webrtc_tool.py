"""WebRTC data-channel tool (ROADMAP 2028 H2) — offline, fake-aiortc tests."""
from __future__ import annotations

import asyncio
import sys
import types

import pytest
from maverick.tools import webrtc_tool as mod
from maverick.tools.webrtc_tool import webrtc_tool

FAKE_SDP = "v=0\r\no=- 0 0 IN IP4 127.0.0.1\r\ns=fake-offer\r\n"


def _install_fake_aiortc(monkeypatch, record):
    class FakeDescription:
        def __init__(self, sdp="", type=""):  # noqa: A002 - aiortc's kwarg name
            self.sdp = sdp
            self.type = type

    class FakeChannel:
        def __init__(self, label):
            self.label = label

        def send(self, message):
            record.append(("channel.send", self.label, message))

    class FakePC:
        def __init__(self):
            record.append(("RTCPeerConnection",))
            self.localDescription = None

        def createDataChannel(self, label):
            record.append(("createDataChannel", label))
            return FakeChannel(label)

        async def createOffer(self):
            record.append(("createOffer",))
            return FakeDescription(FAKE_SDP, "offer")

        async def setLocalDescription(self, desc):
            record.append(("setLocalDescription", desc.type))
            self.localDescription = desc

        async def setRemoteDescription(self, desc):
            record.append(("setRemoteDescription", desc.type, desc.sdp))

        async def close(self):
            record.append(("close",))

    fake = types.ModuleType("aiortc")
    fake.RTCPeerConnection = FakePC
    fake.RTCSessionDescription = FakeDescription
    monkeypatch.setitem(sys.modules, "aiortc", fake)


@pytest.fixture(autouse=True)
def _fresh_state():
    mod._reset_state()
    yield
    mod._reset_state()


def _run(args):
    return asyncio.run(webrtc_tool().fn(args))


def test_missing_dep_reported(monkeypatch):
    monkeypatch.setitem(sys.modules, "aiortc", None)  # force ImportError
    out = _run({"op": "offer"})
    assert "ERROR" in out and "maverick-agent[webrtc]" in out


def test_offer_returns_sdp_and_call_shape(monkeypatch):
    record = []
    _install_fake_aiortc(monkeypatch, record)
    out = _run({"op": "offer"})
    assert out == FAKE_SDP
    assert record == [
        ("RTCPeerConnection",),
        ("createDataChannel", "maverick"),
        ("createOffer",),
        ("setLocalDescription", "offer"),
    ]


def test_offer_custom_label(monkeypatch):
    record = []
    _install_fake_aiortc(monkeypatch, record)
    _run({"op": "offer", "label": "telemetry"})
    assert ("createDataChannel", "telemetry") in record


def test_second_offer_closes_previous(monkeypatch):
    record = []
    _install_fake_aiortc(monkeypatch, record)
    _run({"op": "offer"})
    _run({"op": "offer"})
    assert ("close",) in record


def test_answer_applies_remote_description(monkeypatch):
    record = []
    _install_fake_aiortc(monkeypatch, record)
    _run({"op": "offer"})
    out = _run({"op": "answer", "remote_sdp": "v=0 remote"})
    assert "applied" in out
    assert ("setRemoteDescription", "answer", "v=0 remote") in record


def test_answer_without_offer_errors(monkeypatch):
    _install_fake_aiortc(monkeypatch, [])
    out = _run({"op": "answer", "remote_sdp": "v=0"})
    assert "ERROR" in out and "offer" in out


def test_answer_requires_sdp(monkeypatch):
    _install_fake_aiortc(monkeypatch, [])
    _run({"op": "offer"})
    assert "ERROR" in _run({"op": "answer", "remote_sdp": "  "})


def test_send_over_channel(monkeypatch):
    record = []
    _install_fake_aiortc(monkeypatch, record)
    _run({"op": "offer"})
    out = _run({"op": "send", "message": "hello peer"})
    assert out == "sent 10 chars on channel 'maverick'"
    assert ("channel.send", "maverick", "hello peer") in record


def test_send_without_channel_errors(monkeypatch):
    _install_fake_aiortc(monkeypatch, [])
    assert "ERROR" in _run({"op": "send", "message": "x"})


def test_close_tears_down(monkeypatch):
    record = []
    _install_fake_aiortc(monkeypatch, record)
    _run({"op": "offer"})
    assert _run({"op": "close"}) == "connection closed"
    assert ("close",) in record
    assert mod._state["pc"] is None and mod._state["channel"] is None


def test_close_idempotent_without_dep():
    # close never needs aiortc when nothing is open.
    assert _run({"op": "close"}) == "no open connection"


def test_unknown_op(monkeypatch):
    _install_fake_aiortc(monkeypatch, [])
    assert "unknown op" in _run({"op": "dance"})


def test_factory_shape():
    tool = webrtc_tool()
    assert tool.name == "webrtc"
    assert "media" in tool.description.lower()  # honest data-channel-only scope
