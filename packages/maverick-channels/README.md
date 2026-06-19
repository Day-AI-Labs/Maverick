# maverick-channels

Channel adapters for Lightwork. A channel normalizes incoming messages
from any platform into a shared `{user_id, text, attachments}` shape,
hands it to the orchestrator, and routes the response back.

This is how phone-companion mode works: Lightwork itself runs on your
Desktop or VPS (`maverick serve`), and any of these channels gives your
phone (or any other client) a frontend.

## Channels

| Channel  | Status   | Install                                  | Notes |
|----------|----------|------------------------------------------|-------|
| CLI      | ready    | bundled                                  | stdin/stdout, used by `maverick start` |
| Telegram | ready    | `pip install '.[telegram]'`              | Long-poll, no public endpoint needed |
| Discord  | ready    | `pip install '.[discord]'`               | Gateway WebSocket |
| Slack    | ready    | `pip install '.[slack]'`                 | Socket Mode |
| Signal   | ready    | bundled (needs `signal-cli` on PATH)     | JSON-RPC over subprocess |
| Email    | ready    | bundled                                  | IMAP poll + SMTP send (stdlib) |
| Matrix   | ready    | `pip install '.[matrix]'`                | Federated, end-to-end encryptable |
| WhatsApp | scaffold | `pip install '.[whatsapp]'`              | Twilio webhook — needs public HTTPS |
| SMS      | scaffold | `pip install '.[sms]'`                   | Twilio webhook — needs public HTTPS |
| iMessage | scaffold | bundled                                  | macOS only, needs Full Disk Access |

or everything at once:

```bash
pip install 'maverick-channels[all]'
```

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

## Wiring channels

In `~/.maverick/config.toml`:

```toml
[channels.telegram]
enabled = true
bot_token = "${TELEGRAM_BOT_TOKEN}"
allowed_user_ids = ["123456789"]
# optional alternative: allowed_chat_ids = ["-1001234567890"]

[channels.discord]
enabled = true
bot_token = "${DISCORD_BOT_TOKEN}"

[channels.slack]
enabled = false
app_token = "${SLACK_APP_TOKEN}"
bot_token = "${SLACK_BOT_TOKEN}"

[channels.signal]
enabled = false
phone_number = "+12345550199"

[channels.email]
enabled = false
imap_host = "imap.gmail.com"
imap_user = "${EMAIL_USER}"
imap_password = "${EMAIL_APP_PASSWORD}"
smtp_host = "smtp.gmail.com"
smtp_port = 465
smtp_user = "${EMAIL_USER}"
smtp_password = "${EMAIL_APP_PASSWORD}"
```

Then run:

```bash
maverick serve
```

Multiple channels can be enabled simultaneously — each runs in its own
async task.
