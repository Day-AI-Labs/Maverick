# maverick-channels

Channel adapters for Maverick. A channel normalizes incoming messages
from any platform (CLI, Telegram, iMessage, WhatsApp, PWA) into a
shared `{user_id, text, attachments}` shape, hands it to the
orchestrator, and routes the response back.

This is how phone-companion mode works: Maverick itself runs on your
Desktop or VPS, and any of these channels gives your phone a frontend.

## Channels

| Channel | Status | How |
|---|---|---|
| CLI (stdin/stdout) | ready | Bundled with `maverick start` |
| Telegram bot | scaffold | `pip install maverick-channels[telegram]` |
| iMessage | planned | macOS-side SMS forwarding bridge |
| WhatsApp | planned | Twilio |
| PWA | planned | Browser-side, talks to a tiny localhost server |
| Native iOS/Android | planned | React Native shell over the channel protocol |

## The interface

Every channel implements:

```python
class Channel:
    async def start(self) -> None: ...
    async def send(self, user_id: str, text: str) -> None: ...
    async def stop(self) -> None: ...
```

And dispatches `IncomingMessage(user_id, text, attachments)` to a single
handler the wizard wires up.
