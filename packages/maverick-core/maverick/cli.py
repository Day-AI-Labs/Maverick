"""Maverick CLI."""
from __future__ import annotations

import asyncio
import functools
import logging
import os
import re
import sys
import uuid
from pathlib import Path
from urllib.parse import quote

import click

# Council round-2 perf-seat fix: keep the top-level import surface
# minimal so `maverick --help` and `maverick version` don't pay for
# heavy submodules (orchestrator, agent, swarm, skills, sandbox) they
# never use. Submodules import lazily inside the command bodies that
# actually need them. `world_model` stays at module top — its imports
# are stdlib (sqlite3, dataclasses, pathlib) and the DEFAULT_DB
# constant is used in the click option default below.
from .world_model import DEFAULT_DB, open_world  # noqa: E402  -- cheap stdlib chain

_TERMINAL_CONTROL_RE = re.compile(
    r"(?:\x1b\][^\x07\x1b]*(?:\x07|\x1b\\|$))"
    r"|(?:\x1b\[[0-?]*[ -/]*[@-~])"
    r"|(?:\x1b[@-Z\\-_])"
    r"|[\x00-\x1f\x7f-\x9f]"
)


def _strip_terminal_control(text: str) -> str:
    """Remove terminal control bytes before rendering untrusted text."""
    return _TERMINAL_CONTROL_RE.sub("", text)


def _default_model() -> str:
    """Lazy resolver so the click default callback doesn't pull `.llm`
    (and the anthropic SDK) at module import time."""
    from .llm import DEFAULT_MODEL
    return DEFAULT_MODEL


_PROVIDER_ENV_VARS = (
    "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY",
    "OPENROUTER_API_KEY", "MOONSHOT_API_KEY", "DEEPSEEK_API_KEY",
    "XAI_API_KEY",
)


def _fact_subject_token(channel: str, user: str) -> str:
    """Stable, delimiter-safe token for explicitly user-scoped facts."""
    return f"{quote(channel, safe='')}:{quote(user, safe='')}"


def _has_configured_provider() -> bool:
    """True if config.toml configures a usable provider.

    A consumer who set up a local / OpenAI-compatible model (LM Studio,
    llama.cpp, Ollama, vLLM, a private proxy) keeps the key -- or no key at
    all -- in ``[providers.<name>]`` rather than a well-known env var. Such a
    provider is reachable when it has a non-empty ``api_key`` (config
    interpolates ``${VAR}`` to "" when unset, so an empty one doesn't count)
    or a ``base_url`` (self-hosted endpoints need no key).
    """
    try:
        from .config import load_config
        providers = (load_config() or {}).get("providers") or {}
    except Exception:  # pragma: no cover -- never block on a config read
        return False
    for pcfg in providers.values():
        if not isinstance(pcfg, dict):
            continue
        if str(pcfg.get("api_key", "")).strip():
            return True
        if str(pcfg.get("base_url", "")).strip():
            return True
    return False


def _require_llm_key() -> str:
    """Council UX/capabilities fix: don't sys.exit(2) on missing ANTHROPIC_API_KEY.

    First, check every supported provider's env var; return the first
    one set (the LLM facade dispatches on model id, not env var, so any
    valid provider config is fine). Then accept a provider configured in
    config.toml (local / OpenAI-compatible models keep credentials there,
    not in a well-known env var). If neither, print an actionable error
    that points at ``maverick init`` and exit cleanly.
    """
    for var in _PROVIDER_ENV_VARS:
        if os.environ.get(var):
            return var
    if _has_configured_provider():
        return "config"
    click.echo(
        "Maverick can't reach an LLM. No provider key is set.\n"
        "\n"
        "Set one up with:  maverick init\n"
        "Or export an existing key, for example:\n"
        "  export ANTHROPIC_API_KEY=sk-ant-...\n"
        "  export OPENAI_API_KEY=sk-...",
        err=True,
    )
    sys.exit(2)


def _humanize_run_error(e: Exception) -> str:
    """Map an operational run failure to a one-line, actionable message.

    Sandbox/provider errors used to reach the user as a raw traceback. The
    failures a consumer actually hits -- no Docker daemon, a rejected or
    typo'd key, a dropped connection, exhausted credits -- each get a plain
    sentence and a next step instead.
    """
    name = type(e).__name__.lower()
    msg = str(e).strip()
    low = msg.lower()
    # Sandbox backends already raise an actionable RuntimeError, e.g.
    # "Docker not available. ... change [sandbox] backend to 'local'".
    if isinstance(e, RuntimeError) and (
        "not available" in low or "docker" in low or "podman" in low
        or "sandbox" in low
    ):
        return f"Couldn't start the sandbox.\n  {msg}"
    if "authentication" in name or "invalid x-api-key" in low or "401" in msg:
        return (
            "Your LLM API key was rejected (401).\n"
            "  Check the key in ~/.maverick/.env or your shell, then retry.\n"
            "  Diagnose with:  maverick doctor"
        )
    # A typo'd / unavailable model id surfaces as a provider 404 (Anthropic/
    # OpenAI raise NotFoundError). Point at `maverick config`, where [models]
    # are set -- NOT `maverick doctor`, which only validates the API key and
    # would send the user chasing a non-existent auth problem.
    if "notfound" in name or "404" in msg or ("model" in low and "not found" in low):
        return (
            "The model id wasn't found by the provider (404).\n"
            "  This usually means a typo'd or unavailable model id.\n"
            "  Check the model in [models]:  maverick config"
        )
    if "ratelimit" in name or "429" in msg:
        return ("The LLM provider rate-limited this run (429). "
                "Wait a moment and retry.")
    if ("connection" in name or "timeout" in name
            or "connect" in low or "network" in low):
        return ("Couldn't reach the LLM provider. Check your network "
                "connection, then retry.")
    if "quota" in low or "credit" in low or "insufficient" in low or "billing" in low:
        return (f"The LLM provider refused the request: {msg}\n"
                "  Check your plan / billing, then retry.")
    # Anything unanticipated: a short line, not a 20-frame stack trace.
    return (
        "The run stopped on an unexpected error.\n"
        f"  {type(e).__name__}: {msg}\n"
        "  Re-run with MAVERICK_DEBUG=1 for the full traceback, "
        "or check `maverick doctor`."
    )


def _humane_errors(fn):
    """Wrap a run-driving command so operational failures print a friendly
    message and exit non-zero instead of dumping a traceback (and exiting 0).

    Set ``MAVERICK_DEBUG=1`` to bypass and re-raise the original exception.
    Use as the innermost decorator (closest to ``def``).
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (SystemExit, click.ClickException, click.Abort):
            raise
        except KeyboardInterrupt:
            click.echo("\nInterrupted.", err=True)
            sys.exit(130)
        except Exception as e:  # noqa: BLE001 -- top-level humane boundary
            if os.environ.get("MAVERICK_DEBUG"):
                raise
            click.echo(_humanize_run_error(e), err=True)
            sys.exit(1)
    return wrapper


def _kernel():
    """Lazy-import the agent-runtime modules into a single namespace.

    Importing ``.orchestrator`` transitively pulls agent + swarm +
    blackboard + sandbox + skills + tools (~30 ms). Commands that
    don't drive the agent (``version``, ``doctor``, ``config``,
    ``audit``, ``cache``, ``retention``, ``skill *``, ``template *``)
    never need any of it. Call this at the top of any command that does.
    """
    import types

    from .budget import Budget
    from .llm import DEFAULT_MODEL, LLM
    from .orchestrator import run_goal_sync
    from .sandbox import build_sandbox
    from .secrets import scrub
    return types.SimpleNamespace(
        Budget=Budget, LLM=LLM, DEFAULT_MODEL=DEFAULT_MODEL,
        run_goal_sync=run_goal_sync, build_sandbox=build_sandbox, scrub=scrub,
    )


_CLI_SECURITY_WARNING_LOGGERS = ("maverick.sandbox", "maverick.orchestrator")


class _CliDefaultWarningFilter(logging.Filter):
    """Keep routine WARNING noise quiet while surfacing safety warnings."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno >= logging.ERROR:
            return True
        return any(
            record.name == name or record.name.startswith(f"{name}.")
            for name in _CLI_SECURITY_WARNING_LOGGERS
        )


def _configure_cli_logging() -> None:
    """Keep routine library log lines off the consumer's terminal by default.

    The CLI installs no log handler, so Python's last-resort handler dumps any
    library WARNING/ERROR (e.g. "ignoring unreadable config.toml
    (TOMLDecodeError...)") straight to stderr mid-run. Install a root handler
    so routine warnings are suppressed by default while security-posture
    warnings still surface:

      - ``MAVERICK_DEBUG`` set  -> verbose: DEBUG-level logs to stderr.
      - ``MAVERICK_LOG_LEVEL``  -> honored as-is (operators who want logs).
      - otherwise               -> ERROR+ reaches the terminal, plus WARNING
        diagnostics from the sandbox / Shield safety path.

    Delegates to ``logging_config.configure_logging`` (idempotent) so the
    JSON-format / context-filter wiring stays in one place.
    """
    from .logging_config import configure_logging
    default_warning_filter = False
    if os.environ.get("MAVERICK_DEBUG"):
        level = "DEBUG"
    elif os.environ.get("MAVERICK_LOG_LEVEL"):
        # Explicit operator logging preference wins as-is.
        level = os.environ["MAVERICK_LOG_LEVEL"]
    else:
        # Root must admit WARNING records so the filter below can pass through
        # sandbox / Shield safety warnings while dropping routine library noise.
        level = "WARNING"
        default_warning_filter = True
    try:
        configure_logging(level=level)
        if default_warning_filter:
            safety_filter = _CliDefaultWarningFilter()
            for handler in logging.getLogger().handlers:
                handler.addFilter(safety_filter)
    except Exception:  # pragma: no cover -- logging setup must never break the CLI
        pass


@click.group(epilog=(
    "New here? Start with these four:\n"
    "\n"
    "\b\n"
    "  maverick init            set up (API key, sandbox, budget)\n"
    "  maverick start \"...\"      run a task\n"
    "  maverick chat            talk to it interactively\n"
    "  maverick doctor          check your setup\n"
    "\n"
    "The other commands are for power users; most people never need them."
))
@click.option("--db", default=str(DEFAULT_DB), help="World model database path.")
@click.option("--model", default=None, help="LLM model id (default: from config).")
@click.pass_context
def main(ctx: click.Context, db: str, model: str | None) -> None:
    """Maverick: multi-agent swarm for long-horizon work."""
    _configure_cli_logging()
    ctx.ensure_object(dict)
    ctx.obj["db"] = Path(db)
    ctx.obj["model"] = model  # resolved lazily on first use
    # `--model` is a run-wide override. The agents resolve their model via
    # model_for_role(), not the LLM facade's default, so threading it through
    # the env is what actually makes the flag apply to every agent (it was
    # silently ignored before -- the LLM default got overridden per call).
    if model:
        os.environ["MAVERICK_MODEL_OVERRIDE"] = model


@main.command()
@click.option("--fast", is_flag=True,
              help="Skip every prompt; use recommended defaults.")
@click.option("--resume", is_flag=True,
              help="Resume from the last unanswered wizard question.")
def init(fast: bool, resume: bool) -> None:
    """Run the interactive setup wizard."""
    try:
        from maverick_installer.wizard import run as run_wizard
    except ImportError:
        # The wizard lives in the optional `installer` extra. Installing
        # `maverick-installer` into its own pipx venv (the previous
        # message's advice) creates an isolated env where the kernel
        # can't import it. The correct path is to inject the extra into
        # the same env Maverick already lives in.
        click.echo(
            "Install: pipx install 'maverick-agent[installer]'",
            err=True,
        )
        click.echo(
            "Or, if Maverick is already installed:  "
            "pipx inject maverick-agent maverick-installer",
            err=True,
        )
        sys.exit(2)
    sys.exit(run_wizard(fast=fast, resume=resume))


@main.command()
def doctor() -> None:
    """Diagnose your Maverick installation."""
    from .health import diagnose
    diagnose()


