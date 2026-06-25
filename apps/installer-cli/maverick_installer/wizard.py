"""Maverick interactive installer.

Configures Maverick for a fresh install. Sets up:
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
    ("bluesky",  "Bluesky (AT Protocol)",               ["BLUESKY_HANDLE", "BLUESKY_PASSWORD"]),
    ("mastodon", "Mastodon (any instance)",             ["MASTODON_ACCESS_TOKEN"]),
    ("irc",      "IRC (channels + DMs)",                 []),
    # Voice API key is provider-specific (VAPI/RETELL/BLAND), resolved in the
    # voice block below; only the webhook token is static here.
    ("voice",    "Voice (Vapi/Retell/Bland)",            ["VAPI_WEBHOOK_TOKEN"]),
    ("whatsapp", "WhatsApp (Twilio, needs webhook)",    ["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN"]),
    ("whatsapp_cloud", "WhatsApp (Meta Cloud API, needs webhook)",
     ["WHATSAPP_CLOUD_ACCESS_TOKEN", "WHATSAPP_CLOUD_PHONE_NUMBER_ID",
      "WHATSAPP_CLOUD_VERIFY_TOKEN", "WHATSAPP_CLOUD_APP_SECRET"]),
    ("sms",      "SMS (Twilio, needs webhook)",         ["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN"]),
    ("imessage", "iMessage (macOS only)",               []),
    ("threads",  "Threads (Meta, polling)",              ["THREADS_ACCESS_TOKEN", "THREADS_USER_ID"]),
    ("rcs",      "RCS (Google RBM, approved agents only)",
     ["RCS_AGENT_ID", "RCS_SERVICE_ACCOUNT_JSON", "RCS_WEBHOOK_TOKEN"]),
]


# Channels that are scaffolds: they ship runtime code but can't work
# end-to-end from a default install — whatsapp/sms need a Twilio account
# plus a public webhook (maverick_channels documents both as "scaffold"),
# and imessage is macOS-only and needs Full Disk Access. Offering them in
# the default checkbox is dishonest: users pick them, then hit a dead end.
# Gate them behind an explicit opt-in (see pick_channels).
EXPERIMENTAL_CHANNELS: set[str] = {"whatsapp", "whatsapp_cloud", "sms", "imessage",
                                   "threads", "rcs"}


# Ordered advanced-flow steps, mirroring the pick_* sequence in run().
# Purely a progress-bar aid: changing this list never changes the config.
STEPS: list[tuple[str, str]] = [
    ("deployment", "Deployment"),
    ("providers", "Providers"),
    ("role_models", "Models"),
    ("channels", "Channels"),
    ("safety", "Safety"),
    ("signed_skills", "Signed skills"),
    ("budget", "Budget"),
    ("sandbox", "Sandbox"),
    ("capabilities", "Capabilities"),
    ("self_learning", "Self-learning"),
    ("automation_import", "Automation import"),
    ("oauth_vault", "OAuth token vault"),
    ("governed_connectors", "Governed connectors"),
    ("durable", "Durable execution"),
    ("finance", "Finance suite"),
    ("advanced", "Advanced reasoning"),
    ("web_search", "Web search"),
    ("mcp_servers", "MCP servers"),
    ("plugins", "Plugins"),
    ("tool_acl", "Tool ACL"),
    ("rate_limits", "Rate limits"),
    ("retention", "Retention"),
    ("analytics", "Analytics"),
    ("persona", "Persona"),
    ("notifications", "Notifications"),
    ("webhooks", "Webhooks"),
    ("a2a", "A2A"),
]


def _step_indicator(index: int, *, done: list[str] | None = None) -> str:
    """Format the ``Step N/M`` progress line for the ``index``-th step
    (1-based), optionally trailed by a breadcrumb of completed labels.

    Returns plain text (no Rich markup): styling is applied by the caller
    via ``console.print(..., style=...)`` so the literal "Step N/M" text
    stays contiguous in rendered output instead of being fragmented by
    inline ANSI codes. Defined as a pure helper so tests can assert the
    formatting without driving the whole wizard.
    """
    total = len(STEPS)
    label = STEPS[index - 1][1] if 1 <= index <= total else ""
    line = f"Step {index}/{total} {label}"
    if done:
        line += f"  ({' > '.join(done)})"
    return line


def _safe_int(s: str, *, default: int) -> int:
    """``int()`` that doesn't crash on whitespace, empty, or junk input."""
    try:
        return int(str(s or "").strip())
    except (TypeError, ValueError):
        return default


def _csv_list(raw: str, *, lower: bool = False) -> list[str]:
    """Split a comma-separated prompt answer into trimmed, non-empty items."""
    items = [x.strip() for x in str(raw or "").split(",") if x.strip()]
    return [x.lower() for x in items] if lower else items


def _safe_float(s: str, *, default: float) -> float:
    """``float()`` that doesn't crash on whitespace, empty, or junk input."""
    try:
        return float(str(s or "").strip())
    except (TypeError, ValueError):
        return default


# ---------- prompt primitives ----------

def _ask(question: Any) -> Any:
    """Run a questionary prompt, treating a ``None`` answer as an abort.

    questionary's ``.ask()`` returns ``None`` when the user presses
    Ctrl-C / Ctrl-D or when there's no interactive TTY (e.g. stdin is a
    pipe). Every call site then did ``.split()`` / ``.strip()`` on the
    result and crashed with an opaque ``AttributeError``. Convert that
    to ``KeyboardInterrupt`` so the entry point prints a clean "Aborted"
    message and exits 130 instead of dumping a traceback.
    """
    answer = question.ask()
    if answer is None:
        raise KeyboardInterrupt
    return answer


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
    return _ask(questionary.select(message, choices=choices, default=default))


def _q_text(message: str, default: str = "") -> str:
    if questionary is None:
        val = input(f"{message} [{default}]: ").strip()
        return val or default
    return _ask(questionary.text(message, default=default))


def _q_secret(message: str) -> str:
    if questionary is None:
        import getpass

        return getpass.getpass(f"{message}: ").strip()
    # Route through _ask so Ctrl-C / Ctrl-D / non-TTY (questionary returns
    # None) raises KeyboardInterrupt and aborts the wizard, like every other
    # prompt. The old `.ask() or ""` swallowed the abort into "", which
    # callers read as "skip this key" -- so Ctrl-C silently continued.
    return _ask(questionary.password(message)) or ""


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
    # questionary.checkbox ignores `default` (it's documented "not used by
    # checkbox"). To actually pre-select the defaults, wrap them as
    # pre-checked Choice objects whose value is the title string -- so
    # callers still get back the same strings they passed in.
    default_set = set(default or [])
    q_choices: Any = (
        [questionary.Choice(c, checked=c in default_set) for c in choices]
        if default_set else choices
    )
    return _ask(questionary.checkbox(message, choices=q_choices))


def _q_confirm(message: str, default: bool = True) -> bool:
    if questionary is None:
        val = input(f"{message} [{'Y/n' if default else 'y/N'}]: ").strip().lower()
        if not val:
            return default
        return val.startswith("y")
    return _ask(questionary.confirm(message, default=default))


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
    """Ping Anthropic with the key. Returns (ok, message).

    Skip the prefix check: Anthropic now ships admin keys, batch keys,
    and several legacy formats. The API ping handles whatever shape
    the key takes.
    """
    if not key.strip():
        return False, "empty key"
    try:
        import anthropic
    except ImportError:
        return True, "anthropic SDK not installed -- skipping validation"
    try:
        client = anthropic.Anthropic(api_key=key, timeout=5.0)
        # Minimal call -- list available models is enough to verify auth.
        list(client.models.list(limit=1))
        return True, "validated"
    except anthropic.AuthenticationError:
        return False, "API rejected the key"
    except Exception as e:
        return True, f"validation skipped: {type(e).__name__}"


def _validate_openai_key(key: str) -> tuple[bool, str]:
    if not key.strip():
        return False, "empty key"
    # Azure OpenAI keys are 32-char hex with no prefix; OpenAI ships
    # sk-, sk-proj-, sk-svcacct-. Just ping the API and let it tell us.
    try:
        from openai import AuthenticationError, OpenAI
    except ImportError:
        return True, "openai SDK not installed -- skipping validation"
    try:
        client = OpenAI(api_key=key, timeout=5.0)
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
        client = OpenAI(api_key=key, base_url=base_url, timeout=5.0)
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


# ---------- validation cache ----------

VALIDATION_CACHE_PATH = CONFIG_DIR / "validation-cache.json"
_VALIDATION_TTL_SECONDS = 7 * 24 * 3600  # 7 days


def _key_fingerprint(env_name: str, key: str) -> str:
    import hashlib
    digest = hashlib.sha256(f"{env_name}\x00{key}".encode()).hexdigest()
    return digest[:32]


def _load_validation_cache() -> dict[str, Any]:
    try:
        import json as _json
        return _json.loads(VALIDATION_CACHE_PATH.read_text())
    except (OSError, ValueError):
        return {}


def _save_validation_cache(cache: dict[str, Any]) -> None:
    import json as _json
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        VALIDATION_CACHE_PATH.write_text(_json.dumps(cache, default=str))
        try:
            os.chmod(VALIDATION_CACHE_PATH, 0o600)
        except OSError:
            pass
    except OSError:
        pass


def _cached_validation(env_name: str, key: str) -> tuple[bool, str] | None:
    """Return cached (ok, msg) if the same key was validated within the TTL."""
    import time as _time
    if not key.strip():
        return None
    cache = _load_validation_cache()
    fp = _key_fingerprint(env_name, key)
    entry = cache.get(fp)
    if not entry:
        return None
    ts = float(entry.get("ts", 0))
    if (_time.time() - ts) > _VALIDATION_TTL_SECONDS:
        return None
    return bool(entry.get("ok", False)), str(entry.get("msg", "cached"))


def _remember_validation(env_name: str, key: str, ok: bool, msg: str) -> None:
    import time as _time
    if not key.strip():
        return
    cache = _load_validation_cache()
    cache[_key_fingerprint(env_name, key)] = {
        "ts": _time.time(),
        "ok": ok,
        "msg": msg,
    }
    _save_validation_cache(cache)


# ---------- error UI ----------

def show_bad_key_error(env_name: str, msg: str) -> None:
    """Council UX seat error screen #1: provider rejected the key."""
    console.print()
    console.print(Panel.fit(
        f"[bold]That {env_name.split('_')[0].title()} key didn't work.[/bold]\n\n"
        f"{msg}\n\n"
        "Common causes:\n"
        "  1. Typo (the secret is long; copy/paste, don't retype).\n"
        "  2. The key was deleted from your account.\n"
        "  3. Billing isn't set up on the provider.",
        border_style="red",
    ))


def show_network_error(provider: str, exception_type: str) -> None:
    """Council UX seat error screen #2: validator couldn't reach the provider."""
    console.print()
    console.print(Panel.fit(
        f"[bold]Couldn't reach {provider} to check the key ({exception_type}).[/bold]\n\n"
        "Usually a network block or proxy. Your key is saved either way;\n"
        "if it's wrong the first goal you run will say so.",
        border_style="yellow",
    ))


def show_install_failure(exc: BaseException) -> None:
    """Council UX seat error screen #3: catch-all for unexpected setup failures."""
    console.print()
    console.print(Panel.fit(
        "[bold]Setup hit a problem and stopped.[/bold]\n\n"
        f"{type(exc).__name__}: {exc}\n\n"
        "Nothing was changed. Try again, or report the issue with the\n"
        "diagnostic output of [bold]maverick doctor[/bold].",
        border_style="red",
    ))


def show_browser_capture_timeout(provider: str) -> None:
    """Council UX seat error screen #4: browser session capture timed out."""
    console.print()
    console.print(Panel.fit(
        f"[bold]Sign-in to {provider} didn't complete in time.[/bold]\n\n"
        "Try again, or pick a different option (paste an API key, or use a\n"
        "local model).",
        border_style="yellow",
    ))


# ---------- wizard steps ----------

def welcome() -> None:
    console.print(Panel.fit(
        "[bold]Lightwork installer[/bold]\n\n"
        "Next you'll pick a setup mode: a quick consumer flow (a few\n"
        "questions, safe defaults) or advanced (configure every model,\n"
        "channel, safety level, and budget). Re-run any time with\n"
        "[bold]maverick init[/bold].",
        border_style="cyan",
    ))


def pick_deployment() -> str:
    pick = _q_select(
        "Where will Lightwork run?",
        [
            "desktop  - This computer (recommended for first-time users)",
            "docker   - Local Docker container (isolated, easy to remove)",
            "vps      - Remote server you own (always-on)",
            "phone    - Phone companion (Lightwork runs on desktop/VPS; phone is a frontend)",
        ],
    )
    return pick.split()[0]


def pick_providers() -> list[str]:
    choices = []
    for prov_id, info in catalog.PROVIDERS.items():
        tag = "[ready]" if info["status"] == "ready" else "[v0.2]"
        choices.append(f"{prov_id:10} {tag} - {info['label']}")

    picks = _q_checkbox(
        "Which AI providers do you want to use?",
        choices,
        default=[choices[0]],
    )
    return [p.split()[0] for p in picks]


_LOCAL_FIRST_PROVIDERS = frozenset({"ollama", "tgi"})


def _local_first_model(providers: list[str]) -> str | None:
    """Return the default local model spec for the selected providers."""
    for prov in providers:
        if prov not in _LOCAL_FIRST_PROVIDERS:
            continue
        info = catalog.PROVIDERS.get(prov)
        models = (info or {}).get("models") or []
        if models:
            return f"{prov}:{models[0]['id']}"
    return None


def pick_models_per_role(providers: list[str]) -> dict[str, str]:
    console.print()
    if _q_confirm(
        "Use the default model for each role?",
        default=True,
    ):
        return {}

    console.print()
    console.print(
        "[bold]Pick a model for each agent role.[/bold] "
        "Large models (orchestrator, revisor) suit big roles; "
        "cheap roles (summarizer) can use smaller ones.\n"
    )

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


# Inbound channels enforce a sender allowlist (fail-closed): only these
# IDs can drive the agent and spend budget. The wizard must collect it or
# the channel refuses to start. See maverick_channels.base.is_allowed.
_ALLOWLIST_CHANNELS = {
    "telegram", "discord", "slack", "signal", "email",
    "matrix", "bluesky", "mastodon", "irc", "imessage", "sms", "whatsapp",
    "whatsapp_cloud", "threads", "rcs",
}
_ALLOWLIST_HINT = {
    "telegram": "numeric Telegram user IDs",
    "discord": "numeric Discord user IDs",
    "slack": "Slack user IDs, e.g. U01ABC",
    "signal": "phone numbers, e.g. +12345550199",
    "email": "email addresses",
    "matrix": "MXIDs, e.g. @you:matrix.org",
    "bluesky": "handles or DIDs",
    "mastodon": "acct names, e.g. you@instance",
    "irc": "authenticated IRC account names (requires IRCv3 account-tag)",
    "imessage": "phone numbers or emails",
    "sms": "phone numbers, e.g. +14155551234",
    "whatsapp": "senders as Twilio sends them, e.g. whatsapp:+14155551234",
    "whatsapp_cloud": "bare wa_id digits, e.g. 14155551234",
    "threads": "Threads usernames of allowed authors",
    "rcs": "E.164 MSISDNs, e.g. +14155551234",
}


def _channel_base_cfg(ch_id: str, envs: set[str]) -> dict[str, Any]:
    """Build the channel-specific config for ``ch_id`` (excluding allowlists).

    May add provider-specific env vars to ``envs`` (e.g. voice keys).
    """
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
        cfg["smtp_port"] = _safe_int(_q_text("  SMTP port", default="465"), default=465)
        cfg["imap_user"] = "${EMAIL_USER}"
        cfg["imap_password"] = "${EMAIL_APP_PASSWORD}"
        cfg["smtp_user"] = "${EMAIL_USER}"
        cfg["smtp_password"] = "${EMAIL_APP_PASSWORD}"
        cfg["poll_interval"] = 30
    elif ch_id == "matrix":
        cfg["homeserver"] = _q_text("  Matrix homeserver URL", default="https://matrix.org")
        cfg["user_id"] = _q_text("  Matrix user ID (e.g., @you:matrix.org)", default="")
        cfg["access_token"] = "${MATRIX_ACCESS_TOKEN}"
    elif ch_id == "bluesky":
        cfg["handle"] = "${BLUESKY_HANDLE}"
        cfg["password"] = "${BLUESKY_PASSWORD}"
        cfg["poll_interval"] = 60
    elif ch_id == "mastodon":
        cfg["instance"] = _q_text(
            "  Mastodon instance URL", default="https://mastodon.social",
        )
        cfg["access_token"] = "${MASTODON_ACCESS_TOKEN}"
        cfg["poll_interval"] = 30
    elif ch_id == "voice":
        provider = (_q_text(
            "  Voice provider (vapi, retell, bland)", default="vapi",
        ).strip().lower() or "vapi")
        cfg["provider"] = provider
        key_env = {
            "vapi": "VAPI_API_KEY",
            "retell": "RETELL_API_KEY",
            "bland": "BLAND_API_KEY",
        }.get(provider, "VAPI_API_KEY")
        # Collect the provider-specific key so the wizard actually prompts
        # for it; otherwise a retell/bland config references ${RETELL_API_KEY}
        # / ${BLAND_API_KEY} that the user was never asked to enter.
        envs.add(key_env)
        cfg["api_key"] = "${" + key_env + "}"
        # Inbound webhook auth is Vapi-shaped today; keep the token ref.
        cfg["webhook_token"] = "${VAPI_WEBHOOK_TOKEN}"
        cfg["phone_number"] = _q_text(
            "  Phone number (E.164, optional)", default="",
        )
        cfg["assistant_id"] = _q_text(
            "  Assistant/agent ID (optional)", default="",
        )
        cfg["port"] = _safe_int(
            _q_text("  Webhook port", default="8770"), default=8770,
        )
    elif ch_id == "whatsapp":
        cfg["account_sid"] = "${TWILIO_ACCOUNT_SID}"
        cfg["auth_token"] = "${TWILIO_AUTH_TOKEN}"
        cfg["from_number"] = _q_text(
            "  WhatsApp 'from' (e.g., whatsapp:+14155238886)", default=""
        )
        cfg["port"] = _safe_int(_q_text("  Webhook port", default="8765"), default=8765)
    elif ch_id == "sms":
        cfg["account_sid"] = "${TWILIO_ACCOUNT_SID}"
        cfg["auth_token"] = "${TWILIO_AUTH_TOKEN}"
        cfg["from_number"] = _q_text(
            "  SMS 'from' number (e.g., +14155551234)", default=""
        )
        cfg["port"] = _safe_int(_q_text("  Webhook port", default="8766"), default=8766)
    elif ch_id == "imessage":
        cfg["poll_interval"] = 5

    return cfg


