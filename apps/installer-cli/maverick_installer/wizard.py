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

v0.1.1 additions (council UX feedback):
  - Preflight: Python version, write perms, optional docker check
  - API key validation: pings Anthropic with the entered key before save
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
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


def _q_secret(message: str) -> str:
    if questionary is None:
        import getpass

        return getpass.getpass(f"{message}: ").strip()
    return questionary.password(message).ask() or ""


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


# ---------- preflight ----------

def preflight() -> bool:
    """Check the environment before asking any questions.

    Returns True if all critical checks pass. Warnings are shown but
    don't block the wizard.
    """
    console.print("\n[dim]Checking your environment...[/dim]")
    all_ok = True

    # Python version
    if sys.version_info < (3, 10):
        console.print(f"[red]✗[/red] Python 3.10+ required (you have {sys.version.split()[0]})")
        all_ok = False
    else:
        console.print(f"[green]✓[/green] Python {sys.version.split()[0]}")

    # Config dir writable
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        test_file = CONFIG_DIR / ".write-test"
        test_file.write_text("ok")
        test_file.unlink()
        console.print(f"[green]✓[/green] {CONFIG_DIR} is writable")
    except (PermissionError, OSError) as e:
        console.print(f"[red]✗[/red] Can't write to {CONFIG_DIR}: {e}")
        all_ok = False

    # Docker (advisory only -- only matters if user picks docker sandbox)
    if shutil.which("docker"):
        try:
            subprocess.run(
                ["docker", "version"],
                capture_output=True, timeout=5, check=True,
            )
            console.print("[green]✓[/green] Docker is running")
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            console.print(
                "[yellow]![/yellow] Docker installed but daemon isn't responding "
                "(only matters if you pick the docker sandbox)"
            )
    else:
        console.print(
            "[yellow]![/yellow] Docker not installed "
            "(only matters if you pick the docker sandbox)"
        )

    return all_ok


# ---------- validators ----------

def _validate_anthropic_key(key: str) -> tuple[bool, str]:
    """Ping Anthropic with the key. Returns (ok, message)."""
    if not key.startswith("sk-ant-"):
        return False, "key doesn't start with 'sk-ant-' -- typo?"
    try:
        import anthropic
    except ImportError:
        return True, "anthropic SDK not installed -- skipping validation"
    try:
        client = anthropic.Anthropic(api_key=key)
        # Minimal call -- list available models is enough to verify auth.
        list(client.models.list(limit=1))
        return True, "validated"
    except anthropic.AuthenticationError:
        return False, "API rejected the key"
    except Exception as e:
        return True, f"validation skipped: {type(e).__name__}"


def _validate_openai_key(key: str) -> tuple[bool, str]:
    if not key.startswith("sk-"):
        return False, "key doesn't start with 'sk-' -- typo?"
    try:
        from openai import AuthenticationError, OpenAI
    except ImportError:
        return True, "openai SDK not installed -- skipping validation"
    try:
        client = OpenAI(api_key=key)
        list(client.models.list().data[:1])
        return True, "validated"
    except AuthenticationError:
        return False, "API rejected the key"
    except Exception as e:
        return True, f"validation skipped: {type(e).__name__}"


def _validate_openai_compat_key(key: str, base_url: str, label: str) -> tuple[bool, str]:
    """For openai-compatible endpoints (Moonshot, DeepSeek, xAI, Gemini)."""
    if not key:
        return False, "empty key"
    try:
        from openai import AuthenticationError, OpenAI
    except ImportError:
        return True, "openai SDK not installed -- skipping validation"
    try:
        client = OpenAI(api_key=key, base_url=base_url)
        list(client.models.list().data[:1])
        return True, f"validated against {label}"
    except AuthenticationError:
        return False, f"{label} rejected the key"
    except Exception as e:
        # Network / route errors are non-fatal -- saving still useful.
        return True, f"validation skipped: {type(e).__name__}"


