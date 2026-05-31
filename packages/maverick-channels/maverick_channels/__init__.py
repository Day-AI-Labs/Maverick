"""Channel adapters for Maverick.

A channel normalizes incoming messages from any platform into a shared
``IncomingMessage`` shape, hands it to the orchestrator, and routes the
response back. This is the surface Maverick uses to power phone-companion
mode — the agent itself runs on Desktop or VPS, and channels give a
phone (or any other client) a way to talk to it.

Available channels (status as of v0.1):
  - cli       (ready)
  - telegram  (ready)
  - discord   (ready)
  - slack     (ready)
  - signal    (ready, requires signal-cli on PATH)
  - email     (ready, stdlib only)
  - matrix    (ready, requires matrix-nio)
  - whatsapp  (scaffold, requires Twilio + public webhook)
  - sms       (scaffold, requires Twilio + public webhook)
  - imessage  (macOS only)
"""
from .base import Channel, Handler, IncomingMessage

__version__ = "0.1.5"
__all__ = ["Channel", "IncomingMessage", "Handler"]
