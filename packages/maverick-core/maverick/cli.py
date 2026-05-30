"""Maverick CLI."""
from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
from pathlib import Path

import click

# Council round-2 perf-seat fix: keep the top-level import surface
# minimal so `maverick --help` and `maverick version` don't pay for
# heavy submodules (orchestrator, agent, swarm, skills, sandbox) they
# never use. Submodules import lazily inside the command bodies that
# actually need them. `world_model` stays at module top — its imports
# are stdlib (sqlite3, dataclasses, pathlib) and the DEFAULT_DB
# constant is used in the click option default below.
from .world_model import DEFAULT_DB, WorldModel  # noqa: E402  -- cheap stdlib chain


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


def _require_llm_key() -> str:
    """Council UX/capabilities fix: don't sys.exit(2) on missing ANTHROPIC_API_KEY.

    First, check every supported provider's env var; return the first
    one set (the LLM facade dispatches on model id, not env var, so any
    valid provider config is fine). If none, print an actionable error
    that points at ``maverick init`` and exit cleanly.
    """
    for var in _PROVIDER_ENV_VARS:
        if os.environ.get(var):
            return var
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
    from .llm import LLM, DEFAULT_MODEL
    from .orchestrator import run_goal_sync
    from .sandbox import build_sandbox
    from .secrets import scrub
    return types.SimpleNamespace(
        Budget=Budget, LLM=LLM, DEFAULT_MODEL=DEFAULT_MODEL,
        run_goal_sync=run_goal_sync, build_sandbox=build_sandbox, scrub=scrub,
    )


@click.group()
@click.option("--db", default=str(DEFAULT_DB), help="World model database path.")
@click.option("--model", default=None, help="LLM model id (default: from config).")
@click.pass_context
def main(ctx: click.Context, db: str, model: str | None) -> None:
    """Maverick: multi-agent swarm for long-horizon work."""
    ctx.ensure_object(dict)
    ctx.obj["db"] = Path(db)
    ctx.obj["model"] = model  # resolved lazily on first use


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
        s = Shield.from_config()
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
        editor = os.environ.get("EDITOR", "nano")
        os.execvp(editor, [editor, str(p)])
        return
    if not p.exists():
        click.echo(f"No config at {p}. Run:  maverick init", err=True)
        sys.exit(1)
    click.echo(p.read_text(encoding="utf-8"))


