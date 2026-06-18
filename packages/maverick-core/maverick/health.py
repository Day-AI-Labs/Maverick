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

# diagnose() accumulates the labels of failed (✗) checks here so the CLI can
# exit nonzero when the install is actually broken. doctor used to print red
# rows but always exit 0, so `maverick doctor && deploy` and CI health gates
# couldn't tell a broken deployment from a healthy one (user-testing finding).
_FAILURES: list[str] = []


def _is_outage(exc: BaseException) -> bool:
    """True if ``exc`` signals the provider is actually unreachable/down --
    a connection error, a timeout, or a 5xx server response -- as opposed to
    a local reason the probe couldn't run (SDK quirk, unexpected shape).

    Matched by class name so this works for both the anthropic and openai
    SDKs (and their httpx-level timeouts) without importing either eagerly.
    Both SDKs share these exception names (APIConnectionError / APITimeoutError
    / APIStatusError, with the 5xx InternalServerError as an APIStatusError
    subclass).
    """
    names = {c.__name__ for c in type(exc).__mro__}
    if names & {"APIConnectionError", "APITimeoutError", "ConnectError",
                "ConnectTimeout", "ReadTimeout", "TimeoutException"}:
        return True
    # 5xx server-side outage. InternalServerError subclasses APIStatusError and
    # carries a status_code; treat any >=500 status as a real outage.
    if "APIStatusError" in names:
        code = getattr(exc, "status_code", None)
        return isinstance(code, int) and code >= 500
    return "InternalServerError" in names


def _row(marker: str, label: str, detail: str = "", fix: str = "") -> None:
    if marker == RED:
        _FAILURES.append(label)
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
        # Not a failure when some OTHER provider is configured (env key,
        # base-url env, or a [providers.<name>] table): a self-hosted
        # Ollama/vLLM deployment is healthy with no Anthropic key at all.
        # Doctor used to hard-RED here regardless (predicate split-brain,
        # platform-test finding).
        try:
            from .config import any_provider_configured
            other = any_provider_configured()
        except Exception:
            other = False
        if other:
            _row(YELLOW, "anthropic",
                 "ANTHROPIC_API_KEY not set (another provider is configured)",
                 fix="fine unless a [models] role routes to an anthropic model")
        else:
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
        # A real outage (no connection / timeout / 5xx) is RED -- the agent
        # cannot reach the API, so reporting it as a benign YELLOW "skipped"
        # hid genuine downtime. Anything else (unexpected SDK shape) stays
        # YELLOW: we just couldn't run the probe.
        if _is_outage(e):
            _row(RED, "anthropic", f"API unreachable: {type(e).__name__}",
                 fix="check network / proxy / api.anthropic.com status; key format looks right")
        else:
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
        # Real outage (no connection / timeout / 5xx) is RED; everything else
        # stays YELLOW "skipped" -- see _check_anthropic.
        if _is_outage(e):
            _row(RED, "openai", f"API unreachable: {type(e).__name__}",
                 fix="check network / proxy / status.openai.com")
        else:
            _row(YELLOW, "openai", f"validation skipped: {type(e).__name__}")


def _check_sandbox_docker() -> None:
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


def _check_sandbox_podman() -> None:
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


def _check_sandbox_kubernetes(cfg: dict) -> None:
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


def _check_sandbox_firecracker(cfg: dict) -> None:
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


def _check_sandbox(cfg: dict) -> None:
    # Match build_sandbox(): the backend is user-typed config and is compared
    # case-sensitively below, so normalize or a valid "Docker" misreports as
    # the "unsupported" catch-all while build_sandbox actually runs it.
    backend = str(cfg.get("sandbox", {}).get("backend", "local") or "local").strip().lower()
    if backend == "local":
        _row(GREEN, "sandbox", "local subprocess")
        return
    if backend == "docker":
        _check_sandbox_docker()
        return
    if backend == "podman":
        _check_sandbox_podman()
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
        _check_sandbox_kubernetes(cfg)
        return
    if backend == "firecracker":
        _check_sandbox_firecracker(cfg)
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
    # Resolve the SAME db the runtime opens (Workspace.current().db_path, which
    # the main CLI group uses as the default --db): home- and tenant-aware.
    # The frozen world_model.DEFAULT_DB always pointed at ~/.maverick/world.db,
    # so under MAVERICK_HOME or an active tenant doctor reported a path the
    # runtime never touches (user-testing finding).
    from .workspace import Workspace
    from .world_model import WorldModel
    db_path = Workspace.current().db_path
    try:
        w = WorldModel(db_path)
        _row(GREEN, "world-db", f"{db_path} (schema v{w.schema_version})")
    except Exception as e:
        _row(RED, "world-db", f"open failed: {e}",
             fix=f"check permissions on {db_path.parent}, or delete world.db to start fresh")


def _check_shield() -> None:
    try:
        from maverick_shield import Shield
    except ImportError:
        from .shield_policy import shield_required
        if shield_required():
            _row(RED, "shield",
                 "shield REQUIRED (enterprise / [safety] require_shield) but "
                 "maverick-shield is not installed — external traffic is refused",
                 fix="pip install maverick-shield")
            return
        _row(YELLOW, "shield", "maverick-shield not installed",
             fix="pip install maverick-shield  (built-in fallback rules will activate)")
        return
    # warn_if_missing=False: doctor renders the shield row (with remediation)
    # itself, so the raw "SDK not installed" log line would just bleed into the
    # health-check output mid-table.
    s = Shield.from_config(warn_if_missing=False)
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