@main.command()
def version() -> None:
    """Show installed package versions + runtime info."""
    import importlib.metadata

    click.echo(click.style("Maverick installed packages", bold=True))
    # PyPI distribution name for the core is `maverick-agent` (the
    # `maverick` name was squatted). Fall back to `maverick` if the
    # squatter ever releases the original name.
    pkg_names = [
        ("maverick-agent",     ("maverick-agent", "maverick")),
        ("maverick-shield",    ("maverick-shield",)),
        ("maverick-channels",  ("maverick-channels",)),
        ("maverick-dashboard", ("maverick-dashboard",)),
        ("maverick-mcp-server", ("maverick-mcp-server",)),
        ("maverick-installer", ("maverick-installer",)),
    ]
    for display, candidates in pkg_names:
        version = None
        for c in candidates:
            try:
                version = importlib.metadata.version(c)
                break
            except importlib.metadata.PackageNotFoundError:
                continue
        if version:
            click.echo(f"  {display:22s} {version}")
        else:
            click.echo(f"  {display:22s} " + click.style("not installed", fg="yellow"))
    click.echo("")
    click.echo(click.style("Runtime", bold=True))
    try:
        from .world_model import SCHEMA_VERSION
        click.echo(f"  schema:                v{SCHEMA_VERSION}")
    except Exception:
        pass
    try:
        from maverick_shield import Shield
        # warn_if_missing=False: this command prints the backend itself, so the
        # raw "SDK not installed" log line would just bleed into the table.
        s = Shield.from_config(warn_if_missing=False)
        click.echo(f"  shield backend:        {s.backend}")
    except ImportError:
        click.echo("  shield backend:        (maverick-shield not installed)")
    try:
        from .providers import KNOWN_PROVIDERS
        click.echo(f"  providers:             {', '.join(KNOWN_PROVIDERS)}")
    except Exception:
        pass
    try:
        from .persona import load_persona
        p = load_persona()
        if p["name"] or p["style"]:
            ident = p["name"] or "(unnamed)"
            style = p["style"] or "(default)"
            click.echo(f"  persona:               {ident} ({style})")
        else:
            click.echo("  persona:               (none)")
    except Exception:
        pass
    click.echo(f"  python:                {sys.version.split()[0]}")
    click.echo(f"  platform:              {sys.platform}")


@main.command()
@click.argument("action", type=click.Choice(["show", "path", "edit"]), default="show")
def config(action: str) -> None:
    """Show, locate, or edit ~/.maverick/config.toml."""
    from .config import config_path
    p = config_path()
    if action == "path":
        click.echo(str(p))
        return
    if action == "edit":
        import shlex
        # EDITOR is commonly set with args (e.g. "code --wait"); execvp treats
        # the whole string as one binary name and fails. Split it.
        parts = shlex.split(os.environ.get("EDITOR", "nano")) or ["nano"]
        try:
            os.execvp(parts[0], parts + [str(p)])
        except OSError as e:
            raise click.ClickException(f"could not launch editor {parts[0]!r}: {e}")
        return
    if not p.exists():
        click.echo(f"No config at {p}. Run:  maverick init", err=True)
        sys.exit(1)
    click.echo(p.read_text(encoding="utf-8"))


@main.command()
@click.pass_context
def budget(ctx) -> None:
    """Show total spend + per-run cost history."""
    world = open_world(ctx.obj["db"])
    total = world.total_spend()
    click.echo(click.style("Total spend", bold=True))
    click.echo(f"  ${total['dollars']:.4f}  across {total['runs']} run(s)")
    click.echo(
        f"  {total['input_tokens']:,} input tokens  /  "
        f"{total['output_tokens']:,} output tokens"
    )
    click.echo("")
    eps = world.list_episodes(limit=15)
    if not eps:
        click.echo("no completed runs yet.")
        return
    click.echo(click.style("Recent runs", bold=True))
    for e in eps:
        outcome = e.outcome or "running"
        click.echo(
            f"  ep #{e.id} (goal {e.goal_id}) [{outcome}]  "
            f"${e.cost_dollars:.4f}  "
            f"in={e.input_tokens:,} out={e.output_tokens:,} tools={e.tool_calls}"
        )


@main.command("runs")
@click.option("--json", "as_json", is_flag=True,
              help="Emit machine-readable JSON (array of run objects).")
@click.option("-n", "--limit", default=50, type=int, help="Max runs to show.")
@click.option("--goal", "goal_id", default=None, type=int,
              help="Only runs for this goal id.")
@click.pass_context
def runs(ctx, as_json: bool, limit: int, goal_id) -> None:
    """List recent runs (episodes) with cost, status, and timing.

    A "run" is one episode of the agent loop against a goal. ``--json``
    emits a stable array (one object per run) — this is the contract the
    VS Code extension's runs view consumes, so keep the field names
    stable.
    """
    world = open_world(ctx.obj["db"])
    try:
        episodes = world.list_episodes(limit=limit, goal_id=goal_id)
        goal_cache = {}
        records = []
        for e in episodes:
            if e.goal_id not in goal_cache:
                goal_cache[e.goal_id] = world.get_goal(e.goal_id)
            g = goal_cache[e.goal_id]
            duration = (
                round(e.ended_at - e.started_at, 3)
                if e.ended_at is not None else None
            )
            records.append({
                "episode_id": e.id,
                "goal_id": e.goal_id,
                "goal_title": g.title if g else None,
                "goal_status": g.status if g else None,
                "outcome": e.outcome,            # None while the run is live
                "running": e.ended_at is None,
                "started_at": e.started_at,
                "ended_at": e.ended_at,
                "duration_s": duration,
                "cost_dollars": e.cost_dollars,
                "input_tokens": e.input_tokens,
                "output_tokens": e.output_tokens,
                "tool_calls": e.tool_calls,
            })
    finally:
        world.close()

    if as_json:
        import json as _json
        click.echo(_json.dumps(records, default=str))
        return

    if not records:
        click.echo("no runs yet.")
        return
    click.echo(click.style(f"Recent runs ({len(records)})", bold=True))
    for r in records:
        state = "running" if r["running"] else (r["outcome"] or "done")
        title = _strip_terminal_control(r["goal_title"] or "")[:48]
        click.echo(
            f"  ep #{r['episode_id']:<4} goal {r['goal_id']:<4} "
            f"[{state:<10}] ${r['cost_dollars']:.4f}  "
            f"in={r['input_tokens']:,} out={r['output_tokens']:,} "
            f"tools={r['tool_calls']}  {title}"
        )


@main.command()
@click.option("--host", default="127.0.0.1")
@click.option("--port", default=8765, type=int)
@click.option("--token", default=None,
              help="Bearer token for non-/healthz requests.")
def dashboard(host: str, port: int, token) -> None:
    """Start the local web dashboard + REST API."""
    if token:
        os.environ["MAVERICK_DASHBOARD_TOKEN"] = token
        click.echo(click.style(
            "Bearer auth enabled. Use ?token=... or Authorization: Bearer.",
            fg="yellow",
        ))
    try:
        from maverick_dashboard.app import app as fastapi_app
    except ImportError:
        click.echo("Install: pip install maverick-dashboard", err=True)
        sys.exit(2)
    import uvicorn
    click.echo(f"Maverick dashboard: http://{host}:{port}")
    click.echo(f"REST API docs:      http://{host}:{port}/docs")
    uvicorn.run(fastapi_app, host=host, port=port, log_level="info")


@main.command()
@click.option("--http", "use_http", is_flag=True,
              help="Serve over Streamable HTTP instead of stdio.")
@click.option("--host", default="127.0.0.1", show_default=True,
              help="Bind host (with --http).")
@click.option("--port", default=8771, type=int, show_default=True,
              help="Port (with --http).")
def mcp(use_http: bool, host: str, port: int) -> None:
    """Start the MCP server on stdio (or --http).

    This is Maverick's official cross-language surface. Any MCP-speaking
    client (TypeScript, Go, Rust, .NET, JVM, plus every IDE-side MCP
    client like Claude Code / Cursor / Continue / Zed) can drive the
    swarm from outside Python via this command. See
    docs/clients/typescript-quickstart.md for a 20-line example.
    """
    try:
        from maverick_mcp.server import MCPServer
    except ImportError:
        click.echo("Install: pip install maverick-mcp-server", err=True)
        sys.exit(2)
    if use_http:
        try:
            from maverick_mcp.http_transport import serve
        except ImportError:
            click.echo("Install: pip install 'maverick-mcp-server[http]'", err=True)
            sys.exit(2)
        serve(host=host, port=port)
    else:
        # Run the stdio server directly. Going through server.main() would
        # re-parse sys.argv and reject the `mcp` subcommand token (the bug
        # that made `maverick mcp` -- the command every quickstart uses --
        # exit before serving).
        MCPServer().run()


@main.group("mcp-registry")
def mcp_registry_group() -> None:
    """Discover + install external MCP servers from a registry.

    A registry is a self-hostable `<base>/mcp/index.json` (point
    `[mcp_registries] indexes` at your own). `add` writes the chosen server into
    `[mcp_servers.<name>]` in ~/.maverick/config.toml; the kernel loads it on the
    next run. (`maverick mcp` — without `-registry` — starts Maverick's own MCP
    server; this group manages the servers Maverick *consumes*.)
    """


@mcp_registry_group.command("browse")
def mcp_registry_browse() -> None:
    """List MCP servers available in the registry."""
    from .mcp_registry import load_mcp_registry
    entries = load_mcp_registry()
    if not entries:
        click.echo("no registry entries (index empty or unreachable).")
        return
    for e in entries:
        mark = " [verified]" if e.verified else ""
        transport = "http" if (e.spec or {}).get("url") else "stdio"
        click.echo(f"  {e.name}{mark}  v{e.version}  ({transport})")
        if e.summary:
            click.echo(f"    {e.summary}")
    click.echo("")
    click.echo("install one with:  maverick mcp-registry add <name>")


@mcp_registry_group.command("add")
@click.argument("name")
def mcp_registry_add(name: str) -> None:
    """Install a registry MCP server by name into config."""
    from .mcp_registry import add_mcp_server_to_config, install_mcp_from_registry
    try:
        spec = install_mcp_from_registry(name)
        add_mcp_server_to_config(spec.name, spec.to_dict())
    except ValueError as e:
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(2)
    transport = "http" if spec.is_http else "stdio"
    click.echo(f"added: {spec.name} ({transport}) -> [mcp_servers.{spec.name}]")
    click.echo("it loads on your next `maverick start` / `maverick chat`.")


@mcp_registry_group.command("remove")
@click.argument("name")
def mcp_registry_remove(name: str) -> None:
    """Remove a configured MCP server from config."""
    from .mcp_registry import remove_mcp_server_from_config
    if remove_mcp_server_from_config(name):
        click.echo(f"removed: {name}")
    else:
        click.echo(f"no MCP server {name!r} in config.", err=True)
        sys.exit(2)


@mcp_registry_group.command("list")
@click.pass_context
def mcp_registry_list(ctx) -> None:
    """List MCP servers currently configured in ~/.maverick/config.toml."""
    from .mcp_client import load_mcp_specs_from_config
    specs = load_mcp_specs_from_config()
    if not specs:
        click.echo("no MCP servers configured. add one with "
                   "`maverick mcp-registry add <name>`.")
        return
    for s in specs:
        if s.is_http:
            click.echo(f"  {s.name}  (http)  {s.url}")
        else:
            argstr = " ".join([s.command, *s.args])
            click.echo(f"  {s.name}  (stdio)  {argstr}")


@main.command()
@click.argument("title", required=False)
@click.option("--description", default="")
@click.option("--template", "template_name", default=None)
@click.option("--param", "-p", "params", multiple=True)
@click.option("--max-dollars", default=None, type=float)
@click.option("--max-wall-seconds", default=None, type=float)
@click.option("--max-depth", default=3, type=int)
@click.option("--workdir", default=None)
@click.option("--sandbox", "sandbox_backend", default=None,
              type=click.Choice(["local", "docker", "podman", "devcontainer",
                                 "kubernetes", "ssh", "firecracker"]))
@click.option("--coding-mode", is_flag=True,
              help="Strict diff-only worker prompts + git apply --check "
                   "self-validation. Use for SWE-bench-style runs.")
@click.option("--best-of-n", default=1, type=int,
              help="In coding mode, generate N candidate patches and "
                   "pick the one whose tests pass (or applies smallest).")
@click.option("--fail-to-pass", default=None,
              help="||-separated pytest node IDs that must pass after fix "
                   "(SWE-bench FAIL_TO_PASS). Enables test-driven verifier.")