@main.command()
@click.pass_context
def budget(ctx) -> None:
    """Show total spend + per-run cost history."""
    world = WorldModel(ctx.obj["db"])
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
def mcp() -> None:
    """Start the MCP server on stdio.

    This is Maverick's official cross-language surface. Any MCP-speaking
    client (TypeScript, Go, Rust, .NET, JVM, plus every IDE-side MCP
    client like Claude Code / Cursor / Continue / Zed) can drive the
    swarm from outside Python via this command. See
    docs/clients/typescript-quickstart.md for a 20-line example.
    """
    try:
        from maverick_mcp.server import main as mcp_main
    except ImportError:
        click.echo("Install: pip install maverick-mcp-server", err=True)
        sys.exit(2)
    mcp_main()


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
              type=click.Choice(["local", "docker", "ssh", "firecracker"]))
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
@click.pass_context
def start(
    ctx, title, description, template_name, params,
    max_dollars, max_wall_seconds, max_depth, workdir, sandbox_backend,
    coding_mode, best_of_n, fail_to_pass, pass_to_pass,
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

    k = _kernel()
    world = WorldModel(ctx.obj["db"])
    goal_id = world.create_goal(title, description)
    click.echo(f"goal #{goal_id} created: {title}")
    llm = k.LLM(model=ctx.obj["model"] or k.DEFAULT_MODEL)
    bud = k.Budget(
        max_dollars=max_dollars or 5.0,
        max_wall_seconds=max_wall_seconds or 3600.0,
    )
    sandbox = k.build_sandbox(workdir=workdir, backend=sandbox_backend)

    # Council UX finding: `maverick start "..."` used to look hung
    # between "goal created" and the final printout. A background poller
    # streams goal_events to stderr so the user sees the swarm thinking
    # in real time. Non-tty output (e.g. piped to a file) skips the
    # poller so logs aren't littered with progress lines.
    import threading
    stop_poll = threading.Event()
    if not click.get_text_stream("stderr").isatty() or os.environ.get("MAVERICK_NO_PROGRESS"):
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
        wm = WorldModel(db_path)
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
def chat(ctx, max_depth: int, max_dollars: float, workdir) -> None:
    """Interactive chat REPL. Each turn becomes a goal.

    Multi-line input: end a line with ``\\`` to continue, or open with
    ``\"\"\"`` to enter a paste block ending with ``\"\"\"`` on its own line.
    """
    _require_llm_key()
    k = _kernel()
    world = WorldModel(ctx.obj["db"])
    llm = k.LLM(model=ctx.obj["model"] or k.DEFAULT_MODEL)
    sandbox = k.build_sandbox(workdir=workdir)
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
        click.echo(click.style(f"  ... goal #{goal_id}", fg="bright_black"))
        bud = k.Budget(max_dollars=max_dollars)
        try:
            result = k.run_goal_sync(llm, world, bud, goal_id,
                                   sandbox=sandbox, max_depth=max_depth)
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


@main.command()
@click.option("--max-depth", default=3, type=int)
@click.option("--verbose", "-v", is_flag=True)
def serve(max_depth: int, verbose: bool) -> None:
    """Start the channel server."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
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
    world = WorldModel(ctx.obj["db"])
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
    world = WorldModel(ctx.obj["db"])
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
    world = WorldModel(ctx.obj["db"])
    world.answer(question_id, " ".join(answer))
    click.echo(f"answered #{question_id}")


@main.command()
@click.option("--goal-id", type=int, default=None)
@click.option("--max-depth", default=3, type=int)
@click.pass_context
def resume(ctx, goal_id, max_depth: int) -> None:
    """Resume a blocked goal."""
    _require_llm_key()
    world = WorldModel(ctx.obj["db"])
    if goal_id is None:
        g = world.active_goal()
        if not g:
            click.echo("no active or blocked goal to resume.")
            return
        goal_id = g.id
    open_qs = world.open_questions(goal_id)
    if open_qs:
        click.echo(f"cannot resume goal #{goal_id}: {len(open_qs)} open question(s).")
        for q in open_qs:
            click.echo(f"  #{q.id}: {q.question}")
        return
    k = _kernel()
    llm = k.LLM(model=ctx.obj["model"] or k.DEFAULT_MODEL)
    bud = k.Budget()
    result = k.run_goal_sync(llm, world, bud, goal_id, max_depth=max_depth)
    click.echo(result)


@main.command()
@click.argument("key")
@click.argument("value", nargs=-1, required=True)
@click.pass_context
def fact(ctx, key: str, value: tuple[str, ...]) -> None:
    """Set a fact in the world model."""
    world = WorldModel(ctx.obj["db"])
    world.upsert_fact(key, " ".join(value))
    click.echo(f"set {key}")


@main.command()
@click.pass_context
def facts(ctx) -> None:
    """List known facts."""
    world = WorldModel(ctx.obj["db"])
    for k, v in world.get_facts().items():
        click.echo(f"  {k}: {v}")


@main.command()
def skills() -> None:
    """List skills the swarm has distilled or installed."""
    from .skills import SKILLS_DIR, load_skills
    items = load_skills()
    if not items:
        click.echo(f"no skills yet (in {SKILLS_DIR}).")
        return
    for s in items:
        click.echo(f"  {s.name}")
        for t in s.triggers[:3]:
            click.echo(f"    trigger: {t}")


@main.group()
def plugin() -> None:
    """Scaffold + manage Maverick plugins."""


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
    from .plugin_scaffold import scaffold, ScaffoldError
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
    removed = cookie_store.clear_session(provider)
    if removed:
        click.echo(f"Cleared session for {provider}")
    else:
        click.echo(f"No session stored for {provider}", err=True)
        sys.exit(1)


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
    world = WorldModel(ctx.obj["db"])
    convs = [
        c for c in world.list_conversations(channel)
        if c.user_id == user
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

    # Step 5: scrub the subject from PRIOR audit-log lines. Audit payloads
    # (goal_start / tool_call / channel events) carry channel:user_id, so
    # without this the identity we just erased stayed readable in
    # ~/.maverick/audit/*.ndjson -- an Art.17 gap (scrub_user was dead
    # code, never called). Done BEFORE recording the erase event below so
    # that event (which hashes the subject) isn't itself scrubbed.
    # NOTE: if [audit] sign is enabled, rewriting lines breaks the
    # hash-chain; `maverick audit verify` will then report a discontinuity
    # at the erasure point. Re-anchoring a signed chain post-erasure is a
    # tracked follow-up; leaving PII in place would violate Art.17.
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

    # GDPR Art. 30: record that an erasure happened without deriving a stable
    # identifier from the subject. Low-entropy user IDs (phone numbers, short
    # handles, numeric IDs) are enumerable, so even a truncated hash can
    # re-identify the erased person if audit logs are read.
    import secrets

    from . import audit
    audit.record(
        "erase",
        channel=channel,
        erasure_id=secrets.token_hex(8),
        conversations=len(convs),
        turns=removed_turns,
        goals=len(goal_ids),
        attachments=removed_attachments,
        audit_lines_scrubbed=audit_scrubbed,
    )

    # GDPR Art. 17 completeness: the DB rows + files are gone, but the
    # agent also wrote goal/turn text into the audit NDJSON. Tombstone the
    # subject there too, or erasure leaks the very data it promised to
    # remove. (The erase record above hashes the subject, so this won't
    # match it.)
    scrubbed = 0
    try:
        scrubbed, _ = audit.scrub_user(channel, user)
    except Exception as e:  # never fail the erasure on a scrub hiccup
        click.echo(f"⚠ audit-log scrub failed: {e}", err=True)

    click.echo(
        f"erased {len(convs)} conversation(s), {removed_turns} turn(s), "
        f"{len(goal_ids)} goal(s) and all linked rows, "
        f"{removed_attachments} attachment file(s), "
        f"{scrubbed} audit event(s) scrubbed"
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
    world = WorldModel(ctx.obj["db"])
    convs = [
        c for c in world.list_conversations(channel)
        if c.user_id == user
    ]
    data = {
        "channel": channel,
        "user_id": user,
        "conversations": [],
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
        Path(output).write_text(payload, encoding="utf-8")
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
    world = WorldModel(ctx.obj["db"])
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
            world = WorldModel(ctx.obj["db"])
            llm = k.LLM(model=ctx.obj["model"] or k.DEFAULT_MODEL)
            sandbox = k.build_sandbox(workdir=str(p.parent if p.is_file() else p))
            title = (m.text or m.follow_lines[0] if m.follow_lines else "").strip()[:80]
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
    for ev in default_audit_log().grep(pattern, day=day):
        click.echo(_json.dumps(ev, default=str))


@audit.command("verify")
@click.option("--day", default=None, help="YYYY-MM-DD (default: today).")
@click.option("--file", "file_", default=None, type=click.Path(), help="Audit file to verify.")
@click.option(
    "--pubkey", default=None,
    help="Trusted Ed25519 pubkey (hex). Required for real third-party "
         "tamper-evidence; without it a locally-held key is trusted.",
)
def audit_verify(day: str | None, file_: str | None, pubkey: str | None) -> None:
    """Verify the Ed25519 hash-chain of a (signed) audit log.

    Reports any broken links/signatures. Exits non-zero if the chain is
    not intact, so it can gate CI / cron checks. Only meaningful when
    audit signing is enabled ([audit] sign = true).
    """
    import datetime as _dt
    from pathlib import Path as _Path

    from .audit import verify_chain
    from .audit.writer import DEFAULT_AUDIT_DIR

    if file_:
        path = _Path(file_)
    else:
        d = day or _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
        path = DEFAULT_AUDIT_DIR / f"{d}.ndjson"

    if not pubkey:
        click.echo(
            "warning: no --pubkey given; trusting a locally-held key. For "
            "third-party tamper-evidence, pass the externally-held pubkey.",
            err=True,
        )
    breaks = verify_chain(path, pubkey_hex=pubkey)
    if not breaks:
        click.echo(f"OK: chain intact ({path})")
        return
    click.echo(f"FAIL: {len(breaks)} issue(s) in {path}", err=True)
    for b in breaks:
        click.echo(f"  line {b.line_no}: {b.reason} — {b.detail}", err=True)
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
    world = WorldModel(ctx.obj["db"])
    try:
        episodes = world.list_episodes(limit=100_000 if csv_out else 10_000)
    finally:
        world.close()
    if month:
        import datetime as _dt
        start = _dt.datetime.strptime(month, "%Y-%m").timestamp()
        # End-of-month: add ~31 days and trim by month.
        end = start + 31 * 86_400
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
    world = WorldModel(ctx.obj["db"])
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
    out_path.write_text(_json.dumps(bundle, default=str, indent=2))
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
    rows = al.grep(pattern, day=day) if pattern else al.tail(num, day=day)
    for r in rows[-num:]:
        click.echo(_json.dumps(r, default=str))


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