def _check_data_residency(cfg: dict) -> None:
    """When the deployment DECLARES a data-residency requirement
    (``[residency] region`` / ``MAVERICK_RESIDENCY_REGION``), warn about any
    residency-sensitive feature still defaulting to a US region — silently
    routing a sovereign client's data through us-east-1/us-central1 is a real
    compliance hit. No declared requirement -> no-op (no noise)."""
    region = (os.environ.get("MAVERICK_RESIDENCY_REGION")
              or str((cfg.get("residency") or {}).get("region") or "")).strip()
    if not region:
        return
    if not os.environ.get("AWS_REGION") and not (cfg.get("s3") or {}).get("region"):
        _row(YELLOW, "residency",
             f"residency={region!r} but AWS_REGION is unset — S3 attachments "
             "default to us-east-1",
             fix="set AWS_REGION to an in-region value")
    if not os.environ.get("VERTEX_LOCATION") and not (cfg.get("vertex") or {}).get("location"):
        _row(YELLOW, "residency",
             f"residency={region!r} but VERTEX_LOCATION is unset — Vertex "
             "defaults to us-central1",
             fix="set VERTEX_LOCATION to an in-region value (if Vertex is used)")


def _check_config_perms() -> None:
    """Config may hold tokens/secrets — warn if it's group/world-accessible."""
    try:
        from .config import config_path
        p = config_path()
        if not p.exists():
            return
        mode = p.stat().st_mode & 0o777
    except Exception:  # pragma: no cover - never break doctor
        return
    if mode & 0o077:
        _row(YELLOW, "config-perms",
             f"{p} is group/world-accessible (mode {oct(mode)})",
             fix=f"chmod 600 {p} — it may hold tokens/secrets")
    else:
        _row(GREEN, "config-perms", "config.toml is owner-only (0600)")


def _check_client_binding() -> None:
    """One Maverick per enterprise client — surface the binding and fail loudly
    when it's enforced but unset (the deployment would otherwise serve from the
    shared root)."""
    try:
        from .client import status as client_status
        st = client_status()
    except Exception as e:  # pragma: no cover - never break doctor
        _row(YELLOW, "client", f"binding status unavailable: {e}")
        return
    cid = st.get("client_id")
    if cid:
        _row(GREEN, "client", f"bound to {cid!r} — data root {st['data_root']}")
    elif st.get("enforced"):
        _row(RED, "client",
             "client binding ENFORCED but no client id set — refusing to serve "
             "unbound",
             fix="set MAVERICK_CLIENT_ID (service unit) or [client] id in config")
    else:
        _row(YELLOW, "client",
             "no client binding (shared root) — single-tenant/legacy mode",
             fix="for an enterprise deployment set [client] id + enforce = true")


def _check_agent_trust() -> None:
    """Surface the Agent Trust Plane state — especially the silent footgun
    where the plane is ENGAGED (e.g. via enterprise mode) but the registry is
    empty, so every external agent is denied with no other signal."""
    try:
        from .agent_trust import status as trust_status
        st = trust_status()
    except Exception as e:  # pragma: no cover - never break doctor
        _row(YELLOW, "agent-trust", f"status unavailable: {e}")
        return
    if not st.get("enforced"):
        _row(GREEN, "agent-trust", "disengaged (external agents ungoverned — default)")
        return
    count = int(st.get("count") or 0)
    if count == 0:
        _row(RED, "agent-trust",
             "ENGAGED but the [agent_trust] registry is EMPTY — every external "
             "agent (federation/A2A/fleet) is denied",
             fix="add [agent_trust] agents = [...] entries, or unset enforce")
        return
    inactive = sum(1 for a in st.get("agents", []) if not a.get("active", True))
    detail = f"engaged — {count} agent(s) registered"
    if inactive:
        _row(YELLOW, "agent-trust", detail + f"; {inactive} expired/revoked",
             fix="rotate or remove expired/revoked entries")
    else:
        _row(GREEN, "agent-trust", detail)


def diagnose() -> int:
    """Run every health check, print the report, and return the number of
    failed (✗) checks. 0 == healthy. The CLI exits nonzero when this is
    nonzero so a deploy gate or CI can detect a broken install."""
    _FAILURES.clear()
    click.echo(click.style("Maverick health check\n", bold=True))
    cfg = _check_config()
    _check_config_perms()
    _check_data_residency(cfg)
    _check_client_binding()
    _check_anthropic()
    _check_openai()
    _check_sandbox(cfg)
    _check_channels(cfg)
    _check_world_db()
    _check_shield()
    _check_agent_trust()
    click.echo("")
    if _FAILURES:
        click.echo(click.style(
            f"{len(_FAILURES)} check(s) need attention: " + ", ".join(_FAILURES),
            fg="red") + "   Re-run after fixing:  maverick doctor")
        return len(_FAILURES)
    click.echo(click.style("Done.", fg="bright_black") + "  Re-run any time:  maverick doctor")
    return 0
