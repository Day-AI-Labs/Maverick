# Deployment

Four deployment targets, all driven by the same `maverick init` wizard.

## Desktop

For most users.

```bash
pipx install 'maverick-agent[installer]'
maverick init
```

Runs as your user. Stores everything under `~/.maverick/`. The sandbox
`workdir` defaults to `~/maverick-workspace/`. Nothing listens on a
network port unless you enable a channel that needs one (WhatsApp/SMS).

**Coming soon:** native single-file builds (PyInstaller / nuitka) and a
notarized Tauri-based GUI installer for users who don't open terminals.

## Docker

Isolated, reproducible, easy to nuke.

```bash
docker run -it --rm \
  -v ~/maverick-workspace:/workspace \
  -v ~/.maverick/config.toml:/root/.maverick/config.toml:ro \
  -e ANTHROPIC_API_KEY=... \
  ghcr.io/texasreaper62/maverick:latest \
  start "..."
```

For untrusted skills, **do not** mount `~/.maverick/` into the same
container that runs the agent tools. A local sandbox inside this
container can read mounted files and process environment variables.
Mount only the workspace and a read-only `config.toml`; keep API keys
scoped to this container run.

## VPS

Always-on, accessible from anywhere via channel adapters.

The `vps` deployment target generates:

- A `systemd` unit at `/etc/systemd/system/maverick.service`
- A Caddy reverse proxy config (if you need HTTPS for WhatsApp/SMS webhooks)
- Config under `/etc/maverick/config.toml` (`MAVERICK_CONFIG` env)

```bash
curl -sSL https://raw.githubusercontent.com/texasreaper62/maverick/main/deploy/vps/install.sh | sudo bash
sudo systemctl enable --now maverick
```

## Phone (companion mode)

Maverick itself runs on Desktop or VPS — your phone is a frontend that
talks to it through one of the channels below. This avoids the cost,
privacy, and capability tradeoffs of running an agent on the phone
itself, while keeping parity with the desktop experience.

Start the channel server on whichever machine Maverick runs on:

```bash
maverick serve
```

### Channel matrix

| Channel  | Status   | Setup | Public webhook needed? |
|----------|----------|-------|------------------------|
| Telegram | ready    | Create a bot via @BotFather, paste token | no |
| Discord  | ready    | Create a Discord app + bot, enable Message Content Intent | no |
| Slack    | ready    | Create app, enable Socket Mode, paste both tokens | no |
| Signal   | ready    | Install signal-cli, register your number | no |
| Email    | ready    | IMAP + SMTP credentials (Gmail app password works) | no |
| Matrix   | ready    | Homeserver URL + user_id + access token | no |
| WhatsApp | scaffold | Twilio Business API + public HTTPS endpoint | YES |
| SMS      | scaffold | Twilio + public HTTPS endpoint | YES |
| iMessage | scaffold | macOS only + Full Disk Access permission | no |

Multiple channels can be enabled at once; each runs in its own async task.

### Channel setup recipes

**Telegram (easiest):**

1. Message [@BotFather](https://t.me/BotFather) on Telegram
2. Run `/newbot`, follow prompts, copy the token
3. `maverick init` — enable telegram, paste token at the env-var prompt
4. `maverick serve`
5. Find your bot in Telegram and message it

**Discord:**

1. https://discord.com/developers/applications → New Application
2. Bot tab → Add Bot → enable Message Content Intent → copy token
3. OAuth2 → URL Generator → scopes: `bot`; permissions: Read Messages, Send Messages
4. Open the generated URL to invite the bot to your server
5. `maverick init`, enable discord, paste token

**Slack:**

1. https://api.slack.com/apps → Create New App → From scratch
2. Socket Mode → Enable; generate an App-Level Token with `connections:write` scope
3. OAuth & Permissions → add bot scopes: `chat:write`, `im:history`, `im:read`
4. Install to your workspace; copy Bot Token
5. Event Subscriptions → enable; subscribe to `message.im`
6. `maverick init`, enable slack, paste both tokens

**Signal:**

1. Install signal-cli: https://github.com/AsamK/signal-cli
2. Register: `signal-cli -u +12345550199 register`
3. Verify with the SMS code: `signal-cli -u +12345550199 verify 123-456`
4. `maverick init`, enable signal, enter your number

**Email:**

1. Use an app password (Gmail Settings → 2FA → App Passwords)
2. `maverick init`, enable email, paste IMAP/SMTP details + app password

**Matrix:**

1. Create account on matrix.org (or self-hosted homeserver)
2. Get access token (Element → Settings → Help & About → Access Token)
3. `maverick init`, enable matrix, paste homeserver, user_id, token

**WhatsApp / SMS (require public webhook):**

1. Sign up at twilio.com; verify a sender
2. Run Maverick on a VPS (you need a public HTTPS endpoint)
3. Caddyfile in `deploy/vps/Caddyfile` shows the reverse-proxy pattern
4. `maverick init`, enable whatsapp/sms, paste Twilio creds + from number
5. In Twilio console, set the webhook URL to
   `https://yourdomain.com/webhook/whatsapp` (or `/sms`)

**iMessage (macOS only):**

1. System Settings → Privacy & Security → Full Disk Access
2. Add `/usr/bin/python3` (or your Python interpreter) to the list
3. `maverick init`, enable imessage
