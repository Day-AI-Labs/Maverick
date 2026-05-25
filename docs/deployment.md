# Deployment

Four deployment targets, all driven by the same `maverick init` wizard.

## Desktop

For most users.

```bash
pipx install maverick
maverick init
```

Runs as your user. Stores everything under `~/.maverick/`. The sandbox `workdir` defaults to `~/maverick-workspace/`. Nothing listens on a network port; you talk to it through the CLI.

**Coming soon:** native single-file builds (PyInstaller / nuitka) and a notarized Tauri-based GUI installer for users who don't open terminals.

## Docker

Isolated, reproducible, easy to nuke.

```bash
docker run -it --rm \
  -v ~/.maverick:/root/.maverick \
  -v ~/maverick-workspace:/workspace \
  -e ANTHROPIC_API_KEY \
  ghcr.io/texasreaper62/maverick:latest \
  start "..."
```

The sandbox is *inside* the container; the agent can't reach files outside the mounted workdir. Recommended for users running untrusted skills.

*(Image build comes next session.)*

## VPS

Always-on, accessible from anywhere via channel adapters (Telegram, etc.).

The `vps` deployment target generates:

- A `systemd` unit at `/etc/systemd/system/maverick.service`
- A Caddy reverse proxy config (if you also want a web dashboard)
- Config under `/etc/maverick/config.toml` (`MAVERICK_CONFIG` env)

```bash
maverick init --target=vps
sudo systemctl enable --now maverick
```

*(Generator templates come next session.)*

## Phone (companion mode)

Maverick itself runs on Desktop or VPS — the phone is just a frontend.

Supported channels (planned, prioritized):

1. **Telegram bot** (simplest, recommended) — set `[channels.telegram] enabled = true` and provide a bot token.
2. **iMessage** via the standard SMS forwarding setup.
3. **WhatsApp** via Twilio.
4. **PWA** for browsers.
5. **Native iOS / Android** later — React Native shell around the same channel protocol.

Why companion-mode instead of native-first: native AI agents on phones today are either expensive, locked to specific models, or have privacy compromises. Running on your own machine and using the phone as a frontend gives you full control and parity with the desktop experience.
