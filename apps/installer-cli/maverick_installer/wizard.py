"""Maverick interactive installer.

A friendly, opinionated walk-through. Sets up:
  - deployment target
  - AI providers and per-role models
  - channels (Telegram, Discord, Slack, Signal, WhatsApp, SMS, Email,
    Matrix, iMessage)
  - safety profile
  - sandbox backend
  - budget caps
  - API keys (stored in ~/.maverick/.env, referenced from config.toml via ${VAR})

Writes ~/.maverick/config.toml and ~/.maverick/.env. The agent reads from there.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel

try:
    import questionary
except ImportError:  # pragma: no cover
    questionary = None  # type: ignore

from . import models as catalog


CONFIG_DIR = Path.home() / ".maverick"
CONFIG_FILE = CONFIG_DIR / "config.toml"
ENV_FILE = CONFIG_DIR / ".env"

console = Console()


# Channel catalog: (id, label, env_vars_needed)
CHANNELS: list[tuple[str, str, list[str]]] = [
    ("telegram", "Telegram bot (free, easiest)",        ["TELEGRAM_BOT_TOKEN"]),
    ("discord",  "Discord bot (Gateway WS)",            ["DISCORD_BOT_TOKEN"]),
    ("slack",    "Slack (Socket Mode)",                 ["SLACK_APP_TOKEN", "SLACK_BOT_TOKEN"]),
    ("signal",   "Signal (via signal-cli)",             []),
    ("email",    "Email (IMAP/SMTP, stdlib only)",      ["EMAIL_USER", "EMAIL_APP_PASSWORD"]),
    ("matrix",   "Matrix (federated)",                  ["MATRIX_ACCESS_TOKEN"]),
    ("whatsapp", "WhatsApp (Twilio, needs webhook)",    ["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN"]),
    ("sms",      "SMS (Twilio, needs webhook)",         ["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN"]),
    ("imessage", "iMessage (macOS only)",               []),
]


# ---------- prompt primitives ----------

def _q_select(message: str, choices: list[str], default: str | None = None) -> str:
    if questionary is None:
        print(message)
        for i, c in enumerate(choices):
            marker = "*" if default == c else " "
            print(f"  {marker} {i+1}) {c}")
        while True:
            choice = input("> ").strip()
            if not choice and default:
                return default
            if choice.isdigit() and 1 <= int(choice) <= len(choices):
                return choices[int(choice) - 1]
    return questionary.select(message, choices=choices, default=default).ask()


def _q_text(message: str, default: str = "") -> str:
    if questionary is None:
        val = input(f"{message} [{default}]: ").strip()
        return val or default
    return questionary.text(message, default=default).ask()


def _q_checkbox(message: str, choices: list[str], default: list[str] | None = None) -> list[str]:
    if questionary is None:
        print(f"{message} (comma-separated numbers, blank = none)")
        for i, c in enumerate(choices):
            marker = "*" if default and c in default else " "
            print(f"  {marker} {i+1}) {c}")
        raw = input("> ").strip()
        if not raw:
            return default or []
        picks = [c.strip() for c in raw.split(",")]
        return [choices[int(p) - 1] for p in picks if p.isdigit() and 1 <= int(p) <= len(choices)]
    return questionary.checkbox(message, choices=choices, default=default).ask()


def _q_confirm(message: str, default: bool = True) -> bool:
    if questionary is None:
        val = input(f"{message} [{'Y/n' if default else 'y/N'}]: ").strip().lower()
        if not val:
            return default
        return val.startswith("y")
    return questionary.confirm(message, default=default).ask()


# ---------- wizard steps ----------

def welcome() -> None:
    console.print(Panel.fit(
        "[bold cyan]Welcome to Maverick.[/bold cyan]\n\n"
        "An AI agent you fully control — pick your models, your safety\n"
        "level, your deployment target, and your channels. Privacy-first,\n"
        "safety by default.\n\n"
        "This wizard takes about 3 minutes. You can re-run it any time:\n"
        "  [bold]maverick init[/bold]",
        title="Maverick Installer",
        border_style="cyan",
    ))


def pick_deployment() -> str:
    pick = _q_select(
        "Where will Maverick run?",
        [
            "desktop  - This computer (recommended for first-time users)",
            "docker   - Local Docker container (isolated, easy to remove)",
            "vps      - Remote server you own (always-on)",
            "phone    - Phone companion (Maverick runs on desktop/VPS; phone is a frontend)",
        ],
    )
    return pick.split()[0]


def pick_providers() -> list[str]:
    choices = []
    for prov_id, info in catalog.PROVIDERS.items():
        tag = "[ready]" if info["status"] == "ready" else "[v0.2]"
        choices.append(f"{prov_id:10} {tag} - {info['label']}")

    picks = _q_checkbox(
        "Which AI providers do you want to use? (API keys requested only for the ones you pick.)",
        choices,
        default=[choices[0]],
    )
    return [p.split()[0] for p in picks]


def pick_models_per_role(providers: list[str]) -> dict[str, str]:
    console.print()
    console.print(Panel.fit(
        "[bold]Per-role model assignment[/bold]\n\n"
        "Maverick is a swarm — different roles do different work. Heavy roles\n"
        "(orchestrator, revisor) benefit from a smart model; cheap roles\n"
        "(summarizer) can use a small one. Pick what you want for each.",
        border_style="cyan",
    ))

    role_models: dict[str, str] = {}
    for role, hint in catalog.ROLES:
        choices: list[str] = []
        for prov in providers:
            info = catalog.PROVIDERS.get(prov)
            if not info:
                continue
            tag = "" if info["status"] == "ready" else " [v0.2]"
            for m in info["models"]:
                choices.append(f"{prov}:{m['id']}{tag}  - {m['notes']}")
        choices.append("[skip - use default]")

        default_spec = catalog.default_for_role(role)
        default_choice = next((c for c in choices if c.startswith(default_spec)), choices[0])

        pick = _q_select(f"  {role}: {hint}", choices, default=default_choice)
        if pick.startswith("[skip"):
            continue
        role_models[role] = pick.split()[0]
    return role_models


def pick_channels(deployment: str) -> tuple[dict[str, dict[str, Any]], set[str]]:
    """Returns (channels_config, env_vars_needed)."""
    console.print()
    if deployment == "desktop":
        if not _q_confirm(
            "Enable any messaging channels (Telegram, Discord, Signal, etc.) for remote access?",
            default=False,
        ):
            return {}, set()
    elif deployment == "phone":
        console.print(
            "[bold]Phone-companion mode:[/bold] pick the channels your phone will use.\n"
        )

    choices = [f"{ch_id:9} - {label}" for ch_id, label, _ in CHANNELS]
    picked = _q_checkbox("Which channels do you want to enable?", choices)
    picked_ids = [p.split()[0] for p in picked]

    channels: dict[str, dict[str, Any]] = {}
    envs: set[str] = set()

    for ch_id in picked_ids:
        info = next((c for c in CHANNELS if c[0] == ch_id), None)
        if info is None:
            continue
        envs.update(info[2])

        cfg: dict[str, Any] = {"enabled": True}

        if ch_id == "telegram":
            cfg["bot_token"] = "${TELEGRAM_BOT_TOKEN}"
        elif ch_id == "discord":
            cfg["bot_token"] = "${DISCORD_BOT_TOKEN}"
        elif ch_id == "slack":
            cfg["app_token"] = "${SLACK_APP_TOKEN}"
            cfg["bot_token"] = "${SLACK_BOT_TOKEN}"
        elif ch_id == "signal":
            cfg["phone_number"] = _q_text(
                "  Signal phone number (e.g., +12345550199)", default=""
            )
        elif ch_id == "email":
            cfg["imap_host"] = _q_text("  IMAP server", default="imap.gmail.com")
            cfg["smtp_host"] = _q_text("  SMTP server", default="smtp.gmail.com")
            cfg["smtp_port"] = int(_q_text("  SMTP port", default="465"))
            cfg["imap_user"] = "${EMAIL_USER}"
            cfg["imap_password"] = "${EMAIL_APP_PASSWORD}"
            cfg["smtp_user"] = "${EMAIL_USER}"
            cfg["smtp_password"] = "${EMAIL_APP_PASSWORD}"
            cfg["poll_interval"] = 30
        elif ch_id == "matrix":
            cfg["homeserver"] = _q_text("  Matrix homeserver URL", default="https://matrix.org")
            cfg["user_id"] = _q_text("  Matrix user ID (e.g., @you:matrix.org)", default="")
            cfg["access_token"] = "${MATRIX_ACCESS_TOKEN}"
        elif ch_id == "whatsapp":
            cfg["account_sid"] = "${TWILIO_ACCOUNT_SID}"
            cfg["auth_token"] = "${TWILIO_AUTH_TOKEN}"
            cfg["from_number"] = _q_text(
                "  WhatsApp 'from' (e.g., whatsapp:+14155238886)", default=""
            )
            cfg["port"] = int(_q_text("  Webhook port", default="8765"))
        elif ch_id == "sms":
            cfg["account_sid"] = "${TWILIO_ACCOUNT_SID}"
            cfg["auth_token"] = "${TWILIO_AUTH_TOKEN}"
            cfg["from_number"] = _q_text(
                "  SMS 'from' number (e.g., +14155551234)", default=""
            )
            cfg["port"] = int(_q_text("  Webhook port", default="8766"))
        elif ch_id == "imessage":
            cfg["poll_interval"] = 5

        channels[ch_id] = cfg

    return channels, envs


def pick_safety() -> dict[str, Any]:
    pick = _q_select(
        "Safety profile (powered by Agent Shield):",
        [
            "strict     - Block on any medium+ threat. Best for sensitive use.",
            "balanced   - Block on high+ threats. Recommended default.",
            "permissive - Block only on critical threats. For research/experimentation.",
            "off        - No safety scanning. NOT recommended.",
        ],
        default="balanced   - Block on high+ threats. Recommended default.",
    )
    profile = pick.split()[0]
    threshold = {
        "strict": "medium",
        "balanced": "high",
        "permissive": "critical",
        "off": "critical",
    }[profile]
    return {
        "profile": profile,
        "block_threshold": threshold,
        "scan_input": profile != "off",
        "scan_tool_calls": profile != "off",
        "scan_output": profile != "off",
    }


def pick_budget() -> dict[str, float]:
    console.print()
    console.print("[dim]Budget caps prevent runaway costs. Conservative defaults:[/dim]")
    return {
        "max_dollars": float(_q_text("  Max $ per run", default="5.0")),
        "max_wall_seconds": float(_q_text("  Max wall-clock seconds per run", default="3600")),
        "max_tool_calls": int(_q_text("  Max tool calls per run", default="500")),
    }


def pick_sandbox() -> dict[str, Any]:
    pick = _q_select(
        "Sandbox backend (where the agent runs shell commands):",
        [
            "local  - Subprocess on this machine (fastest, least isolated)",
            "docker - Throwaway Docker container (recommended)",
            "ssh    - Remote machine [v0.2]",
        ],
        default="docker - Throwaway Docker container (recommended)",
    )
    backend = pick.split()[0]
    workdir = _q_text("  Workspace directory", default=str(Path.home() / "maverick-workspace"))
    return {"backend": backend, "workdir": workdir, "timeout": 60}


def collect_api_keys(providers: list[str], channel_envs: set[str]) -> dict[str, str]:
    keys: dict[str, str] = {}
    needed: list[str] = []

    for prov in providers:
        info = catalog.PROVIDERS.get(prov, {})
        env_name = info.get("env")
        if env_name:
            needed.append(env_name)

    needed.extend(sorted(channel_envs))

    if not needed:
        return keys

    console.print()
    console.print("[bold]API keys / tokens[/bold] (stored in ~/.maverick/.env, chmod 600)")
    for env_name in dict.fromkeys(needed):  # dedupe preserving order
        current = os.environ.get(env_name, "")
        masked = (current[:7] + "...") if current else "(none)"
        val = _q_text(f"  {env_name} [current: {masked}]", default=current)
        if val:
            keys[env_name] = val
    return keys


# ---------- write + verify ----------

def write_config(
    deployment: str,
    providers: list[str],
    role_models: dict[str, str],
    channels: dict[str, dict[str, Any]],
    safety: dict[str, Any],
    budget: dict[str, float],
    sandbox: dict[str, Any],
    keys: dict[str, str],
) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    if keys:
        ENV_FILE.write_text("\n".join(f"{k}={v}" for k, v in keys.items()) + "\n")
        os.chmod(ENV_FILE, 0o600)

    lines = [
        "# Maverick config. Regenerate with:  maverick init",
        "",
        "[deploy]",
        f'target = "{deployment}"',
        "",
    ]
    for prov in providers:
        info = catalog.PROVIDERS.get(prov, {})
        lines.append(f"[providers.{prov}]")
        env_name = info.get("env")
        if env_name:
            lines.append(f'api_key = "${{{env_name}}}"')
        if prov == "ollama":
            lines.append('base_url = "http://localhost:11434"')
        lines.append("")
    if role_models:
        lines.append("[models]")
        for role, spec in role_models.items():
            lines.append(f'{role} = "{spec}"')
        lines.append("")

    for ch_id, cfg in channels.items():
        lines.append(f"[channels.{ch_id}]")
        for k, v in cfg.items():
            if isinstance(v, bool):
                lines.append(f"{k} = {str(v).lower()}")
            elif isinstance(v, (int, float)):
                lines.append(f"{k} = {v}")
            else:
                lines.append(f'{k} = "{v}"')
        lines.append("")

    lines.append("[budget]")
    for k, v in budget.items():
        lines.append(f"{k} = {v}")
    lines.append("")
    lines.append("[safety]")
    for k, v in safety.items():
        if isinstance(v, bool):
            lines.append(f"{k} = {str(v).lower()}")
        else:
            lines.append(f'{k} = "{v}"')
    lines.append("")
    lines.append("[sandbox]")
    for k, v in sandbox.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            lines.append(f"{k} = {v}")
        else:
            lines.append(f'{k} = "{v}"')

    CONFIG_FILE.write_text("\n".join(lines) + "\n")
    console.print(f"[green]✓[/green] Wrote {CONFIG_FILE}")
    if keys:
        console.print(f"[green]✓[/green] Wrote {ENV_FILE} (chmod 600)")


def smoke_test() -> bool:
    console.print()
    console.print("[dim]Running smoke test...[/dim]")
    try:
        from maverick.config import load_config
        cfg = load_config()
        assert cfg.get("deploy", {}).get("target"), "deploy target missing"
        console.print("[green]✓[/green] Config readable")
    except Exception as e:
        console.print(f"[red]✗[/red] Config read failed: {e}")
        return False

    try:
        import maverick_shield  # noqa: F401
        console.print("[green]✓[/green] Maverick Shield available")
    except ImportError:
        console.print("[yellow]⚠[/yellow] maverick-shield not installed (safety will be disabled)")

    try:
        import anthropic  # noqa: F401
        console.print("[green]✓[/green] Anthropic SDK available")
    except ImportError:
        console.print("[yellow]⚠[/yellow] anthropic not installed; install with: pip install anthropic")

    return True


def run() -> int:
    welcome()
    deployment = pick_deployment()
    providers = pick_providers()
    if not providers:
        console.print("[red]No providers selected. Aborting.[/red]")
        return 1
    role_models = pick_models_per_role(providers)
    channels, channel_envs = pick_channels(deployment)
    safety = pick_safety()
    budget = pick_budget()
    sandbox = pick_sandbox()
    keys = collect_api_keys(providers, channel_envs)

    console.print()
    if not _q_confirm("Write config and finish?", default=True):
        console.print("Aborted. Nothing written.")
        return 0

    write_config(deployment, providers, role_models, channels, safety, budget, sandbox, keys)
    ok = smoke_test()
    if ok:
        console.print()
        next_step = "maverick serve" if channels else 'maverick start "hello"'
        console.print(Panel.fit(
            "[bold green]All set.[/bold green]\n\n"
            "Try:\n"
            f"  [bold]{next_step}[/bold]\n"
            "  [bold]maverick status[/bold]\n"
            "  [bold]maverick skills[/bold]",
            border_style="green",
        ))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(run())
