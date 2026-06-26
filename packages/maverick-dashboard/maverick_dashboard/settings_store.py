"""Dashboard Settings overlay for provider keys + capability/feature toggles.

Writes ``~/.maverick/dashboard-config.toml`` (config.dashboard_overrides_path),
which ``maverick.config.load_config`` deep-merges over config.toml — so a key
or toggle set in the UI takes effect on the next run without touching the
user's config.toml. (Models / budget / tool denials live in the separate
runtime-overrides.toml, read via their own hooks.)

Secrets: provider api_keys are written here at 0600. The kernel resolves
``[providers.<name>].api_key`` from config BEFORE the env vars, so a key set
here unblocks goals immediately. The HTTP layer must NEVER echo a stored key
back — callers get a masked hint only (see ``state()``).
"""
from __future__ import annotations

import json
import os
import threading

from maverick import config

# Serializes the overlay load-modify-save in-process; cross_process_lock in
# _locked() extends it across processes (multiple dashboard workers edit
# provider keys / toggles).
_SETTINGS_LOCK = threading.Lock()


def _locked():
    from contextlib import ExitStack

    from maverick.file_lock import cross_process_lock
    stack = ExitStack()
    stack.enter_context(_SETTINGS_LOCK)
    stack.enter_context(cross_process_lock(config.dashboard_overrides_path()))
    return stack

# Providers offered in the UI: name, label, env var(s) that also satisfy it,
# whether a base_url (self-hosted endpoint) is relevant.
PROVIDERS: list[dict] = [
    {"name": "anthropic", "label": "Anthropic (Claude)", "env": ["ANTHROPIC_API_KEY"], "base_url": False},
    {"name": "openai", "label": "OpenAI", "env": ["OPENAI_API_KEY"], "base_url": False},
    {"name": "gemini", "label": "Google Gemini", "env": ["GEMINI_API_KEY", "GOOGLE_API_KEY"], "base_url": False},
    {"name": "openrouter", "label": "OpenRouter", "env": ["OPENROUTER_API_KEY"], "base_url": False},
    {"name": "moonshot", "label": "Moonshot", "env": ["MOONSHOT_API_KEY"], "base_url": False},
    {"name": "deepseek", "label": "DeepSeek", "env": ["DEEPSEEK_API_KEY"], "base_url": False},
    {"name": "xai", "label": "xAI (Grok)", "env": ["XAI_API_KEY", "GROK_API_KEY"], "base_url": False},
    {"name": "ollama", "label": "Ollama (self-hosted)", "env": [], "base_url": True},
    {"name": "vllm", "label": "vLLM / OpenAI-compatible", "env": ["VLLM_BASE_URL", "OPENAI_COMPATIBLE_BASE_URL"], "base_url": True},
]
_PROVIDER_NAMES = {p["name"] for p in PROVIDERS}

# Mirror maverick.config.get_capabilities/get_features keys + defaults.
CAPABILITY_DEFAULTS = {
    "computer_use": False, "browser": False, "web_search": False,
    "mobile_tools": False, "ros": False, "code_exec": False,
}
FEATURE_DEFAULTS = {"skills": True, "world_model": True, "streaming": True}

# Channels offered in the UI: name + per-field spec. Keys MUST match what
# server.py's _wire_<name> reads from [channels.<name>] (verified against the
# wiring), so a value saved here actually configures the channel via the
# load_config() deep-merge. ``secret`` fields are masked + never echoed back;
# ``type: int`` fields are stored as numbers.
CHANNELS: list[dict] = [
    {"name": "telegram", "label": "Telegram", "fields": [
        {"key": "bot_token", "label": "Bot token", "secret": True},
    ]},
    {"name": "discord", "label": "Discord", "fields": [
        {"key": "bot_token", "label": "Bot token", "secret": True},
    ]},
    {"name": "slack", "label": "Slack", "fields": [
        {"key": "app_token", "label": "App-level token", "secret": True},
        {"key": "bot_token", "label": "Bot token", "secret": True},
    ]},
    {"name": "whatsapp_cloud", "label": "WhatsApp (Cloud API)", "fields": [
        {"key": "access_token", "label": "Access token", "secret": True},
        {"key": "phone_number_id", "label": "Phone number ID", "secret": False},
        {"key": "verify_token", "label": "Verify token", "secret": True},
        {"key": "app_secret", "label": "App secret", "secret": True},
        {"key": "port", "label": "Webhook port", "secret": False, "type": "int"},
    ]},
    {"name": "sms", "label": "SMS (Twilio)", "fields": [
        {"key": "account_sid", "label": "Account SID", "secret": False},
        {"key": "auth_token", "label": "Auth token", "secret": True},
        {"key": "from_number", "label": "From number", "secret": False},
        {"key": "port", "label": "Webhook port", "secret": False, "type": "int"},
    ]},
    {"name": "email", "label": "Email (IMAP/SMTP)", "fields": [
        {"key": "imap_host", "label": "IMAP host", "secret": False},
        {"key": "imap_user", "label": "IMAP user", "secret": False},
        {"key": "imap_password", "label": "IMAP password", "secret": True},
        {"key": "smtp_host", "label": "SMTP host", "secret": False},
        {"key": "smtp_user", "label": "SMTP user", "secret": False},
        {"key": "smtp_password", "label": "SMTP password", "secret": True},
        {"key": "smtp_port", "label": "SMTP port", "secret": False, "type": "int"},
    ]},
]
_CHANNELS_BY_NAME = {c["name"]: c for c in CHANNELS}