@click.option("--pass-to-pass", default=None,
              help="||-separated pytest node IDs that must KEEP passing.")
@click.option("--dry-cost", is_flag=True,
              help="Estimate cost from similar past runs and exit "
                   "(no LLM key needed, no swarm run, no goal created).")
@click.pass_context
@_humane_errors
def start(
    ctx, title, description, template_name, params,
    max_dollars, max_wall_seconds, max_depth, workdir, sandbox_backend,
    coding_mode, best_of_n, fail_to_pass, pass_to_pass, dry_cost,
) -> None:
    """Start a new goal and run the swarm."""
    # Coding-mode flags propagate via env so coding_mode.from_env()
    # picks them up everywhere (agent prompt, patch validator,
    # test-driven verifier, best-of-N candidate eval).
    if coding_mode:
        os.environ["MAVERICK_CODING_MODE"] = "1"
    if best_of_n > 1:
        os.environ["MAVERICK_BEST_OF_N"] = str(best_of_n)
    if fail_to_pass:
        os.environ["MAVERICK_FAIL_TO_PASS"] = fail_to_pass
    if pass_to_pass:
        os.environ["MAVERICK_PASS_TO_PASS"] = pass_to_pass
    # A --dry-cost estimate needs no LLM (it never runs the swarm), so don't
    # gate it on a provider key.
    if not dry_cost:
        _require_llm_key()
    if template_name:
        from .templates import load_template
        try:
            tpl = load_template(template_name)
        except FileNotFoundError as e:
            click.echo(f"ERROR: {e}", err=True)
            sys.exit(2)
        param_dict = {}
        for raw in params:
            if "=" not in raw:
                click.echo(f"ERROR: --param must be key=value, got {raw!r}", err=True)
                sys.exit(2)
            k, v = raw.split("=", 1)
            param_dict[k.strip()] = v.strip()
        try:
            title, description = tpl.render(**param_dict)
        except ValueError as e:
            click.echo(f"ERROR: {e}", err=True)
            sys.exit(2)
        max_dollars = max_dollars or tpl.budget_dollars
        max_wall_seconds = max_wall_seconds or tpl.budget_wall_seconds
        click.echo(f"[template {tpl.name}] {title}")
    elif not title:
        click.echo("ERROR: pass TITLE or --template <name>", err=True)
        sys.exit(2)

    if dry_cost:
        # Forecast from past priced runs and exit — no goal created, no run.
        from .cost_forecast import forecast, gather_samples, render
        world = open_world(ctx.obj["db"])
        try:
            fc = forecast(gather_samples(world), f"{title} {description}".strip())
        finally:
            world.close()
        click.echo(render(fc))
        return

    k = _kernel()
    world = open_world(ctx.obj["db"])
    goal_id = world.create_goal(title, description)
    click.echo(f"goal #{goal_id} created: {title}")
    llm = k.LLM(model=ctx.obj["model"] or k.DEFAULT_MODEL)
    # Honor [budget] in config.toml (start used to build Budget() directly,
    # so config caps were silently ignored). Precedence: built-in defaults
    # < config < explicit CLI flags. A None flag passes through as "unset".
    from .budget import budget_from_config
    bud = budget_from_config(
        defaults={"max_dollars": 5.0, "max_wall_seconds": 3600.0},
        max_dollars=max_dollars,
        max_wall_seconds=max_wall_seconds,
    )
    sandbox = k.build_sandbox(workdir=workdir, backend=sandbox_backend)

    # Council UX finding: `maverick start "..."` used to look hung
    # between "goal created" and the final printout. A background poller
    # streams goal_events to stderr so the user sees the swarm thinking
    # in real time. Non-tty output (e.g. piped to a file) skips the
    # poller so logs aren't littered with progress lines.
    import threading

    from .config import get_features
    stop_poll = threading.Event()
    # Suppress the live poller when: output isn't a TTY (don't litter piped
    # logs), MAVERICK_NO_PROGRESS is set (runtime override), or [features]
    # streaming is disabled in config (persistent opt-out).
    try:
        _streaming_on = get_features()["streaming"]
    except Exception:
        _streaming_on = True
    if (not click.get_text_stream("stderr").isatty()
            or os.environ.get("MAVERICK_NO_PROGRESS")
            or not _streaming_on):
        poller = None
    else:
        poller = threading.Thread(
            target=_stream_progress, args=(world.path, goal_id, stop_poll),
            daemon=True,
        )
        poller.start()

    try:
        if coding_mode and best_of_n > 1:
            import asyncio as _asyncio

            from .orchestrator import run_goal_best_of_n
            result = _asyncio.run(run_goal_best_of_n(
                llm, world, bud, goal_id,
                sandbox=sandbox, max_depth=max_depth, n=best_of_n,
            ))
        else:
            result = k.run_goal_sync(
                llm, world, bud, goal_id,
                sandbox=sandbox, max_depth=max_depth,
            )
    finally:
        stop_poll.set()
        if poller is not None:
            poller.join(timeout=2.0)
        # Close so WorldModel.close()'s WAL TRUNCATE checkpoint runs; the
        # poller thread (already joined) used its own connection.
        world.close()
    click.echo("")
    click.echo(result)


@main.command("report-issue")
@click.argument("goal_id", type=int)
@click.option("--repo", default=None,
              help="GitHub repo owner/name to file against (default: Maverick).")
@click.pass_context
def report_issue(ctx, goal_id: int, repo: str | None) -> None:
    """Build a pre-filled GitHub bug-report URL from a failed goal run.

    Gathers the goal's error events, scrubs secrets, and prints a
    github.com/.../issues/new link with the context filled in. No network
    call -- open the URL yourself to file the report.
    """
    from .issue_report import DEFAULT_REPO, build_report
    world = open_world(ctx.obj["db"])
    g = world.get_goal(goal_id)
    if g is None:
        click.echo(f"No goal #{goal_id}.", err=True)
        sys.exit(1)
    errors = [e for e in world.goal_events(goal_id, limit=10_000) if e.kind == "error"]
    url = build_report(g, errors, repo=repo or DEFAULT_REPO)
    click.echo("Open this URL to file a pre-filled bug report:\n")
    click.echo(url)


@main.command("share")
@click.argument("goal_id", type=int)
def share(goal_id: int) -> None:
    """Share a run as a sanitized, private GitHub gist.

    Exports the run's trajectory (secrets scrubbed) and uploads it as a
    secret gist. Needs a GitHub token in GITHUB_TOKEN (or GH_TOKEN).
    """
    from .run_share import share_run
    try:
        url = share_run(goal_id)
    except RuntimeError as e:
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(1)
    click.echo(f"Shared run #{goal_id}: {url}")


def _sanitize_progress_content(text: str, limit: int = 200) -> str:
    """Sanitize untrusted event content before printing to a TTY.

    - Scrub secret-looking values.
    - Remove terminal control bytes / ANSI escape sequences.
    - Collapse CR/LF to spaces for one-line progress output.
    """
    from .secrets import scrub  # lazy: only used by the streaming helper
    cleaned = scrub(text or "")
    # Strip common ANSI/OSC escape sequences.
    cleaned = re.sub(r"\x1B\[[0-?]*[ -/]*[@-~]", "", cleaned)
    cleaned = re.sub(r"\x1B\][^\x07\x1B]*(?:\x07|\x1B\\)", "", cleaned)
    # Replace newlines / carriage returns, then drop remaining control chars.
    cleaned = cleaned.replace("\r", " ").replace("\n", " ")
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", "", cleaned)
    return cleaned[:limit]


def _stream_progress(db_path, goal_id: int, stop) -> None:
    """Poll goal_events and print one line per new entry to stderr.

    Uses a fresh WorldModel so we don't share the connection with the
    main thread (SQLite WAL handles concurrent reads + one writer).
    """
    try:
        wm = open_world(db_path)
    except Exception:
        return
    seen = 0
    labels = {
        "plan": "thinking", "finding": "answer", "observation": "result",
        "error": "error", "verify": "checking", "artifact": "produced",
    }
    while not stop.is_set():
        try:
            evs = wm.goal_events(goal_id, since_id=seen, limit=200)
            for e in evs:
                label = labels.get(e.kind, e.kind)
                # Strip the hex suffix from agent names for readability.
                agent = e.agent.split("-")[0] if e.agent else "agent"
                content = _sanitize_progress_content(e.content, limit=200)
                click.echo(
                    click.style(f"  [{agent}] ", fg="bright_black")
                    + click.style(f"{label}: ", fg="cyan")
                    + content,
                    err=True,
                )
                seen = e.id
        except Exception:
            pass
        if stop.wait(timeout=1.5):
            break
    wm.close()


@main.command()
@click.option("--max-depth", default=3, type=int)
@click.option("--max-dollars", default=2.0, type=float)
@click.option("--workdir", default=None)
@click.pass_context
@_humane_errors
def chat(ctx, max_depth: int, max_dollars: float, workdir) -> None:
    """Interactive chat REPL. Each turn becomes a goal.

    Multi-line input: end a line with ``\\`` to continue, or open with
    ``\"\"\"`` to enter a paste block ending with ``\"\"\"`` on its own line.
    """
    _require_llm_key()
    k = _kernel()
    world = open_world(ctx.obj["db"])
    llm = k.LLM(model=ctx.obj["model"] or k.DEFAULT_MODEL)
    sandbox = k.build_sandbox(workdir=workdir)
    # Thread turns through a conversation scoped to this REPL process.
    # Do not use a fixed (channel, user_id) key here: conversations are
    # persistent, so a global CLI key would replay prior chat sessions into
    # unrelated future prompts.
    session_user_id = f"local:{uuid.uuid4().hex}"
    conversation = world.get_or_create_conversation("cli", session_user_id)
    click.echo(click.style("Maverick chat. Type 'exit' to leave.", fg="cyan"))
    click.echo(click.style(
        "Multi-line: end a line with \\ or wrap a block in \"\"\".",
        fg="bright_black",
    ))
    while True:
        try:
            line = click.prompt("", prompt_suffix="> ", default="", show_default=False)
        except (EOFError, click.exceptions.Abort):
            click.echo("")
            return
        line = line.rstrip()
        if not line:
            continue
        if line in ("exit", "quit", "/exit", "/quit"):
            return

        # Paste-block mode: """ ... """
        if line.startswith('"""'):
            buf = [line[3:]] if len(line) > 3 else []
            while True:
                try:
                    nxt = click.prompt(
                        "", prompt_suffix="... ", default="", show_default=False,
                    )
                except (EOFError, click.exceptions.Abort):
                    click.echo("")
                    break
                if nxt.rstrip().endswith('"""'):
                    tail = nxt.rstrip()[:-3].rstrip()
                    if tail:
                        buf.append(tail)
                    break
                buf.append(nxt)
            full = "\n".join(buf).strip()
        # Line-continuation mode: trailing backslash.
        elif line.endswith("\\"):
            buf = [line[:-1].rstrip()]
            while True:
                try:
                    nxt = click.prompt(
                        "", prompt_suffix="... ", default="", show_default=False,
                    ).rstrip()
                except (EOFError, click.exceptions.Abort):
                    click.echo("")
                    break
                if nxt.endswith("\\"):
                    buf.append(nxt[:-1].rstrip())
                else:
                    buf.append(nxt)
                    break
            full = "\n".join(b for b in buf if b)
        else:
            full = line

        if not full.strip():
            continue

        title = full.splitlines()[0][:80]
        goal_id = world.create_goal(title, full)
        # Record the user's turn so run_goal threads it (and the assistant's
        # reply, which run_goal appends) into the next turn's context.
        world.append_turn(conversation.id, "user", full, goal_id=goal_id)
        click.echo(click.style(f"  ... goal #{goal_id}", fg="bright_black"))
        from .budget import budget_from_config
        bud = budget_from_config(max_dollars=max_dollars)
        try:
            result = k.run_goal_sync(llm, world, bud, goal_id,
                                   sandbox=sandbox, max_depth=max_depth,
                                   conversation_id=conversation.id)
        except Exception as e:
            click.echo(click.style(f"  ✗ {e}", fg="red"))
            continue
        click.echo(result)
        click.echo("")


@main.group()
def template() -> None:
    """Manage goal templates."""