def _validate_moonshot_key(key: str) -> tuple[bool, str]:
    return _validate_openai_compat_key(
        key, "https://api.moonshot.ai/v1", "Moonshot",
    )


def _validate_deepseek_key(key: str) -> tuple[bool, str]:
    return _validate_openai_compat_key(
        key, "https://api.deepseek.com/v1", "DeepSeek",
    )


def _validate_xai_key(key: str) -> tuple[bool, str]:
    return _validate_openai_compat_key(
        key, "https://api.x.ai/v1", "xAI",
    )


def _validate_gemini_key(key: str) -> tuple[bool, str]:
    return _validate_openai_compat_key(
        key, "https://generativelanguage.googleapis.com/v1beta/openai/", "Gemini",
    )


_VALIDATORS = {
    "ANTHROPIC_API_KEY": _validate_anthropic_key,
    "OPENAI_API_KEY":    _validate_openai_key,
    "MOONSHOT_API_KEY":  _validate_moonshot_key,
    "DEEPSEEK_API_KEY":  _validate_deepseek_key,
    "XAI_API_KEY":       _validate_xai_key,
    "GEMINI_API_KEY":    _validate_gemini_key,
    # Channel tokens validated when 'maverick serve' starts (less time-critical).
}


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
    if _q_confirm(
        "Use recommended defaults for per-role models? (Yes = skip the 8-question gauntlet)",
        default=True,
    ):
        return {}

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


