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

from maverick import config

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
    return "\n".join(lines).rstrip() + "\n"


def _write(data: dict) -> None:
    p = config.dashboard_overrides_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".toml.tmp")
    fd = os.open(tmp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(_dump(data))
    os.replace(tmp, p)
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass


def set_provider(name: str, api_key: str | None = None, base_url: str | None = None) -> None:
    """Set a provider's api_key/base_url. Empty/None values are left unchanged
    (so re-saving a base_url never wipes a key you can't see). Use
    ``clear_provider`` to remove."""
    if name not in _PROVIDER_NAMES:
        raise ValueError("unknown provider")
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
    data = load_overlay()
    (data.get("providers") or {}).pop(name, None)
    _write(data)


def set_toggle(section: str, name: str, enabled: bool) -> None:
    """Override a [capabilities] or [features] flag in the overlay."""
    defaults = {"capabilities": CAPABILITY_DEFAULTS, "features": FEATURE_DEFAULTS}.get(section)
    if defaults is None or name not in defaults:
        raise ValueError("unknown setting")
    data = load_overlay()
    data.setdefault(section, {})[name] = bool(enabled)
    _write(data)


def _raw_config_providers() -> dict:
    """Providers from config.toml ONLY (no overlay), to attribute the source."""
    try:
        return config._load_config_file(config.config_path()).get("providers", {}) or {}
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


__all__ = [
    "PROVIDERS", "CAPABILITY_DEFAULTS", "FEATURE_DEFAULTS",
    "load_overlay", "set_provider", "clear_provider", "set_toggle", "state",
]