@template.command("list")
def template_list() -> None:
    from .templates import list_templates
    names = list_templates()
    if not names:
        click.echo("no templates found.")
        return
    for n in names:
        click.echo(f"  {n}")


@template.command("show")
@click.argument("name")
def template_show(name: str) -> None:
    from .templates import load_template
    try:
        t = load_template(name)
    except FileNotFoundError as e:
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(2)
    click.echo(f"template: {t.name}\npath: {t.path}\ntitle: {t.title}")
    click.echo(f"budget: ${t.budget_dollars} / {t.budget_wall_seconds}s")
    click.echo(f"params: {', '.join(t.params) or '(none)'}\n")
    click.echo(t.body)


@template.command("browse")
def template_browse() -> None:
    """List goal templates available in the community registry."""
    from .templates import browse_templates
    entries = browse_templates()
    if not entries:
        click.echo("no registry templates (index empty or unreachable).")
        return
    for e in entries:
        mark = " [verified]" if e.verified else ""
        click.echo(f"  {e.name}{mark}  v{e.version}")
        if e.summary:
            click.echo(f"    {e.summary}")
    click.echo("")
    click.echo("install one with:  maverick template add <name>")


@template.command("add")
@click.argument("name")
def template_add(name: str) -> None:
    """Install a registry goal template by name (hash-verified)."""
    from .templates import install_template_from_catalog
    try:
        t = install_template_from_catalog(name)
    except ValueError as e:
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(2)
    click.echo(f"installed: {t.name} -> {t.path}")
    click.echo(f"run it with:  maverick start --template {t.name}")


@main.command()
@click.argument("question")
@click.option("--rounds", default=2, show_default=True, type=int,
              help="Number of debate rounds before the judge decides.")
@click.option("--max-dollars", default=1.0, show_default=True, type=float,
              help="Spend cap for the whole debate.")
@click.option("--for", "for_stance", default=None,
              help="Stance the proponent defends (default: 'yes / sound').")
@click.option("--against", "against_stance", default=None,
              help="Stance the skeptic defends (default: 'no / flawed').")
@click.pass_context
def debate(ctx, question: str, rounds: int, max_dollars: float,
           for_stance: str | None, against_stance: str | None) -> None:
    """Run a two-sided debate on QUESTION and print the judged verdict.

    Two LLM debaters -- a proponent and a skeptic -- argue for ROUNDS rounds,
    then an impartial judge declares a winner. Useful for pressure-testing a
    decision before you commit to it.
    """
    from .budget import Budget
    from .debate import DebateParticipant, run_debate
    k = _kernel()
    llm = k.LLM(model=ctx.obj["model"] or k.DEFAULT_MODEL)
    participants = [
        DebateParticipant(
            name="Proponent",
            persona=for_stance or "the answer is YES / the proposal is sound",
            llm_complete=llm.complete,
        ),
        DebateParticipant(
            name="Skeptic",
            persona=against_stance or "the answer is NO / the proposal is flawed",
            llm_complete=llm.complete,
        ),
    ]
    result = run_debate(
        question, participants, judge_complete=llm.complete,
        rounds=rounds, budget=Budget(max_dollars=max_dollars),
    )
    for t in result.transcript:
        click.echo(f"\n[{t.speaker}]\n{t.text}")
    click.echo("\n" + "=" * 48)
    click.echo(f"Winner: {result.winner}")
    click.echo(f"Why: {result.judge_reason}")
    if result.key_argument:
        click.echo(f"Key argument: {result.key_argument}")
    click.echo(f"\n[{result.rounds_completed} round(s), ${result.total_dollars:.4f}]")


@main.command()
@click.option("--idle-sleep", default=2.0, show_default=True,
              help="Seconds to wait when the queue is empty.")
def worker(idle_sleep: float) -> None:
    """Run the background job worker.

    Drains the job queue (``~/.maverick/jobs.db``) and runs jobs armed with
    ``maverick schedule add``. Runs until interrupted (Ctrl-C / SIGTERM).
    """
    from .worker import Worker
    w = Worker(idle_sleep=idle_sleep)
    click.echo(f"worker: draining {w.queue.db_path} (Ctrl-C to stop)")
    w.run_forever()


@main.group()
def schedule() -> None:
    """Schedule recurring jobs via cron (run them with `maverick worker`)."""


@schedule.command("add")
@click.argument("cron_expr")
@click.argument("kind")
@click.option("--payload", default=None,
              help='JSON object for the job handler, e.g. \'{"goal_id": 5}\'.')
def schedule_add(cron_expr: str, kind: str, payload: str | None) -> None:
    """Arm a recurring job: 5-field CRON_EXPR firing job KIND.

    Example: maverick schedule add "0 9 * * *" run_goal --payload '{"goal_id": 5}'
    """
    import json

    from .job_queue import JobQueue
    from .scheduler import CronError, next_run, schedule_cron
    try:
        next_run(cron_expr)  # validate up front
    except CronError as e:
        click.echo(f"ERROR: bad cron expression: {e}", err=True)
        sys.exit(2)
    data: dict = {}
    if payload:
        try:
            data = json.loads(payload)
        except ValueError as e:
            click.echo(f"ERROR: --payload must be valid JSON: {e}", err=True)
            sys.exit(2)
        if not isinstance(data, dict):
            click.echo("ERROR: --payload must be a JSON object.", err=True)
            sys.exit(2)
    from .worker import BUILTIN_JOB_KINDS
    if kind not in BUILTIN_JOB_KINDS:
        click.echo(
            f"WARNING: {kind!r} is not a built-in job kind "
            f"(only {sorted(BUILTIN_JOB_KINDS)} ship by default). "
            "It will fail unless your `maverick worker` registers a handler for it.",
            err=True,
        )
    data["__cron__"] = cron_expr
    job_id, run_at = schedule_cron(JobQueue(), cron_expr, kind, data)
    from datetime import datetime
    when = datetime.fromtimestamp(run_at).strftime("%Y-%m-%d %H:%M:%S")
    click.echo(f"scheduled job {job_id} (kind={kind}); next run {when}")


@schedule.command("list")
def schedule_list() -> None:
    """List armed recurring schedules (pending cron jobs)."""
    from datetime import datetime

    from .job_queue import JobQueue
    jobs = [j for j in JobQueue().list(status="pending") if j.payload.get("__cron__")]
    if not jobs:
        click.echo("no scheduled jobs.")
        return
    for j in jobs:
        when = datetime.fromtimestamp(j.run_at).strftime("%Y-%m-%d %H:%M:%S")
        click.echo(f"  [{j.id}] {j.payload['__cron__']!r} kind={j.kind} next={when}")


@schedule.command("rm")
@click.argument("job_id", type=int)
def schedule_rm(job_id: int) -> None:
    """Cancel a scheduled (pending) job by id."""
    from .job_queue import JobQueue
    if JobQueue().cancel(job_id):
        click.echo(f"cancelled job {job_id}")
    else:
        click.echo(f"no pending job {job_id} (already running/done, or unknown).",
                   err=True)
        sys.exit(1)


@main.command()
@click.option("--max-depth", default=3, type=int)
@click.option("--verbose", "-v", is_flag=True)
def serve(max_depth: int, verbose: bool) -> None:
    """Start the channel server."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    # _configure_cli_logging (run by the group) defaults the root level to
    # ERROR so library noise stays off a consumer's terminal -- but `serve`
    # is a long-running server that wants its INFO/DEBUG logs. basicConfig is
    # a no-op once a handler exists, so set the level explicitly here.
    logging.getLogger().setLevel(logging.DEBUG if verbose else logging.INFO)
    try:
        from .server import build_from_config
    except ImportError as e:
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(2)
    try:
        server = build_from_config()
    except RuntimeError as e:
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(2)
    server.max_depth = max_depth
    click.echo("Maverick serve running. Ctrl-C to stop.")
    try:
        asyncio.run(server.run())
    except KeyboardInterrupt:
        click.echo("\nshutting down...")
        asyncio.run(server.stop())


@main.command("history")
@click.option("--limit", default=20, type=int)
@click.pass_context
def history(ctx, limit: int) -> None:
    """Show recent goal + episode history.

    Registered as ``history`` (not ``logs``): a second ``@main.command("logs")``
    for the audit log silently shadowed this one. ``logs`` now unambiguously
    means the audit log; this goal/episode view is ``maverick history``."""
    world = open_world(ctx.obj["db"])
    goals = world.list_goals()
    if not goals:
        click.echo("no goals yet.")
        return
    for g in goals[-limit:]:
        click.echo(f"#{g.id} [{g.status}] {g.title}")
        if g.result:
            preview = (g.result or "")[:200].replace("\n", " ")
            click.echo(f"  -> {preview}{'...' if len(g.result) > 200 else ''}")


@main.command()
@click.pass_context
def status(ctx) -> None:
    """Show recent goals and open questions."""
    world = open_world(ctx.obj["db"])
    # Self-heal: a CLI run killed mid-flight (or pre-fix crash) leaves goals
    # stranded in 'active'/'pending'. The dashboard reclaims these on startup,
    # but a CLI-only user never triggers that -- so do it here, where the
    # ghosts are seen. Only touches rows older than the reclaim age window.
    try:
        world.reclaim_orphan_goals()
    except Exception:  # pragma: no cover -- never block `status` on cleanup
        pass
    goals = world.list_goals()
    if not goals:
        click.echo("no goals yet. start one with `maverick start \"...\"`")
        return
    for g in goals[-10:]:
        click.echo(f"  #{g.id} [{g.status}] {g.title}")
    qs = world.open_questions()
    if qs:
        click.echo("")
        click.echo("open questions:")
        for q in qs:
            click.echo(f"  #{q.id} (goal {q.goal_id}): {q.question}")


@main.command()
@click.argument("question_id", type=int)
@click.argument("answer", nargs=-1, required=True)
@click.pass_context
def answer(ctx, question_id: int, answer: tuple[str, ...]) -> None:
    """Answer a pending question."""
    world = open_world(ctx.obj["db"])
    if not world.answer(question_id, " ".join(answer)):
        click.echo(
            f"no such question #{question_id}. "
            "See open questions with `maverick status`.",
            err=True,
        )
        sys.exit(1)
    click.echo(f"answered #{question_id}")


@main.command()
@click.argument("goal_id_arg", required=False, type=int, metavar="[GOAL_ID]")
@click.option("--goal-id", "goal_id", type=int, default=None,
              help="The goal to resume (alternative to the positional GOAL_ID).")
@click.option("--max-depth", default=3, type=int)
@click.option("--max-dollars", type=float, default=None,
              help="Raise the dollar cap for this resume (e.g. after a budget halt).")
@click.option("--max-wall-seconds", type=float, default=None,
              help="Raise the wall-clock cap for this resume.")
@click.pass_context
@_humane_errors
def resume(ctx, goal_id_arg, goal_id, max_depth: int, max_dollars, max_wall_seconds) -> None:
    """Resume a blocked goal.

    Pass the goal id positionally (``maverick resume 7``) or via ``--goal-id``;
    omit both to resume the current active/blocked goal.
    """
    _require_llm_key()
    world = open_world(ctx.obj["db"])
    # The positional arg and --goal-id are equivalent; the option wins if both
    # are given. The budget-halt / error messages suggest the positional form.
    if goal_id is None:
        goal_id = goal_id_arg
    if goal_id is None:
        g = world.active_goal()
        if not g:
            click.echo("no active or blocked goal to resume.")
            return
        goal_id = g.id
    elif not world.get_goal(goal_id):
        # An explicit --goal-id that doesn't exist is a user error: report it
        # and exit non-zero. Otherwise the run prints run_goal's "no such goal"
        # and still exits 0, which a script can't detect (export exits 2 here).
        click.echo(f"no such goal #{goal_id}. See `maverick status`.", err=True)
        sys.exit(2)
    open_qs = world.open_questions(goal_id)
    if open_qs:
        click.echo(f"cannot resume goal #{goal_id}: {len(open_qs)} open question(s).")
        for q in open_qs:
            click.echo(f"  #{q.id}: {q.question}")
        return
    k = _kernel()
    llm = k.LLM(model=ctx.obj["model"] or k.DEFAULT_MODEL)
    # Honor [budget] config, and let --max-dollars/--max-wall-seconds raise
    # the cap on resume (the budget-halt message tells users to do this).
    from .budget import budget_from_config
    bud = budget_from_config(
        max_dollars=max_dollars,
        max_wall_seconds=max_wall_seconds,
    )
    # Honor the configured [sandbox] backend on resume too -- without this,
    # resume always fell back to run_goal's default local backend, ignoring a
    # user who configured docker/podman (a quiet safety + consistency gap).
    sandbox = k.build_sandbox()
    result = k.run_goal_sync(llm, world, bud, goal_id,
                             sandbox=sandbox, max_depth=max_depth,
                             resume=True)
    click.echo(result)


@main.command()
@click.argument("key")
@click.argument("value", nargs=-1, required=True)
@click.pass_context
def fact(ctx, key: str, value: tuple[str, ...]) -> None:
    """Set a fact in the world model."""
    if not key.strip():
        click.echo("error: fact key cannot be empty", err=True)
        sys.exit(2)
    world = open_world(ctx.obj["db"])
    world.upsert_fact(key, " ".join(value))
    click.echo(f"set {key}")


@main.command()
@click.pass_context
def facts(ctx) -> None:
    """List known facts."""
    world = open_world(ctx.obj["db"])
    items = world.get_facts()
    if not items:
        click.echo('no facts yet. set one with `maverick fact <key> "<value>"`')
        return
    for k, v in items.items():
        click.echo(f"  {k}: {v}")


@main.group(invoke_without_command=True)
@click.pass_context
def skills(ctx: click.Context) -> None:
    """List skills the swarm has distilled or installed.

    With no subcommand, lists skills. Use `skills stats` to see each skill's
    track record and `skills evict` to prune ones that rarely help.
    """
    if ctx.invoked_subcommand is not None:
        return
    from .skills import SKILLS_DIR, load_skills
    items = load_skills()
    if not items:
        click.echo(f"no skills yet (in {SKILLS_DIR}).")
        return
    for s in items:
        click.echo(f"  {s.name}")
        for t in s.triggers[:3]:
            click.echo(f"    trigger: {t}")


@skills.command("stats")
def skills_stats() -> None:
    """Show each skill's usage track record (uses / win-rate / recall weight)."""
    from . import skill_stats
    from .skills import load_skills
    items = load_skills()
    if not items:
        click.echo("no skills yet.")
        return
    for s in items:
        st = skill_stats.get(s.name)
        if st is None or st.uses == 0:
            click.echo(f"  {s.name}: no usage recorded")
            continue
        decided = st.wins + st.losses
        wr = (st.wins / decided) if decided else 0.0
        click.echo(
            f"  {s.name}: uses={st.uses} wins={st.wins} losses={st.losses} "
            f"win_rate={wr:.0%} weight={skill_stats.decay_weight(s.name):.2f}"
        )


