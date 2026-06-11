"""WebRTC data-channel tool (roadmap: 2028 H2 — capabilities).

Speaks WebRTC via ``aiortc`` so an agent can hold a peer-to-peer DATA CHANNEL
with a browser, another agent, or any WebRTC endpoint and exchange text:

  - ``offer``  — create an RTCPeerConnection + data channel, return the local
                 SDP offer (hand it to the remote peer out-of-band);
  - ``answer`` — apply the remote peer's answer SDP;
  - ``send``   — ship a text message over the open data channel;
  - ``close``  — tear the connection down.

Honest scope: DATA CHANNELS ONLY. Media tracks (audio/video capture,
playback, transcoding) are out of scope for this tool, and signalling is the
caller's job — copy the SDP blobs over any channel you already have (the
dashboard, a webhook, a file). One connection at a time, held module-level,
mirroring the browser tool's single persistent session.

``aiortc`` is optional (``pip install 'maverick-agent[webrtc]'``); every
aiortc import is lazy so the kernel — and these ops' error paths — work
without it.

Factory exported, NOT registered in the default tool set: callers opt in.
"""
from __future__ import annotations

from typing import Any

from . import Tool

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "op": {
            "type": "string",
            "enum": ["offer", "answer", "send", "close"],
            "description": "offer (create + return SDP), answer (apply remote SDP), send, close.",
        },
        "remote_sdp": {"type": "string", "description": "Remote answer SDP (answer op)."},
        "message": {"type": "string", "description": "Text to send over the data channel (send op)."},
        "label": {"type": "string", "description": "Data-channel label for offer (default 'maverick')."},
    },
    "required": ["op"],
}

# One connection at a time (module-level, like the browser session).
_state: dict[str, Any] = {"pc": None, "channel": None}


def _reset_state() -> None:
    _state["pc"] = None
    _state["channel"] = None


async def _run(args: dict[str, Any]) -> str:
    op = args.get("op")

    if op == "close":  # works without aiortc installed (nothing to close)
        pc = _state["pc"]
        _reset_state()
        if pc is None:
            return "no open connection"
        await pc.close()
        return "connection closed"

    try:
        from aiortc import RTCPeerConnection, RTCSessionDescription
    except ImportError:
        return ("ERROR: aiortc not installed. "
                "Run: pip install 'maverick-agent[webrtc]'")

    if op == "offer":
        if _state["pc"] is not None:  # replace any previous connection
            await _state["pc"].close()
            _reset_state()
        pc = RTCPeerConnection()
        channel = pc.createDataChannel(str(args.get("label") or "maverick"))
        offer = await pc.createOffer()
        await pc.setLocalDescription(offer)  # aiortc gathers ICE here
        _state["pc"], _state["channel"] = pc, channel
        return pc.localDescription.sdp

    if op == "answer":
        pc = _state["pc"]
        if pc is None:
            return "ERROR: no pending offer; run op=offer first"
        sdp = str(args.get("remote_sdp") or "")
        if not sdp.strip():
            return "ERROR: answer requires remote_sdp"
        await pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type="answer"))
        return "remote answer applied; the data channel opens once ICE connects"

    if op == "send":
        channel = _state["channel"]
        if channel is None:
            return "ERROR: no data channel; run op=offer (then op=answer) first"
        message = str(args.get("message") or "")
        channel.send(message)
        return f"sent {len(message)} chars on channel {channel.label!r}"

    return f"ERROR: unknown op {op!r}"


def webrtc_tool() -> Tool:
    """Factory: WebRTC data-channel messaging (offer/answer/send/close)."""
    return Tool(
        name="webrtc",
        description=(
            "Hold a WebRTC DATA CHANNEL with a remote peer: offer returns the "
            "local SDP, answer applies the remote answer SDP, send ships a "
            "text message, close hangs up. Data channels only — no media "
            "tracks; exchange the SDP blobs out-of-band yourself. Requires "
            "the 'webrtc' extra (aiortc)."
        ),
        input_schema=_SCHEMA,
        fn=_run,
    )


__all__ = ["webrtc_tool"]