def pick_capabilities() -> dict[str, bool]:
    """Opt-in to high-impact tools the wizard ships disabled by default.

    Computer-use and browser tools are Devin/Hermes/OpenClaw-class
    capabilities. They're heavy on deps and have real safety implications
    (the agent can drive your mouse/keyboard or open external sites), so
    users explicitly enable them.
    """
    console.print()
    console.print(Panel.fit(
        "[bold]Advanced capabilities[/bold]\n\n"
        "Optional tools that extend what the agent can do. Each\n"
        "requires an optional dep and has real side effects:\n\n"
        "  • [bold]computer-use[/bold]: agent sees your screen and drives\n"
        "    mouse + keyboard (matches Anthropic's computer_20250124 spec)\n"
        "  • [bold]browser[/bold]: agent navigates the web via Playwright\n"
        "    (discrete navigate / click / type / extract actions)\n\n"
        "You can change these later in ~/.maverick/config.toml.",
        border_style="cyan",
    ))
    use_computer = _q_confirm(
        "Enable computer-use tool? (agent controls your mouse/keyboard)",
        default=False,
    )
    use_browser = _q_confirm(
        "Enable browser tool? (agent can open web pages via Playwright)",
        default=False,
    )
    return {
        "computer_use": use_computer,
        "browser": use_browser,
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
        val = _q_secret(f"  {env_name} [current: {masked}] (leave blank to keep current)")
        if not val:
            if current:
                keys[env_name] = current
            continue

        # Validate when we know how.
        validator = _VALIDATORS.get(env_name)
        if validator:
            ok, msg = validator(val)
            marker = "[green]✓[/green]" if ok else "[red]✗[/red]"
            console.print(f"    {marker} {msg}")
            if not ok and not _q_confirm("Save anyway?", default=False):
                continue
        keys[env_name] = val
    return keys


def collect_browser_sessions(providers: list[str]) -> list[str]:
    """Capture session cookies for any browser-session providers picked.

    Returns the list of provider keys that successfully got a session
    stored. The caller writes these into config.toml so the kernel
    routes the right roles to them.
    """
    session_providers = [
        p for p in providers
        if catalog.PROVIDERS.get(p, {}).get("session")
    ]
    if not session_providers:
        return []

    console.print()
    console.print(Panel.fit(
        "[bold yellow]Browser session capture[/bold yellow]\n\n"
        "You picked one or more browser-session providers. Maverick will\n"
        "replay your existing chat session against the provider's web\n"
        "endpoints to use your consumer subscription quota instead of\n"
        "paying per API token.\n\n"
        "[bold]Important caveats:[/bold]\n"
        "  • Programmatic use of consumer chat may violate the provider's\n"
        "    ToS. Maverick uses only YOUR session on YOUR account; what\n"
        "    you do with that is your call.\n"
        "  • Consumer chat does NOT expose tool-use. Session providers\n"
        "    only work for non-tool roles (summarizer, writer, analyst).\n"
        "  • Cookies expire frequently (~1 hour for ChatGPT). When they\n"
        "    do, re-run: [bold]maverick session import <provider>[/bold]\n"
        "  • Sessions are stored at ~/.maverick/sessions/ with chmod 600.",
        border_style="yellow",
    ))

    # Offer Playwright auto-capture once if available; falls back to
    # the per-provider paste flow if the user declines or it isn't
    # installed.
    use_auto = False
    try:
        from maverick.session_providers.browser_capture import playwright_available
        if playwright_available():
            use_auto = _q_confirm(
                "Use auto-capture? (We open a browser, you sign in normally, "
                "we read the cookies.) [recommended]",
                default=True,
            )
        else:
            console.print(
                "[dim]Playwright not installed -- using DevTools paste flow. "
                "Install with: pip install 'maverick-agent[capture]'[/dim]"
            )
    except ImportError:
        pass

    captured: list[str] = []
    for prov in session_providers:
        if use_auto and _capture_via_playwright(prov):
            captured.append(prov)
            continue
        if prov == "chatgpt-session":
            if _capture_chatgpt_session():
                captured.append(prov)
        elif prov == "claude-session":
            if _capture_claude_session():
                captured.append(prov)
        elif prov == "kimi-session":
            if _capture_kimi_session():
                captured.append(prov)
        elif prov == "grok-session":
            if _capture_grok_session():
                captured.append(prov)
        elif prov == "gemini-session":
            if _capture_gemini_session():
                captured.append(prov)
        else:
            console.print(
                f"[yellow]⚠[/yellow] {prov}: no capture flow implemented "
                "yet; skipping."
            )
    return captured


def _capture_via_playwright(provider: str) -> bool:
    """Drive the Playwright auto-capture flow. Returns True on success."""
    try:
        from maverick.session_providers.browser_capture import auto_capture
        from maverick.session_providers import cookie_store
    except ImportError:
        return False
    console.print(f"[bold]Auto-capturing {provider}[/bold]")
    console.print(
        "  Browser window opening. Sign in normally; we read the cookies "
        "automatically once you're logged in.\n"
        "  (Window closes after capture or 5-minute timeout.)"
    )
    try:
        blob = auto_capture(provider)
    except Exception as e:
        console.print(f"[red]✗[/red] auto-capture failed: {e}")
        return False
    if not blob:
        console.print(
            f"[yellow]⚠[/yellow] {provider}: auto-capture didn't get cookies "
            "(timeout?). Falling back to paste flow."
        )
        return False
    path = cookie_store.save_session(provider, blob)
    console.print(f"[green]✓[/green] Captured {provider} -> {path}")
    return True


def _capture_chatgpt_session() -> bool:
    """Walk the user through pasting their chatgpt.com session cookie."""
    console.print()
    console.print("[bold]Capturing ChatGPT session[/bold]")
    console.print(
        "  1. In Chrome/Firefox/Safari, sign in at https://chatgpt.com\n"
        "  2. Open DevTools (F12) -> Application -> Cookies -> chatgpt.com\n"
        "  3. Copy the value of [bold]__Secure-next-auth.session-token[/bold]"
    )
    token = _q_text("  Paste session token", default="")
    if not token.strip():
        console.print("[yellow]⚠[/yellow] No token entered; skipping ChatGPT session.")
        return False

    # Try to import + store via the kernel's cookie_store. If the kernel
    # isn't installed (rare in dev setups), surface that clearly.
    try:
        from maverick.session_providers import cookie_store
    except ImportError:
        console.print(
            "[red]✗[/red] maverick-core not installed; can't store session. "
            "Run: pip install maverick-agent"
        )
        return False

    blob = {
        "cookies": {"__Secure-next-auth.session-token": token.strip()},
    }
    path = cookie_store.save_session("chatgpt-session", blob)
    console.print(f"[green]✓[/green] Saved session to {path} (chmod 600)")
    return True


def _capture_claude_session() -> bool:
    """Walk the user through pasting their claude.ai sessionKey cookie."""
    console.print()
    console.print("[bold]Capturing Claude.ai session[/bold]")
    console.print(
        "  1. In Chrome/Firefox/Safari, sign in at https://claude.ai\n"
        "  2. Open DevTools (F12) -> Application -> Cookies -> claude.ai\n"
        "  3. Copy the value of [bold]sessionKey[/bold] (starts with 'sk-ant-sid01-')"
    )
    token = _q_text("  Paste sessionKey", default="")
    if not token.strip():
        console.print("[yellow]⚠[/yellow] No token entered; skipping Claude session.")
        return False

    try:
        from maverick.session_providers import cookie_store
    except ImportError:
        console.print(
            "[red]✗[/red] maverick-core not installed; can't store session. "
            "Run: pip install maverick-agent"
        )
        return False

    blob = {"cookies": {"sessionKey": token.strip()}}
    path = cookie_store.save_session("claude-session", blob)
    console.print(f"[green]✓[/green] Saved session to {path} (chmod 600)")
    return True


def _capture_kimi_session() -> bool:
    """Walk the user through pasting their kimi.com access_token cookie."""
    console.print()
    console.print("[bold]Capturing Kimi session[/bold]")
    console.print(
        "  1. In your browser, sign in at https://kimi.com\n"
        "  2. Open DevTools (F12) -> Application -> Cookies -> kimi.com\n"
        "  3. Copy the value of [bold]access_token[/bold] (long JWT)"
    )
    token = _q_text("  Paste access_token", default="")
    if not token.strip():
        console.print("[yellow]⚠[/yellow] No token entered; skipping Kimi.")
        return False
    try:
        from maverick.session_providers import cookie_store
    except ImportError:
        console.print("[red]✗[/red] maverick-core not installed.")
        return False
    blob = {"cookies": {"access_token": token.strip()}}
    path = cookie_store.save_session("kimi-session", blob)
    console.print(f"[green]✓[/green] Saved session to {path} (chmod 600)")
    return True


def _capture_grok_session() -> bool:
    """Walk the user through pasting their x.com auth_token + ct0 cookies."""
    console.print()
    console.print("[bold]Capturing Grok (x.com) session[/bold]")
    console.print(
        "  1. In your browser, sign in at https://x.com (need Premium for Grok)\n"
        "  2. Open DevTools (F12) -> Application -> Cookies -> x.com\n"
        "  3. Copy the value of [bold]auth_token[/bold]\n"
        "  4. Copy the value of [bold]ct0[/bold] (CSRF token; both required)"
    )
    auth_token = _q_text("  Paste auth_token", default="")
    ct0 = _q_text("  Paste ct0", default="")
    if not auth_token.strip() or not ct0.strip():
        console.print("[yellow]⚠[/yellow] Both auth_token AND ct0 required; skipping.")
        return False
    try:
        from maverick.session_providers import cookie_store
    except ImportError:
        console.print("[red]✗[/red] maverick-core not installed.")
        return False
    blob = {"cookies": {
        "auth_token": auth_token.strip(),
        "ct0": ct0.strip(),
    }}
    path = cookie_store.save_session("grok-session", blob)
    console.print(f"[green]✓[/green] Saved session to {path} (chmod 600)")
    return True


def _capture_gemini_session() -> bool:
    """Walk the user through pasting their gemini.google.com __Secure-1PSID cookie."""
    console.print()
    console.print("[bold]Capturing Gemini session[/bold]")
    console.print(
        "  1. In your browser, sign in at https://gemini.google.com\n"
        "  2. Open DevTools (F12) -> Application -> Cookies -> gemini.google.com\n"
        "  3. Copy the value of [bold]__Secure-1PSID[/bold]\n"
        "  4. (Optional but recommended) also copy __Secure-1PSIDTS and __Secure-1PSIDCC"
    )
    psid = _q_text("  Paste __Secure-1PSID", default="")
    if not psid.strip():
        console.print("[yellow]⚠[/yellow] No PSID entered; skipping Gemini.")
        return False
    psidts = _q_text("  Paste __Secure-1PSIDTS (optional)", default="")
    psidcc = _q_text("  Paste __Secure-1PSIDCC (optional)", default="")
    try:
        from maverick.session_providers import cookie_store
    except ImportError:
        console.print("[red]✗[/red] maverick-core not installed.")
        return False
    cookies = {"__Secure-1PSID": psid.strip()}
    if psidts.strip():
        cookies["__Secure-1PSIDTS"] = psidts.strip()
    if psidcc.strip():
        cookies["__Secure-1PSIDCC"] = psidcc.strip()
    path = cookie_store.save_session("gemini-session", {"cookies": cookies})
    console.print(f"[green]✓[/green] Saved session to {path} (chmod 600)")
    return True


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
    capabilities: dict[str, bool] | None = None,
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
        if info.get("session"):
            # Browser-session providers store their auth in
            # ~/.maverick/sessions/<provider>.json (chmod 600), not in
            # an env var. Mark the kind so the loader can warn early.
            lines.append('kind = "session"')
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

    if capabilities:
        lines.append("")
        lines.append("[capabilities]")
        for k, v in capabilities.items():
            lines.append(f"{k} = {str(v).lower()}")

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


PARTIAL_STATE_PATH = CONFIG_DIR / "wizard-partial.json"


def _save_partial(state: dict[str, Any]) -> None:
    """Persist wizard progress so --resume can pick up later."""
    try:
        import json as _json
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        PARTIAL_STATE_PATH.write_text(_json.dumps(state, default=str))
        os.chmod(PARTIAL_STATE_PATH, 0o600)
    except OSError:
        pass


def _load_partial() -> dict[str, Any] | None:
    """Return persisted partial state, or None if absent."""
    if not PARTIAL_STATE_PATH.exists():
        return None
    try:
        import json as _json
        return _json.loads(PARTIAL_STATE_PATH.read_text())
    except (OSError, ValueError):
        return None


def _clear_partial() -> None:
    try:
        if PARTIAL_STATE_PATH.exists():
            PARTIAL_STATE_PATH.unlink()
    except OSError:
        pass


def run_fast() -> int:
    """``maverick init --fast``: zero-question setup with sensible defaults.

    Skips every prompt. Writes a minimal config that runs on Anthropic
    Claude (BYOK via ANTHROPIC_API_KEY env), Docker sandbox, balanced
    safety, $5/run cap. Users can `maverick init` later to customize.
    """
    welcome()
    if not preflight():
        console.print(
            "[red]Preflight failed.[/red] Fix the issues above and re-run."
        )
        return 1
    console.print(
        "[bold]Fast setup:[/bold] using recommended defaults. "
        "Run `maverick init` (no --fast) anytime to customize.\n"
    )
    deployment = "desktop"
    providers = ["anthropic"]
    role_models: dict[str, str] = {}  # use ROLE_MODELS defaults
    channels: dict[str, Any] = {}
    safety = {
        "profile": "balanced",
        "block_threshold": "high",
        "scan_input": True,
        "scan_tool_calls": True,
        "scan_output": True,
    }
    budget = {
        "max_dollars": 5.0,
        "max_wall_seconds": 3600.0,
        "max_tool_calls": 500,
    }
    sandbox = {
        "backend": "docker",
        "workdir": str(Path.home() / "maverick-workspace"),
        "timeout": 60,
    }
    capabilities = {"computer_use": False, "browser": False}
    # Pick up the API key from the env if it's already there;
    # otherwise the wizard's later run can populate ~/.maverick/.env.
    keys: dict[str, str] = {}
    if os.environ.get("ANTHROPIC_API_KEY"):
        keys["ANTHROPIC_API_KEY"] = os.environ["ANTHROPIC_API_KEY"]
    write_config(
        deployment, providers, role_models, channels, safety, budget,
        sandbox, keys, capabilities,
    )
    smoke_test()
    console.print()
    console.print(Panel.fit(
        "[bold green]Fast setup complete.[/bold green]\n\n"
        "Try: [bold]maverick start \"hello\"[/bold]\n"
        "(If ANTHROPIC_API_KEY wasn't set, edit ~/.maverick/.env first.)",
        border_style="green",
    ))
    return 0


def run(fast: bool = False, resume: bool = False) -> int:
    if fast:
        return run_fast()
    welcome()
    if not preflight():
        console.print(
            "[red]Preflight failed.[/red] Fix the issues above and re-run `maverick init`."
        )
        return 1

    # --resume: load any persisted partial state and only ask
    # questions the user hasn't answered yet.
    state: dict[str, Any] = {}
    if resume:
        loaded = _load_partial()
        if loaded:
            state = loaded
            console.print(
                f"[dim]Resuming from {PARTIAL_STATE_PATH}: "
                f"{len(state)} answers already on file.[/dim]\n"
            )
        else:
            console.print(
                f"[yellow]⚠[/yellow] No partial state at {PARTIAL_STATE_PATH}; "
                "starting fresh.\n"
            )

    deployment = state.get("deployment") or pick_deployment()
    state["deployment"] = deployment
    _save_partial(state)

    providers = state.get("providers") or pick_providers()
    if not providers:
        console.print("[red]No providers selected. Aborting.[/red]")
        return 1
    state["providers"] = providers
    _save_partial(state)

    role_models = state.get("role_models")
    if role_models is None:
        role_models = pick_models_per_role(providers)
        state["role_models"] = role_models
        _save_partial(state)

    channels_state = state.get("channels")
    if channels_state is None:
        channels, channel_envs = pick_channels(deployment)
        # JSON-safe: store envs as a sorted list.
        state["channels"] = channels
        state["channel_envs"] = sorted(channel_envs)
        _save_partial(state)
    else:
        channels = channels_state
        channel_envs = set(state.get("channel_envs") or [])

    safety = state.get("safety") or pick_safety()
    state["safety"] = safety
    _save_partial(state)

    budget = state.get("budget") or pick_budget()
    state["budget"] = budget
    _save_partial(state)

    sandbox = state.get("sandbox") or pick_sandbox()
    state["sandbox"] = sandbox
    _save_partial(state)

    capabilities = state.get("capabilities") or pick_capabilities()
    state["capabilities"] = capabilities
    _save_partial(state)

    # Keys/sessions are never persisted to disk in the partial state
    # (they're secrets; the only safe place is ~/.maverick/.env).
    keys = collect_api_keys(providers, channel_envs)
    collect_browser_sessions(providers)

    console.print()
    if not _q_confirm("Write config and finish?", default=True):
        console.print("Aborted. Partial state saved; resume with `maverick init --resume`.")
        return 0

    write_config(deployment, providers, role_models, channels, safety, budget, sandbox, keys, capabilities)
    _clear_partial()
    ok = smoke_test()
    if ok:
        console.print()
        next_step = "maverick serve" if channels else 'maverick start "hello"'
        console.print(Panel.fit(
            "[bold green]All set.[/bold green]\n\n"
            "Try:\n"
            f"  [bold]{next_step}[/bold]\n"
            "  [bold]maverick status[/bold]\n"
            "  [bold]maverick skill install gh:texasreaper62/awesome-maverick-skills[/bold]",
            border_style="green",
        ))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(run())