@skills.command("evict")
@click.option("--apply", "do_apply", is_flag=True,
              help="Delete the candidates (default: dry-run, just lists them).")
@click.option("--min-uses", type=int, default=5, show_default=True,
              help="Only consider skills used at least this many times.")
@click.option("--max-win-rate", type=float, default=0.2, show_default=True,
              help="Flag skills whose win rate is at or below this.")
def skills_evict(do_apply: bool, min_uses: int, max_win_rate: float) -> None:
    """List (or with --apply, remove) skills that have had a fair trial and rarely help."""
    from . import skill_stats
    from .skills import remove_skill
    cands = skill_stats.evictable(min_uses=min_uses, max_win_rate=max_win_rate)
    if not cands:
        click.echo("no eviction candidates.")
        return
    for name in cands:
        if do_apply:
            click.echo(f"  {'removed' if remove_skill(name) else 'not found'}: {name}")
        else:
            click.echo(f"  candidate: {name}")
    if not do_apply:
        click.echo("\n(dry-run; re-run with --apply to remove them)")


@main.command()
@click.option("--limit", type=int, default=50, show_default=True,
              help="Max entries to show.")
def learned(limit: int) -> None:
    """List capabilities the swarm acquired via self-learning."""
    import datetime as _dt

    from . import self_learning
    items = self_learning.history(limit=limit)
    if not items:
        click.echo(
            "no learned capabilities yet "
            f"(ledger: {self_learning.LEARNED_PATH}).\n"
            "Enable self-learning with [self_learning] enable = true "
            "or MAVERICK_SELF_LEARNING=1."
        )
        return
    for e in items:
        when = _dt.datetime.fromtimestamp(e.ts).strftime("%Y-%m-%d %H:%M")
        mark = "" if e.outcome == "acquired" else f" [{e.outcome}]"
        click.echo(f"  {when}  [{e.kind}] {e.name}{mark}")
        if e.need:
            click.echo(f"    for: {e.need}")


@main.group()
def plugin() -> None:
    """Scaffold + manage Maverick plugins."""


@plugin.command("list")
def plugin_list() -> None:
    """List active plugins (tools, channels, skills, personas) + the allowlist."""
    from .plugins import _allowed_plugin_names, installed_plugins
    try:
        slots = installed_plugins()
    except Exception as e:  # pragma: no cover -- discovery must never crash the CLI
        click.echo(f"plugin discovery failed: {e}", err=True)
        sys.exit(1)
    if not any(slots.values()):
        click.echo("no active plugins. scaffold one with `maverick plugin new <name>`.")
    else:
        for slot, names in slots.items():
            if names:
                click.echo(f"  {slot}: {', '.join(names)}")
    # Plugins load only when allowlisted (a security default); show it so a
    # user whose installed plugin isn't appearing knows why.
    allow = _allowed_plugin_names()
    if allow is None:
        click.echo('\nallowlist: ALL enabled ([plugins] enabled = ["*"])')
    else:
        listed = ", ".join(sorted(allow)) if allow else "(none)"
        click.echo(
            f"\nallowlist: {listed} "
            "-- enable more via [plugins] enabled in ~/.maverick/config.toml"
        )


@plugin.command("new")
@click.argument("name")
@click.option(
    "--kind",
    type=click.Choice(("tool", "channel", "persona")),
    default="tool",
    show_default=True,
    help="Plugin kind. Skills install via `maverick skill install`; "
         "MCP servers go in [mcp_servers.<name>] in config.toml.",
)
@click.option(
    "--dest", type=click.Path(file_okay=False), default=".",
    show_default=True, help="Parent directory; a NAME/ subdir is created here.",
)
def plugin_new(name: str, kind: str, dest: str) -> None:
    """Generate a working plugin skeleton at ./<NAME>/.

    Closes the council ecosystem-seat gap: third-party contributors had
    no on-ramp besides hand-writing pyproject.toml + the entry-point
    block + a manifest. This generates all four files with a working
    factory the contributor can ``pip install -e .`` and exercise
    immediately.
    """
    from .plugin_scaffold import ScaffoldError, scaffold
    try:
        files = scaffold(name, kind, dest=Path(dest))
    except ScaffoldError as e:
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(2)
    click.echo(f"Scaffolded {name} ({kind}) at {Path(dest) / name}:")
    for f in files:
        click.echo(f"  {f.relative_to(Path(dest))}")
    click.echo("")
    click.echo("Next steps:")
    click.echo(f"  cd {name}")
    click.echo("  pip install -e .")
    click.echo("  pytest -v")


@main.group()
def skill() -> None:
    """Manage skills (install, remove, info)."""


@skill.command("install")
@click.argument("source")
def skill_install(source: str) -> None:
    """Install a SKILL.md from a URL, gh:org/repo[:path], or local path."""
    from .skills import install_skill
    try:
        s = install_skill(source)
    except ValueError as e:
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(2)
    click.echo(f"installed: {s.name} -> {s.path}")


@skill.command("browse")
def skill_browse() -> None:
    """List skills available in the federated catalog."""
    from .catalog import load_catalog
    entries = load_catalog("skills")
    if not entries:
        click.echo("no catalog entries (index empty or unreachable).")
        return
    for e in entries:
        mark = " [verified]" if e.verified else ""
        click.echo(f"  {e.name}{mark}  v{e.version}")
        if e.summary:
            click.echo(f"    {e.summary}")
    click.echo("")
    click.echo("install one with:  maverick skill add <name>")


@skill.command("add")
@click.argument("name")
def skill_add(name: str) -> None:
    """Install a catalog skill by name (hash-verified)."""
    from .skills import install_from_catalog
    try:
        s = install_from_catalog(name)
    except ValueError as e:
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(2)
    click.echo(f"installed: {s.name} -> {s.path}")


@skill.command("remove")
@click.argument("name")
def skill_remove(name: str) -> None:
    from .skills import remove_skill
    if remove_skill(name):
        click.echo(f"removed: {name}")
    else:
        click.echo(f"no skill named {name!r}", err=True)
        sys.exit(2)


@skill.command("info")
@click.argument("name")
def skill_info(name: str) -> None:
    from .skills import load_skills
    for s in load_skills():
        if s.name == name:
            click.echo(s.path)
            for t in s.triggers:
                click.echo(f"trigger: {t}")
            click.echo("")
            click.echo(s.body)
            return
    click.echo(f"no skill named {name!r}", err=True)
    sys.exit(2)


@skill.command("validate")
@click.argument("path", type=click.Path())
def skill_validate(path: str) -> None:
    """Lint a SKILL.md for publish-readiness (offline; does not install)."""
    from .skills import validate_skill_file
    r = validate_skill_file(Path(path))
    for w in r.warnings:
        click.echo(click.style(f"  warning: {w}", fg="yellow"))
    for e in r.errors:
        click.echo(click.style(f"  error: {e}", fg="red"), err=True)
    if r.ok:
        click.echo(click.style("OK: skill is valid for publishing.", fg="green"))
    else:
        click.echo(f"INVALID: {len(r.errors)} error(s).", err=True)
        sys.exit(1)


@main.command()
@click.option("--goal-id", type=int, default=None, help="Specific goal to watch.")
@click.option("--interval", type=float, default=1.5, help="Refresh seconds.")
@click.pass_context
def monitor(ctx, goal_id, interval) -> None:
    """Watch agent activity in real time (plan tree + recent events)."""
    from .monitor import monitor_loop
    sys.exit(monitor_loop(
        db_path=ctx.obj["db"],
        goal_id=goal_id,
        interval_seconds=interval,
    ))


@main.group()
def session() -> None:
    """Manage browser-session credentials for consumer-chat providers."""


@session.command("list")
def session_list() -> None:
    """List providers with a stored session."""
    from .session_providers import cookie_store
    names = cookie_store.list_sessions()
    if not names:
        click.echo("No sessions stored.")
        return
    for name in names:
        click.echo(name)


_SESSION_IMPORT_PROFILES: dict[str, dict] = {
    "chatgpt": {
        "canon": "chatgpt-session",
        "cookie_key": "__Secure-next-auth.session-token",
        "hint_url": "chatgpt.com",
    },
    "claude": {
        "canon": "claude-session",
        "cookie_key": "sessionKey",
        "hint_url": "claude.ai",
    },
    "kimi": {
        "canon": "kimi-session",
        "cookie_key": "access_token",
        "hint_url": "kimi.com",
    },
    "grok": {
        # Grok needs auth_token + ct0; the CLI prompts for ct0 as a 2nd input.
        "canon": "grok-session",
        "cookie_key": "auth_token",
        "extra_cookie_key": "ct0",
        "hint_url": "x.com",
    },
    "gemini": {
        "canon": "gemini-session",
        "cookie_key": "__Secure-1PSID",
        "hint_url": "gemini.google.com",
    },
}
# Aliases for the canonical names.
for _alias, _canon in [
    ("chatgpt-session", "chatgpt"),
    ("claude-session", "claude"),
    ("kimi-session", "kimi"),
    ("grok-session", "grok"),
    ("gemini-session", "gemini"),
]:
    _SESSION_IMPORT_PROFILES[_alias] = _SESSION_IMPORT_PROFILES[_canon]