def _tomllib():
    try:
        import tomllib  # 3.11+
    except ModuleNotFoundError:  # 3.10
        import tomli as tomllib  # type: ignore[no-redef]
    return tomllib


def load_overlay() -> dict:
    p = config.dashboard_overrides_path()
    if not p.exists():
        return {}
    try:
        with open(p, "rb") as f:
            return _tomllib().load(f)
    except (OSError, ValueError):
        return {}


def _toml_str(value: str) -> str:
    return json.dumps(str(value))  # JSON strings are valid TOML basic strings


def _dump(data: dict) -> str:
    lines = [
        "# Dashboard-managed settings overlay (provider keys + capability/feature",
        "# toggles). Edit via the dashboard Settings page, not by hand. Your",
        "# config.toml is never touched by the dashboard.",
        "",
    ]
    for section in ("capabilities", "features"):
        tbl = data.get(section) or {}
        if tbl:
            lines.append(f"[{section}]")
            for k in sorted(tbl):
                lines.append(f"{k} = {'true' if tbl[k] else 'false'}")
            lines.append("")
    for name in sorted(data.get("providers") or {}):
        pcfg = data["providers"][name] or {}
        fields = [(f, pcfg.get(f)) for f in ("api_key", "base_url") if pcfg.get(f)]
        if not fields:
            continue
        lines.append(f"[providers.{name}]")
        for field, val in fields:
            lines.append(f"{field} = {_toml_str(val)}")
        lines.append("")
    for name in sorted(data.get("channels") or {}):
        ccfg = data["channels"][name] or {}
        if not ccfg:
            continue
        lines.append(f"[channels.{name}]")
        lines.append(f"enabled = {'true' if ccfg.get('enabled') else 'false'}")
        for k in sorted(ccfg):
            if k == "enabled":
                continue
            v = ccfg[k]
            if isinstance(v, bool):
                lines.append(f"{k} = {'true' if v else 'false'}")
            elif isinstance(v, int):
                lines.append(f"{k} = {v}")
            else:
                lines.append(f"{k} = {_toml_str(v)}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _write(data: dict) -> None:
    # Unique temp + os.replace (0600): the fixed ".toml.tmp" collided between two
    # concurrent workers. RMW serialization is in the mutators via _locked().
    from maverick.file_lock import atomic_write_text
    atomic_write_text(config.dashboard_overrides_path(), _dump(data))


def set_provider(name: str, api_key: str | None = None, base_url: str | None = None) -> None:
    """Set a provider's api_key/base_url. Empty/None values are left unchanged
    (so re-saving a base_url never wipes a key you can't see). Use
    ``clear_provider`` to remove."""
    if name not in _PROVIDER_NAMES:
        raise ValueError("unknown provider")
    with _locked():
        data = load_overlay()
        pcfg = data.setdefault("providers", {}).setdefault(name, {})
        if api_key and api_key.strip():
            pcfg["api_key"] = api_key.strip()
        if base_url and base_url.strip():
            pcfg["base_url"] = base_url.strip()
        if not pcfg:
            data["providers"].pop(name, None)
        _write(data)


def clear_provider(name: str) -> None:
    if name not in _PROVIDER_NAMES:
        raise ValueError("unknown provider")
    with _locked():
        data = load_overlay()
        (data.get("providers") or {}).pop(name, None)
        _write(data)


def set_toggle(section: str, name: str, enabled: bool) -> None:
    """Override a [capabilities] or [features] flag in the overlay."""
    defaults = {"capabilities": CAPABILITY_DEFAULTS, "features": FEATURE_DEFAULTS}.get(section)
    if defaults is None or name not in defaults:
        raise ValueError("unknown setting")
    with _locked():
        data = load_overlay()
        data.setdefault(section, {})[name] = bool(enabled)
        _write(data)


def set_channel(name: str, enabled: bool, values: dict | None = None) -> None:
    """Enable/disable a channel and set its credentials in the overlay. A blank
    field value is left unchanged (so toggling enabled never wipes a secret you
    can't see). Writes [channels.<name>] to dashboard-config.toml, which
    load_config() deep-merges -- so `maverick serve` picks it up with no
    config.toml edit. Use ``clear_channel`` to remove."""
    spec = _CHANNELS_BY_NAME.get(name)
    if spec is None:
        raise ValueError("unknown channel")
    values = values or {}
    data = load_overlay()
    ccfg = data.setdefault("channels", {}).setdefault(name, {})
    ccfg["enabled"] = bool(enabled)
    for field in spec["fields"]:
        key = field["key"]
        raw = values.get(key)
        val = raw.strip() if isinstance(raw, str) else raw
        if val in (None, ""):
            continue  # blank -> keep the stored value (don't wipe a hidden secret)
        if field.get("type") == "int":
            try:
                ccfg[key] = int(val)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{field['label']} must be a number") from exc
        else:
            ccfg[key] = str(val)
    _write(data)


def clear_channel(name: str) -> None:
    """Remove a channel's overlay table entirely (reverts to config.toml/env)."""
    if name not in _CHANNELS_BY_NAME:
        raise ValueError("unknown channel")
    data = load_overlay()
    (data.get("channels") or {}).pop(name, None)
    _write(data)


def _raw_config_providers() -> dict:
    """Providers from config.toml ONLY (no overlay), to attribute the source."""
    try:
        return config._load_config_file(config.config_path()).get("providers", {}) or {}
    except Exception:
        return {}


def _raw_config_channels() -> dict:
    """Channels from config.toml ONLY (no overlay), to attribute the source."""
    try:
        return config._load_config_file(config.config_path()).get("channels", {}) or {}
    except Exception:
        return {}


def _mask(secret: str) -> str:
    s = str(secret)
    return ("•" * 4 + s[-4:]) if len(s) > 4 else "••••"


def state() -> dict:
    """Redacted snapshot for the settings page. NEVER returns a raw key."""
    overlay = load_overlay()
    ov_providers = overlay.get("providers") or {}
    raw_providers = _raw_config_providers()
    providers = []
    for p in PROVIDERS:
        name = p["name"]
        ov = ov_providers.get(name) or {}
        raw = raw_providers.get(name) or {}
        env_set = any(os.environ.get(v) for v in p["env"])
        key = ov.get("api_key") or raw.get("api_key")
        base = ov.get("base_url") or raw.get("base_url")
        if ov.get("api_key") or ov.get("base_url"):
            via = "dashboard"
        elif raw.get("api_key") or raw.get("base_url"):
            via = "config.toml"
        elif env_set:
            via = "environment"
        else:
            via = None
        providers.append({
            "name": name, "label": p["label"], "base_url_field": p["base_url"],
            "configured": bool(key or base or env_set), "via": via,
            "key_hint": _mask(key) if (ov.get("api_key") or raw.get("api_key")) else None,
            "base_url": base or "",
            "env_hint": ", ".join(p["env"]) if p["env"] else "",
            "dashboard_set": bool(ov),
        })
    caps_eff = config.get_capabilities()
    feats_eff = config.get_features()
    ov_caps = overlay.get("capabilities") or {}
    ov_feats = overlay.get("features") or {}
    capabilities = [
        {"name": k, "enabled": bool(caps_eff.get(k, v)), "overridden": k in ov_caps}
        for k, v in CAPABILITY_DEFAULTS.items()
    ]
    features = [
        {"name": k, "enabled": bool(feats_eff.get(k, v)), "overridden": k in ov_feats}
        for k, v in FEATURE_DEFAULTS.items()
    ]
    return {"providers": providers, "capabilities": capabilities, "features": features}


def channels_state() -> list[dict]:
    """Redacted snapshot for the channels page. NEVER returns a raw secret:
    secret fields are blanked (with a masked hint), non-secret fields prefill so
    the form shows the current host/port/etc."""
    overlay = load_overlay()
    ov_ch = overlay.get("channels") or {}
    raw_ch = _raw_config_channels()
    out = []
    for spec in CHANNELS:
        name = spec["name"]
        ov = ov_ch.get(name) or {}
        raw = raw_ch.get(name) or {}
        fields = []
        for f in spec["fields"]:
            ov_v = ov.get(f["key"])
            raw_v = raw.get(f["key"])
            v = ov_v if ov_v not in (None, "") else raw_v
            configured = v not in (None, "")
            fields.append({
                "key": f["key"], "label": f["label"],
                "secret": bool(f.get("secret")), "type": f.get("type", "text"),
                "value": "" if f.get("secret") else (str(v) if configured else ""),
                "hint": _mask(v) if (configured and f.get("secret")) else "",
                "configured": configured,
            })
        out.append({
            "name": name, "label": spec["label"],
            "enabled": bool(ov.get("enabled", raw.get("enabled", False))),
            "fields": fields, "dashboard_set": bool(ov),
            "via": "dashboard" if ov else ("config.toml" if raw else None),
        })
    return out


__all__ = [
    "PROVIDERS", "CAPABILITY_DEFAULTS", "FEATURE_DEFAULTS", "CHANNELS",
    "load_overlay", "set_provider", "clear_provider", "set_toggle", "state",
    "set_channel", "clear_channel", "channels_state",
]
