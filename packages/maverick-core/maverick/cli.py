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
            result = run_goal_sync(
                llm, world, bud, goal_id,
                sandbox=sandbox, max_depth=max_depth,
            )
    finally:
        stop_poll.set()
        if poller is not None:
            poller.join(timeout=2.0)
    click.echo("")
    click.echo(result)


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
                content = e.content[:200]
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
            return


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


@main.command()
@click.option("--channel", required=True, help="Channel name (e.g. telegram, sms).")
@click.option("--user", required=True, help="The channel user_id to erase.")
@click.option("--yes", is_flag=True, help="Skip confirmation.")
@click.pass_context
def erase(ctx, channel: str, user: str, yes: bool) -> None:
    """GDPR Art. 17 right-to-erasure: delete everything Maverick knows
    about a given (channel, user_id) — conversations, turns, attachments
    on disk, and the conversation row itself."""
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

    # Step 2: collect attachment paths to unlink (after commit).
    attachment_paths: list[str] = []
    for gid in goal_ids:
        for a in world.list_attachments(gid):
            attachment_paths.append(a.path)

    # Step 3: cascade DELETEs in a single transaction.
    removed_turns = 0
    try:
        world.conn.execute("BEGIN IMMEDIATE")
        cur = world.conn.execute(
            f"DELETE FROM turns WHERE conversation_id IN ({placeholders})",
            conv_ids,
        )
        removed_turns = cur.rowcount

        if goal_ids:
            gph = ",".join("?" * len(goal_ids))
            gids = list(goal_ids)
            # Order matters: children before parents (FK now enforced).
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

    click.echo(
        f"erased {len(convs)} conversation(s), {removed_turns} turn(s), "
        f"{len(goal_ids)} goal(s) and all linked rows, "
        f"{removed_attachments} attachment file(s)"
    )


@main.command()
@click.option("--channel", required=True, help="Channel name.")
@click.option("--user", required=True, help="The channel user_id to export.")
@click.option("--output", "-o", type=click.Path(), default=None,
              help="Write JSON to file (default stdout).")
@click.pass_context
def export(ctx, channel: str, user: str, output) -> None:
    """GDPR Art. 15 right-of-access: dump everything Maverick knows about
    a given (channel, user_id) as JSON."""
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
            if not os.environ.get("ANTHROPIC_API_KEY"):
                click.echo("ERROR: ANTHROPIC_API_KEY not set; skipping --run.", err=True)
                continue
            world = WorldModel(ctx.obj["db"])
            llm = LLM(model=ctx.obj["model"])
            sandbox = build_sandbox(workdir=str(p.parent if p.is_file() else p))
            title = (m.text or m.follow_lines[0] if m.follow_lines else "").strip()[:80]
            goal_id = world.create_goal(title or "watch-mode goal", m.to_goal())
            click.echo(click.style(f"  -> goal #{goal_id}", fg="bright_black"))
            try:
                result = run_goal_sync(
                    llm, world, Budget(max_dollars=max_dollars),
                    goal_id, sandbox=sandbox, max_depth=2,
                )
                click.echo(result)
            except Exception as e:
                click.echo(click.style(f"  goal #{goal_id} failed: {e}", fg="red"))

    if count == 0:
        click.echo(f"no AI markers found in {path}")
    else:
        click.echo(f"\nfound {count} marker(s)")


if __name__ == "__main__":
    main()