@session.command("import")
@click.argument(
    "provider",
    type=click.Choice(sorted(_SESSION_IMPORT_PROFILES.keys())),
)
@click.option(
    "--token", default=None,
    help="Paste the session cookie value here, or omit to be prompted.",
)
def session_import(provider: str, token: str | None) -> None:
    """Import a session cookie captured from your browser.

    Step 1: Sign in at the provider in your normal browser.
    Step 2: Open DevTools -> Application -> Cookies.
    Step 3: Copy the session cookie value and paste it here.
    """
    from .session_providers import cookie_store
    profile = _SESSION_IMPORT_PROFILES[provider]
    canon, cookie_key, hint_url = profile["canon"], profile["cookie_key"], profile["hint_url"]
    extra_key = profile.get("extra_cookie_key")
    if token is None:
        click.echo(
            f"Find your session cookie at {hint_url} -> DevTools (F12) -> "
            f"Application -> Cookies -> {cookie_key}"
        )
        token = click.prompt("Paste session token", hide_input=True)
    if not token or not token.strip():
        click.echo("No token entered; aborting.", err=True)
        sys.exit(2)
    cookies = {cookie_key: token.strip()}
    if extra_key:
        click.echo(f"Also need the {extra_key} cookie (from the same site).")
        extra_val = click.prompt(f"Paste {extra_key}", hide_input=True)
        if not extra_val or not extra_val.strip():
            click.echo(f"No {extra_key} entered; aborting.", err=True)
            sys.exit(2)
        cookies[extra_key] = extra_val.strip()
    blob = {"cookies": cookies}
    path = cookie_store.save_session(canon, blob)
    click.echo(f"Saved session to {path} (chmod 600)")


@session.command("clear")
@click.argument("provider")
def session_clear(provider: str) -> None:
    """Delete a stored session."""
    from .session_providers import cookie_store
    # `session import chatgpt` stores under the canonical name
    # ('chatgpt-session'), so accept the same short alias here -- otherwise
    # `session clear chatgpt` reports "no session" right after a successful
    # import. Unknown names pass through unchanged (the store is generic).
    profile = _SESSION_IMPORT_PROFILES.get(provider)
    name = profile["canon"] if profile else provider
    removed = cookie_store.clear_session(name)
    if removed:
        click.echo(f"Cleared session for {name}")
    else:
        click.echo(f"No session stored for {name}", err=True)
        sys.exit(1)


def _conversation_user_matches(conv_user_id: str, requested: str, channel: str) -> bool:
    """Match a conversation's user_id for erase/export-user.

    Most channels store externally supplied user ids and must match exactly:
    identifiers such as Twilio WhatsApp ``whatsapp:+15551234567`` or Matrix
    room ids naturally contain colons, so treating any ``<prefix>:`` as the
    requested user can disclose or erase unrelated conversations.

    The only family match Maverick currently needs is the local CLI chat
    namespace: each REPL session is stored as ``local:<uuid>``, while the
    documented GDPR subject is ``--channel cli --user local``.
    """
    if conv_user_id == requested:
        return True
    return channel == "cli" and requested == "local" and conv_user_id.startswith("local:")


@main.command()
@click.option("--channel", required=True, help="Channel name (e.g. telegram, sms).")
@click.option("--user", required=True, help="The channel user_id to erase.")
@click.option("--yes", is_flag=True, help="Skip confirmation.")
@click.pass_context
def erase(ctx, channel: str, user: str, yes: bool) -> None:
    """Erase everything Maverick knows about a (channel, user_id) pair.

    GDPR Art. 17 right-to-erasure: removes conversations, turns,
    attachments on disk, and the conversation row itself. (First line kept
    abbreviation-free so Click's short help isn't truncated at "Art.".)"""
    world = open_world(ctx.obj["db"])
    convs = [
        c for c in world.list_conversations(channel)
        if _conversation_user_matches(c.user_id, user, channel)
    ]
    if not convs:
        click.echo(f"no conversation found for {channel}:{user}")
        return
    if not yes:
        click.echo(f"This will erase {len(convs)} conversation(s) for {channel}:{user}.")
        click.confirm("Proceed?", abort=True)

    # Council security finding: previous version left goals, messages,
    # episodes, questions, goal_events, attachments-rows, and
    # processed_messages intact -- a documented Art. 17 violation. Full
    # cascade now wipes every row referencing goals tied to this user's
    # conversations, in one transaction so a partial failure rolls back.
    # Attachment FILE unlinks happen AFTER the DB transaction commits so
    # we don't leave dangling rows pointing at deleted paths if the DB
    # write fails.

    # Step 1: gather every goal_id referenced by any turn in any of
    # these conversations. We use ALL turns (not just recent), so a
    # conversation with >10k turns doesn't leave orphan attachments.
    conv_ids = [c.id for c in convs]
    backend_erase = getattr(world, "erase_conversations", None)
    if backend_erase is not None:
        goal_ids, attachment_paths, removed_turns = backend_erase(conv_ids)
    else:
        placeholders = ",".join("?" * len(conv_ids))
        goal_ids: set[int] = set()
        for row in world.conn.execute(
            f"SELECT DISTINCT goal_id FROM turns "
            f"WHERE conversation_id IN ({placeholders}) AND goal_id IS NOT NULL",
            conv_ids,
        ).fetchall():
            goal_ids.add(row[0])

        # Step 1b: expand to the transitive closure of subgoals. A recursive
        # swarm creates child goals via parent_id that are NOT tied to a turn,
        # so they're missing from the turn-derived set above. Deleting a parent
        # while a child still references it (goals.parent_id FK) aborts the
        # whole transaction -- a required Art.17 erasure that silently does
        # nothing. Walk the parent_id tree so every descendant is included.
        if goal_ids:
            frontier = list(goal_ids)
            while frontier:
                fph = ",".join("?" * len(frontier))
                child_rows = world.conn.execute(
                    f"SELECT id FROM goals WHERE parent_id IN ({fph})", frontier,
                ).fetchall()
                new_children = [r[0] for r in child_rows if r[0] not in goal_ids]
                goal_ids.update(new_children)
                frontier = new_children

        # Step 2: collect attachment paths to unlink (after commit).
        attachment_paths: list[str] = []
        for gid in goal_ids:
            for a in world.list_attachments(gid):
                attachment_paths.append(a.path)

        # Step 3: cascade DELETEs in a single transaction.
        removed_turns = 0
        try:
            world.conn.execute("BEGIN IMMEDIATE")
            # Defer FK checks to COMMIT so deleting parents and children in one
            # statement can't trip the goals.parent_id self-FK mid-statement.
            # Combined with the transitive-closure expansion above, every
            # referenced row is gone by COMMIT, so the deferred check passes.
            world.conn.execute("PRAGMA defer_foreign_keys = ON")
            cur = world.conn.execute(
                f"DELETE FROM turns WHERE conversation_id IN ({placeholders})",
                conv_ids,
            )
            removed_turns = cur.rowcount

            if goal_ids:
                gph = ",".join("?" * len(goal_ids))
                gids = list(goal_ids)
                # FK checks are deferred to COMMIT (above) and the goal_ids set
                # is the full subgoal closure, so delete order is not load-bearing.
                world.conn.execute(f"DELETE FROM goal_events WHERE goal_id IN ({gph})", gids)
                world.conn.execute(f"DELETE FROM messages    WHERE goal_id IN ({gph})", gids)
                world.conn.execute(f"DELETE FROM questions   WHERE goal_id IN ({gph})", gids)
                world.conn.execute(f"DELETE FROM attachments WHERE goal_id IN ({gph})", gids)
                # facts.source_episode_id REFERENCES episodes(id): a fact the agent
                # distilled from this user's run carries their PII in `value` AND
                # holds an FK to the episode we're about to delete. Leaving it both
                # (a) violated Art.17 (PII survived erasure) and (b) tripped the
                # deferred-FK check at COMMIT once the user had any fact, aborting
                # the whole erase. Delete those facts before the episodes.
                world.conn.execute(
                    f"DELETE FROM facts WHERE source_episode_id IN "
                    f"(SELECT id FROM episodes WHERE goal_id IN ({gph}))", gids,
                )
                world.conn.execute(f"DELETE FROM episodes    WHERE goal_id IN ({gph})", gids)
                world.conn.execute(
                    f"DELETE FROM processed_messages WHERE goal_id IN ({gph})", gids,
                )
                world.conn.execute(f"DELETE FROM goals WHERE id IN ({gph})", gids)

            world.conn.execute(
                f"DELETE FROM conversations WHERE id IN ({placeholders})", conv_ids,
            )
            world.conn.commit()
        except Exception:
            world.conn.rollback()
            raise

    # Step 4: now that DB rows are gone, unlink files. A failure here
    # only leaks file bytes (no row points at them) -- the metadata is
    # already erased, which is the part that matters legally.
    removed_attachments = 0
    for p in attachment_paths:
        try:
            Path(p).unlink(missing_ok=True)
            removed_attachments += 1
        except OSError:
            pass

    # Step 4b: scrub explicitly user-scoped global facts. Facts are global
    # key/value pairs with no per-user attribution, so erase only touches
    # facts deliberately keyed as user:<channel>:<user_id>:<name>. Arbitrary
    # substring matching is unsafe for short/common user ids because it can
    # delete unrelated operator knowledge or other users' data.
    fact_subject = _fact_subject_token(channel, user)
    scrubbed_fact_keys = world.delete_facts_matching(fact_subject)

    # Step 4c: the optional LLM cache (MAVERICK_LLM_CACHE=1) is content-
    # addressed on the full prompt -- system + messages include the user's
    # goal text and the model's replies, so the cache retains exactly the
    # PII we just erased. It can't be purged by subject (the key is a hash of
    # content, not tied to a user), so clear it wholesale; it's a perf cache,
    # safe to drop. Only when the DB already exists, so a single erase on a
    # cache-disabled install doesn't create an empty cache file. Best-effort.
    try:
        from .llm_cache import DEFAULT_DB as _llm_cache_db
        if _llm_cache_db.exists():
            from .llm_cache import LLMCache
            LLMCache().clear()
    except Exception as exc:  # pragma: no cover - defensive
        click.echo(
            f"warning: erased the database but could not clear the LLM cache "
            f"({type(exc).__name__}: {exc}); it may retain prior prompts.",
            err=True,
        )

    # Step 5: scrub the subject from PRIOR audit-log lines. Audit payloads
    # (goal_start / tool_call / channel events) carry channel:user_id, so
    # without this the identity we just erased stayed readable in
    # ~/.maverick/audit/*.ndjson -- an Art.17 gap (scrub_user was dead
    # code, never called). Done BEFORE recording the erase event below so
    # that event (which hashes the subject) isn't itself scrubbed.
    # If [audit] sign is enabled scrub_user verifies the chain before mutating
    # it and re-anchors only the files it changed (leaving PII in place would
    # violate Art.17, but blindly re-signing old tampering would destroy audit
    # evidence).
    audit_scrubbed = 0
    try:
        from .audit import scrub_user
        audit_scrubbed, _ = scrub_user(channel, user)
    except Exception as exc:
        click.echo(
            f"warning: erased the database but could not scrub the audit log "
            f"({type(exc).__name__}: {exc}); run `maverick audit grep {user}` "
            "to check.",
            err=True,
        )

    # Scrubbing may have re-anchored signed audit files, so drop any cached
    # signer before appending the erase marker. The compatibility hook is safe:
    # it refuses to rewrite already-broken chains unless the erase helper
    # verified them before mutation.
    from . import audit

    try:
        audit.reanchor_after_erase()
    except Exception as e:  # pragma: no cover - defensive
        click.echo(f"⚠ audit re-anchor failed: {e}", err=True)

    # GDPR Art. 30: record that an erasure happened without deriving a stable
    # identifier from the subject. Low-entropy user IDs (phone numbers, short
    # handles, numeric IDs) are enumerable, so even a truncated hash can
    # re-identify the erased person if audit logs are read.
    import secrets

    audit.record(
        "erase",
        channel=channel,
        erasure_id=secrets.token_hex(8),
        conversations=len(convs),
        turns=removed_turns,
        goals=len(goal_ids),
        attachments=removed_attachments,
        audit_lines_scrubbed=audit_scrubbed,
        facts_scrubbed=len(scrubbed_fact_keys),
    )

    click.echo(
        f"erased {len(convs)} conversation(s), {removed_turns} turn(s), "
        f"{len(goal_ids)} goal(s) and all linked rows, "
        f"{removed_attachments} attachment file(s), "
        f"{audit_scrubbed} audit event(s) scrubbed, "
        f"{len(scrubbed_fact_keys)} fact(s) scrubbed"
    )
    if scrubbed_fact_keys:
        click.echo(
            "  facts removed (global key/value, scoped with user:<channel>:<user_id>: "
            f"prefix): {', '.join(scrubbed_fact_keys)}"
        )


