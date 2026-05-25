"""Maverick CLI."""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

import click

from .budget import Budget
from .llm import DEFAULT_MODEL, LLM
from .orchestrator import run_goal_sync
from .sandbox import build_sandbox
from .skills import (
    SKILLS_DIR,
    install_skill,
    load_skills,
    remove_skill,
)
from .world_model import DEFAULT_DB, WorldModel


@click.group()
@click.option("--db", default=str(DEFAULT_DB), help="World model database path.")
@click.option("--model", default=DEFAULT_MODEL, help="LLM model id.")
@click.pass_context
def main(ctx: click.Context, db: str, model: str) -> None:
    """Maverick: multi-agent swarm for long-horizon work."""
    ctx.ensure_object(dict)
    ctx.obj["db"] = Path(db)
    ctx.obj["model"] = model


@main.command()
def init() -> None:
    """Run the interactive setup wizard."""
    try:
        from maverick_installer.wizard import run as run_wizard
    except ImportError:
        click.echo("Install: pipx install maverick-installer", err=True)
        sys.exit(2)
    sys.exit(run_wizard())


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
        ("maverick-mcp",       ("maverick-mcp",)),
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
    click.echo(p.read_text())


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
    """Start the MCP server on stdio."""
    try:
        from maverick_mcp.server import main as mcp_main
    except ImportError:
        click.echo("Install: pip install maverick-mcp", err=True)
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
              type=click.Choice(["local", "docker", "ssh"]))
@click.pass_context
def start(
    ctx, title, description, template_name, params,
    max_dollars, max_wall_seconds, max_depth, workdir, sandbox_backend,
) -> None:
    """Start a new goal and run the swarm."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        click.echo("ERROR: ANTHROPIC_API_KEY not set. Run: maverick doctor", err=True)
        sys.exit(2)
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

    world = WorldModel(ctx.obj["db"])
    goal_id = world.create_goal(title, description)
    click.echo(f"goal #{goal_id} created: {title}")
    llm = LLM(model=ctx.obj["model"])
    bud = Budget(
        max_dollars=max_dollars or 5.0,
        max_wall_seconds=max_wall_seconds or 3600.0,
    )
    sandbox = build_sandbox(workdir=workdir, backend=sandbox_backend)
    result = run_goal_sync(llm, world, bud, goal_id, sandbox=sandbox, max_depth=max_depth)
    click.echo("")
    click.echo(result)


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
    if not os.environ.get("ANTHROPIC_API_KEY"):
        click.echo("ERROR: ANTHROPIC_API_KEY not set.", err=True)
        sys.exit(2)
    world = WorldModel(ctx.obj["db"])
    llm = LLM(model=ctx.obj["model"])
    sandbox = build_sandbox(workdir=workdir)
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
        bud = Budget(max_dollars=max_dollars)
        try:
            result = run_goal_sync(llm, world, bud, goal_id,
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


@main.command()
@click.option("--limit", default=20, type=int)
@click.pass_context
def logs(ctx, limit: int) -> None:
    """Show recent goal + episode history."""
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
    if not os.environ.get("ANTHROPIC_API_KEY"):
        click.echo("ERROR: ANTHROPIC_API_KEY not set.", err=True)
        sys.exit(2)
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
    llm = LLM(model=ctx.obj["model"])
    bud = Budget()
    result = run_goal_sync(llm, world, bud, goal_id, max_depth=max_depth)
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
    items = load_skills()
    if not items:
        click.echo(f"no skills yet (in {SKILLS_DIR}).")
        return
    for s in items:
        click.echo(f"  {s.name}")
        for t in s.triggers[:3]:
            click.echo(f"    trigger: {t}")


@main.group()
def skill() -> None:
    """Manage skills (install, remove, info)."""


@skill.command("install")
@click.argument("source")
def skill_install(source: str) -> None:
    """Install a SKILL.md."""
    try:
        s = install_skill(source)
    except ValueError as e:
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(2)
    click.echo(f"installed: {s.name} -> {s.path}")


@skill.command("remove")
@click.argument("name")
def skill_remove(name: str) -> None:
    if remove_skill(name):
        click.echo(f"removed: {name}")
    else:
        click.echo(f"no skill named {name!r}", err=True)
        sys.exit(2)


@skill.command("info")
@click.argument("name")
def skill_info(name: str) -> None:
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


if __name__ == "__main__":
    main()