def _channel_allowlist(ch_id: str, cfg: dict[str, Any]) -> None:
    """Prompt for and apply per-channel sender allowlists in-place on ``cfg``."""
    if ch_id in _ALLOWLIST_CHANNELS:
        hint = _ALLOWLIST_HINT.get(ch_id, "sender IDs")
        raw_ids = _q_text(
            f"  Allowed senders, comma-separated ({hint}) — "
            "only these can drive the agent",
            default="",
        )
        ids = _csv_list(raw_ids)
        if ids:
            cfg["allowed_user_ids"] = ids
        else:
            env_name = (
                "IRC_ALLOWED_ACCOUNTS"
                if ch_id == "irc"
                else ch_id.upper() + "_ALLOWED_USER_IDS"
            )
            console.print(
                "  [yellow]No allowlist set — this channel will refuse "
                f"all senders until you set {env_name} "
                "or add allowed_user_ids to config.[/yellow]"
            )
    elif ch_id == "voice":
        raw = _q_text(
            "  Allowed caller numbers (E.164, comma-separated; "
            "blank = any authenticated caller)",
            default="",
        )
        callers = _csv_list(raw)
        if callers:
            cfg["allowed_callers"] = callers


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

    selectable = [c for c in CHANNELS if c[0] not in EXPERIMENTAL_CHANNELS]
    if _q_confirm(
        "Show experimental/unfinished channels (WhatsApp, SMS, iMessage)? "
        "These are scaffolds and may not work end-to-end.",
        default=False,
    ):
        selectable += [
            (ch_id, f"{label} [experimental]", envs)
            for ch_id, label, envs in CHANNELS
            if ch_id in EXPERIMENTAL_CHANNELS
        ]

    choices = [f"{ch_id:9} - {label}" for ch_id, label, _ in selectable]
    picked = _q_checkbox("Which channels do you want to enable?", choices)
    picked_ids = [p.split()[0] for p in picked]

    channels: dict[str, dict[str, Any]] = {}
    envs: set[str] = set()

    for ch_id in picked_ids:
        info = next((c for c in CHANNELS if c[0] == ch_id), None)
        if info is None:
            continue
        envs.update(info[2])

        cfg = _channel_base_cfg(ch_id, envs)
        _channel_allowlist(ch_id, cfg)

        channels[ch_id] = cfg

    return channels, envs