@main.command("compliance")
@click.option("--format", "fmt", type=click.Choice(["text", "json"]), default="text",
              help="Output format.")
@click.pass_context
def compliance_cmd(ctx, fmt: str) -> None:
    """Report GDPR + EU AI Act control coverage for this deployment.

    Maps each active control to the article it supports and flags opt-in
    controls that are off. Control coverage only -- not a legal attestation.
    """
    from .compliance import (
        compliance_report,
        render_report_json,
        render_report_text,
    )
    checks = compliance_report()
    click.echo(
        render_report_json(checks) if fmt == "json" else render_report_text(checks)
    )


@main.command("export-user")
@click.option("--channel", required=True, help="Channel name.")
@click.option("--user", required=True, help="The channel user_id to export.")
@click.option("--output", "-o", type=click.Path(), default=None,
              help="Write JSON to file (default stdout).")
@click.pass_context
def export_user(ctx, channel: str, user: str, output) -> None:
    """Export everything Maverick knows about a (channel, user_id) as JSON.

    GDPR Art. 15 right-of-access. Registered as ``export-user`` so it does
    not collide with ``export`` (the goal-trajectory bundle below); a
    duplicate Click command name silently shadowed this one, making the
    data-subject export unreachable from the CLI."""
    import json
    world = open_world(ctx.obj["db"])
    convs = [
        c for c in world.list_conversations(channel)
        if _conversation_user_matches(c.user_id, user, channel)
    ]
    data = {
        "channel": channel,
        "user_id": user,
        "conversations": [],
        # Explicitly user-scoped global facts. Facts have no per-user
        # attribution, so export only includes keys deliberately namespaced as
        # user:<channel>:<user_id>:<name> rather than arbitrary substring
        # matches.
        "facts": world.facts_matching(_fact_subject_token(channel, user)),
    }
    for c in convs:
        turns = world.recent_turns(c.id, limit=10_000)
        conv_data = {
            "id": c.id,
            "created_at": c.created_at,
            "last_seen": c.last_seen,
            "turns": [
                {"role": t.role, "content": t.content, "ts": t.ts,
                 "goal_id": t.goal_id}
                for t in turns
            ],
            "attachments": [],
        }
        for t in turns:
            if t.goal_id is None:
                continue
            for a in world.list_attachments(t.goal_id):
                conv_data["attachments"].append({
                    "filename": a.filename, "mime": a.mime,
                    "size_bytes": a.size_bytes, "sha256": a.sha256,
                    "goal_id": a.goal_id,
                })
        data["conversations"].append(conv_data)

    payload = json.dumps(data, indent=2, default=str)
    if output:
        # A GDPR export carries the subject's full conversation content.
        # Create it 0o600 (not the umask's world-readable 0644) so a
        # co-tenant can't read it, and fail cleanly instead of dumping a
        # traceback on a bad/unwritable path.
        try:
            fd = os.open(str(output), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
        except OSError as e:
            raise click.ClickException(f"could not write {output}: {e}")
        click.echo(f"exported to {output}")
    else:
        click.echo(payload)


@main.command()
@click.option("--days", default=90, type=int,
              help="Delete conversations idle longer than N days.")
@click.option("--events-days", default=30, type=int,
              help="Delete goal_events older than N days.")
@click.option("--yes", is_flag=True)
@click.pass_context
def gc(ctx, days: int, events_days: int, yes: bool) -> None:
    """Garbage-collect old conversations and goal_events.

    Tier 1 council finding: retention was "forever" by default; this
    command (plus the systemd timer in deploy/vps/) enforces a policy.
    """
    world = open_world(ctx.obj["db"])
    if not yes:
        click.echo(
            f"This will prune conversations idle > {days}d and "
            f"goal_events older than {events_days}d."
        )
        click.confirm("Proceed?", abort=True)
    convs = world.prune_conversations(idle_for_seconds=days * 24 * 3600)
    events = world.prune_goal_events(older_than_seconds=events_days * 24 * 3600)
    # Twilio dedup rows accumulate one-per-webhook forever; reap after
    # 30 days (the retry window is minutes so this is generous).
    dedup = world.prune_processed_messages(older_than_seconds=30 * 24 * 3600)
    click.echo(
        f"pruned {convs} conversation(s), {events} goal_event row(s), "
        f"{dedup} processed-message row(s)"
    )


@main.group("donate")
def donate() -> None:
    """Opt-in trajectory donation. Default OFF.

    Enable in ~/.maverick/config.toml:
      [telemetry]
      donate_trajectories = true
      donate_text = false  # set true to include task text (off by default)
    """


@donate.command("status")
def donate_status() -> None:
    """Show pending records in the outbox (NOT yet uploaded)."""
    from .donation import _donations_enabled, _text_donations_enabled, list_pending
    click.echo(f"donate_trajectories: {_donations_enabled()}")
    click.echo(f"donate_text:         {_text_donations_enabled()}")
    pending = list_pending()
    if not pending:
        click.echo("outbox: empty")
        return
    click.echo(f"outbox: {len(pending)} record(s) pending")
    for p in pending[:10]:
        click.echo(f"  {p.name}  ({p.stat().st_size} bytes)")


@donate.command("clear")
@click.option("--yes", is_flag=True)
def donate_clear(yes: bool) -> None:
    """Delete every pending donation record without uploading."""
    from .donation import clear_outbox, list_pending
    pending = list_pending()
    if not pending:
        click.echo("outbox: empty (nothing to clear)")
        return
    if not yes:
        click.echo(f"This will delete {len(pending)} pending record(s).")
        click.confirm("Proceed?", abort=True)
    n = clear_outbox()
    click.echo(f"cleared {n} record(s)")




def _watch_goal_allowed(goal_text: str) -> tuple[bool, str | None]:
    """Best-effort Shield scan for watch-mode marker goals."""
    try:
        from maverick_shield import Shield  # type: ignore
    except ImportError:
        return True, None

    try:
        verdict = Shield.from_config().scan_input(goal_text)
    except Exception as exc:  # pragma: no cover
        logging.getLogger(__name__).warning(
            "Shield raised %s during watch --run scan; failing open",
            type(exc).__name__,
        )
        return True, None

    if verdict.allowed:
        return True, None
    return False, f"blocked by Shield ({verdict.severity}): {'; '.join(verdict.reasons)}"

@main.command()
@click.argument("path", type=click.Path(exists=True))
@click.option("--run", is_flag=True, help="Spawn a goal per match (default: print only).")
@click.option("--max-dollars", default=2.0, type=float)
@click.pass_context
@_humane_errors
def watch(ctx, path: str, run: bool, max_dollars: float) -> None:
    """Scan a file or directory for `# AI: <task>` markers and (optionally)
    run each as a goal. One-shot scan; for a long-running watcher use
    `entr` / `watchman` / `fswatch` and pipe to this command."""
    from .watch_mode import scan_dir, scan_file
    p = Path(path)
    matches = scan_file(p) if p.is_file() else scan_dir(p)

    count = 0
    for m in matches:
        count += 1
        click.echo(
            click.style(f"[{m.path}:{m.line_number}] ", fg="bright_black")
            + click.style(f"AI{m.marker}", fg="cyan")
            + f" {m.text}"
        )
        if m.follow_lines:
            for fl in m.follow_lines[:4]:
                click.echo(f"    {fl}")

        if run:
            # Don't sys.exit in the watch loop: just skip this marker and continue.
            if not any(os.environ.get(v) for v in _PROVIDER_ENV_VARS):
                click.echo(
                    "Skipping --run: no provider key set. Run 'maverick init' to configure.",
                    err=True,
                )
                continue
            k = _kernel()
            world = open_world(ctx.obj["db"])
            llm = k.LLM(model=ctx.obj["model"] or k.DEFAULT_MODEL)
            sandbox = k.build_sandbox(workdir=str(p.parent if p.is_file() else p))
            title = (m.text or (m.follow_lines[0] if m.follow_lines else "")).strip()[:80]
            goal_text = m.to_goal()
            allowed, reason = _watch_goal_allowed(goal_text)
            if not allowed:
                click.echo(click.style(f"  skipped: {reason}", fg="yellow"), err=True)
                continue
            goal_id = world.create_goal(title or "watch-mode goal", goal_text)
            click.echo(click.style(f"  -> goal #{goal_id}", fg="bright_black"))
            try:
                result = k.run_goal_sync(
                    llm, world, k.Budget(max_dollars=max_dollars),
                    goal_id, sandbox=sandbox, max_depth=2,
                )
                click.echo(result)
            except Exception as e:
                click.echo(click.style(f"  goal #{goal_id} failed: {e}", fg="red"))

    if count == 0:
        click.echo(f"no AI markers found in {path}")
    else:
        click.echo(f"\nfound {count} marker(s)")


# ----- Audit log ---------------------------------------------------------

@main.group()
def audit() -> None:
    """Inspect the audit log (~/.maverick/audit/YYYY-MM-DD.ndjson)."""


@audit.command("tail")
@click.option("-n", "--num", default=50, type=int, help="Lines to tail.")
@click.option("--day", default=None, help="YYYY-MM-DD (default: today).")
def audit_tail(num: int, day: str | None) -> None:
    """Print the last N audit events."""
    import json as _json

    from .audit import default_audit_log
    for ev in default_audit_log().tail(num, day=day):
        click.echo(_json.dumps(ev, default=str))


@audit.command("grep")
@click.argument("pattern")
@click.option("--day", default=None, help="YYYY-MM-DD (default: today).")
def audit_grep(pattern: str, day: str | None) -> None:
    """Regex grep over today's audit log."""
    import json as _json

    from .audit import default_audit_log
    try:
        events = default_audit_log().grep(pattern, day=day)
    except ValueError as e:
        click.echo(f"error: {e}", err=True)
        sys.exit(2)
    for ev in events:
        click.echo(_json.dumps(ev, default=str))


@audit.command("verify")
@click.option("--day", default=None, help="YYYY-MM-DD (default: today).")
@click.option("--all", "all_days", is_flag=True,
              help="Verify every YYYY-MM-DD.ndjson day-file in the audit dir.")
@click.option("--tenant", default=None,
              help="Tenant whose audit dir to verify (default: active/none).")
@click.option("--file", "file_", default=None, type=click.Path(),
              help="A single audit file to verify (overrides --day/--all).")
@click.option(
    "--pubkey", default=None,
    help="Trusted Ed25519 pubkey (hex). Required for real third-party "
         "tamper-evidence; without it a locally-held key is trusted.",
)
def audit_verify(
    day: str | None, all_days: bool, tenant: str | None,
    file_: str | None, pubkey: str | None,
) -> None:
    """Verify the tamper-evident audit log and exit non-zero on any break.

    Walks the Ed25519 hash-chain of the audit day-file(s) and the cross-file
    tip-ledger, printing a concise OK / per-file break report. Exits 1 if any
    break is found and 0 if clean, so CI / cron / SOC 2 evidence checks can gate
    on it. By default it verifies today's day-file; ``--all`` sweeps every
    day-file in the audit dir. Only meaningful when audit signing is enabled
    ([audit] sign = true).

    If ``cryptography`` is unavailable the chain can't be verified at all; that
    is reported as a verification break and exits 1 so automation cannot pass
    unverifiable evidence as clean.
    """
    import datetime as _dt
    from pathlib import Path as _Path

    from .audit import verify_anchors, verify_chain
    from .paths import data_dir

    # Resolve the audit dir tenant-aware (matching the writer/signer), unless an
    # explicit --file pins one file in some other location.
    audit_dir = data_dir("audit", tenant=tenant) if tenant else data_dir("audit")

    if file_:
        paths = [_Path(file_)]
        anchor_dir = paths[0].parent
    elif all_days:
        # The anchor ledger is verified separately as the tip-ledger; don't
        # also walk it as if it were a day-file.
        paths = [p for p in sorted(audit_dir.glob("*.ndjson"))
                 if p.name != "anchors.ndjson"]
        anchor_dir = audit_dir
        if not paths:
            click.echo(f"no audit day-files in {audit_dir}")
    else:
        d = day or _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
        paths = [audit_dir / f"{d}.ndjson"]
        anchor_dir = audit_dir

    if not pubkey:
        click.echo(
            "warning: no --pubkey given; trusting a locally-held key. For "
            "third-party tamper-evidence, pass the externally-held pubkey.",
            err=True,
        )

    any_break = False
    for path in paths:
        breaks = verify_chain(path, pubkey_hex=pubkey)
        if breaks:
            any_break = True
            click.echo(f"FAIL: {len(breaks)} issue(s) in {path}", err=True)
            for b in breaks:
                click.echo(f"  line {b.line_no}: {b.reason} — {b.detail}", err=True)
        else:
            click.echo(f"OK: chain intact ({path})")

    # Cross-file check: a whole deleted/truncated day-file is invisible to the
    # per-file chain above; the signed tip-ledger catches it.
    anchor_breaks = verify_anchors(anchor_dir, pubkey_hex=pubkey)
    if anchor_breaks:
        any_break = True
        click.echo(
            f"FAIL: {len(anchor_breaks)} cross-file tip-ledger issue(s) in {anchor_dir}",
            err=True,
        )
        for b in anchor_breaks:
            click.echo(f"  anchor: {b.reason} — {b.detail}", err=True)
    else:
        click.echo(f"OK: tip-ledger intact ({anchor_dir})")

    if any_break:
        raise SystemExit(1)


# ----- Killswitch --------------------------------------------------------

@main.command()
@click.option("--reason", default="manual halt", help="Why you're halting.")
def halt(reason: str) -> None:
    """Halt all in-flight goals by writing the HALT file."""
    from .killswitch import _halt_file_path
    p = _halt_file_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(reason + "\n")
    click.echo(f"halt set: {p}")


@main.command("unhalt")
def unhalt() -> None:
    """Remove the HALT file to allow goals to run again."""
    from .killswitch import _halt_file_path
    p = _halt_file_path()
    if p.exists():
        p.unlink()
        click.echo(f"cleared: {p}")
    else:
        click.echo(f"no halt file at {p}")


# ----- Cost / export / logs --------------------------------------------

@main.command()
@click.option("--month", default=None, help="YYYY-MM (default: lifetime totals).")
@click.option("--model", default=None, help="Filter to one model id.")
@click.option("--csv", "csv_out", is_flag=True,
              help="Output one row per episode in CSV format.")
@click.pass_context
def cost(ctx, month: str | None, model: str | None, csv_out: bool) -> None:
    """Summarize spend across the world model."""
    world = open_world(ctx.obj["db"])
    try:
        episodes = world.list_episodes(limit=100_000 if csv_out else 10_000)
    finally:
        world.close()
    if month:
        import datetime as _dt
        try:
            m_start = _dt.datetime.strptime(month, "%Y-%m")
        except ValueError:
            raise click.ClickException("--month must be YYYY-MM (e.g. 2026-05)")
        start = m_start.timestamp()
        # True next-month boundary (a fixed +31 days over-counted short months,
        # e.g. Feb pulled in early March).
        end = _dt.datetime(
            m_start.year + (m_start.month == 12),
            (m_start.month % 12) + 1,
            1,
        ).timestamp()
        episodes = [
            e for e in episodes
            if start <= (e.started_at or 0) < end
        ]
    if model:
        # Outcome strings carry model id in the format "model=X ...".
        episodes = [e for e in episodes if model in (e.outcome or "")]

    if csv_out:
        import csv as _csv
        writer = _csv.writer(sys.stdout)
        writer.writerow([
            "episode_id", "goal_id", "started_at", "ended_at", "outcome",
            "dollars", "input_tokens", "output_tokens", "tool_calls",
        ])
        for e in episodes:
            writer.writerow([
                e.id, e.goal_id,
                e.started_at, e.ended_at or "",
                e.outcome or "",
                f"{(e.cost_dollars or 0):.6f}",
                e.input_tokens, e.output_tokens, e.tool_calls,
            ])
        return

    total = sum((e.cost_dollars or 0) for e in episodes)
    in_tok = sum((e.input_tokens or 0) for e in episodes)
    out_tok = sum((e.output_tokens or 0) for e in episodes)
    tool_calls = sum((e.tool_calls or 0) for e in episodes)
    click.echo(f"Episodes:    {len(episodes):>10}")
    click.echo(f"Dollars:     ${total:.4f}")
    click.echo(f"Input tok:   {in_tok:>10,}")
    click.echo(f"Output tok:  {out_tok:>10,}")
    click.echo(f"Tool calls:  {tool_calls:>10,}")


@main.command("export")
@click.argument("goal_id", type=int)
@click.option("-o", "--output", type=click.Path(),
              help="Path for the bundle (default: ./goal-<id>.json).")
@click.pass_context
def export_goal(ctx, goal_id: int, output: str | None) -> None:
    """Export a goal's full trajectory as a portable JSON bundle.

    The bundle includes the goal record, all child goals, every event,
    and the episode summaries. No prompt content is included unless it
    was logged to events.
    """
    import json as _json
    world = open_world(ctx.obj["db"])
    try:
        goal = world.get_goal(goal_id)
        if goal is None:
            click.echo(f"goal {goal_id} not found", err=True)
            sys.exit(2)
        events = world.goal_events(goal_id, limit=10_000)
        episodes = world.list_episodes(limit=200, goal_id=goal_id)
        from dataclasses import asdict
        bundle = {
            "v": 1,
            "goal": asdict(goal),
            "events": [asdict(e) for e in events],
            "episodes": [asdict(e) for e in episodes],
        }
    finally:
        world.close()
    out_path = Path(output) if output else Path(f"goal-{goal_id}.json")
    try:
        out_path.write_text(_json.dumps(bundle, default=str, indent=2))
    except OSError as e:
        raise click.ClickException(f"could not write {out_path}: {e}")
    click.echo(f"wrote {out_path}")


@main.command("logs")
@click.argument("pattern", required=False)
@click.option("-n", "--num", default=200, type=int, help="Lines to show.")
@click.option("--day", default=None, help="YYYY-MM-DD (default: today).")
def logs_cmd(pattern: str | None, num: int, day: str | None) -> None:
    """Show recent audit log entries (optionally regex-filtered).

    Equivalent to `maverick audit grep <pattern>` or `audit tail -n N`.
    """
    import json as _json

    from .audit import default_audit_log
    al = default_audit_log()
    try:
        rows = al.grep(pattern, day=day) if pattern else al.tail(num, day=day)
    except ValueError as e:
        click.echo(f"error: {e}", err=True)
        sys.exit(2)
    for r in rows[-num:]:
        click.echo(_json.dumps(r, default=str))


# ----- SOC 2 evidence --------------------------------------------------

_REQUIRED_SOC2_CONTROLS = (
    "capability_enforcement",
    "tenant_isolation",
    "usage_quotas",
    "oidc_auth",
)


def _soc2_posture_ready(evidence) -> bool:
    """Return True only when required SOC 2 controls report a ready posture."""
    controls = evidence.get("controls", {}) if isinstance(evidence, dict) else {}
    if not isinstance(controls, dict):
        return False
    for control in _REQUIRED_SOC2_CONTROLS:
        probe = controls.get(control, {})
        if not isinstance(probe, dict) or probe.get("status") != "enabled":
            return False

    audit_log = evidence.get("audit_log", {}) if isinstance(evidence, dict) else {}
    if not isinstance(audit_log, dict) or audit_log.get("status") != "ok":
        return False

    signing_key = evidence.get("audit_signing_key", {}) if isinstance(evidence, dict) else {}
    return isinstance(signing_key, dict) and signing_key.get("status") == "enabled"


@main.command("soc2")
@click.option("--json", "compact", is_flag=True,
              help="Emit compact single-line JSON (default: pretty, indent=2).")
def soc2(compact: bool) -> None:
    """Print a SOC 2 technical-posture snapshot as JSON.

    Serializes ``collect_soc2_evidence()`` -- which controls are ON in this
    deployment and whether the audit log verifies -- for auditors / CI /
    automation. The collector is fail-soft (it never raises), so this command
    always emits a JSON object. The command exits non-zero when required
    controls or audit-log checks are not in a SOC 2-ready state.
    """
    import json as _json

    from .soc2 import collect_soc2_evidence
    evidence = collect_soc2_evidence()
    if compact:
        click.echo(_json.dumps(evidence, default=str))
    else:
        click.echo(_json.dumps(evidence, default=str, indent=2))
    if not _soc2_posture_ready(evidence):
        sys.exit(1)


# ----- DSAR subject-data export ----------------------------------------

@main.group("dsar")
def dsar_group() -> None:
    """Data-subject access requests (GDPR Art. 15 / 20)."""


@dsar_group.command("export")
@click.option("--user", "user_id", required=True,
              help="The channel user_id (subject) to export.")
@click.option("--tenant", default=None, help="Tenant to read from (default: active).")
@click.option("--output", "-o", type=click.Path(), default=None,
              help="Write JSON to file (default stdout).")
@click.option("--json", "compact", is_flag=True,
              help="Emit compact single-line JSON (default: pretty, indent=2).")
def dsar_export(user_id: str, tenant: str | None, output, compact: bool) -> None:
    """Export everything Maverick holds for a subject as a JSON bundle.

    Serializes ``export_subject_data()`` -- the subject's conversations, the
    turns/goals/episodes those reference, and their audit rows -- for the
    right of access / portability. The exporter is fail-soft (an unknown
    subject or empty install yields a structured, empty bundle), so this
    command always emits a JSON object and exits 0.
    """
    import json as _json

    from .dsar import export_subject_data
    bundle = export_subject_data(user_id, tenant=tenant)
    payload = (
        _json.dumps(bundle, default=str)
        if compact
        else _json.dumps(bundle, default=str, indent=2)
    )
    if output:
        # A DSAR export carries the subject's full conversation content.
        # Create it 0o600 (not the umask's world-readable 0644) so a
        # co-tenant can't read it, and fail cleanly instead of dumping a
        # traceback on a bad/unwritable path.
        try:
            fd = os.open(str(output), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
        except OSError as e:
            raise click.ClickException(f"could not write {output}: {e}")
        click.echo(f"exported to {output}")
    else:
        click.echo(payload)


# ----- Cache management ------------------------------------------------

@main.group("cache")
def cache_group() -> None:
    """Inspect and clear in-process caches (file reads, repo map, embeddings)."""


@cache_group.command("stats")
def cache_stats_cmd() -> None:
    """Show cache sizes."""
    import json as _json

    from .cache import stats
    click.echo(_json.dumps(stats(), default=str, indent=2))


@cache_group.command("purge")
@click.option(
    "--scope", "scopes", multiple=True,
    type=click.Choice(["files", "repo_map", "skill_embeddings", "all"]),
    help="Scope to purge (repeatable). Default: all.",
)
def cache_purge_cmd(scopes: tuple[str, ...]) -> None:
    """Purge cache(s)."""
    import json as _json

    from .cache import purge
    report = purge(scopes or ("all",))
    click.echo(_json.dumps(report, default=str, indent=2))


# ----- Retention enforcement ------------------------------------------

@main.group("retention")
def retention_group() -> None:
    """Enforce ~/.maverick/config.toml [retention] rules."""


@retention_group.command("enforce")
@click.option("--dry-run", is_flag=True, help="Report what would be removed.")
@click.option("--audit-days", type=int, default=None,
              help="Override [retention].audit_days.")
@click.option("--episodes-days", type=int, default=None,
              help="Override [retention].episodes_days.")
@click.option("--events-days", type=int, default=None,
              help="Override [retention].events_days.")
def retention_enforce_cmd(
    dry_run: bool,
    audit_days: int | None,
    episodes_days: int | None,
    events_days: int | None,
) -> None:
    """Apply retention rules to the audit log and world model."""
    import json as _json

    from .audit.retention import enforce
    # CLI overrides take precedence if any are set; otherwise read config.
    cfg: dict | None = None
    if any(v is not None for v in (audit_days, episodes_days, events_days)):
        cfg = {}
        if audit_days is not None:
            cfg["audit_days"] = audit_days
        if episodes_days is not None:
            cfg["episodes_days"] = episodes_days
        if events_days is not None:
            cfg["events_days"] = events_days
    report = enforce(config=cfg, dry_run=dry_run)
    click.echo(_json.dumps(report, default=str, indent=2))


if __name__ == "__main__":
    main()
