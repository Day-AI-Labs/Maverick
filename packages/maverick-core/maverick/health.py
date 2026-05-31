"""`maverick doctor`: end-to-end health check with remediation.

v0.1.6: every red/yellow row now ends with an actionable verb so users
aren't told "something's wrong" without knowing what to do (council UX
review).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

import click

GREEN = click.style("✓", fg="green")
YELLOW = click.style("!", fg="yellow")
RED = click.style("✗", fg="red")


def _row(marker: str, label: str, detail: str = "", fix: str = "") -> None:
    line = f"  {marker} {label}"
    if detail:
        line += click.style(f"  ({detail})", fg="bright_black")
    click.echo(line)
    if fix:
        click.echo(click.style(f"      → {fix}", fg="cyan"))


def _check_config() -> dict:
    # tomllib (with config.py's 3.10 tomli fallback) is reused for the
    # validity probe below.
    from .config import config_path, load_config, tomllib
    p = config_path()
    if not p.exists():
        _row(RED, "config", f"{p} not found",
             fix="run  maverick init")
        return {}
    # Parse directly: load_config() fails SOFT (returns {} + logs a warning) on
    # a syntax error, so checking validity through it always reported GREEN --
    # a corrupt config that silently drops every user setting went unflagged by
    # the very tool meant to catch it.
    try:
        with open(p, "rb") as f:
            tomllib.load(f)
    except Exception as e:
        _row(RED, "config", f"invalid TOML -- your settings are being IGNORED ({e})",
             fix=f"edit {p} -- fix the TOML syntax, or back it up + re-run `maverick init`")
        return {}
    _row(GREEN, "config", str(p))
    return load_config(p)


def _check_anthropic() -> None:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        _row(RED, "anthropic", "ANTHROPIC_API_KEY not set",
             fix="add to ~/.maverick/.env or `export ANTHROPIC_API_KEY=sk-ant-...`")
        return
    if not key.startswith("sk-ant-"):
        _row(YELLOW, "anthropic", "key doesn't start with sk-ant-",
             fix="re-check the key at https://console.anthropic.com/settings/keys")
        return
    try:
        import anthropic
    except ImportError:
        _row(YELLOW, "anthropic", "SDK not installed",
             fix="pip install anthropic")
        return
    try:
        client = anthropic.Anthropic(api_key=key)
        list(client.models.list(limit=1))
        _row(GREEN, "anthropic", "key validated")
    except anthropic.AuthenticationError:
        _row(RED, "anthropic", "API rejected the key",
             fix="generate a new key at https://console.anthropic.com/settings/keys, then `maverick init` to update .env")
    except Exception as e:
        _row(YELLOW, "anthropic", f"validation skipped: {type(e).__name__}",
             fix="check network / proxy; key format looks right")


def _check_openai() -> None:
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        return
    try:
        from openai import AuthenticationError, OpenAI
    except ImportError:
        _row(YELLOW, "openai", "SDK not installed",
             fix="pip install 'maverick-agent[openai]'")
        return
    try:
        client = OpenAI(api_key=key)
        list(client.models.list().data[:1])
        _row(GREEN, "openai", "key validated")
    except AuthenticationError:
        _row(RED, "openai", "API rejected the key",
             fix="regenerate at https://platform.openai.com/api-keys, then `maverick init`")
    except Exception as e:
        _row(YELLOW, "openai", f"validation skipped: {type(e).__name__}")


def _check_sandbox(cfg: dict) -> None:
    # Match build_sandbox(): the backend is user-typed config and is compared
    # case-sensitively below, so normalize or a valid "Docker" misreports as
    # the "unsupported" catch-all while build_sandbox actually runs it.
    backend = str(cfg.get("sandbox", {}).get("backend", "local") or "local").strip().lower()
    if backend == "local":
        _row(GREEN, "sandbox", "local subprocess")
        return
    if backend == "docker":
        if not shutil.which("docker"):
            _row(RED, "sandbox", "docker not on PATH",
                 fix="install Docker Desktop (https://docker.com/products/docker-desktop) or change [sandbox] backend to 'local' in ~/.maverick/config.toml")
            return
        try:
            subprocess.run(
                ["docker", "version"],
                capture_output=True, timeout=5, check=True,
            )
            _row(GREEN, "sandbox", "docker daemon responding")
        except subprocess.CalledProcessError:
            _row(RED, "sandbox", "docker daemon not running",
                 fix="start Docker Desktop, or `sudo systemctl start docker` on Linux")
        except subprocess.TimeoutExpired:
            _row(RED, "sandbox", "docker version timed out",
                 fix="docker is installed but unresponsive -- restart Docker Desktop")
        return
    if backend == "podman":
        if not shutil.which("podman"):
            _row(RED, "sandbox", "podman not on PATH",
                 fix="install podman, or change [sandbox] backend to 'docker'/'local' in ~/.maverick/config.toml")
            return
        try:
            subprocess.run(
                ["podman", "version"],
                capture_output=True, timeout=5, check=True,
            )
            _row(GREEN, "sandbox", "podman responding")
        except subprocess.CalledProcessError:
            _row(RED, "sandbox", "podman present but not responding",
                 fix="check `podman version`; on Linux/macOS you may need `podman machine start`")
        except subprocess.TimeoutExpired:
            _row(RED, "sandbox", "podman version timed out",
                 fix="podman is installed but unresponsive")
        return
    if backend == "devcontainer":
        # The devcontainer backend builds/runs through Docker under the hood.
        if not shutil.which("docker"):
            _row(RED, "sandbox", "devcontainer needs Docker, not on PATH",
                 fix="install Docker -- the devcontainer backend builds/runs via docker")
            return
        _row(YELLOW, "sandbox",
             "devcontainer (Docker present; also needs a .devcontainer/devcontainer.json with an image)")
        return
    if backend == "kubernetes":
        if not shutil.which("kubectl"):
            _row(RED, "sandbox", "kubectl not on PATH",
                 fix="install kubectl and configure a kubeconfig context")
            return
        ctx = cfg.get("sandbox", {}).get("context")
        try:
            subprocess.run(
                ["kubectl", "version", "--client"],
                capture_output=True, timeout=5, check=True,
            )
            detail = "kubectl present" + (f", context={ctx}" if ctx else "")
            _row(GREEN, "sandbox", f"{detail} (cluster reachability not checked)")
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            _row(RED, "sandbox", "kubectl present but `kubectl version --client` failed",
                 fix="check your kubectl install")
        return
    if backend == "firecracker":
        provider = str(cfg.get("sandbox", {}).get("provider", "local") or "local").strip().lower()
        if provider == "e2b":
            if os.environ.get("E2B_API_KEY"):
                _row(GREEN, "sandbox", "firecracker via E2B (E2B_API_KEY set)")
            else:
                _row(RED, "sandbox", "firecracker provider=e2b but E2B_API_KEY unset",
                     fix='export E2B_API_KEY=..., or set [sandbox] provider = "local"')
        elif provider == "local":
            if shutil.which("firecracker"):
                _row(GREEN, "sandbox", "firecracker binary present")
            else:
                _row(RED, "sandbox", "firecracker binary not on PATH",
                     fix='install firecracker, or set [sandbox] provider = "e2b"')
        else:
            _row(YELLOW, "sandbox", f"firecracker provider={provider!r} unknown",
                 fix='[sandbox] provider must be "local" or "e2b"')
        return
    if backend == "ssh":
        host = cfg.get("sandbox", {}).get("host", "")
        if not host:
            _row(RED, "sandbox", "backend=ssh but no [sandbox] host=",
                 fix='edit ~/.maverick/config.toml and add: host = "user@example.com"')
            return
        _row(YELLOW, "sandbox", f"ssh -> {host} (live check not performed)")
        return
    _row(YELLOW, "sandbox", f"backend={backend} not recognized",
         fix="supported: local, docker, podman, devcontainer, kubernetes, firecracker, ssh")


CHANNEL_DEPS = {
    "telegram": ("telegram", "python-telegram-bot"),
    "discord":  ("discord", "discord.py"),
    "slack":    ("slack_sdk", "slack_sdk"),
    "matrix":   ("nio", "matrix-nio"),
    "whatsapp": ("twilio", "twilio + fastapi"),
    "sms":      ("twilio", "twilio + fastapi"),
}


def _check_channels(cfg: dict) -> None:
    channels = cfg.get("channels", {})
    if not channels:
        return
    for name, ch_cfg in channels.items():
        if not ch_cfg.get("enabled"):
            continue
        dep = CHANNEL_DEPS.get(name)
        if dep:
            mod, friendly = dep
            try:
                __import__(mod)
                _row(GREEN, f"channel:{name}", f"{friendly} installed")
            except ImportError:
                _row(YELLOW, f"channel:{name}", f"{friendly} not installed",
                     fix=f"pip install 'maverick-channels[{name}]'")
                continue
        elif name == "signal":
            if not shutil.which("signal-cli"):
                _row(YELLOW, "channel:signal", "signal-cli not on PATH",
                     fix="install signal-cli per https://github.com/AsamK/signal-cli, then register your number")
                continue
            _row(GREEN, "channel:signal", "signal-cli present")
        elif name == "imessage":
            if sys.platform != "darwin":
                _row(RED, "channel:imessage", f"requires macOS (you're on {sys.platform})",
                     fix="disable in config or run Maverick from a Mac")
                continue
            _row(GREEN, "channel:imessage", "macOS")
        elif name == "email":
            _row(GREEN, "channel:email", "stdlib only")


def _check_world_db() -> None:
    from .world_model import DEFAULT_DB, WorldModel
    try:
        w = WorldModel(DEFAULT_DB)
        _row(GREEN, "world-db", f"{DEFAULT_DB} (schema v{w.schema_version})")
    except Exception as e:
        _row(RED, "world-db", f"open failed: {e}",
             fix=f"check permissions on {DEFAULT_DB.parent}, or delete world.db to start fresh")


def _check_shield() -> None:
    try:
        from maverick_shield import Shield
    except ImportError:
        _row(YELLOW, "shield", "maverick-shield not installed",
             fix="pip install maverick-shield  (built-in fallback rules will activate)")
        return
    s = Shield.from_config()
    backend_label = {
        "agent-shield": "agent-shield SDK (full ~115 patterns)",
        "builtin": "builtin rules (~20 high-impact patterns)",
        "none": "DISABLED -- [safety] profile=off in config",
    }.get(s.backend, s.backend)
    if s.backend == "agent-shield":
        _row(GREEN, "shield", backend_label)
    elif s.backend == "builtin":
        _row(YELLOW, "shield", backend_label,
             fix="pip install agent-shield  (when published) for full coverage")
    else:
        _row(RED, "shield", backend_label,
             fix="set [safety] profile = \"balanced\" in ~/.maverick/config.toml to re-enable")


def diagnose() -> None:
    click.echo(click.style("Maverick health check\n", bold=True))
    cfg = _check_config()
    _check_anthropic()
    _check_openai()
    _check_sandbox(cfg)
    _check_channels(cfg)
    _check_world_db()
    _check_shield()
    click.echo("")
    click.echo(click.style("Done.", fg="bright_black") + "  Re-run any time:  maverick doctor")