def pick_safety() -> dict[str, Any]:
    pick = _q_select(
        "Safety profile:",
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
    # Agent compartments: when one agent's scan blocks a threat, record its
    # signature so the rest of the swarm is immune to the same attack for the
    # run. Moot with safety off (nothing scans). Off by default.
    compartments = False
    if profile != "off":
        compartments = _q_confirm(
            "  Enable agent compartments (one agent's blocked threat immunizes "
            "the rest of the swarm for the run)?",
            default=False,
        )
    return {
        "profile": profile,
        "block_threshold": threshold,
        "scan_input": profile != "off",
        "scan_tool_calls": profile != "off",
        "scan_output": profile != "off",
        "compartments": compartments,
    }


def pick_signed_skills() -> dict[str, Any]:
    """Optional Ed25519 signing policy for installed skills.

    Returns a dict written under ``[skills]``. Defaults keep current
    behavior (no trusted publishers, unsigned skills allowed)."""
    console.print()
    console.print(
        "[dim]Signed skills: a publisher can sign a SKILL.md with an Ed25519 "
        "key. Paste trusted publisher public keys (hex) to verify against; "
        "leave blank to skip.[/dim]"
    )
    raw = _q_text("  Trusted skill publisher pubkeys (comma-separated hex)", default="")
    trusted = _csv_list(raw)
    require = _q_confirm(
        "  Reject unsigned skills (only install signed + trusted ones)?",
        default=False,
    )
    require_catalog = _q_confirm(
        "  Require a verified signature for catalog installs (even with no "
        "trusted keys above)?",
        default=False,
    )
    return {
        "trusted_pubkeys": trusted,
        "require_signed": require,
        "require_signed_catalog": require_catalog,
    }


def pick_budget() -> dict[str, float]:
    console.print()
    console.print("[dim]Per-run caps. Edit later in ~/.maverick/config.toml.[/dim]")
    return {
        "max_dollars": _safe_float(
            _q_text("  Max $ per run", default="5.0"), default=5.0,
        ),
        "max_wall_seconds": _safe_float(
            _q_text("  Max wall-clock seconds per run", default="3600"),
            default=3600.0,
        ),
        "max_tool_calls": _safe_int(
            _q_text("  Max tool calls per run", default="500"), default=500,
        ),
    }


def pick_capabilities() -> dict[str, bool]:
    """Opt-in to high-impact tools that ship disabled.

    Computer-use, browser, ROS robotics, and code-exec tools have real safety
    side effects (mouse/keyboard control, arbitrary navigation, robot/simulator
    commands, or sandboxed tool orchestration), so they default to off until you
    explicitly enable them.
    """
    console.print()
    use_computer = _q_confirm(
        "Enable computer-use? Lets the agent see your screen and drive the mouse/keyboard.",
        default=False,
    )
    use_browser = _q_confirm(
        "Enable browser? Lets the agent navigate the web via Playwright.",
        default=False,
    )
    use_ros = _q_confirm(
        "Enable ROS robotics? Lets the agent publish topics or call services "
        "against ROS_BRIDGE_URL over rosbridge. Only enable for trusted robot/sim "
        "operators.",
        default=False,
    )
    use_code_exec = _q_confirm(
        "Enable code_exec? Lets the agent run a sandboxed Python script that "
        "orchestrates several tool calls in one turn (keeps large intermediate "
        "outputs out of context). Runs code in the sandbox, like the shell tool.",
        default=False,
    )
    # The embedded-device tool (JTAG/I2C) is always registered, but its
    # DESTRUCTIVE ops (flash write, target reset) stay refused until the
    # operator opts in here -> [embedded] allow_flash. Default off.
    embedded_flash = _q_confirm(
        "Allow embedded-device flashing? The JTAG tool can erase/reflash YOUR "
        "OWN connected device's firmware (OpenOCD). Off = it refuses flash/reset.",
        default=False,
    )
    deferred_tools = _q_confirm(
        "Use deferred tool loading? The model sees the core toolset and "
        "discovers the 400+ SaaS connectors on demand via find_tools -- "
        "cuts per-call token cost ~60%. Disable only if you want every "
        "connector schema offered on every turn.",
        default=True,
    )
    return {
        "computer_use": use_computer,
        "browser": use_browser,
        "ros": use_ros,
        "code_exec": use_code_exec,
        "embedded_flash": embedded_flash,
        "deferred_tools": deferred_tools,
    }


def pick_self_learning() -> dict[str, Any]:
    """Opt-in to self-learning: acquire/build new capabilities on demand.

    Off by default. When on, the agent can install catalog skills, generate
    + run new tools, and discover REST APIs when it hits a capability gap.
    Generating and executing fresh code is a real trust decision, so this
    ships disabled and we say so plainly. Returns a dict written under
    ``[self_learning]``.

    MCP-server acquisition (#422) is a separate, even-higher-trust knob: it
    re-enables the capability #392 disabled, but only for curated, hash-pinned
    catalog servers AND only after explicit operator approval. It ships OFF
    independently of the self-learning master switch.
    """
    console.print()
    console.print(
        "[dim]Self-learning lets the agent close capability gaps on its own: "
        "install skills, discover REST APIs, even write & run new tools. "
        "It generates and executes fresh code in-process, so it's OFF by "
        "default.[/dim]"
    )
    enable = _q_confirm("Enable self-learning?", default=False)
    if not enable:
        return {"enable": False}
    create_tools = _q_confirm(
        "  Allow the agent to GENERATE and run new tools (full autonomy)?",
        default=True,
    )
    preflight = _q_confirm(
        "  Pre-acquire likely skills before each run (one extra LLM call)?",
        default=True,
    )
    console.print(
        "[dim]  MCP acquisition: the agent may PROPOSE adding a curated, "
        "hash-pinned catalog MCP server (never a free-text command). Each one "
        "still needs your explicit approval before it starts.[/dim]"
    )
    allow_mcp = _q_confirm(
        "  Allow agent to propose catalog MCP servers (operator-approved)?",
        default=False,
    )
    distill_local = _q_confirm(
        "  Distill successful runs into local skills? After a successful run, "
        "save a reusable skill under ~/.maverick/learned-skills.",
        default=False,
    )
    return {
        "enable": True,
        "preflight": preflight,
        "create_tools": create_tools,
        "allow_mcp_acquisition": allow_mcp,
        "distill_local": distill_local,
        "max_acquisitions": 5,
    }


def pick_automation_import() -> dict[str, Any]:
    """Opt-in to importing clients' existing automations into Lightwork.

    Off by default. When on, ``maverick import`` can pull workflow definitions
    from platforms that expose them (n8n/Make/Workato/Power Automate/UiPath) and
    turn each into a Lightwork template, plus connect-and-trigger for Zapier/
    Notion. It reaches out to third-party platforms and writes user templates,
    so it ships disabled. Returns a dict written under ``[automation_import]``.
    """
    console.print()
    console.print(
        "[dim]Automation import pulls workflows your clients already built "
        "(n8n/Make/Workato/Power Automate/UiPath) into Lightwork templates, and "
        "lets Zapier/Notion trigger Lightwork. It calls third-party APIs and "
        "writes templates, so it's OFF by default.[/dim]"
    )
    enable = _q_confirm("Enable automation import?", default=False)
    if not enable:
        return {"enable": False}
    create_schedules = _q_confirm(
        "  Auto-create Lightwork schedules for imported cron triggers? "
        "(off = import the template, you activate the schedule yourself)",
        default=False,
    )
    return {"enable": True, "create_schedules": create_schedules}


def pick_oauth_vault() -> dict[str, Any]:
    """Opt-in to sealing captured OAuth tokens in the per-tenant vault.

    Off by default. When on, the OAuth helper seals access/refresh tokens
    encrypted-at-rest under the tenant's DEK (one data key per tenant) instead
    of writing them to a plaintext file. Returns a dict written under
    ``[oauth]``.
    """
    console.print()
    console.print(
        "[dim]The OAuth token vault seals captured access/refresh tokens "
        "encrypted-at-rest under each tenant's own key (no plaintext token "
        "files, no cross-tenant readability). Recommended for hosted/multi-"
        "tenant deploys. OFF by default.[/dim]"
    )
    return {"vault": _q_confirm("Seal OAuth tokens in the per-tenant vault?",
                                default=False)}


def pick_governed_connectors() -> dict[str, Any]:
    """Opt-in to routing live system-of-record writes through governed Actions.

    Off by default. When on, a selected enterprise connector (Salesforce,
    ServiceNow) is registered as a typed governed Action: a write previews its
    effect, hits the approval floor (``[actions] require_approval_at``), and
    records a tamper-evident lineage link -- instead of a bare confirm-gated
    tool call. Returns a dict written under ``[governed_connectors]``.
    """
    try:
        from maverick.governed_rest import available_rest_connectors
        choices = available_rest_connectors()
    except Exception:  # pragma: no cover -- never block the wizard
        choices = ["salesforce", "servicenow"]
    console.print()
    console.print(
        "[dim]Governed connectors route a live system-of-record write "
        f"({', '.join(choices)}) through simulate -> approve -> commit -> "
        "lineage: the write hits the approval floor and is recorded in a "
        "tamper-evident chain. OFF by default.[/dim]"
    )
    if not _q_confirm("Enable governed system-of-record connectors?", default=False):
        return {"enable": False}
    selected = [c for c in choices
                if _q_confirm(f"  Register {c} as a governed connector?", default=False)]
    # Standing approver of record: when these connectors are wrapped in the live
    # tool path, a write is approval-gated against this identity (the agent can't
    # self-approve). Blank = writes are previewed but refused until an operator
    # commits them out of band.
    approver = _q_text(
        "  Approver of record for governed writes (blank = refuse agent writes "
        "without out-of-band approval):", default="").strip()
    return {"enable": True, "connectors": selected, "approver": approver}


def pick_durable() -> dict[str, Any]:
    """Opt-in to durable execution (crash-resume via checkpoints).

    Off by default. When on, a long-running goal checkpoints its loop state at
    each step so ``maverick resume`` continues from where a crash left off
    instead of re-running from the start. Returns a dict written under
    ``[durable]``.
    """
    console.print()
    console.print(
        "[dim]Durable execution checkpoints a goal's progress so a crash or "
        "restart resumes from the last step instead of starting over. Adds a "
        "small write per step; OFF by default.[/dim]"
    )
    if not _q_confirm("Enable durable execution (crash-resume)?", default=False):
        return {"enabled": False}
    return {"enabled": True, "keep_last": 5}


def pick_finance() -> dict[str, Any]:
    """Opt-in to the finance suite governance (finance-agent-suite §5/§8).

    Off by default. When enabled, governance pauses money movement for a human,
    you pick the compliance regimes to enforce (strictest-wins), set the
    delegation-of-authority dollar tiers, and point at an OFAC SDN list. Returns a
    dict written under ``[governance]`` / ``[finance]`` / ``[screening]``.
    """
    console.print()
    console.print(
        "[dim]Finance suite: the CFO-office governance wrapper -- segregation of "
        "duties, maker-checker, dollar-threshold approvals, and a signed book of "
        "record. Enabling pauses every money movement for a human and lets you "
        "enforce compliance regimes. OFF by default.[/dim]"
    )
    if not _q_confirm("Enable the finance suite governance?", default=False):
        return {"enable": False}
    regimes = _q_checkbox(
        "Compliance regimes to enforce (strictest-wins union):",
        ["sox", "coso", "gaap", "pci", "glba", "aml", "sec", "irs"],
        default=["sox", "gaap"],
    )
    require_human_above = _safe_float(
        _q_text("  Pause money movement above $ (DoA threshold; 0 = pause all)",
                default="5000"),
        default=5000.0,
    )
    deny_above = _safe_float(
        _q_text("  Hard-deny money movement above $ (0 = no hard ceiling)",
                default="0"),
        default=0.0,
    )
    require_fresh = _q_confirm(
        "  Require a FRESH human approval each time a paused action runs "
        "(ignore any prior 'remember this' grant)?",
        default=False,
    )
    sdn_path = _q_text(
        "  OFAC SDN list path for sanctions screening (blank to set later)",
        default="",
    ).strip()
    return {
        "enable": True,
        "regimes": regimes,
        "require_human_above": require_human_above,
        "deny_above": deny_above,
        "require_fresh_human_approval": require_fresh,
        "sdn_path": sdn_path,
    }


def pick_oidc() -> dict[str, Any]:
    """Opt-in to OIDC ID-token verification for `maverick serve` (SSO).

    Off by default. When enabled, the server verifies an OpenID-Connect ID
    token (RS256/ES256 only — never HMAC/none) against the issuer + audience
    you configure, and maps the verified ``sub`` to a ``user:<sub>`` principal.
    Returns a dict written under ``[auth.oidc]``; ``{"enabled": False}`` when
    declined (so the writer emits nothing).
    """
    console.print(
        "[dim]OIDC SSO lets users authenticate to `maverick serve` with your "
        "identity provider (Okta, Auth0, Entra, Google, ...). Tokens are "
        "verified with the IdP's public keys; only RS256/ES256 are accepted "
        "(HMAC/none are rejected to prevent algorithm-confusion). OFF by "
        "default.[/dim]"
    )
    if not _q_confirm("Enable OIDC SSO token verification?", default=False):
        return {"enabled": False}
    issuer = _q_text(
        "  Issuer URL (the IdP's 'iss', e.g. https://example.okta.com)",
        default="",
    ).strip()
    audience = _q_text(
        "  Audience (your app's client_id / API audience)", default="",
    ).strip()
    jwks_uri = _q_text(
        "  JWKS URI (the IdP's signing-key endpoint, "
        "e.g. https://example.okta.com/oauth2/v1/keys)",
        default="",
    ).strip()
    result: dict[str, Any] = {
        "enabled": True,
        "issuer": issuer,
        "audience": audience,
        "jwks_uri": jwks_uri,
    }
    # Optional: the built-in browser-login (authorization-code) flow. The
    # default path is bearer-token verification only (API clients) or a reverse
    # proxy for browser SSO; this self-contained flow is for deployments that
    # can't run an auth proxy. OFF unless the operator opts in and supplies the
    # OAuth client + a session-signing secret.
    console.print(
        "[dim]Optional: built-in browser login. Lets the dashboard run the "
        "OAuth2 authorization-code flow itself (browser SSO without a separate "
        "auth proxy). Needs an OAuth client_id/secret registered with your IdP "
        "and a redirect URI of <dashboard-url>/auth/callback. OFF by "
        "default.[/dim]"
    )
    if _q_confirm("  Also enable the built-in browser login flow?", default=False):
        client_id = _q_text(
            "    OAuth client_id (this dashboard's registered client)", default="",
        ).strip()
        client_secret = _q_text(
            "    OAuth client_secret", default="",
        ).strip()
        redirect_uri = _q_text(
            "    Redirect URI (must be <dashboard-url>/auth/callback)", default="",
        ).strip()
        session_secret = _q_text(
            "    Session-signing secret (a long random string; keep it secret)",
            default="",
        ).strip()
        result.update(
            {
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "session_secret": session_secret,
            }
        )
    return result


def pick_advanced() -> dict[str, Any]:
    """Opt-in to advanced reasoning features that ship off by default.

    Each trades extra tokens/latency for quality on hard or long-running
    goals. All editable later in ~/.maverick/config.toml.
    """
    console.print()
    advanced: dict[str, Any] = {
        "cost_aware": _q_confirm(
            "Cost-aware routing? Use the cheapest capable model per role to cut spend.",
            default=False,
        ),
        "tree_of_thought": _q_confirm(
            "Tree-of-thought planning? Draft a few plans and let a critic pick the "
            "best before working (more tokens up front, fewer dead ends).",
            default=False,
        ),
        "compact_history": _q_confirm(
            "Compact long conversations? Keep the most relevant older turns under a "
            "token budget instead of just the last few.",
            default=False,
        ),
        "compaction_strategy": _q_select(
            "  Compaction strategy? (default = simple shrink)",
            ["default     - keep recent + trim big tool outputs",
             "learned     - LLM summary, self-tuning prompt picker",
             "multimodal  - stub heavy image/audio blocks to text",
             "streaming   - incremental running summary (long chats)",
             "graph       - entity-relation digest"],
            default="default     - keep recent + trim big tool outputs",
        ).split()[0],
        "reflexion": _q_confirm(
            "Reflexion learning? Remember lessons from failed runs and recall them "
            "on the next similar goal.",
            default=False,
        ),
        "fleet_memory": _q_confirm(
            "Fleet memory? Let EXTERNAL agents (Agentforce, Copilot, custom) "
            "deposit experience into and recall from Maverick's governed "
            "memory -- Shield-scanned, provenance-tagged, audited reads. "
            "An explicit trust decision; OFF by default.",
            default=False,
        ),
        "memory_guard": _q_confirm(
            "Memory Guard (OWASP ASI06)? Screen every stored fact for prompt-"
            "injection/poisoning, stamp it with provenance + a trust tier, and "
            "keep low-trust memory out of the agent's standing brief (trust-aware "
            "retrieval). Every decision is audited. OFF by default.",
            default=False,
        ),
        "temporal_memory": _q_confirm(
            "Temporal memory? Keep a bitemporal history of every fact (validity "
            "windows) instead of overwriting -- answer 'what did we believe on "
            "date X, and why' for the Operating Record. OFF by default.",
            default=False,
        ),
        "fairness_monitor": _q_confirm(
            "Continuous fairness monitoring (ISO 42001 A.6.2.6)? Watch decision "
            "outcomes over a rolling window and raise a signed FAIRNESS_ALERT when "
            "the four-fifths rule is breached or fairness drifts below baseline. A "
            "deployment opts in by feeding the monitor its outcomes. OFF by default.",
            default=False,
        ),
        "specialist_discipline": _q_confirm(
            "Specialist operating discipline? Append each business suite's "
            "professional guardrails (finance maker-checker, legal privilege, "
            "HR PII-minimization, ...) to every domain pack's persona at "
            "spawn. Recommended; prompts only, hard limits stay enforced by "
            "capabilities/governance.",
            default=True,
        ),
        "allow_pack_editing": _q_confirm(
            "Allow editing agents (domain packs) from the dashboard? Operators "
            "can fork/tweak a specialist's persona, tools, and workflow per "
            "client; an edit is validated before it saves, so it can never "
            "weaken the safety envelope. Turn off to lock the agent roster.",
            default=True,
        ),
        "allow_role_editing": _q_confirm(
            "Allow editing the core roles (orchestrator, coder, ...) from the "
            "dashboard? Operators can add a per-client system-prompt addendum "
            "to a role. Turn off to lock role behavior. (Model/effort routing "
            "is configured separately.)",
            default=True,
        ),
        "dreaming": _q_confirm(
            "Dreaming (offline consolidation)? `maverick dream` replays recent "
            "runs while idle, distills recurring wins into skills per department, "
            "turns repeated failures into recalled insights (promoting patterns "
            "shared across departments), retires skills whose track record "
            "decayed, and prunes stale lessons. Deterministic, no LLM calls "
            "(opt-in rehearsal runs are separate and budgeted).",
            default=False,
        ),
        "verify_ensemble": _q_confirm(
            "Ensemble verification? Cross-check final answers with a panel of models "
            "(slower, stronger).",
            default=False,
        ),
        "risk_proportional_verify": _q_confirm(
            "Risk-proportional verification? Skip the verifier on trivial, low-risk "
            "answers (short, prose-only, no tools or code) to save tokens and latency.",
            default=False,
        ),
        "autonomy_gate": _q_confirm(
            "Autonomy gate? When sub-agents disagree, cross-check the answer with a "
            "model panel AND hold irreversible (high-risk) actions until the "
            "disagreement is resolved or a human approves.",
            default=False,
        ),
        "headless_assume": _q_confirm(
            "Autonomous (headless) mode? When no human is available to answer, the "
            "agent states a reasonable assumption and continues instead of stalling "
            "on a clarifying question. Best for batch / unattended runs.",
            default=False,
        ),
        "governed_actions": _q_confirm(
            "Governed actions? Record a tamper-evident lineage of every consequential "
            "agent action (writes, shell) so a run's actions are auditable end-to-end.",
            default=False,
        ),
        "workforce_levels": _q_confirm(
            "Per-agent autonomy levels? Treat each agent like a hire with a level of "
            "authority you set -- observe / suggest / request-approval / autonomous, "
            "per action risk -- starting supervised (onboarding) and graduating on a "
            "clean record. Off by default, every agent stages actions for human "
            "execution. Per-agent overrides go under [workforce.agents].",
            default=False,
        ),
        "calibration_enforce": _q_confirm(
            "Calibration interlock? Freeze self-improvement (trajectory donation) "
            "if the verifier stops telling correct answers from incorrect ones on "
            "your labeled set, so the system never learns from a drifted evaluator.",
            default=False,
        ),
        "adaptive_compute": _q_confirm(
            "Adaptive test-time compute? Concentrate effort on uncertain sub-tasks "
            "and spend less when the swarm agrees (cheaper, focused).",
            default=False,
        ),
        "best_of_n": _q_confirm(
            "Best-of-N answers? Sample a few candidate answers and keep the one the "
            "verifier scores highest (stronger, more tokens).",
            default=False,
        ),
        "skill_synthesis": _q_confirm(
            "Test-time skill synthesis? Write a short task-specific cheat-sheet for "
            "each goal before working on it.",
            default=False,
        ),
        "experience_guidance": _q_confirm(
            "Experience-guided orchestration? Steer planning with how similar past "
            "goals turned out (what worked, what failed).",
            default=False,
        ),
        "credit_assignment": _q_confirm(
            "Counterfactual credit assignment? After a swarm answers, work out which "
            "sub-agent actually helped (ablate + re-verify) to improve learning and "
            "routing. Costs extra verifier calls per swarm.",
            default=False,
        ),
        "causal_promotion": _q_confirm(
            "Counterfactual promotion? When governed self-improvement is on, promote a "
            "learned change (tool/prompt/policy) only if its confounder-adjusted CAUSAL "
            "effect on outcomes clears the bar -- not just a correlation that co-occurred "
            "with success. Each promotion records the effect, its confidence interval, and "
            "what it adjusted for. Requires self-improvement enabled.",
            default=False,
        ),
        "rehearsal": _q_confirm(
            "Pre-execution rehearsal? Before a risky plan runs, simulate it against the "
            "learned world-model of your environment and gate on the prediction: proceed "
            "when the model is confident it's safe, BLOCK a confidently-poor outcome, and "
            "ESCALATE to a human when the model is unsure or has never seen the move. "
            "Governance that lets agents be bolder where it's earned; off by default.",
            default=False,
        ),
        "speculative": _q_confirm(
            "Speculative execution? On turns where the world-model is highly confident "
            "what comes next (a well-trodden, near-deterministic step), draft with a cheap "
            "model instead of the frontier one -- reserving the expensive model for novel "
            "or uncertain turns. Cuts cost/latency on repetitive workflows; off by default "
            "and a no-op until you set a draft model.",
            default=False,
        ),
        "data_engine": _q_confirm(
            "Cognitive Data Engine? The Tesla-style improvement flywheel: production "
            "failures are triaged by CAUSAL impact on real outcomes (fix what moves "
            "reality most, not what's merely frequent), then mined, validated in the "
            "world-model, and promoted through the safety ladder. The workforce compounds "
            "from its own experience; off by default.",
            default=False,
        ),
        "operations_scientist": _q_confirm(
            "Operations Scientist? An agent that DISCOVERS a better process and proves it: "
            "it pairs a harmful action with the beneficial habit that should replace it, "
            "validates the swap in the world-model, then runs a real causal experiment and "
            "ships the proven win. Discovery, not just labour; off by default.",
            default=False,
        ),
        "consequence": _q_confirm(
            "Consequence Engine? Ground the workforce's learning in REAL outcomes instead "
            "of a model's self-graded proxy: when a downstream result lands (an invoice "
            "paid, a ticket reopened), it overrides the proxy reward so the data engine "
            "learns from reality. Reality is the reward signal; off by default.",
            default=False,
        ),
        "emergent_protocol": _q_confirm(
            "Emergent coordination shorthand? Swarms evolve short codes for the boilerplate "
            "they repeat (cheaper coordination), while every code decodes EXACTLY back to "
            "English -- the auditable translation layer, so nothing is ever hidden from the "
            "Shield or a human. Off by default; a no-op until a codebook is learned.",
            default=False,
        ),
        "emergent_codec": _q_confirm(
            "Measure the token-aware codec on live coordination? The codec that saves "
            "actual frontier TOKENS (not just bytes), via byte-stuffed cheap codes. When "
            "on, the blackboard measures -- never changes -- what it would compress real "
            "traffic to, so you can confirm the savings before agents ever read codes. "
            "Off by default; pure telemetry, the audit/Shield path is untouched.",
            default=False,
        ),
        "enforce_capabilities": _q_confirm(
            "Enforce agent capabilities? Each agent runs under a scoped grant and "
            "spawned sub-agents can only narrow it, never exceed it (least privilege).",
            default=False,
        ),
        "per_call_token_exchange": _q_confirm(
            "Per-call token exchange? Each tool call trades the run-long grant for "
            "a freshly minted, single-tool, short-lived signed token (zero-trust; "
            "shrinks the blast radius of a mid-run compromise). Needs capability "
            "enforcement.",
            default=False,
        ),
        "enforce_quotas": _q_confirm(
            "Enforce per-principal usage quotas? Track spend (dollars + tokens) per "
            "user per day and refuse to start a new goal once the daily cap is hit "
            "(chargeback / cost governance across runs, beyond the per-run budget).",
            default=False,
        ),
        "tenant_by_user": _q_confirm(
            "Isolate each user into their own tenant? Per-user cross-session memory "
            "is kept separate — recommended for multi-user servers.",
            default=False,
        ),
        "client_id": _q_text(
            "Client/tenant id for THIS deployment (one Maverick per enterprise "
            "client). All data (world DB, audit, memory, fleet) is isolated under "
            "this id — leave blank only for a personal/single-user install. "
            "Letters/digits/._- e.g. \"acme-corp\".",
            default="",
        ),
        "enterprise": _q_confirm(
            "Enterprise mode (private/sensitive data)? Pin every LLM call to a "
            "local/self-hosted model so data never leaves your boundary, gate "
            "destructive actions, and enforce per-agent capabilities. Recommended "
            "when the agent handles PHI/PII/financial data.",
            default=False,
        ),
        "agent_trust": _q_confirm(
            "Govern which OUTSIDE agents your agents may talk to? Engages the Agent "
            "Trust Plane: external agents (federation peers, A2A callers, fleet "
            "agents) are default-DENIED unless listed in [agent_trust] agents with a "
            "pinned key, direction, and tool/budget/data ceiling. Auto-on under "
            "enterprise mode; recommended at the company boundary.",
            default=False,
        ),
        "anonymous_logs": _q_confirm(
            "Anonymous mode? Scrub user-identifying content (goal text, user/channel "
            "ids, home paths, emails/phones) from logs and audit events — hashes or "
            "sentinels instead of raw values. Good for shared/regulated environments.",
            default=False,
        ),
        "encrypt_at_rest": _q_confirm(
            "Encrypt sensitive local stores at rest? Seals the cross-session "
            "memory store with AES-256-GCM (key in ~/.maverick/keys, chmod 600). "
            "Implied by enterprise mode; recommended for PHI/PII/financial data.",
            default=False,
        ),
        "encrypt_per_tenant": _q_confirm(
            "Per-tenant encryption keys? Each tenant gets its own data key "
            "(wrapped by a KMS KEK) so one tenant's key never opens another's "
            "data — the posture a hosted multi-tenant store needs. Requires "
            "at-rest encryption; reads of existing data stay transparent. "
            "Off by default (single-tenant boxes don't need it).",
            default=False,
        ),
        "pg_rls": _q_confirm(
            "Database-enforced tenant isolation (Postgres Row-Level Security)? "
            "Only for the shared Postgres backend with MULTIPLE tenants: the DB "
            "itself rejects cross-tenant rows as defense-in-depth over the "
            "app-layer scoping. REQUIRES one-time prep first — assign legacy rows "
            "with `maverick tenant backfill --tenant <id>` and verify with "
            "`maverick tenant rls-preflight`, or pre-tenancy rows become invisible. "
            "Off by default; leave off for SQLite or single-tenant installs.",
            default=False,
        ),
        "audit_sign": _q_confirm(
            "Sign the audit log for tamper-evidence? Ed25519 hash-chains every "
            "audit row (plus a signed cross-file ledger) so `maverick audit verify` "
            "can prove the log was not altered — the basis for SOC 2 evidence. "
            "Needs the [audit-signing] extra; falls back to unsigned if absent.",
            default=False,
        ),
        "audit_worm": _q_confirm(
            "Export closed audit day-files to a write-once (WORM) store? Beyond "
            "tamper-EVIDENCE, this makes the historical log un-alterable: each "
            "closed day-file is shipped with a retention lock so it can't be "
            "rewritten or deleted (S3 Object-Lock for regulator-grade WORM, or a "
            "local read-only mirror). Run `maverick audit worm push` (e.g. nightly "
            "cron). Defaults to a local mirror; edit [audit.worm] for S3.",
            default=False,
        ),
        "saml": _q_confirm(
            "Enable SAML 2.0 SSO (alongside or instead of OIDC)? For enterprises "
            "whose IdP (Okta, Entra/Azure AD, ADFS) mandates SAML over OIDC. "
            "Writes a [auth.saml] template you fill in with your SP/IdP details, "
            "then hand /saml/metadata to the IdP. Needs the [saml] extra (pysaml2) "
            "and the browser-login session secret. Off by default.",
            default=False,
        ),
        "security_autofix": _q_confirm(
            "Let the security assessor auto-fix low-risk gaps? With enterprise mode "
            "on, `maverick remediate --apply` may auto-apply reversible, in-boundary "
            "config fixes (enable audit signing, set retention); anything "
            "behaviour-changing stays gated for a human. Off by default; every fix "
            "is audited and reversible.",
            default=False,
        ),
        "dual_approval": _q_confirm(
            "Require two-person approval for risky actions (N-of-M dual control)? "
            "A high/critical-risk action then needs 2 DISTINCT approvers in the "
            "dashboard queue, and the requester can't approve their own request — "
            "the segregation-of-duties control SOX / SOC 2 / HIPAA auditors test. "
            "Writes [security] approvals_required = 2. Off by default.",
            default=False,
        ),
        "deferred_tools": _q_confirm(
            "Deferred tool loading? Show the model a small core toolset plus a "
            "find_tools search tool, loading the long tail (80+ integrations, MCP) "
            "on demand. Big context savings when many tools are enabled.",
            default=False,
        ),
        "shield_updates": _q_confirm(
            "Pull signed shield-rule updates? Fetches a publisher-signed rules "
            "bundle ([shield] update_url + update_pubkey; Ed25519-verified, "
            "downgrades refused) and stages it for the shield. Off by default.",
            default=False,
        ),
        "ebpf_monitor": _q_confirm(
            "Enable the eBPF syscall monitor? An operator-run bpftrace "
            "supervisor tracing execve/connect/openat for the agent's PID tree "
            "(needs root + bpftrace at runtime). Off by default.",
            default=False,
        ),
        "local_runtime": _q_confirm(
            "Manage a local model server (vLLM / TGI / llama.cpp)? Writes "
            "[local_runtime] so `maverick local-runtime plan` composes the "
            "right batching / KV-cache / precision flags for your engine; "
            "configure the engine + model in config.toml after the wizard. "
            "Off by default.",
            default=False,
        ),
        "output_cache": _q_confirm(
            "Cache tool outputs? Memoize side-effect-free (read-only) tool calls "
            "within a run so a repeated read isn't re-done. Off by default.",
            default=False,
        ),
        "hardware_sensors": _q_confirm(
            "Enable host hardware sensors? Lets agents read this machine's "
            "temperatures, fans, and battery via the [sensors] extra. Off by "
            "default because it exposes host telemetry to tool calls.",
            default=False,
        ),
        "local_first": _q_confirm(
            "Local-first models? When a configured local model's server is "
            "reachable, prefer it over a remote provider (privacy + cost). Only "
            "applies when you haven't pinned a model. Off by default.",
            default=False,
        ),
        "energy_aware": _q_confirm(
            "Energy-aware routing? On a laptop, downgrade to a cheaper/faster "
            "model when the battery is low. Off by default.",
            default=False,
        ),
        "effort": _q_confirm(
            "Per-role reasoning effort? Keep the orchestrator/coder at high effort "
            "but run bulk roles (researcher/verifier/writer) at lower effort — the "
            "biggest cost/latency lever on Opus 4.7/4.8. Off by default.",
            default=False,
        ),
        "cache_prewarm": _q_confirm(
            "Pre-warm the prompt cache at start? A max_tokens=0 prefill writes the "
            "system+tools cache so the first turn doesn't pay the cold-write "
            "latency (best for interactive use). Off by default.",
            default=False,
        ),
        "hedge_requests": _q_confirm(
            "Hedge slow LLM requests? If a call hasn't returned within ~1.5s, fire "
            "a backup request and take whichever finishes first (tightens p99 on a "
            "provider with variable latency). Costs extra on slow calls. Off by "
            "default.",
            default=False,
        ),
    }
    # Federated insight exchange rides on dreaming: trusted peer keys are
    # only worth asking for when the loop that produces/consumes insights is
    # on. Imports are fail-closed without them.
    if advanced.get("dreaming") and _q_confirm(
        "  Exchange consolidated insights with trusted peer instances? "
        "(signed bundles via `maverick insights-export/-import`)",
        default=False,
    ):
        raw = _q_text(
            "  Trusted peer insight pubkeys (comma-separated hex Ed25519)",
            default="",
        )
        advanced["insight_pubkeys"] = [k.strip() for k in raw.split(",")
                                       if k.strip()]
    # Tax-constants content channel: law changes ship as SIGNED bundles
    # (fail-closed against the publisher keys), auto-applied by
    # `maverick tax prepare` / `maverick tax update`.
    if _q_confirm(
        "  Auto-update tax computation constants from a signed publisher "
        "channel? (new tax law as a content release, not a code release)",
        default=False,
    ):
        advanced["tax_update_url"] = _q_text(
            "  Constants update URL", default="").strip()
        raw = _q_text(
            "  Trusted publisher pubkeys (comma-separated hex Ed25519)",
            default="",
        )
        advanced["tax_pubkeys"] = [k.strip() for k in raw.split(",")
                                   if k.strip()]
    # OIDC SSO is a string-bearing toggle (issuer/audience/jwks_uri), so it has
    # its own prompt; the result is nested under the "oidc" key and the writer
    # emits a single [auth.oidc] table for it.
    advanced["oidc"] = pick_oidc()
    return advanced


def _docker_available() -> bool:
    """Return True iff the `docker` binary is on PATH AND the daemon
    responds. Used to pick a safe sandbox default in consumer mode and
    to choose the wizard's default in dev mode."""
    if not shutil.which("docker"):
        return False
    try:
        subprocess.run(
            ["docker", "version"],
            capture_output=True, timeout=2, check=True,
        )
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return False


# Container backends pick their image from the coding language (see
# sandbox._IMAGE_BY_LANGUAGE). local/ssh run model shell on the host toolchain
# and devcontainer reuses the user's own image, so the language hint only
# changes anything for these three.
_LANGUAGE_BACKENDS = {"docker", "gvisor", "podman", "kubernetes"}


def pick_sandbox() -> dict[str, Any]:
    # Security-first default: keep Docker selected by default regardless
    # of current daemon reachability to avoid silently falling back to
    # the least isolated local backend.
    docker_default = "docker - Throwaway Docker container (recommended)"
    pick = _q_select(
        "Sandbox backend (where the agent runs shell commands):",
        [
            "local  - Subprocess on this machine (fastest, least isolated)",
            "docker - Throwaway Docker container (recommended)",
            "gvisor - Docker + gVisor runsc kernel (strongest isolation)",
            "podman - Throwaway Podman container (rootless)",
            "devcontainer - Reuse a .devcontainer config",
            "kubernetes - Pod-per-command in a cluster (kubectl)",
            "ssh    - Remote machine",
        ],
        default=docker_default,
    )
    backend = pick.split()[0]
    workdir = _q_text("  Workspace directory", default=str(Path.home() / "maverick-workspace"))
    cfg: dict[str, Any] = {"backend": backend, "workdir": workdir, "timeout": 60}
    # Non-Python coders get a toolchain image that can actually run their tests
    # (cargo/go test, the JS runner, ...). Python is the default image, so we
    # only write [sandbox] language when it's something else -- existing and
    # Python configs stay byte-identical.
    if backend in _LANGUAGE_BACKENDS:
        languages = [
            "python     - python:3.12-slim (default)",
            "javascript - node:22 (JavaScript / TypeScript)",
            "go         - golang:1",
            "rust       - rust:1",
            "java       - eclipse-temurin:21 (Java / Kotlin)",
            "ruby       - ruby:3",
        ]
        lang = _q_select(
            "  What do you mostly code in? (sets the container's toolchain)",
            languages,
            default=languages[0],
        ).split()[0]
        if lang != "python":
            cfg["language"] = lang
    return cfg


# ---------- new wizard steps (council parity pass) ----------

def pick_web_search() -> tuple[bool, list[str]]:
    """Enable web search + pick a default backend. Returns (enabled, env_vars_needed)."""
    if not _q_confirm(
        "Enable web search? (Tavily / Brave / SerpAPI / DuckDuckGo)",
        default=True,
    ):
        return False, []
    pick = _q_select(
        "  Default backend:",
        [
            "tavily   - best quality, free tier ~1k/mo, BYOK",
            "brave    - generous free tier, BYOK",
            "serpapi  - paid, covers more engines",
            "ddg      - no key, rate-limited",
        ],
        default="tavily   - best quality, free tier ~1k/mo, BYOK",
    )
    backend = pick.split()[0]
    envs = {
        "tavily":  ["TAVILY_API_KEY"],
        "brave":   ["BRAVE_API_KEY"],
        "serpapi": ["SERPAPI_API_KEY"],
        "ddg":     [],
    }[backend]
    os.environ["MAVERICK_SEARCH_BACKEND"] = backend  # picked up by web_search tool
    return True, envs


def pick_mcp_servers() -> dict[str, dict[str, Any]]:
    """Configure MCP servers the agent will consume as tools.

    MCP servers expose their own tools (filesystem, GitHub, etc.) via a
    JSON-RPC protocol. The agent calls them as ``mcp_<name>__<tool>``.
    Skip if you don't know what MCP is.
    """
    if not _q_confirm(
        "Add MCP servers? (extensibility hook; skip if unsure)",
        default=False,
    ):
        return {}
    servers: dict[str, dict[str, Any]] = {}
    console.print(
        "[dim]Example: name 'filesystem', command 'npx', "
        "args '-y @modelcontextprotocol/server-filesystem /tmp'.[/dim]"
    )
    while True:
        name = _q_text("  Name (blank to finish)", default="").strip()
        if not name:
            break
        cmd = _q_text(f"  {name}: command", default="").strip()
        if not cmd:
            console.print("  [yellow]skipped (no command)[/yellow]")
            continue
        args_raw = _q_text(f"  {name}: args (space-separated)", default="").strip()
        args = args_raw.split() if args_raw else []
        servers[name] = {"command": cmd, "args": args}
        if not _q_confirm("  Add another?", default=False):
            break
    return servers


def pick_plugins() -> list[str]:
    """Allowlist for pip-installed plugin packages.

    Plugins are loaded only when listed in ``[plugins].enabled``. We
    scan installed entry-points and offer a checkbox; if nothing is
    installed, the step is a no-op.
    """
    discovered: set[str] = set()
    try:
        from maverick.plugins import _entry_points  # type: ignore[attr-defined]
        for group in (
            "maverick.tools",
            "maverick.channels",
            "maverick.skills",
            "maverick.personas",
        ):
            for ep in _entry_points(group):
                discovered.add(ep.name)
    except Exception as e:
        console.print(
            f"[yellow]Plugin discovery skipped: {e}[/yellow] "
            "(no plugins will be offered; re-run the wizard to retry)"
        )
        return []
    if not discovered:
        return []
    console.print()
    console.print(
        "[bold]Plugins discovered via entry_points:[/bold] "
        + ", ".join(sorted(discovered))
    )
    if not _q_confirm(
        "Enable any of these? (allow-listed for security; skip is safe)",
        default=False,
    ):
        return []
    return _q_checkbox("Enable plugins:", sorted(discovered))


def pick_ts_plugins() -> list[list[str]]:
    """TypeScript (NDJSON stdio) plugin commands — writes ``[plugins].ts``.

    Each entry is the argv that serves the plugin (e.g.
    ``node /path/to/plugin.js``); Maverick discovers its tools via
    ``--describe`` at boot. Skipped by default — most setups have none.
    """
    if not _q_confirm(
        "Add any TypeScript plugins? (commands like: node /path/plugin.js)",
        default=False,
    ):
        return []
    commands: list[list[str]] = []
    while True:
        raw = _q_text("  Plugin command (blank to finish)", default="")
        if not raw.strip():
            break
        commands.append(raw.split())
    return commands


def pick_plugin_permissions() -> tuple[list[str], bool]:
    """Grants + enforcement for enabled plugins (writes ``[plugins].grant`` /
    ``enforce_permissions``).

    A plugin declares the permissions it needs (network / fs_write / subprocess)
    in its manifest. By default an ungranted request is loaded with a warning;
    granting here silences it, and enforcing *skips* a plugin that requests
    something ungranted. Returns ``(grant, enforce)``; only asked when at least
    one plugin is enabled.
    """
    grant = _q_checkbox(
        "Permissions enabled plugins may use "
        "(ungranted requests warn, or are skipped if you enforce next):",
        ["network", "fs_write", "subprocess"],
        default=[],
    )
    enforce = _q_confirm(
        "Skip plugins that request a permission you didn't grant? "
        "(recommended; off = load with a warning)",
        default=False,
    )
    return grant, enforce


def pick_tool_acl(channels: dict[str, Any]) -> dict[str, Any]:
    """Optional per-tool / per-channel allow/deny lists.

    Common pattern: a Telegram channel may chat but shouldn't run
    shell. Power users only; defaults to no restriction.
    """
    if not _q_confirm(
        "Restrict tools the agent may run? (skip for full access)",
        default=False,
    ):
        return {}
    acl: dict[str, Any] = {}
    common = ["shell", "write_file", "computer", "browser", "http_fetch", "apply_patch"]
    denied = _q_checkbox(
        "Deny these tools globally (rare; usually empty):",
        common,
        default=[],
    )
    if denied:
        acl["denied_tools"] = denied
    for ch_id in channels:
        if not _q_confirm(f"  Restrict tools available over {ch_id}?", default=False):
            continue
        ch_denied = _q_checkbox(
            f"    Deny over {ch_id}:",
            common,
            default=["shell", "computer"],
        )
        acl.setdefault("channels", {})[ch_id] = {"denied_tools": ch_denied}
    return acl


def pick_rate_limits(channels: dict[str, Any]) -> dict[str, str]:
    """Per-tool sliding-window rate caps."""
    default = bool(channels)  # default ON when exposing via channels
    if not _q_confirm(
        "Cap call rate per tool? (recommended when exposing via channels)",
        default=default,
    ):
        return {}
    limits: dict[str, str] = {}
    proposed = [
        ("web_search", "10/60"),
        ("http_fetch", "30/60"),
        ("shell",      "30/60"),
        ("mcp_*",      "60/60"),
    ]
    for name, spec_default in proposed:
        spec = _q_text(
            f"  {name} (N/seconds, blank to skip)",
            default=spec_default,
        ).strip()
        if spec:
            limits[name] = spec
    return limits


def pick_retention() -> dict[str, int]:
    """Auto-prune audit logs and world-model rows."""
    if not _q_confirm(
        "Auto-prune audit logs + old episodes after N days?",
        default=True,
    ):
        return {}
    return {
        "audit_days":    _safe_int(_q_text("  Audit log retention days",   default="90"),  default=90),
        "episodes_days": _safe_int(_q_text("  Episode retention days",     default="365"), default=365),
        "events_days":   _safe_int(_q_text("  Goal-event retention days",  default="180"), default=180),
    }


def pick_analytics() -> dict[str, Any]:
    """Consent step for MCP-client language analytics. OFF by default.

    When granted, the MCP server tallies a coarse language bucket from each
    client's User-Agent (typescript / go / rust / c# / java / python) into a
    local counts file — no request content, no identifiers, nothing leaves
    the machine. The tally feeds the Q1-2027 language-bindings gate
    (``maverick.mcp_analytics.non_python_share()``). Returns a dict written
    under ``[analytics]``.
    """
    console.print()
    console.print(
        "[dim]Optional: count which languages drive this agent over MCP "
        "(a coarse bucket from each client's User-Agent). Counts stay in a "
        "local file — no request content, no identifiers, nothing is "
        "uploaded. The tally feeds the decision on funding native client "
        "libraries; OFF by default.[/dim]"
    )
    if not _q_confirm("Count MCP client languages locally?", default=False):
        return {}
    return {"mcp_client_language": True}


def pick_persona() -> dict[str, str]:
    """Agent identity: name + voice."""
    if not _q_confirm(
        "Customise the agent's name and style? (skip for defaults)",
        default=False,
    ):
        return {}
    name = _q_text("  Agent name", default="Maverick").strip() or "Maverick"
    style_pick = _q_select(
        "  Style:",
        [
            "concise   - terse, direct",
            "balanced  - default",
            "verbose   - explains its reasoning",
        ],
        default="balanced  - default",
    )
    return {"name": name, "style": style_pick.split()[0]}


def pick_notifications() -> tuple[dict[str, Any], list[str]]:
    """Run-end notification webhook. Returns (config, env_vars_needed)."""
    if not _q_confirm(
        "Get pinged when long runs finish? (ntfy / Pushover / Slack / Discord)",
        default=False,
    ):
        return {}, []
    pick = _q_select(
        "  Backend:",
        [
            "ntfy      - free, no signup, push to phone via ntfy.sh",
            "pushover  - one-time $5, phone push",
            "slack     - incoming webhook",
            "discord   - webhook URL",
        ],
        default="ntfy      - free, no signup, push to phone via ntfy.sh",
    )
    backend = pick.split()[0]
    if backend == "ntfy":
        topic = _q_text(
            "  ntfy topic (any unique string; treat as a password)",
            default="",
        ).strip()
        return ({"backend": "ntfy", "topic": topic}, []) if topic else ({}, [])
    if backend == "pushover":
        return (
            {"backend": "pushover",
             "user_key": "${PUSHOVER_USER_KEY}",
             "app_token": "${PUSHOVER_APP_TOKEN}"},
            ["PUSHOVER_USER_KEY", "PUSHOVER_APP_TOKEN"],
        )
    if backend == "slack":
        return (
            {"backend": "slack", "webhook_url": "${SLACK_NOTIFY_WEBHOOK}"},
            ["SLACK_NOTIFY_WEBHOOK"],
        )
    if backend == "discord":
        return (
            {"backend": "discord", "webhook_url": "${DISCORD_NOTIFY_WEBHOOK}"},
            ["DISCORD_NOTIFY_WEBHOOK"],
        )
    return {}, []


def pick_webhooks() -> tuple[dict[str, Any], list[str]]:
    """Outbound run-lifecycle webhooks. Returns (config, env_vars_needed).

    Distinct from pick_notifications (a single run-end ping): these are
    signed POSTs fired on every lifecycle event (goal_created,
    goal_finished, episode_finished, final_emitted) to one or more
    endpoints, for integrations (Zapier, custom receivers, dashboards).
    """
    if not _q_confirm(
        "POST run events to your own endpoint(s)? (signed lifecycle webhooks)",
        default=False,
    ):
        return {}, []
    raw = _q_text(
        "  Endpoint URL(s), comma-separated",
        default="",
    ).strip()
    urls = _csv_list(raw)
    if not urls:
        return {}, []
    cfg: dict[str, Any] = {"outbound": urls}
    envs: list[str] = []
    if _q_confirm("  Sign payloads with an HMAC secret?", default=True):
        cfg["secret"] = "${MAVERICK_WEBHOOK_SECRET}"
        envs.append("MAVERICK_WEBHOOK_SECRET")
    return cfg, envs


def pick_deliverable_handoff() -> tuple[dict[str, Any], list[str]]:
    """System-of-record hand-off for APPROVED deliverables. Returns
    (config, env_vars_needed).

    Distinct from lifecycle webhooks: this fires only when a human signs off a
    gated deliverable (a forecast, a CECL memo), POSTing it to a downstream
    system (treasury / GL / Jira) so an approved result lands there instead of
    being re-keyed by hand. Signed with the same [webhooks] HMAC secret."""
    if not _q_confirm(
        "POST approved deliverables to a system-of-record endpoint?",
        default=False,
    ):
        return {}, []
    url = _q_text("  System-of-record endpoint URL", default="").strip()
    if not url:
        return {}, []
    return {"handoff_webhook": url}, []


def pick_persona_roles() -> dict[str, Any]:
    """Bind the operator to persona consumer role(s) for the deliverables inbox.

    Sets ``[personas] default`` so the signed-in user lands on their own
    deliverables ("my forecasts") instead of the full list. Per-user mappings
    (``[personas]`` keyed by principal) are added later like RBAC roles; this is
    the single-user default."""
    if not _q_confirm(
        "Default the deliverables inbox to your own role(s)?",
        default=False,
    ):
        return {}
    raw = _q_text(
        "  Your primary role(s) (e.g. fpa_analyst, controller; space/comma separated)",
        default="",
    ).strip()
    roles = [r.strip() for r in raw.replace(",", " ").split() if r.strip()]
    return {"default": roles} if roles else {}


def pick_connectors() -> dict[str, str]:
    """Collect credentials for enterprise connectors (ServiceNow, Salesforce,
    Snowflake, SAP, ...).

    Connectors are always registered in the kernel; they only need their
    BASE_URL/TOKEN env vars set to work. Returns ``{ENV_NAME: value}`` for the
    systems the user chose to connect now, merged into ~/.maverick/.env. The
    catalog (and ``docs/connectors.md``) come from ``connector_catalog()`` in
    maverick-core, so this stays in sync as connectors are added. Secrets
    collected here are never persisted to the partial-state file.
    """
    try:
        from maverick.tools.enterprise_connectors import connector_catalog
        entries = connector_catalog()
    except Exception as e:  # maverick-core not importable / catalog moved
        console.print(f"[yellow]Connector catalog unavailable: {e}[/yellow]")
        return {}
    if not entries:
        return {}
    console.print()
    console.print(
        f"[dim]Maverick ships {len(entries)} enterprise connectors "
        "(ServiceNow, Salesforce, Snowflake, SAP, Workday, Datadog, ...). "
        "Full list: docs/connectors.md. Connect any now, or add them later in "
        "~/.maverick/.env.[/dim]"
    )
    if not _q_confirm("Connect any enterprise systems now?", default=False):
        return {}
    by_name = {e["name"]: e for e in entries}
    raw = _q_text(
        "  Which systems? (comma-separated names, e.g. servicenow, snowflake)",
        default="",
    )
    picked = _csv_list(raw, lower=True)
    keys: dict[str, str] = {}
    for name in dict.fromkeys(picked):  # dedupe, preserve order
        entry = by_name.get(name)
        if entry is None:
            console.print(
                f"  [yellow]unknown connector '{name}' — skipped "
                "(see docs/connectors.md for valid names)[/yellow]"
            )
            continue
        console.print(f"  [bold]{entry['label']}[/bold]")
        for env_name, is_secret in entry["env"]:
            current = os.environ.get(env_name, "")
            if is_secret:
                masked = (current[:4] + "...") if current else "(none)"
                val = _q_secret(
                    f"    {env_name} [current: {masked}] (blank = keep current)"
                )
                if not val and current:
                    val = current
            else:
                val = _q_text(f"    {env_name}", default=current)
            if val:
                keys[env_name] = val
    return keys


def collect_api_keys(providers: list[str], channel_envs: set[str]) -> dict[str, str]:
    keys: dict[str, str] = {}
    needed: list[str] = []

    for prov in providers:
        info = catalog.PROVIDERS.get(prov, {})
        env_name = info.get("env")
        if env_name:
            needed.append(env_name)
        needed.extend(info.get("env_vars", []))

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

        # Validate when we know how, with a 7-day cache so re-runs of
        # the wizard don't burn an API round-trip on every key.
        validator = _VALIDATORS.get(env_name)
        if validator:
            cached = _cached_validation(env_name, val)
            if cached is not None:
                ok, msg = cached
                marker = "[green]ok[/green]" if ok else "[red]x[/red]"
                console.print(f"    {marker} {msg} (cached)")
            else:
                ok, msg = validator(val)
                marker = "[green]ok[/green]" if ok else "[red]x[/red]"
                console.print(f"    {marker} {msg}")
                _remember_validation(env_name, val, ok, msg)
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
        from maverick.session_providers import cookie_store
        from maverick.session_providers.browser_capture import auto_capture
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

def _toml_str(v: Any) -> str:
    """Render a value as a TOML basic string with proper escaping.

    Windows paths (e.g. a sandbox workdir ``C:\\Users\\x\\ws``) contain
    backslashes; emitted raw into a ``"..."`` basic string, ``\\U`` is parsed
    as a unicode escape and the config.toml the wizard just wrote can't be read
    back (``TOMLDecodeError: Invalid hex value``). Escape backslashes and
    double-quotes so the round-trip holds on every platform.
    """
    s = str(v).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{s}"'


def _emit_kv(lines: list[str], k: str, v: Any) -> None:
    """Append one TOML key=value line, type-dispatched."""
    if isinstance(v, bool):
        lines.append(f"{k} = {str(v).lower()}")
    elif isinstance(v, (int, float)):
        lines.append(f"{k} = {v}")
    elif isinstance(v, list):
        rendered = ", ".join(_toml_str(x) for x in v)
        lines.append(f"{k} = [{rendered}]")
    else:
        lines.append(f"{k} = {_toml_str(v)}")


def pick_a2a() -> tuple[dict[str, Any], list[str]]:
    """Expose Maverick to other agents over A2A. Returns (config, envs).

    Off by default: A2A is an outward-facing surface (other agents can
    discover this instance and delegate budget-spending goals to it). When
    enabled we require a bearer token (MAVERICK_A2A_TOKEN) so the task
    endpoint isn't open; the agent card + task endpoint mount on the
    dashboard at /a2a/v1.
    """
    if not _q_confirm(
        "Expose this agent over A2A so other agents can delegate goals to it?",
        default=False,
    ):
        return {}, []
    console.print(
        "  [dim]A2A serves an agent card at /.well-known/agent-card.json and a "
        "task endpoint at /a2a/v1 (on `maverick dashboard`). Budget is clamped "
        "to operator caps; a bearer token is required. A2A goals run under a "
        "tool ceiling (max_risk=medium by default -- edit [a2a].max_risk to "
        "tighten to \"low\" or open to \"high\"/\"none\").[/dim]"
    )
    return {"enabled": True, "max_risk": "medium"}, ["MAVERICK_A2A_TOKEN"]


# Business-function agent suites the factory can spawn from (domain packs under
# maverick/domains/). The kernel's enabled_domains() honors the [suites] table
# this writes; suites are ON by default (opt-out), so writing nothing keeps all.
AGENT_SUITES: list[tuple[str, str]] = [
    ("operations", "Operations / Supply Chain"),
    ("legal", "Legal (General Counsel)"),
    ("finance", "Finance"),
    ("it_grc", "IT / GRC / Security / Privacy / AI-Governance"),
    ("sales_gtm", "Sales / GTM"),
    ("hr", "HR / People"),
    ("product_engineering", "Product & Engineering"),
    ("strategy", "Strategy / Corp Dev / Exec"),
    ("customer_experience", "Customer Experience / Support"),
    ("marketing", "Marketing / Communications"),
    ("procurement", "Procurement / Sourcing"),
    ("data_analytics", "Data & Analytics"),
    ("security_ops", "Security Operations"),
    ("executive_office", "Executive Office / Chief of Staff"),
    ("facilities_ehs", "Facilities / EHS"),
    ("healthcare", "Healthcare (RCM / Payer Ops)"),
    ("insurance", "Insurance (Claims / Underwriting Support)"),
    ("banking", "Banking / Credit Union Ops"),
    ("retail", "Retail / E-commerce"),
    ("manufacturing_vertical", "Manufacturing (Vertical)"),
    ("construction", "Construction / AEC"),
    ("logistics", "Logistics / Transportation"),
    ("professional_services", "Professional Services"),
    ("government_contracting", "Government Contracting"),
    ("education_nonprofit", "Education / Nonprofit"),
    ("tax", "Tax Preparation (CPA Firms)"),
    # Council-expansion verticals (2026).
    ("utilities", "Energy / Utilities"),
    ("real_estate", "Real Estate / Property Management"),
    ("pharma_lifesciences", "Pharma / Life Sciences"),
    ("telecom_media", "Telecom / Media & Entertainment"),
    ("hospitality", "Hospitality / Travel"),
    ("capital_markets", "Capital Markets / Asset Management"),
    # New industry suites (2026 build-out).
    ("oil_gas", "Oil & Gas / Energy (Upstream-Downstream)"),
    ("automotive", "Automotive (OEM / Dealership / Mobility)"),
    ("public_sector", "Public Sector (State & Local Government Operations)"),
    ("agriculture", "Agriculture / Agribusiness"),
    ("aerospace_defense", "Aerospace & Defense"),
    ("maritime", "Maritime / Shipping & Ports"),
    ("travel_aviation", "Travel / Airlines & Aviation"),
    ("mining_metals", "Mining & Metals"),
    ("crypto_digital_assets", "Crypto & Digital Assets"),
    ("chemicals", "Chemicals (Bulk / Specialty / Petrochemical)"),
    ("food_beverage_cpg", "Food, Beverage & CPG"),
    ("medical_devices", "Medical Devices & Diagnostics"),
    ("private_equity_vc", "Private Equity & Venture Capital"),
    ("water_utilities", "Water & Wastewater Utilities"),
    ("renewables_cleantech", "Renewables & Clean Energy"),
    ("semiconductors", "Semiconductors & Electronics"),
]


def pick_suites() -> dict[str, bool]:
    """Which business-function agent suites to enable. All on unless customized.

    Returns a ``suite -> bool`` map for the ``[suites]`` config table (empty when
    the operator keeps the default, so the kernel enables every suite)."""
    console.print()
    console.print("[bold]Agent suites[/bold] — the business functions the agent "
                  "factory can spawn (finance, operations, legal, ...).")
    console.print("[dim]All enabled by default. A disabled suite's agents can't be "
                  "spawned. Editable later in ~/.maverick/config.toml under "
                  "[suites].[/dim]")
    if not _q_confirm("  Customize which suites are enabled? (No = keep all on)",
                      default=False):
        return {}
    out: dict[str, bool] = {}
    for key, label in AGENT_SUITES:
        out[key] = _q_confirm(f"    Enable the {label} suite?", default=True)
    return out


def _cfg_deployment(deployment: str | None) -> list[str]:
    if not deployment:
        return []
    # Record the chosen deployment topology (laptop / vps / ...) for
    # provenance + so a later `maverick init` can default to it.
    return [
        "[deployment]",
        f"type = {_toml_str(str(deployment))}",
        "",
    ]


def _cfg_providers(providers: list[str]) -> list[str]:
    lines: list[str] = []
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
        if prov == "openai_compatible":
            lines.append('base_url = "${OPENAI_COMPATIBLE_BASE_URL}"')
        lines.append("")
    return lines


def _cfg_role_models(role_models: dict[str, str]) -> list[str]:
    if not role_models:
        return []
    lines = ["[models]"]
    for role, spec in role_models.items():
        lines.append(f'{role} = "{spec}"')
    lines.append("")
    return lines


def _cfg_channels(channels: dict[str, dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for ch_id, cfg in channels.items():
        lines.append(f"[channels.{ch_id}]")
        for k, v in cfg.items():
            # _emit_kv handles lists (e.g. the allowed_user_ids array) and
            # escapes string values; the old inline branch emitted a list as
            # a quoted string and didn't escape backslash paths.
            _emit_kv(lines, k, v)
        lines.append("")
    return lines


def _cfg_core(
    budget: dict[str, float],
    safety: dict[str, Any],
    sandbox: dict[str, Any],
) -> list[str]:
    lines = ["[budget]"]
    for k, v in budget.items():
        _emit_kv(lines, k, v)
    lines.append("")
    lines.append("[safety]")
    for k, v in safety.items():
        _emit_kv(lines, k, v)
    lines.append("")
    lines.append("[sandbox]")
    for k, v in sandbox.items():
        _emit_kv(lines, k, v)
    return lines


def _cfg_skills(skills: dict[str, Any] | None) -> list[str]:
    if not skills:
        return []
    # Signed-skill policy. trusted_pubkeys = hex Ed25519 publisher keys
    # a signed SKILL.md must match; require_signed rejects unsigned ones.
    lines = ["", "[skills]"]
    for k, v in skills.items():
        _emit_kv(lines, k, v)
    return lines


def _cfg_self_learning(self_learning: dict[str, Any] | None) -> list[str]:
    if not self_learning:
        return []
    # Self-learning. enable gates the whole feature; sub-toggles let the
    # agent install skills, add MCP servers, and generate+run new tools.
    lines = ["", "[self_learning]"]
    for k, v in self_learning.items():
        _emit_kv(lines, k, v)
    return lines


def _cfg_automation_import(automation_import: dict[str, Any] | None) -> list[str]:
    if not automation_import:
        return []
    # Automation import. enable gates the whole feature; create_schedules lets a
    # recovered cron trigger auto-create a Lightwork schedule on import.
    lines = ["", "[automation_import]"]
    for k, v in automation_import.items():
        _emit_kv(lines, k, v)
    return lines


def _cfg_oauth(oauth: dict[str, Any] | None) -> list[str]:
    if not (oauth and oauth.get("vault")):
        return []
    # Seal captured OAuth tokens in the per-tenant vault (encrypted at rest).
    return ["", "[oauth]", "vault = true"]


def _cfg_governed_connectors(governed_connectors: dict[str, Any] | None) -> list[str]:
    if not (governed_connectors and governed_connectors.get("enable")):
        return []
    # Governed system-of-record connectors. enable turns on the governed write
    # path; connectors selects which reference REST connectors to register.
    lines = ["", "[governed_connectors]"]
    for k, v in governed_connectors.items():
        _emit_kv(lines, k, v)
    return lines


def _cfg_durable(durable: dict[str, Any] | None) -> list[str]:
    if not (durable and durable.get("enabled")):
        return []
    # Durable execution: checkpoint loop state so `maverick resume`
    # continues from the last step after a crash. Off unless opted in.
    lines = ["", "[durable]"]
    for k, v in durable.items():
        _emit_kv(lines, k, v)
    return lines


def _cfg_finance(finance: dict[str, Any] | None) -> list[str]:
    if not finance:
        return []
    # Finance suite governance (finance-agent-suite): pause money movement for
    # a human, enforce compliance regimes (strictest-wins), and screen
    # sanctions. The [governance] scalar key precedes its sub-tables (TOML).
    lines = ["", "[governance]", 'require_human_min_risk = "high"']
    if finance.get("require_fresh_human_approval"):
        # A prior persistent consent grant won't satisfy the Art-14 gate --
        # each paused action needs a fresh human decision.
        lines.append("require_fresh_human_approval = true")
    rha = finance.get("require_human_above") or 0
    if rha and rha > 0:
        lines.append("")
        lines.append("[governance.require_human_above]")
        lines.append(f'"*" = {rha}')
    da = finance.get("deny_above") or 0
    if da and da > 0:
        lines.append("")
        lines.append("[governance.deny_above]")
        lines.append(f'"*" = {da}')
    regimes = finance.get("regimes") or []
    if regimes:
        lines.append("")
        lines.append("[finance]")
        _emit_kv(lines, "regimes", regimes)
    sdn = (finance.get("sdn_path") or "").strip()
    if sdn:
        lines.append("")
        lines.append("[screening]")
        _emit_kv(lines, "sdn_path", sdn)
    return lines


def _cfg_capabilities(
    capability_config: dict[str, Any],
    embedded_flash: bool,
) -> list[str]:
    lines: list[str] = []
    if capability_config:
        lines.append("")
        lines.append("[capabilities]")
        for k, v in capability_config.items():
            lines.append(f"{k} = {str(v).lower()}")
    if embedded_flash:
        lines.append("")
        lines.append("[embedded]")
        lines.append("allow_flash = true")
    return lines


def _cfg_suites(suites: dict[str, bool] | None) -> list[str]:
    if not suites:
        return []
    # Per-suite enable/disable; the kernel's enabled_domains() reads this.
    lines = ["", "[suites]"]
    for k, v in suites.items():
        lines.append(f"{k} = {str(v).lower()}")
    return lines


def _cfg_advanced(  # noqa: C901 - flat sequence of independent opt-in toggles
    advanced: dict[str, Any] | None,
    providers: list[str],
) -> list[str]:
    if not advanced:
        return []
    lines: list[str] = []
    # Advanced reasoning toggles -> the kernel's config sections. Each is
    # off unless the wizard wrote it, matching the modules' own defaults.
    if (advanced.get("cost_aware") or advanced.get("verify_ensemble")
            or advanced.get("energy_aware")
            or advanced.get("autonomy_gate")):
        lines.append("")
        lines.append("[routing]")
        # Constrain routing features enabled by the wizard to the providers
        # the user selected in this run. Some router/verifier fallbacks also
        # know about API keys from the shell environment; the allowlist keeps
        # advanced opt-ins from sending prompts to those unselected providers.
        _emit_kv(lines, "allowed_providers", providers)
        if advanced.get("cost_aware"):
            lines.append("cost_aware = true")
        if advanced.get("verify_ensemble"):
            lines.append("verify_ensemble = true")
        if advanced.get("energy_aware"):
            lines.append("energy_aware = true")
    if advanced.get("risk_proportional_verify"):
        lines.append("")
        lines.append("[verification]")
        lines.append("risk_proportional = true")
    if advanced.get("autonomy_gate") or advanced.get("headless_assume"):
        lines.append("")
        lines.append("[autonomy]")
        if advanced.get("autonomy_gate"):
            lines.append("enable = true")
        # Independent axis: assume-and-proceed instead of blocking on ask_user.
        if advanced.get("headless_assume"):
            lines.append("headless_assume = true")
    if advanced.get("governed_actions"):
        lines.append("")
        lines.append("[actions]")
        lines.append("enable = true")
    if advanced.get("workforce_levels"):
        lines.append("")
        lines.append("[workforce]")
        lines.append("levels = true")
    if advanced.get("calibration_enforce"):
        lines.append("")
        lines.append("[calibration]")
        lines.append("enforce = true")
    if advanced.get("adaptive_compute"):
        lines.append("")
        lines.append("[adaptive_compute]")
        lines.append("enable = true")
    if advanced.get("best_of_n"):
        lines.append("")
        lines.append("[search]")
        lines.append("enable = true")
    if advanced.get("skill_synthesis"):
        lines.append("")
        lines.append("[skill_synthesis]")
        lines.append("enable = true")
    if advanced.get("experience_guidance"):
        lines.append("")
        lines.append("[experience]")
        lines.append("enable = true")
    if advanced.get("credit_assignment"):
        lines.append("")
        lines.append("[credit]")
        lines.append("enable = true")
    if advanced.get("causal_promotion"):
        lines.append("")
        lines.append("[self_improvement]")
        lines.append("# Promote learned changes on their confounder-adjusted causal")
        lines.append("# effect (maverick.promotion_effect), not a correlation. Applies")
        lines.append("# when self-improvement is enabled.")
        lines.append("causal_promotion = true")
    if advanced.get("rehearsal"):
        lines.append("")
        lines.append("[rehearsal]")
        lines.append("# Simulate a risky plan against the learned world-model before it")
        lines.append("# runs; proceed when confidently safe, block a poor outcome, escalate")
        lines.append("# the unknown (maverick.rehearsal). Fail-open while disabled.")
        lines.append("enable = true")
    if advanced.get("speculative"):
        lines.append("")
        lines.append("[speculative]")
        lines.append("# Draft a confidently-predictable turn with a cheap model, keeping the")
        lines.append("# frontier model for novel/uncertain turns (maverick.speculative_exec).")
        lines.append("# Set draft_model to a cheap spec to activate; a no-op until you do.")
        lines.append("enable = true")
        lines.append('# draft_model = "anthropic:claude-haiku-4-5-20251001"')
    if advanced.get("data_engine"):
        lines.append("")
        lines.append("[data_engine]")
        lines.append("# Triage production failures by causal impact on real outcomes, then")
        lines.append("# mine + validate + promote fixes (maverick.data_engine). The Tesla")
        lines.append("# data-engine flywheel for the workforce; reads the trajectory store.")
        lines.append("enable = true")
    if advanced.get("operations_scientist"):
        lines.append("")
        lines.append("[operations_scientist]")
        lines.append("# Discover a better process and prove it: pair a harmful action with")
        lines.append("# the beneficial habit that should replace it, validate the swap in the")
        lines.append("# world-model, then experiment for real (maverick.operations_scientist).")
        lines.append("enable = true")
    if advanced.get("consequence"):
        lines.append("")
        lines.append("[consequence]")
        lines.append("# Ground learning in REAL downstream outcomes: a recorded consequence")
        lines.append("# (invoice paid, ticket reopened) overrides the model's self-graded")
        lines.append("# proxy reward, so the data engine learns from reality (maverick.consequence).")
        lines.append("enable = true")
    if advanced.get("emergent_protocol"):
        lines.append("")
        lines.append("[emergent_protocol]")
        lines.append("# Learn short codes for the swarm's repeated coordination boilerplate;")
        lines.append("# every code decodes exactly back to English, so nothing is hidden from")
        lines.append("# the Shield/audit (maverick.emergent_protocol). No-op until learned.")
        lines.append("enable = true")
    if advanced.get("emergent_codec"):
        lines.append("")
        lines.append("[emergent_codec]")
        lines.append("# Measure the token-aware codec (maverick.emergent_tokens) on the live")
        lines.append("# coordination stream: byte-stuffed cheap codes that save real tokens.")
        lines.append("# Telemetry only -- the rendered text agents/Shield see is unchanged.")
        lines.append("enable = true")
    if advanced.get("enforce_quotas"):
        lines.append("")
        lines.append("[quotas]")
        lines.append("enforce = true")
        # Starter daily caps per principal; edit or set to 0 to disable a
        # dimension. The kernel also reads MAVERICK_QUOTA_* env overrides.
        lines.append("max_dollars_per_day = 25.0")
        lines.append("max_tokens_per_day = 5000000")
    if advanced.get("tenant_by_user"):
        lines.append("")
        lines.append("[tenancy]")
        lines.append("by_user = true")
    _client_id = str(advanced.get("client_id") or "").strip()
    if _client_id:
        lines.append("")
        lines.append("[client]")
        lines.append(f'id = "{_client_id}"')
        # Enforced: refuse to start unbound so this client's data can never land
        # in the shared root. Also set MAVERICK_CLIENT_ID in the service unit.
        lines.append("enforce = true")
    if advanced.get("enterprise"):
        lines.append("")
        lines.append("[enterprise]")
        lines.append("mode = true")
    if advanced.get("agent_trust"):
        lines.append("")
        lines.append("[agent_trust]")
        lines.append("enforce = true")
        # require_signed: refuse a federation peer that authenticates with only a
        # shared token (no pinned-key signature). Peers WITH a pinned key are
        # always signature-verified regardless of this flag.
        lines.append("require_signed = false")
        # Default-deny: external agents must be listed here, by pinned Ed25519
        # public key (lowercase id, e.g. "vega"), with the direction and ceiling
        # they're trusted within. Swap pubkeys out of band
        # (data_dir('audit','keys')/<key_id>.pub). expires_at/not_before (epoch
        # seconds) and revoked support key rotation/revocation.
        lines.append("# agents = [")
        lines.append('#   { id = "vega", pubkey = "<64-hex Ed25519>", '
                     'direction = "both", allow_tools = ["read_file", '
                     '"http_fetch"], max_risk = "medium", max_dollars = 2.0, '
                     'max_wall_seconds = 600, data_scopes = ["support"] },')
        lines.append("# ]")
    if advanced.get("anonymous_logs"):
        lines.append("")
        lines.append("[privacy]")
        lines.append("anonymous = true")
    if advanced.get("encrypt_at_rest"):
        lines.append("")
        lines.append("[encryption]")
        lines.append("at_rest = true")
        if advanced.get("encrypt_per_tenant"):
            lines.append("per_tenant = true")
    if advanced.get("pg_rls"):
        lines.append("")
        lines.append("[world_model]")
        # Database-enforced tenant isolation (Postgres backend only; ignored on
        # SQLite). The policy is strict, fail-closed equality, so prep BEFORE the
        # first start or pre-tenancy (NULL-tenant) rows become invisible:
        #   maverick tenant rls-preflight         # ownership + legacy-row check
        #   maverick tenant backfill --tenant ID  # assign pre-tenancy NULL rows
        lines.append("# Run `maverick tenant rls-preflight` + `maverick tenant "
                     "backfill` before first start (see docs/multi-tenancy.md).")
        lines.append("rls = true")
    if advanced.get("audit_sign"):
        lines.append("")
        lines.append("[audit]")
        lines.append("sign = true")
    if advanced.get("audit_worm"):
        lines.append("")
        # WORM export of closed audit day-files. Defaults to a local read-only
        # mirror (best-effort, tamper-evident); switch provider to "s3" + an
        # Object-Lock bucket for regulator-grade immutability. Ship with
        # `maverick audit worm push` (see docs/security-hardening.md).
        lines.append("[audit.worm]")
        lines.append('provider = "local"   # or "s3" for S3 Object-Lock')
        lines.append("retention_days = 2555   # lock duration (~7y)")
        lines.append('# bucket = "my-audit-worm"   # s3: Object-Lock + versioning enabled')
        lines.append('# prefix = "maverick/audit/"')
        lines.append('# mode = "COMPLIANCE"        # COMPLIANCE | GOVERNANCE')
        lines.append('# region = "us-east-1"')
    # Dashboard editing locks. Both default on, so we only emit the disables --
    # and as ONE [features] table (two tables would be a duplicate-key TOML
    # error). The kernel reads these via config.get_features.
    _feature_locks = []
    if advanced.get("allow_pack_editing") is False:
        _feature_locks.append("pack_editing = false")
    if advanced.get("allow_role_editing") is False:
        _feature_locks.append("role_editing = false")
    if _feature_locks:
        lines.append("")
        lines.append("[features]")
        lines.extend(_feature_locks)
    if advanced.get("tree_of_thought"):
        lines.append("")
        lines.append("[planning]")
        lines.append('mode = "tree_of_thought"')
    if advanced.get("compact_history") or advanced.get("compaction_strategy"):
        lines.append("")
        lines.append("[context]")
        if advanced.get("compact_history"):
            lines.append("compact = true")
        strat = advanced.get("compaction_strategy")
        if strat and strat != "default":
            lines.append(f'compaction_strategy = "{strat}"')
    if advanced.get("reflexion"):
        lines.append("")
        lines.append("[reflexion]")
        lines.append("enable = true")
    if advanced.get("fleet_memory"):
        lines.append("")
        lines.append("[fleet_memory]")
        lines.append("enable = true")
    if advanced.get("memory_guard"):
        lines.append("")
        lines.append("[memory_guard]")
        lines.append("enable = true")
    if advanced.get("temporal_memory"):
        lines.append("")
        lines.append("[memory]")
        lines.append("temporal = true")
    if advanced.get("fairness_monitor"):
        lines.append("")
        lines.append("[fairness_monitor]")
        lines.append("enable = true")
    # Discipline defaults ON; only an explicit decline is written.
    if advanced.get("specialist_discipline") is False:
        lines.append("")
        lines.append("[domains]")
        lines.append("discipline = false")
    if advanced.get("dreaming"):
        lines.append("")
        lines.append("[dreaming]")
        lines.append("enable = true")
        keys = advanced.get("insight_pubkeys") or []
        if keys:
            # Free-text user input: route through _emit_kv so each key is
            # escaped via _toml_str (a key with a quote/backslash would
            # otherwise corrupt the config the wizard writes).
            _emit_kv(lines, "trusted_insight_pubkeys", keys)
    if advanced.get("tax_update_url") or advanced.get("tax_pubkeys"):
        lines.append("")
        lines.append("[tax]")
        lines.append("auto_update = true")
        if advanced.get("tax_update_url"):
            # User-entered free text: escape via _toml_str so a URL with a
            # backslash or quote can't corrupt the config the wizard writes.
            _emit_kv(lines, "update_url", advanced["tax_update_url"])
        tax_keys = advanced.get("tax_pubkeys") or []
        if tax_keys:
            # Same escaping concern as the insight pubkeys above.
            _emit_kv(lines, "trusted_constants_pubkeys", tax_keys)
    if advanced.get("effort"):
        lines.append("")
        lines.append("[effort]")
        lines.append("enabled = true")
    if advanced.get("cache_prewarm"):
        lines.append("")
        lines.append("[cache]")
        lines.append("prewarm = true")
    if advanced.get("hedge_requests"):
        lines.append("")
        lines.append("[latency]")
        lines.append("hedge_ms = 1500")
    tool_lines: list[str] = []
    if advanced.get("deferred_tools"):
        tool_lines.append("deferred_loading = true")
    if advanced.get("output_cache"):
        tool_lines.append("output_cache = true")
    if advanced.get("hardware_sensors"):
        tool_lines.append("hardware_sensors = true")
    if tool_lines:
        lines.append("")
        lines.append("[tools]")
        lines.extend(tool_lines)
    if advanced.get("shield_updates"):
        lines.append("")
        lines.append("[shield]")
        lines.append("federated_updates = true")
        lines.append('# update_url    = "https://..."  # REQUIRED')
        lines.append('# update_pubkey = "<ed25519 hex>"  # REQUIRED')
    if advanced.get("ebpf_monitor"):
        lines.append("")
        lines.append("[ebpf_monitor]")
        lines.append("enable = true")
    if advanced.get("local_runtime"):
        lines.append("")
        lines.append("[local_runtime]")
        lines.append("enabled = true")
        lines.append('# engine = "vllm"  # vllm | tgi | llamacpp')
        lines.append('# model  = "..."   # REQUIRED before `maverick local-runtime plan`')
    if advanced.get("local_first"):
        lines.append("")
        lines.append("[system]")
        lines.append("local_first = true")
        local_model = _local_first_model(providers)
        if local_model:
            lines.append("")
            lines.append("[local_first]")
            _emit_kv(lines, "model", local_model)
    oidc = advanced.get("oidc") or {}
    if isinstance(oidc, dict) and oidc.get("enabled"):
        # SSO ID-token verification for `maverick serve`. Its own table
        # (written once), so no duplicate-[auth.oidc] bug. The kernel reads
        # it via maverick.oidc.oidc_enabled() / load_oidc_config().
        lines.append("")
        lines.append("[auth.oidc]")
        lines.append("enabled = true")
        _emit_kv(lines, "issuer", oidc.get("issuer", ""))
        _emit_kv(lines, "audience", oidc.get("audience", ""))
        _emit_kv(lines, "jwks_uri", oidc.get("jwks_uri", ""))
        # Built-in browser-login fields, written ONLY when the operator
        # opted into that flow (so a bearer-only OIDC config is unchanged).
        # The kernel's login_enabled() additionally gates the routes.
        for key in (
            "client_id", "client_secret", "redirect_uri", "session_secret",
        ):
            val = oidc.get(key)
            if val:
                _emit_kv(lines, key, val)
    if advanced.get("saml"):
        lines.append("")
        # SAML 2.0 SP browser SSO (alongside OIDC). Fill in the SP/IdP details
        # then hand /saml/metadata to the IdP. Needs the [saml] extra (pysaml2)
        # and the [auth.oidc] session_secret above. See docs/security-hardening.md.
        lines.append("[auth.saml]")
        lines.append('sp_entity_id = "https://YOUR-HOST/saml/metadata"')
        lines.append('acs_url = "https://YOUR-HOST/saml/acs"')
        lines.append('idp_metadata_url = "https://IDP/app/metadata"   # or idp_metadata_file')
        lines.append("# want_assertions_signed = true")
        lines.append('# sp_cert_file = ""   # to sign AuthnRequests / decrypt')
        lines.append('# sp_key_file = ""')
    return lines


def _cfg_mcp_servers(mcp_servers: dict[str, dict[str, Any]] | None) -> list[str]:
    if not mcp_servers:
        return []
    lines: list[str] = []
    for name, cfg in mcp_servers.items():
        lines.append("")
        # The server name is free text: a bare identifier goes in as-is, but a
        # name with dots/spaces/quotes must be a quoted+escaped TOML key or it
        # corrupts the table header (e.g. `foo"bar` or `a.b`).
        key = name if name.replace("_", "").replace("-", "").isalnum() else _toml_str(name)
        lines.append(f"[mcp_servers.{key}]")
        for k, v in cfg.items():
            _emit_kv(lines, k, v)
    return lines


def _cfg_registries(header: str, indexes: list[str] | None) -> list[str]:
    if not indexes:
        return []
    lines = ["", f"[{header}]"]
    _emit_kv(lines, "indexes", indexes)
    return lines


def _cfg_plugins(
    plugins: list[str] | None,
    plugin_grant: list[str] | None,
    plugin_enforce: bool,
    ts_plugins: list[list[str]] | None,
) -> list[str]:
    if not (plugins or ts_plugins):
        return []
    lines = ["", "[plugins]"]
    if plugins:
        _emit_kv(lines, "enabled", plugins)
    if plugin_grant:
        _emit_kv(lines, "grant", plugin_grant)
    if plugin_enforce:
        _emit_kv(lines, "enforce_permissions", plugin_enforce)
    if ts_plugins:
        _emit_kv(lines, "ts", ts_plugins)
    return lines


def _cfg_security(tool_acl: dict[str, Any] | None, autofix: bool,
                  dual_approval: bool = False) -> list[str]:
    if not (tool_acl or autofix or dual_approval):
        return []
    lines = ["", "[security]"]
    if autofix:
        lines.append("auto_fix = true")
    if dual_approval:
        # N-of-M dual control (two-person rule): high/critical-risk actions need
        # 2 distinct approvers and the requester can't self-approve. See
        # docs/security-hardening.md. Use a [security.approvals_required] table
        # to vary N per risk band.
        lines.append("approvals_required = 2")
        lines.append("allow_self_approval = false")
    for k, v in (tool_acl or {}).items():
        if k == "channels":
            continue
        _emit_kv(lines, k, v)
    for ch_id, ch_cfg in ((tool_acl or {}).get("channels") or {}).items():
        lines.append("")
        lines.append(f"[security.channels.{ch_id}]")
        for k, v in ch_cfg.items():
            _emit_kv(lines, k, v)
    return lines


def _cfg_rate_limits(rate_limits: dict[str, str] | None) -> list[str]:
    if not rate_limits:
        return []
    lines = ["", "[rate_limits]"]
    for name, spec in rate_limits.items():
        # Quote names that aren't bare identifiers (e.g. "mcp_*").
        key = name if name.replace("_", "").isalnum() else f'"{name}"'
        # spec is free-text ("N/seconds"); escape via _toml_str so a stray
        # quote/backslash can't corrupt the config the wizard writes.
        lines.append(f'{key} = {_toml_str(spec)}')
    return lines


def _cfg_table(header: str, mapping: dict[str, Any] | None) -> list[str]:
    if not mapping:
        return []
    lines = ["", f"[{header}]"]
    for k, v in mapping.items():
        _emit_kv(lines, k, v)
    return lines


def write_config(
    providers: list[str],
    role_models: dict[str, str],
    channels: dict[str, dict[str, Any]],
    safety: dict[str, Any],
    budget: dict[str, float],
    sandbox: dict[str, Any],
    keys: dict[str, str],
    capabilities: dict[str, bool] | None = None,
    *,
    advanced: dict[str, Any] | None = None,
    mcp_servers: dict[str, dict[str, Any]] | None = None,
    mcp_registries: list[str] | None = None,
    template_registries: list[str] | None = None,
    plugins: list[str] | None = None,
    plugin_grant: list[str] | None = None,
    plugin_enforce: bool = False,
    ts_plugins: list[list[str]] | None = None,
    tool_acl: dict[str, Any] | None = None,
    rate_limits: dict[str, str] | None = None,
    retention: dict[str, int] | None = None,
    analytics: dict[str, Any] | None = None,
    persona: dict[str, str] | None = None,
    notifications: dict[str, Any] | None = None,
    webhooks: dict[str, Any] | None = None,
    deliverables: dict[str, Any] | None = None,
    personas: dict[str, Any] | None = None,
    a2a: dict[str, Any] | None = None,
    web_search_enabled: bool = False,
    skills: dict[str, Any] | None = None,
    self_learning: dict[str, Any] | None = None,
    automation_import: dict[str, Any] | None = None,
    oauth: dict[str, Any] | None = None,
    governed_connectors: dict[str, Any] | None = None,
    durable: dict[str, Any] | None = None,
    finance: dict[str, Any] | None = None,
    deployment: str | None = None,
    suites: dict[str, bool] | None = None,
) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    # Re-running the wizard truncates config.toml / .env. The loader explicitly
    # supports hand-editing, so back up any existing file first (0o600) instead
    # of silently destroying a user's manual edits.
    def _backup(path) -> None:
        try:
            if os.path.exists(path):
                bak = str(path) + ".bak"
                tmp = bak + ".tmp"
                try:
                    os.unlink(tmp)
                except FileNotFoundError:
                    pass
                fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                try:
                    with open(path, "rb") as src, os.fdopen(fd, "wb") as dst:
                        fd = -1
                        shutil.copyfileobj(src, dst)
                    try:
                        st = os.stat(path)
                        os.utime(tmp, (st.st_atime, st.st_mtime))
                    except OSError:
                        pass
                    try:
                        os.chmod(tmp, 0o600)
                    except OSError:
                        pass
                    os.replace(tmp, bak)
                    try:
                        os.chmod(bak, 0o600)
                    except OSError:
                        pass
                finally:
                    if fd != -1:
                        os.close(fd)
                    try:
                        os.unlink(tmp)
                    except FileNotFoundError:
                        pass
        except OSError:
            pass

    if keys:
        _backup(ENV_FILE)
        # Atomic + perm-from-creation: previous version was
        # ``write_text(...)`` followed by ``chmod(0o600)``, which left
        # the file world-readable (0o644) for one syscall. Open with
        # ``O_CREAT | O_WRONLY | O_TRUNC`` and mode 0o600 so the file
        # never exists at any other permission.
        body = "\n".join(f"{k}={v}" for k, v in keys.items()) + "\n"
        fd = os.open(
            ENV_FILE,
            os.O_CREAT | os.O_WRONLY | os.O_TRUNC,
            0o600,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(body)
        finally:
            # If the file already existed at a wider mode, tighten it.
            try:
                os.chmod(ENV_FILE, 0o600)
            except OSError:
                pass

    lines = [
        "# Maverick config. Regenerate with:  maverick init",
        "",
    ]
    lines += _cfg_deployment(deployment)
    lines += _cfg_providers(providers)
    lines += _cfg_role_models(role_models)
    lines += _cfg_channels(channels)
    lines += _cfg_core(budget, safety, sandbox)
    lines += _cfg_skills(skills)
    lines += _cfg_self_learning(self_learning)
    lines += _cfg_automation_import(automation_import)
    lines += _cfg_oauth(oauth)
    lines += _cfg_governed_connectors(governed_connectors)
    lines += _cfg_durable(durable)
    lines += _cfg_finance(finance)

    capability_config = dict(capabilities or {})
    if web_search_enabled and not capability_config.get("web_search"):
        # web_search is wired through enable_web_search at kernel
        # boot; reflect the wizard's pick under [capabilities].
        capability_config["web_search"] = True
    if advanced and advanced.get("enforce_capabilities"):
        capability_config["enforce"] = True
    if advanced and advanced.get("per_call_token_exchange"):
        # Per-call token exchange only makes sense atop capability enforcement
        # (a token minted from no grant has nothing to scope), so turning it on
        # implies enforcement.
        capability_config["enforce"] = True
        capability_config["per_call_tokens"] = True

    # The embedded-device flash gate lives under [embedded], not
    # [capabilities] -- pull it out before emitting the capabilities block.
    embedded_flash = bool(capability_config.pop("embedded_flash", False))

    lines += _cfg_capabilities(capability_config, embedded_flash)
    lines += _cfg_suites(suites)
    lines += _cfg_advanced(advanced, providers)
    lines += _cfg_mcp_servers(mcp_servers)
    lines += _cfg_registries("mcp_registries", mcp_registries)
    lines += _cfg_registries("template_registries", template_registries)
    lines += _cfg_plugins(plugins, plugin_grant, plugin_enforce, ts_plugins)
    lines += _cfg_security(tool_acl, bool((advanced or {}).get("security_autofix")),
                           dual_approval=bool((advanced or {}).get("dual_approval")))
    lines += _cfg_rate_limits(rate_limits)
    lines += _cfg_table("retention", retention)
    lines += _cfg_table("analytics", analytics)
    lines += _cfg_table("persona", persona)
    lines += _cfg_table("notifications", notifications)
    lines += _cfg_table("webhooks", webhooks)
    lines += _cfg_table("deliverables", deliverables)
    lines += _cfg_table("personas", personas)
    lines += _cfg_table("a2a", a2a)

    # SECURITY: config.toml is NOT secret-free. Unlike API keys (which live in
    # ~/.maverick/.env and are referenced via ${VAR}), the OIDC browser-login
    # client_secret and session_secret (HMAC session-cookie signing key) are
    # written here as literal values. The 0600 mode below is therefore load-
    # bearing, not just tidiness -- never relax it, and treat this file as
    # secret-bearing in backups/log redaction. chmod 600 so multi-user hosts
    # don't leak it to other accounts.
    config_body = "\n".join(lines) + "\n"
    _backup(CONFIG_FILE)
    fd = os.open(
        CONFIG_FILE,
        os.O_CREAT | os.O_WRONLY | os.O_TRUNC,
        0o600,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(config_body)
    finally:
        try:
            os.chmod(CONFIG_FILE, 0o600)
        except OSError:
            pass
    console.print(f"[green]ok[/green] wrote {CONFIG_FILE} (chmod 600)")
    if keys:
        console.print(f"[green]ok[/green] wrote {ENV_FILE} (chmod 600)")


def smoke_test() -> bool:
    console.print()
    console.print("[dim]Running smoke test...[/dim]")
    try:
        from maverick.config import load_config
        cfg = load_config()
        assert cfg.get("sandbox", {}).get("backend"), "sandbox backend missing"
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
    Claude (BYOK via ANTHROPIC_API_KEY env), the Docker sandbox when its
    daemon is up (else local), balanced safety, $5/run cap. Users can
    `maverick init` later to customize.
    """
    welcome()
    if not preflight():
        console.print(
            "[red]Preflight failed.[/red] Fix the issues above and re-run."
        )
        return 1
    console.print(
        "[bold]Fast setup:[/bold] using safe defaults. "
        "Run `maverick init` (no --fast) anytime to customize.\n"
    )
    providers = ["anthropic"]
    role_models: dict[str, str] = {}  # use ROLE_MODELS defaults
    channels: dict[str, Any] = {}
    safety = {
        "profile": "balanced",
        "block_threshold": "high",
        "scan_input": True,
        "scan_tool_calls": True,
        "scan_output": True,
        "compartments": False,
    }
    budget = {
        "max_dollars": 5.0,
        "max_wall_seconds": 3600.0,
        "max_tool_calls": 500,
    }
    # Prefer the isolated Docker sandbox, but fall back to local when the
    # daemon isn't up -- otherwise fast-setup writes a docker config that the
    # very next `maverick start` can't run (the user never chose docker, yet
    # hits "Docker not available"). Mirrors write_consumer_config.
    backend = "docker" if _docker_available() else "local"
    sandbox = {
        "backend": backend,
        "workdir": str(Path.home() / "maverick-workspace"),
        "timeout": 60,
    }
    denied_tools = ["computer", "browser"]
    if backend == "local":
        denied_tools.extend(["shell", "write_file", "apply_patch", "str_replace_editor"])
        console.print(
            "[yellow]![/yellow] Docker daemon not detected — using the "
            "[bold]local[/bold] sandbox with host-mutating tools disabled. "
            "Run [bold]maverick init[/bold] to switch to docker once it's up."
        )
    capabilities = {"computer_use": False, "browser": False, "ros": False}
    # Pick up the API key from the env if it's already there;
    # otherwise the wizard's later run can populate ~/.maverick/.env.
    keys: dict[str, str] = {}
    if os.environ.get("ANTHROPIC_API_KEY"):
        keys["ANTHROPIC_API_KEY"] = os.environ["ANTHROPIC_API_KEY"]
    write_config(
        providers, role_models, channels, safety, budget,
        sandbox, keys, capabilities,
        tool_acl={"denied_tools": denied_tools},
    )
    smoke_test()
    console.print()
    console.print(Panel.fit(
        "[bold green]Fast setup finished.[/bold green]\n\n"
        "Try: [bold]maverick start \"hello\"[/bold]\n"
        "(If ANTHROPIC_API_KEY wasn't set, edit ~/.maverick/.env first.)",
        border_style="green",
    ))
    return 0


CONSUMER_DEMO_GOAL = "Write me a haiku about Tuesday."
CONSUMER_DEMO_MODEL = "anthropic:claude-haiku-4-5"


def pick_mode() -> str:
    """First-screen picker: consumer vs advanced.

    Council round-2 design: every launch starts here so a non-technical
    user lands in a four-question flow with safe defaults, and a power
    user can opt straight into the full wizard.
    """
    console.print()
    console.print(Panel.fit(
        "[bold]How do you want to set this up?[/bold]\n\n"
        "  consumer  Four questions, safe defaults. About a minute.\n"
        "  advanced  Pick every model, channel, safety level, budget.",
        border_style="cyan",
    ))
    pick = _q_select(
        "Pick a mode:",
        [
            "consumer - just get me running",
            "advanced - let me configure everything",
        ],
        default="consumer - just get me running",
    )
    return pick.split()[0]


def _consumer_budget() -> dict[str, float]:
    """Single-question budget chip picker for consumer mode."""
    pick = _q_select(
        "Stop after spending how much per task?",
        ["$1", "$5", "$20", "custom"],
        default="$5",
    )
    if pick == "custom":
        dollars = _safe_float(_q_text("  Custom cap ($)", default="5.0"), default=5.0)
    else:
        dollars = float(pick.lstrip("$"))
    return {
        "max_dollars": dollars,
        "max_wall_seconds": 600.0,
        "max_tool_calls": 100,
    }


def _consumer_api_key() -> dict[str, str]:
    """Single-screen Anthropic key collection for consumer mode.

    No DevTools paste, no jargon. Three escape hatches:
      1. Paste the key (the default).
      2. Skip for now (write config without keys; user can re-run later).
      3. Open the console in a browser to make a key.
    """
    console.print()
    console.print(
        "Maverick needs an account with Claude (Anthropic). "
        "Get a key at: [cyan]https://console.anthropic.com/settings/keys[/cyan]\n"
        "[dim]It looks like 'sk-ant-...' and is about 100 characters long.[/dim]",
    )
    val = _q_secret("  Paste your Anthropic API key (leave blank to skip):")
    if not val.strip():
        console.print(
            "[yellow]Skipped.[/yellow] You can add one later by running "
            "[bold]maverick init[/bold] again."
        )
        return {}
    # Validate with the 7-day cache.
    cached = _cached_validation("ANTHROPIC_API_KEY", val)
    if cached is not None:
        ok, msg = cached
    else:
        ok, msg = _validate_anthropic_key(val)
        _remember_validation("ANTHROPIC_API_KEY", val, ok, msg)
    if ok:
        console.print(f"  [green]ok[/green] {msg}")
        return {"ANTHROPIC_API_KEY": val}
    # On failure, surface the branded error and let the user decide.
    show_bad_key_error("ANTHROPIC_API_KEY", msg)
    if _q_confirm("Save the key anyway and continue?", default=False):
        return {"ANTHROPIC_API_KEY": val}
    return {}


def write_consumer_config(
    *,
    user_name: str,
    keys: dict[str, str],
    workdir: str,
    budget: dict[str, float],
) -> None:
    """Write a consumer-mode config with the safety-seat safe defaults.

    Single source of truth shared by the CLI consumer flow
    (``run_consumer``) and the desktop installer sidecar
    (``maverick_installer.bridge``) so the two front ends can't drift.
    Creates the workspace dir. Raises on write failure (caller renders
    the branded error).
    """
    Path(workdir).expanduser().mkdir(parents=True, exist_ok=True)
    backend = "docker" if _docker_available() else "local"
    # Computer + browser always require explicit opt-in (consumer is
    # never asked). When there's no Docker sandbox to contain it, also
    # deny the host-mutating tools — fail closed on the host. With
    # Docker present, shell/write_file/apply_patch stay enabled because
    # the container is the blast radius, not the user's machine.
    denied_tools = ["computer", "browser"]
    if backend == "local":
        denied_tools.extend(["shell", "write_file", "apply_patch", "str_replace_editor"])
    write_config(
        ["anthropic"],             # providers
        {},                        # role_models -> kernel defaults
        {},                        # channels -> none in consumer mode
        {
            "profile": "strict",          # strictest shield
            "block_threshold": "medium",  # block medium+ threats
            "scan_input": True,
            "scan_tool_calls": True,
            "scan_output": True,
        },
        budget,
        {
            "backend": backend,
            "workdir": str(Path(workdir).expanduser()),
            "timeout": 60,
        },
        keys,
        {"computer_use": False, "browser": False, "ros": False},  # capabilities
        tool_acl={"denied_tools": denied_tools},
        rate_limits={
            "web_search": "5/60",
            "http_fetch": "10/60",
            "shell": "5/60",
            "mcp_*": "20/60",
        },
        retention={"audit_days": 30, "episodes_days": 90, "events_days": 30},
        persona={"name": "Maverick", "style": "balanced", "user_name": user_name},
        web_search_enabled=True,
    )


def run_consumer() -> int:
    """Four-question consumer flow. Writes a minimal config with
    consumer-grade safe defaults, then prints a one-line demo command."""
    console.print()
    console.print(Panel.fit(
        "[bold]Maverick setup[/bold]\n\n"
        "Four questions. About a minute. You can change anything later\n"
        "by running [bold]maverick init[/bold] again.",
        border_style="cyan",
    ))

    if not preflight():
        console.print(
            "[red]Setup can't continue.[/red] Fix the issues above and try again."
        )
        return 1

    user_name = _q_text(
        "What should we call you?",
        default=os.environ.get("USER") or os.environ.get("USERNAME") or "",
    ).strip() or "you"

    keys = _consumer_api_key()

    workdir = _q_text(
        "Where can Maverick work?",
        default=str(Path.home() / "Documents" / "Maverick"),
    ).strip() or str(Path.home() / "Documents" / "Maverick")

    budget = _consumer_budget()

    try:
        write_consumer_config(
            user_name=user_name, keys=keys, workdir=workdir, budget=budget,
        )
    except Exception as e:
        show_install_failure(e)
        return 1

    # First-goal nudge. Don't run the goal here (the kernel doesn't
    # stream into a wizard window today, and shelling out from inside
    # the installer is ugly); print the one-liner instead. The Haiku
    # model keeps the demo under $0.01 and finishes in a couple of
    # seconds even on cold connections.
    console.print()
    if keys:
        console.print(Panel.fit(
            f"[bold green]Setup complete, {user_name}.[/bold green]\n\n"
            "Try your first goal:\n"
            f"  [bold]maverick start \"{CONSUMER_DEMO_GOAL}\" --model {CONSUMER_DEMO_MODEL}[/bold]\n\n"
            "Then:\n"
            "  [bold]maverick dashboard[/bold]   web UI at http://127.0.0.1:8765",
            border_style="green",
        ))
    else:
        console.print(Panel.fit(
            f"[bold yellow]Setup saved without an API key, {user_name}.[/bold yellow]\n\n"
            "Add one later by exporting ANTHROPIC_API_KEY or by running\n"
            "[bold]maverick init[/bold] again.",
            border_style="yellow",
        ))
    _clear_partial()
    return 0


# (command, one-line description) surfaced after a regulated-posture setup, so a
# non-technical operator discovers the verification + GDPR/EU AI Act
# documentation commands they'd otherwise never find. Defined as data so a test
# can assert the set without rendering the Rich panel.
_COMPLIANCE_COMMANDS: list[tuple[str, str]] = [
    ("maverick enterprise verify", "prove the data boundary holds"),
    ("maverick compliance", "GDPR + EU AI Act control coverage"),
    ("maverick ropa", "GDPR Art. 30 record-of-processing scaffold"),
    ("maverick dpia", "GDPR Art. 35 impact-assessment scaffold"),
    ("maverick ai-act", "EU AI Act risk classification"),
    ("maverick assess", "run a PIA / AIRA / vendor-risk assessment"),
    ("maverick hunt", "hunt the audit trail for agent attacks"),
    ("maverick remediate", "assess security posture + fix low-risk gaps"),
]


def _regulated_deployment(advanced: dict[str, Any]) -> bool:
    """True if the operator turned on a sensitive-data control, so the wizard
    should point them at the compliance + documentation commands."""
    advanced = advanced or {}
    return bool(
        advanced.get("enterprise")
        or advanced.get("encrypt_at_rest")
        or advanced.get("audit_sign")
        or advanced.get("audit_worm")
        or advanced.get("dual_approval")
        or advanced.get("saml")
        or advanced.get("security_autofix")
    )


def show_compliance_commands(advanced: dict[str, Any]) -> None:
    """Print the compliance/documentation command panel after a regulated setup.

    No-op unless the deployment enabled enterprise mode, at-rest encryption, or
    audit signing -- otherwise it's just noise for a personal install.
    """
    if not _regulated_deployment(advanced):
        return
    rows = "\n".join(
        f"  [bold]{cmd}[/bold]{' ' * max(1, 28 - len(cmd))}# {desc}"
        for cmd, desc in _COMPLIANCE_COMMANDS
    )
    console.print()
    console.print(Panel.fit(
        "[bold]You enabled a regulated-data posture.[/bold] Prove and document it:\n\n"
        f"{rows}\n\n"
        "[dim]See docs/regulated-deployment.md. Control coverage, not legal advice.[/dim]",
        border_style="cyan",
        title="Compliance & documentation",
    ))


def _run_simple_picks(state: dict[str, Any], _announce) -> dict[str, Any]:
    """Run the contiguous block of single-answer ``state.get(x) or pick_x()``
    steps (safety through advanced), persisting each. Returns the answers."""
    _announce()
    safety = state.get("safety") or pick_safety()
    state["safety"] = safety
    _save_partial(state)

    _announce()
    signed_skills = state.get("signed_skills") or pick_signed_skills()
    state["signed_skills"] = signed_skills
    _save_partial(state)

    _announce()
    budget = state.get("budget") or pick_budget()
    state["budget"] = budget
    _save_partial(state)

    _announce()
    sandbox = state.get("sandbox") or pick_sandbox()
    state["sandbox"] = sandbox
    _save_partial(state)

    _announce()
    capabilities = state.get("capabilities") or pick_capabilities()
    state["capabilities"] = capabilities
    _save_partial(state)

    _announce()
    self_learning = state.get("self_learning") or pick_self_learning()
    state["self_learning"] = self_learning
    _save_partial(state)

    _announce()
    automation_import = state.get("automation_import") or pick_automation_import()
    state["automation_import"] = automation_import
    _save_partial(state)

    _announce()
    oauth = state.get("oauth") or pick_oauth_vault()
    state["oauth"] = oauth
    _save_partial(state)

    _announce()
    governed_connectors = state.get("governed_connectors") or pick_governed_connectors()
    state["governed_connectors"] = governed_connectors
    _save_partial(state)

    _announce()
    durable = state.get("durable") or pick_durable()
    state["durable"] = durable
    _save_partial(state)

    _announce()
    finance = state.get("finance") or pick_finance()
    state["finance"] = finance
    _save_partial(state)

    _announce()
    advanced = state.get("advanced") or pick_advanced()
    state["advanced"] = advanced
    _save_partial(state)

    return {
        "safety": safety,
        "signed_skills": signed_skills,
        "budget": budget,
        "sandbox": sandbox,
        "capabilities": capabilities,
        "self_learning": self_learning,
        "automation_import": automation_import,
        "oauth": oauth,
        "governed_connectors": governed_connectors,
        "durable": durable,
        "finance": finance,
        "advanced": advanced,
    }


def _run_plugin_picks(
    state: dict[str, Any], _announce, channels: dict[str, Any]
) -> dict[str, Any]:
    """Run the plugin/ACL/policy block (mcp_servers through analytics).

    Uses the ``is None`` sentinel for steps whose legitimate answer is falsy.
    Returns the answers needed downstream by ``write_config``.
    """
    # NOTE: these steps use the `is None` sentinel (not `or`) because a
    # legitimately-declined answer is falsy ({}/[]); the `or` pattern treated
    # "I chose nothing" as "unanswered" and re-prompted it on --resume.
    _announce()
    mcp_servers = state.get("mcp_servers")
    if mcp_servers is None:
        mcp_servers = pick_mcp_servers()
        state["mcp_servers"] = mcp_servers
        _save_partial(state)

    _announce()
    plugins = state.get("plugins")
    if plugins is None:
        plugins = pick_plugins()
        state["plugins"] = plugins
        _save_partial(state)

    ts_plugins = state.get("ts_plugins")
    if ts_plugins is None:
        ts_plugins = pick_ts_plugins()
        state["ts_plugins"] = ts_plugins
        _save_partial(state)

    # Only ask about plugin permissions when at least one plugin is enabled --
    # most setups have none, so the step is skipped entirely.
    plugin_grant = state.get("plugin_grant")
    plugin_enforce = state.get("plugin_enforce", False)
    if plugins and plugin_grant is None:
        plugin_grant, plugin_enforce = pick_plugin_permissions()
        state["plugin_grant"] = plugin_grant
        state["plugin_enforce"] = plugin_enforce
        _save_partial(state)

    _announce()
    tool_acl = state.get("tool_acl")
    if tool_acl is None:
        tool_acl = pick_tool_acl(channels)
        state["tool_acl"] = tool_acl
        _save_partial(state)

    _announce()
    rate_limits = state.get("rate_limits")
    if rate_limits is None:
        rate_limits = pick_rate_limits(channels)
        state["rate_limits"] = rate_limits
        _save_partial(state)

    _announce()
    retention = state.get("retention")
    if retention is None:
        retention = pick_retention()
        state["retention"] = retention
        _save_partial(state)

    _announce()
    analytics = state.get("analytics")
    if analytics is None:
        analytics = pick_analytics()
        state["analytics"] = analytics
        _save_partial(state)

    return {
        "mcp_servers": mcp_servers,
        "plugins": plugins,
        "ts_plugins": ts_plugins,
        "plugin_grant": plugin_grant,
        "plugin_enforce": plugin_enforce,
        "tool_acl": tool_acl,
        "rate_limits": rate_limits,
        "retention": retention,
        "analytics": analytics,
    }


def run(fast: bool = False, resume: bool = False) -> int:
    if fast:
        return run_fast()
    # A non-interactive stdin (CI, Docker build, `... | maverick init`) can't
    # answer prompts -- questionary just prints "Input is not a terminal" and
    # the first prompt aborts with a terse "Aborted!". Detect it up front and
    # point at the paths that DO work without a TTY.
    if not sys.stdin.isatty():
        console.print(
            "[yellow]maverick init needs an interactive terminal.[/yellow]\n"
            "  - run it in a terminal, or\n"
            "  - use  [bold]maverick init --fast[/bold]  for recommended defaults, or\n"
            "  - edit  ~/.maverick/config.toml  by hand (see docs/configuration.md)."
        )
        return 1
    welcome()
    # Council round-2: mode picker on every launch. Consumer is default.
    # Skip the picker on --resume since it implies an in-progress
    # advanced flow.
    if not resume:
        mode = pick_mode()
        if mode == "consumer":
            return run_consumer()
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

    # Progress bar: announce "Step N/M <label>" before each pick_*, with a
    # breadcrumb of steps already behind us. Purely cosmetic.
    _done: list[str] = []
    _step = [0]

    def _announce() -> None:
        _step[0] += 1
        console.print(_step_indicator(_step[0], done=_done), style="bold cyan")
        _done.append(STEPS[_step[0] - 1][1])

    _announce()
    deployment = state.get("deployment") or pick_deployment()
    state["deployment"] = deployment
    _save_partial(state)

    _announce()
    providers = state.get("providers") or pick_providers()
    while not providers:
        # Aborting on empty selection forced the user to restart the
        # whole wizard (UX seat finding). Re-ask instead.
        console.print(
            "[yellow]Pick at least one provider; Maverick needs an LLM.[/yellow]"
        )
        providers = pick_providers()
    state["providers"] = providers
    _save_partial(state)

    _announce()
    role_models = state.get("role_models")
    if role_models is None:
        role_models = pick_models_per_role(providers)
        state["role_models"] = role_models
        _save_partial(state)

    _announce()
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

    _simple = _run_simple_picks(state, _announce)
    safety = _simple["safety"]
    signed_skills = _simple["signed_skills"]
    budget = _simple["budget"]
    sandbox = _simple["sandbox"]
    capabilities = _simple["capabilities"]
    self_learning = _simple["self_learning"]
    automation_import = _simple["automation_import"]
    oauth = _simple["oauth"]
    governed_connectors = _simple["governed_connectors"]
    durable = _simple["durable"]
    finance = _simple["finance"]
    advanced = _simple["advanced"]

    _announce()
    web_search_enabled, web_search_envs = (
        state.get("_web_search_pair") or pick_web_search()
    )
    state["_web_search_pair"] = [web_search_enabled, web_search_envs]
    _save_partial(state)

    _plugins_block = _run_plugin_picks(state, _announce, channels)
    mcp_servers = _plugins_block["mcp_servers"]
    plugins = _plugins_block["plugins"]
    ts_plugins = _plugins_block["ts_plugins"]
    plugin_grant = _plugins_block["plugin_grant"]
    plugin_enforce = _plugins_block["plugin_enforce"]
    tool_acl = _plugins_block["tool_acl"]
    rate_limits = _plugins_block["rate_limits"]
    retention = _plugins_block["retention"]
    analytics = _plugins_block["analytics"]

    _announce()
    persona = state.get("persona")
    if persona is None:
        persona = pick_persona()
        state["persona"] = persona
        _save_partial(state)

    _announce()
    notifications, notify_envs = state.get("_notifications_pair") or pick_notifications()
    state["_notifications_pair"] = [notifications, notify_envs]
    _save_partial(state)

    _announce()
    webhooks, webhook_envs = state.get("_webhooks_pair") or pick_webhooks()
    state["_webhooks_pair"] = [webhooks, webhook_envs]
    _save_partial(state)

    deliverables, deliverable_envs = (
        state.get("_deliverables_pair") or pick_deliverable_handoff())
    state["_deliverables_pair"] = [deliverables, deliverable_envs]
    _save_partial(state)

    personas = state.get("_personas") or pick_persona_roles()
    state["_personas"] = personas
    _save_partial(state)

    _announce()
    a2a_cfg, a2a_envs = state.get("_a2a_pair") or pick_a2a()
    state["_a2a_pair"] = [a2a_cfg, a2a_envs]
    _save_partial(state)

    # Keys/sessions are never persisted to disk in the partial state
    # (they're secrets; the only safe place is ~/.maverick/.env).
    extra_envs = (
        set(web_search_envs) | set(notify_envs) | set(webhook_envs)
        | set(a2a_envs) | set(deliverable_envs)
    )
    keys = collect_api_keys(providers, channel_envs | extra_envs)
    # Enterprise connectors are always registered; collect any credentials the
    # user wants to wire up now (merged into ~/.maverick/.env, never persisted
    # to partial state). Editable later in the .env file.
    keys.update(pick_connectors())
    captured_sessions = collect_browser_sessions(providers)
    if captured_sessions:
        console.print(
            "\n[yellow]Note:[/yellow] session providers are OFF by default "
            "(automating a vendor's consumer UI can risk your account). To "
            "use the session(s) you just captured, set "
            "[bold]MAVERICK_ENABLE_SESSION_PROVIDERS=1[/bold]."
        )

    suites = pick_suites()

    console.print()
    if not _q_confirm("Write config and finish?", default=True):
        # Be honest about where the state lives and what restore does.
        console.print(
            f"Stopped. Partial answers saved to {PARTIAL_STATE_PATH}.\n"
            "Resume with: maverick init --resume"
        )
        return 0

    write_config(
        providers, role_models, channels, safety, budget, sandbox,
        keys, capabilities,
        advanced=advanced,
        mcp_servers=mcp_servers,
        plugins=plugins,
        plugin_grant=plugin_grant,
        ts_plugins=ts_plugins,
        plugin_enforce=plugin_enforce,
        tool_acl=tool_acl,
        rate_limits=rate_limits,
        retention=retention,
        analytics=analytics,
        persona=persona,
        notifications=notifications,
        webhooks=webhooks,
        deliverables=deliverables,
        personas=personas,
        a2a=a2a_cfg,
        web_search_enabled=web_search_enabled,
        skills=signed_skills if (signed_skills.get("trusted_pubkeys") or signed_skills.get("require_signed") or signed_skills.get("require_signed_catalog")) else None,
        self_learning=self_learning if self_learning.get("enable") else None,
        automation_import=automation_import if automation_import.get("enable") else None,
        oauth=oauth if oauth.get("vault") else None,
        governed_connectors=governed_connectors if governed_connectors.get("enable") else None,
        durable=durable if durable.get("enabled") else None,
        finance=finance if finance.get("enable") else None,
        suites=suites,
    )
    _clear_partial()
    ok = smoke_test()
    if ok:
        console.print()
        next_step = "maverick serve" if channels else 'maverick start "hello"'
        console.print(Panel.fit(
            "[bold green]Setup complete.[/bold green]\n\n"
            "Try:\n"
            f"  [bold]{next_step}[/bold]\n"
            "  [bold]maverick status[/bold]\n"
            "  [bold]maverick dashboard[/bold]    # web UI at http://127.0.0.1:8765",
            border_style="green",
        ))
        show_compliance_commands(advanced)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(run())
