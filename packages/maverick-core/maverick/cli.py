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
# are stdlib (sqlite3, dataclasses, pathlib) and `open_world` is used
# by nearly every command below.
from .world_model import open_world  # noqa: E402  -- cheap stdlib chain

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
    """True if any provider surface is configured (shared predicate).

    Delegates to ``maverick.config.any_provider_configured`` so the CLI
    preflight, the LLM clients, and the dashboard agree on what "configured"
    means: well-known key env vars, self-hosted base-URL env vars
    (``VLLM_BASE_URL`` / ``TGI_BASE_URL`` / ``OPENAI_COMPATIBLE_BASE_URL``),
    or a ``[providers.<name>]`` table with a non-empty ``api_key`` /
    ``base_url``. Before this, each component implemented a different subset
    and a keyless self-hosted setup passed one gate and failed the next.
    """
    try:
        from .config import any_provider_configured
        return any_provider_configured()
    except Exception:  # pragma: no cover -- never block on a config read
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


def _run_outcome_blocked(world, goal_id: int) -> bool:
    """True if the goal ended in the kernel's ``blocked`` state -- paused
    awaiting a user answer, stopped by a budget/time cap, or refused by an
    input guard. ``start`` reads this before closing the world DB so it can
    exit nonzero for a halted/paused run (it used to always exit 0); a genuine
    ``done`` completion stays 0."""
    try:
        g = world.get_goal(goal_id)
    except Exception:  # pragma: no cover -- a status read must not mask the result
        return False
    return bool(g and g.status == "blocked")


def _maybe_start_progress_poller(world_path, goal_id, stop_poll):
    """Start the background goal-events poller, or return None when it should
    stay quiet: output isn't a TTY (don't litter piped logs), MAVERICK_NO_PROGRESS
    is set (runtime override), or [features] streaming is off (persistent opt-out)."""
    import threading

    from .config import get_features
    try:
        streaming_on = get_features()["streaming"]
    except Exception:
        streaming_on = True
    if (not click.get_text_stream("stderr").isatty()
            or os.environ.get("MAVERICK_NO_PROGRESS")
            or not streaming_on):
        return None
    poller = threading.Thread(
        target=_stream_progress, args=(world_path, goal_id, stop_poll), daemon=True,
    )
    poller.start()
    return poller


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
@click.option("--db", default=None,
              help="World model database path (default: the active tenant's world.db).")
@click.option("--model", default=None, help="LLM model id (default: from config).")
@click.pass_context
def main(ctx: click.Context, db: str | None, model: str | None) -> None:
    """Maverick: multi-agent swarm for long-horizon work."""
    _configure_cli_logging()
    ctx.ensure_object(dict)
    # Default the world DB to the ACTIVE TENANT's world.db (selected via
    # MAVERICK_TENANT) so one business's run history / goals / facts never pool
    # into another's -- the same isolation the channel server already gets via
    # world_for_tenant(). With no tenant this resolves to the legacy
    # ~/.maverick/world.db, so single-tenant installs are unchanged. An explicit
    # --db always wins.
    if db is None:
        from .workspace import Workspace
        db = str(Workspace.current().db_path)
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
    if diagnose():
        # At least one ✗ check: exit nonzero so `maverick doctor && ...` and CI
        # health gates can detect a broken install (it always exited 0 before).
        sys.exit(1)


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
@click.option("--name", default=None, help="Business name (otherwise prompted).")
@click.option("--doc", "docs", multiple=True,
              help="Path to a document to ingest (repeatable).")
@click.option("--no-llm", is_flag=True,
              help="Use deterministic generation instead of the configured LLM.")
@click.option("--description", default=None,
              help="What the business does (skips the prompt; for non-interactive use).")
@click.option("--industry", default=None,
              help="Industry (skips the prompt; for non-interactive use).")
@click.option("--yes", is_flag=True, help="Skip the approval prompt.")
@click.pass_context
def onboard(ctx: click.Context, name, docs, no_llm, description, industry, yes) -> None:
    """Onboard a business: describe it + attach docs -> a sealed domain agent.

    Generates a domain pack (clamped to a safe envelope), shows it for your
    approval, and on approval saves it so the sealed, knowledge-loaded agent
    goes live. Nothing is activated without your yes.
    """
    from .intake import IntakeSpec, attach_docs_to_profile, run_intake, save_profile

    # Only prompt when a human is attached (a TTY). In non-interactive use (CI,
    # piped stdin) the intake prompts used to fire and then abort even with
    # --name/--no-llm/--yes supplied, so onboarding could not be automated
    # (user-testing finding). Pass --name/--description/--industry/--doc instead.
    interactive = sys.stdin.isatty()
    if not name:
        if not interactive:
            click.echo("ERROR: --name is required for non-interactive onboarding.", err=True)
            sys.exit(2)
        name = click.prompt("Business name")
    if description is None:
        description = (click.prompt("What does the business do?", default="", show_default=False)
                      if interactive else "")
    if industry is None:
        industry = (click.prompt("Industry (optional)", default="", show_default=False)
                    if interactive else "")
    doc_paths = list(docs)
    if not doc_paths and interactive:
        click.echo("Attach documents (blank line to finish):")
        while True:
            p = click.prompt("  document path", default="", show_default=False)
            if not p.strip():
                break
            doc_paths.append(p.strip())

    spec = IntakeSpec(name=name, description=description, industry=industry,
                      doc_paths=doc_paths)

    llm = None
    if not no_llm:
        try:
            from .llm import DEFAULT_MODEL, LLM
            llm = LLM(model=ctx.obj.get("model") or DEFAULT_MODEL)
        except Exception as e:  # no provider/key -> deterministic generation
            click.echo(f"(LLM unavailable; using deterministic generation: {e})", err=True)
    kb = None
    try:
        from .config import get_knowledge
        from .workspace import Workspace
        kcfg = get_knowledge()
        if kcfg.get("enable"):
            from maverick_knowledge import KnowledgeBase, build_embedder, build_store
            # Persist uploads to the active tenant's knowledge store (NOT :memory:,
            # which discards them on exit) so the run-time KB reads the same store.
            # An explicit [knowledge] path still wins.
            if not kcfg.get("path"):
                kcfg = {**kcfg, "path": str(Workspace.current().knowledge_path)}
            # Shield-scan documents at ingest: a poisoned upload is dropped at the
            # door, not only at query time (RAG-poisoning defense).
            shield = None
            try:
                from maverick_shield import Shield
                shield = Shield.from_config(warn_if_missing=False)
            except Exception:
                pass
            kb = KnowledgeBase(store=build_store(kcfg), embedder=build_embedder(kcfg),
                               shield=shield)
            try:  # OCR uploaded diagrams/images when the vision extra is installed
                from maverick_knowledge.image import build_ocr_describer
                kb.image_describer = build_ocr_describer()
            except Exception:
                pass  # no vision extra -> images are skipped, not read as bytes
        elif doc_paths:
            # The client explicitly attached docs AND the generated persona
            # tells the agent to answer from them -- so a quiet "skipping"
            # aside under-sells that the domain agent ends up with NO document
            # memory. Make it a clear, actionable warning (client-journey
            # finding): name the count and the exact remediation.
            click.echo(
                f"WARNING: knowledge is disabled, so the {len(doc_paths)} "
                "document(s) you attached were NOT loaded; this domain agent "
                "will have no document memory. Enable it with `maverick init` "
                "(turn on knowledge) or set [knowledge] enable = true in "
                "~/.maverick/config.toml, then re-run onboard.",
                err=True,
            )
    except Exception as e:  # knowledge layer is optional
        if doc_paths:
            click.echo(f"(knowledge unavailable; skipping doc ingestion: {e})", err=True)

    click.echo("Generating a draft domain agent...")
    profile = run_intake(spec, llm=llm, kb=None)

    click.echo(click.style("\nDraft domain pack (review before it goes live):", bold=True))
    click.echo(f"  name:        {profile.name}")
    click.echo(f"  compartment: {profile.compartment}")
    click.echo(f"  max_risk:    {profile.max_risk}")
    click.echo(f"  allow_tools: {', '.join(profile.allow_tools) or '(none)'}")
    click.echo(f"  deny_tools:  {', '.join(profile.deny_tools) or '(none)'}")
    click.echo(f"  knowledge:   {', '.join(profile.knowledge_sources) or '(none)'}")
    click.echo(f"  persona:     {profile.persona[:400]}")

    if not yes and not click.confirm("\nApprove and activate this agent?", default=False):
        click.echo("Discarded. Nothing was saved.")
        return
    if kb is not None and doc_paths:
        attach_docs_to_profile(spec, profile, kb)
    path = save_profile(profile, approved=True)
    click.echo(click.style(f"\nActivated. Pack saved to {path}", fg="green"))
    click.echo(f"Domain '{profile.name}' is now available to the swarm.")


@main.command()
@click.option("--principal", default=None,
              help="Principal to inspect (default: user:local). Match your "
                   "[role_assignments] key, e.g. user:<oidc-sub>.")
@click.option("--channel", default=None, help="Channel for ACL resolution.")
@click.option("--user", "user_id", default=None, help="Channel user id for ACL resolution.")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON instead of text.")
def whoami(principal: str | None, channel: str | None, user_id: str | None,
           as_json: bool) -> None:
    """Show the effective capability (and role) for a principal.

    Resolves the grant exactly as the agent would -- the [security] ACL narrowed
    by any assigned role ([role_assignments] / [roles]) -- so you can verify what
    a principal is allowed to do before you deploy. Read-only.
    """
    import json as _json

    from .capability import capability_enforced, capability_from_config

    p = principal or "user:local"
    cap = capability_from_config(p, channel=channel, user_id=user_id)
    role = None
    try:  # role_for_principal ships with RBAC; tolerate older kernels.
        from .capability import role_for_principal
        role = role_for_principal(p)
    except Exception:
        pass

    info = {
        "principal": cap.principal,
        "role": role,
        "enforcement": capability_enforced(),
        "allow_tools": sorted(cap.allow_tools) or "all",
        "deny_tools": sorted(cap.deny_tools),
        "max_risk": cap.max_risk or "none",
        "allow_paths": sorted(cap.allow_paths) or "all",
        "allow_hosts": sorted(cap.allow_hosts) or "all",
        "expires_at": cap.expires_at,
    }
    if as_json:
        click.echo(_json.dumps(info, default=str))
        return
    click.echo(click.style(f"principal: {info['principal']}", bold=True))
    click.echo(f"  role:         {role or '(none)'}")
    click.echo(f"  enforcement:  {'ON' if info['enforcement'] else 'off (advisory)'}")
    click.echo(f"  allow_tools:  {info['allow_tools']}")
    click.echo(f"  deny_tools:   {info['deny_tools'] or '(none)'}")
    click.echo(f"  max_risk:     {info['max_risk']}")
    click.echo(f"  allow_paths:  {info['allow_paths']}")
    click.echo(f"  allow_hosts:  {info['allow_hosts']}")
    if info["expires_at"]:
        click.echo(f"  expires_at:   {info['expires_at']}")


@main.group("capability")
def capability_group() -> None:
    """Revoke / restore capability grants (kill a grant before its TTL)."""


@capability_group.command("revoke")
@click.argument("principal")
@click.option("--reason", default="", help="Audit reason for the revocation.")
def capability_revoke_cmd(principal: str, reason: str) -> None:
    """Revoke PRINCIPAL now. Its next tool call is denied even mid-run.

    Propagates to running agents (the registry is re-read on change) when
    capability enforcement is on ([capabilities] enforce = true).
    """
    from .revocation import shared
    rev = shared().revoke(principal, reason=reason)
    click.echo(click.style(f"revoked {principal!r}", fg="yellow")
               + (f" — {rev.reason}" if rev.reason else ""))


@capability_group.command("unrevoke")
@click.argument("principal")
def capability_unrevoke_cmd(principal: str) -> None:
    """Restore PRINCIPAL (remove it from the revocation list)."""
    from .revocation import shared
    if shared().unrevoke(principal):
        click.echo(click.style(f"restored {principal!r}", fg="green"))
    else:
        click.echo(f"{principal!r} was not revoked")


@capability_group.command("revocations")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON.")
def capability_revocations_cmd(as_json: bool) -> None:
    """List revoked principals."""
    import json as _json

    from .revocation import shared
    revs = shared().revoked()
    if as_json:
        click.echo(_json.dumps(
            {p: {"revoked_at": r.revoked_at, "reason": r.reason}
             for p, r in revs.items()}, default=str))
        return
    if not revs:
        click.echo("no revoked principals")
        return
    for p, r in sorted(revs.items()):
        click.echo(f"  {p}  (at {r.revoked_at:.0f})"
                   + (f"  — {r.reason}" if r.reason else ""))


@main.group("overrides")
def overrides_group() -> None:
    """Export / load this workspace's agent customizations as a portable bundle.

    A bundle is a plain directory carrying the workspace's domain-pack overrides
    (``domains/*.toml``) and per-role system-prompt addendums (``roles.toml``).
    Commit it to a repo and ``maverick overrides load`` it in CI so the
    ``agent-on-pr`` review runs as your customized workforce."""


@overrides_group.command("export")
@click.argument("dest", type=click.Path(file_okay=False))
def overrides_export_cmd(dest: str) -> None:
    """Write this workspace's overrides (domain packs + role addendums) into DEST."""
    from .overrides_bundle import export_overrides
    n = export_overrides(dest)
    click.echo(f"exported {n['domains']} domain override(s), "
               f"{n['roles']} role addendum(s) to {dest}")


@overrides_group.command("load")
@click.argument("src", type=click.Path(exists=True, file_okay=False))
def overrides_load_cmd(src: str) -> None:
    """Apply a bundle from SRC into this workspace (each item re-validated)."""
    from .overrides_bundle import load_overrides
    n = load_overrides(src)
    click.echo(f"loaded {n['domains']} domain override(s), "
               f"{n['roles']} role addendum(s)")
    for s in n["skipped"]:
        click.echo(click.style(f"  skipped {s}", fg="yellow"))


@main.group()
def governance() -> None:
    """Inspect the oversight control-plane policy (enterprise)."""


@governance.command("show")
def governance_show() -> None:
    """Show the active org policy from [governance] (default-allow if unset)."""
    from .governance import Policy
    pol = Policy.from_config()
    if pol.is_empty():
        click.echo("no [governance] policy configured (default-allow)")
        return
    click.echo(f"deny_actions:           {sorted(pol.deny_actions) or '(none)'}")
    click.echo(f"require_human_actions:  {sorted(pol.require_human_actions) or '(none)'}")
    click.echo(f"deny_min_risk:          {pol.deny_min_risk or '(none)'}")
    click.echo(f"require_human_min_risk: {pol.require_human_min_risk or '(none)'}")


@governance.command("check")
@click.argument("action")
@click.option("--risk", type=click.Choice(["low", "medium", "high"]), default=None,
              help="Override the action's classified risk.")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON.")
def governance_check(action: str, risk: str | None, as_json: bool) -> None:
    """Show the control-plane verdict for ACTION under the active policy.

    Returns ALLOW / DENY / REQUIRE_HUMAN so you can verify a policy before
    deploying. Read-only.
    """
    import json as _json

    from .governance import evaluate
    v = evaluate(action, risk=risk)
    if as_json:
        click.echo(_json.dumps({
            "action": action, "decision": v.decision.value,
            "rule": v.rule, "reason": v.reason,
        }))
        return
    click.echo(f"{action}: {v.decision.value.upper()}  ({v.rule}) — {v.reason}")


def _governance_denied_counts(principals: set[str], *, limit: int = 500) -> dict[str, int]:
    """Count recent policy-denial audit events per principal (fail-soft).

    The oversight signal is a tool the control plane refused for an agent. On
    this kernel that lands as ``capability_denied``; ``governance_denied`` is
    matched too where a build records it, so the count is forward-compatible.
    """
    counts: dict[str, int] = {}
    try:
        from .audit import EventKind, default_audit_log
        kinds = {EventKind.CAPABILITY_DENIED,
                 getattr(EventKind, "GOVERNANCE_DENIED", "governance_denied")}
        for ev in default_audit_log().tail(limit):
            if ev.get("kind") not in kinds:
                continue
            p = ev.get("principal")
            if p in principals:
                counts[p] = counts.get(p, 0) + 1
    except Exception:  # pragma: no cover -- the oversight view never blocks on audit
        pass
    return counts


@main.group()
def fleet() -> None:
    """Manage per-employee agent fleets (enterprise)."""


@fleet.command("create")
@click.argument("name")
@click.option("--owner", required=True, help="Owning principal, e.g. user:alice.")
@click.option("--agent", "agents", multiple=True, metavar="NAME:ROLE",
              help="An agent as NAME:ROLE (repeatable). ROLE is an RBAC role.")
def fleet_create(name: str, owner: str, agents: tuple[str, ...]) -> None:
    """Create a fleet: an owner plus a roster of NAME:ROLE agents."""
    from .capability import role_exists
    from .fleet import Fleet, FleetAgent, save_fleet, valid_name
    if not valid_name(name):
        click.echo("ERROR: name must be [A-Za-z0-9_-] (<=64 chars)", err=True)
        sys.exit(2)
    roster = []
    for spec in agents:
        agent_name, _, role = spec.partition(":")
        agent_name = agent_name.strip()
        role = role.strip()
        if not valid_name(agent_name) or not role:
            click.echo(f"ERROR: bad --agent {spec!r}; use NAME:ROLE", err=True)
            sys.exit(2)
        if not role_exists(role):
            click.echo(f"ERROR: undefined RBAC role {role!r} for --agent {spec!r}",
                       err=True)
            sys.exit(2)
        roster.append(FleetAgent(name=agent_name, role=role))
    path = save_fleet(Fleet(name=name, owner=owner, agents=tuple(roster)))
    click.echo(f"created fleet {name!r} ({len(roster)} agent(s)) -> {path}")


@fleet.command("list")
def fleet_list() -> None:
    """List fleets."""
    from .fleet import list_fleets
    fleets = list_fleets()
    if not fleets:
        click.echo("no fleets. create one with `maverick fleet create`")
        return
    for f in fleets:
        click.echo(f"  {f.name}  (owner {f.owner}, {len(f.agents)} agent(s))")


@fleet.command("show")
@click.argument("name")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON.")
def fleet_show(name: str, as_json: bool) -> None:
    """Show a fleet's roster (each agent + its role/principal)."""
    import json as _json

    from .fleet import load_fleet
    f = load_fleet(name)
    if f is None:
        click.echo(f"no such fleet: {name}", err=True)
        sys.exit(1)
    if as_json:
        click.echo(_json.dumps(f.to_dict()))
        return
    click.echo(click.style(f"fleet {f.name}  (owner {f.owner})", bold=True))
    if not f.agents:
        click.echo("  (no agents)")
    for a in f.agents:
        line = f"  {a.name:16} role={a.role:14} {f.principal_for(a.name)}"
        click.echo(line + (f"  — {a.description}" if a.description else ""))


@fleet.command("rm")
@click.argument("name")
def fleet_rm(name: str) -> None:
    """Remove a fleet."""
    from .fleet import remove_fleet
    if remove_fleet(name):
        click.echo(f"removed fleet {name!r}")
    else:
        click.echo(f"no such fleet: {name}", err=True)
        sys.exit(1)


@fleet.command("run")
@click.argument("fleet_name")
@click.argument("agent_name")
@click.argument("prompt")
@click.option("--max-dollars", default=None, type=float,
              help="Spend cap for this run (else [budget] / the runner default).")
@click.pass_context
def fleet_run(ctx, fleet_name: str, agent_name: str, prompt: str,
              max_dollars: float | None) -> None:
    """Run a governed goal AS one of a fleet's agents.

    The agent runs least-privileged under its RBAC role's capability and under
    its own audit principal (``agent:<fleet>.<agent>``), so the oversight
    control plane governs the work automatically.
    """
    from .capability import UnknownRoleError, capability_for_role
    from .fleet import load_fleet, record_run
    from .runner import run_goal_in_thread

    f = load_fleet(fleet_name)
    if f is None:
        click.echo(f"no such fleet: {fleet_name}", err=True)
        sys.exit(1)
    agent = next((a for a in f.agents if a.name == agent_name), None)
    if agent is None:
        click.echo(f"no such agent {agent_name!r} in fleet {fleet_name!r}", err=True)
        sys.exit(1)

    principal = f.principal_for(agent.name)
    try:
        cap = capability_for_role(agent.role, principal=principal)
    except UnknownRoleError as exc:
        click.echo(f"ERROR: {exc}", err=True)
        sys.exit(2)
    world = open_world(ctx.obj["db"])
    try:
        goal_id = world.create_goal(prompt)
    finally:
        world.close()
    record_run(fleet_name, agent.name, goal_id)
    click.echo(f"goal #{goal_id} created for {principal} (role {agent.role})")
    status = run_goal_in_thread(goal_id, max_dollars=max_dollars,
                                capability=cap, user_id=principal)
    click.echo(f"goal #{goal_id}: {status or 'did not start'}")


@fleet.command("status")
@click.argument("name")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON.")
@click.pass_context
def fleet_status(ctx, name: str, as_json: bool) -> None:
    """Supervisor oversight: each agent's recent runs + governance denials."""
    import json as _json

    from .fleet import load_fleet, load_runs
    f = load_fleet(name)
    if f is None:
        click.echo(f"no such fleet: {name}", err=True)
        sys.exit(1)

    runs = load_runs(name)
    by_agent: dict[str, list[dict]] = {a.name: [] for a in f.agents}
    for r in runs:
        by_agent.setdefault(str(r.get("agent")), []).append(r)
    denied = _governance_denied_counts({f.principal_for(a.name) for a in f.agents})

    world = open_world(ctx.obj["db"])
    try:
        def _row(r: dict) -> dict:
            gid = r.get("goal_id")
            g = world.get_goal(gid) if isinstance(gid, int) else None
            return {"goal_id": gid, "status": g.status if g else "missing",
                    "ts": r.get("ts")}
        report = []
        for a in f.agents:
            recent = sorted(by_agent.get(a.name, []),
                            key=lambda r: r.get("ts") or 0.0)[-10:]
            report.append({
                "agent": a.name, "role": a.role,
                "principal": f.principal_for(a.name),
                "runs": [_row(r) for r in recent],
                "governance_denied": denied.get(f.principal_for(a.name), 0),
            })
    finally:
        world.close()

    if as_json:
        click.echo(_json.dumps({"fleet": f.name, "agents": report}))
        return
    click.echo(click.style(f"fleet {f.name}  (owner {f.owner})", bold=True))
    for a in report:
        click.echo(f"  {a['agent']:16} role={a['role']:14} {a['principal']}  "
                   f"denied={a['governance_denied']}")
        if not a["runs"]:
            click.echo("      (no runs)")
        for r in a["runs"]:
            click.echo(f"      goal #{r['goal_id']}: {r['status']}")


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
            raise click.ClickException(f"could not launch editor {parts[0]!r}: {e}") from e
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


@main.command("budget-tune")
@click.option("--percentile", type=float, default=90.0,
              help="Percentile of historical goal cost to size the cap to.")
@click.option("--min-samples", type=int, default=5,
              help="Minimum priced goals before a recommendation is made.")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON.")
@click.pass_context
def budget_tune(ctx, percentile: float, min_samples: int, as_json: bool) -> None:
    """Recommend a max_dollars cap learned from historical goal spend.

    Sizes the default to the percentile of what goals actually cost plus a
    margin, so the common case fits while a runaway still trips it. Read-only —
    set the value yourself in config.
    """
    import json as _json

    from .budget_tuner import recommend_for_world
    world = open_world(ctx.obj["db"])
    recs = recommend_for_world(world, pct=percentile, min_samples=min_samples)
    if as_json:
        click.echo(_json.dumps(recs))
        return
    if not recs:
        click.echo(f"not enough priced goals yet (need >= {min_samples}).")
        return
    click.echo(click.style("Recommended max_dollars (learned):", bold=True))
    for cls, info in sorted(recs.items()):
        click.echo(f"  {cls}: ${info['recommended_max_dollars']:.2f}  "
                   f"(p{int(percentile)}=${info[f'p{int(percentile)}']:.2f}, "
                   f"{info['samples']} goal(s))")


@main.command("confidential-compute")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON.")
def confidential_compute_cmd(as_json: bool) -> None:
    """Detect whether this runs inside a confidential VM (SEV-SNP / TDX).

    For a regulated deployment to verify its memory is hardware-encrypted.
    Exits non-zero when NOT confidential, so it can gate a deployment.
    """
    import json as _json

    from .confidential_compute import detect
    rep = detect()
    if as_json:
        click.echo(_json.dumps(rep))
    elif rep["confidential"]:
        kind = "Intel TDX" if rep["tdx"] else "AMD SEV-SNP"
        click.echo(click.style(f"CONFIDENTIAL VM ({kind})", fg="green")
                   + f" — {', '.join(rep['indicators'])}")
    else:
        click.echo(click.style(
            "NOT a confidential VM (no SEV-SNP / TDX indicators)", fg="yellow"))
    if not rep["confidential"]:
        raise SystemExit(1)


@main.command("airgap")
@click.argument("action", type=click.Choice(["check"]), default="check")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON.")
def airgap_cmd(action: str, as_json: bool) -> None:
    """Verify the deployment is configured with no outbound path.

    Audits for a remote model provider, a non-deny-all egress policy, and
    sandbox network access. Exits non-zero on any finding so it can gate a
    deployment. (OS-level air-gapping is the operator's job; this checks
    Maverick's own config.)
    """
    import json as _json

    from .air_gap import audit
    rep = audit()
    if as_json:
        click.echo(_json.dumps(rep))
    elif rep["clean"]:
        click.echo(click.style("AIR-GAPPED: no outbound path in config", fg="green"))
    else:
        click.echo(click.style("NOT air-gapped — findings:", fg="red"))
        for v in rep["violations"]:
            click.echo(f"  • {v}")
    if not rep["clean"]:
        raise SystemExit(1)


@main.command("failures")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON.")
def failures_cmd(as_json: bool) -> None:
    """Show the failure-mode distribution (opt-in [telemetry] failure_modes).

    When the telemetry is on, failed runs record a canonical mode (budget /
    auth / timeout / shield / sandbox / network / error); this reads them back.
    """
    import json as _json

    from .failure_telemetry import enabled, summarize
    s = summarize()
    if as_json:
        click.echo(_json.dumps(s))
        return
    if not s["total"]:
        hint = "" if enabled() else " (telemetry is off — set [telemetry] failure_modes)"
        click.echo(f"no recorded failures{hint}.")
        return
    click.echo(click.style(f"Failure modes ({s['total']} recorded)", bold=True))
    for mode, n in s["by_mode"].items():
        click.echo(f"  {mode:<10} {n}")


# Extends the existing `governance` group (oversight policy) with the
# governed-action audit trail: what a run did, and what a skill/source touched.
@governance.command("lineage")
@click.argument("goal_id", type=int)
@click.option("--json", "as_json", is_flag=True, help="Emit JSON.")
def governance_lineage(goal_id: int, as_json: bool) -> None:
    """Show + verify the tamper-evident action lineage for a goal."""
    import json as _json

    from . import governed_actions as _ga
    links = _ga.load_lineage(goal_id)
    status = _ga.verify_lineage_file(goal_id)
    if as_json:
        click.echo(_json.dumps({"links": links, "verify": status}))
        return
    if not links:
        click.echo(f"no recorded actions for goal {goal_id} "
                   "(governed actions off? set [actions] enable).")
        return
    click.echo(click.style(f"Action lineage for goal {goal_id}", bold=True))
    for i, link in enumerate(links):
        click.echo(f"  {i}. {link.get('action')}  skills={link.get('skills') or []}  "
                   f"sources={link.get('sources') or []}  {str(link.get('hash',''))[:12]}")
    click.echo(status)


@governance.command("impact")
@click.argument("identifier")
@click.option("--kind", type=click.Choice(["skill", "source", "any"]), default="any",
              help="Match the identifier as a skill, a source, or either.")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON.")
def governance_impact(identifier: str, kind: str, as_json: bool) -> None:
    """Impact analysis: which recorded actions depended on a skill/source.

    Use after revoking a skill or flagging a bad source to see exactly what it
    touched across every run.
    """
    import json as _json

    from . import governed_actions as _ga
    hits = _ga.impact_of(identifier, kind=kind)
    if as_json:
        click.echo(_json.dumps(hits))
        return
    if not hits:
        click.echo(f"no recorded actions depended on {identifier!r}.")
        return
    click.echo(click.style(f"Impact of {identifier!r}: {len(hits)} action(s)", bold=True))
    for h in hits:
        click.echo(f"  goal {h['goal_id']}  {h['action']}  via {h['via']}  {h['hash']}")


@main.command("analytics")
@click.option("--sql", default=None, help="Ad-hoc read-only SQL over goals/episodes.")
@click.option("--top", type=int, default=10, help="Top-N costliest goals (default view).")
@click.pass_context
def analytics_cmd(ctx, sql: str | None, top: int) -> None:
    """OLAP analytics over the world model via DuckDB ([duckdb] extra).

    Default view: per-goal cost percentiles + the costliest goals. `--sql`
    runs an ad-hoc SELECT over `goals` and `episodes` (read-only).
    """
    import json as _json

    try:
        from .duckdb_analytics import WorldAnalytics
        # duckdb imports lazily inside the constructor, so the actionable
        # "pip install 'maverick-agent[duckdb]'" ImportError fires HERE --
        # construction must sit inside the catch or the user gets a raw
        # traceback (round-3 platform-test finding).
        wa = WorldAnalytics(open_world(ctx.obj["db"]))
    except ImportError as e:
        raise click.ClickException(str(e)) from e
    try:
        if sql:
            click.echo(_json.dumps(wa.query(sql), default=str))
            return
        pct = wa.cost_percentiles()
        click.echo(click.style("Per-goal cost percentiles", bold=True))
        if pct.get("n"):
            click.echo(f"  goals={int(pct['n'])}  p50=${pct['p50']:.2f}  "
                       f"p90=${pct['p90']:.2f}  p99=${pct['p99']:.2f}  "
                       f"max=${pct['max_cost']:.2f}")
        else:
            click.echo("  no priced goals yet.")
        rows = wa.top_goals(top)
        if rows:
            click.echo(click.style("\nCostliest goals", bold=True))
            for r in rows:
                click.echo(f"  #{int(r['id'])} ${r['total_cost']:.2f} "
                           f"({int(r['ep_count'])} ep)  {r['title']}")
    finally:
        wa.close()


@main.command("compounding")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON.")
@click.option("--window", type=int, default=5, help="Cold/warm window per task class.")
@click.pass_context
def compounding(ctx, as_json: bool, window: int) -> None:
    """Does the workforce get cheaper and better with use? (the compounding moat).

    Per task class, compares the earliest runs (cold) against the most recent
    (warm) and reports the cost and reliability deltas -- the live, per-customer
    proof that learning compounds. Read-only.
    """
    import json as _json

    from .compounding_metric import report_from_world
    world = open_world(ctx.obj["db"])
    reps = report_from_world(world, window=window)
    if as_json:
        click.echo(_json.dumps([r.to_dict() for r in reps]))
        return
    if not reps:
        click.echo("Not enough runs yet to measure compounding "
                   "(need several runs of the same task class).")
        return
    click.echo(click.style("Compounding — cold vs warm by task class", bold=True))
    for r in reps:
        arrow = "improving" if r.improving else "flat/regressing"
        click.echo(
            f"  {r.task_class}: {r.runs} runs  "
            f"cost {r.cost_delta_pct:+.0f}%  success {r.success_delta:+.2f}  [{arrow}]")


@main.command("record-outcome")
@click.argument("goal_id", type=int)
@click.argument("episode_id", type=int)
@click.argument("value", type=float)
@click.option("--kind", default="", help="What the outcome is (e.g. invoice_paid, renewed).")
def record_outcome(goal_id: int, episode_id: int, value: float, kind: str) -> None:
    """Feed a REAL downstream outcome back to a past episode (the grounded reward).

    The Consequence Engine's ingestion entrypoint -- a system-of-record connector
    (or a human) calls this once reality reports back: ``maverick record-outcome
    <goal_id> <episode_id> <value>`` with value in [0,1] (paid=1.0, reopened=0.0,
    or a graded result). The flywheel then prefers this over the verifier proxy
    when it next turns, so learning is grounded in what actually happened.
    """
    from .consequence import record_outcome as _rec
    ok = _rec(goal_id, episode_id, value, kind=kind)
    click.echo(
        f"recorded outcome {value:g} for goal {goal_id} episode {episode_id}"
        f"{(' (' + kind + ')') if kind else ''}" if ok
        else "failed to record outcome")


@main.command("codebook")
@click.option("--limit", type=int, default=5000, help="Coordination messages to learn from.")
@click.option("--show", is_flag=True, help="Show the current codebook without relearning.")
@click.pass_context
def codebook(ctx, limit: int, show: bool) -> None:
    """Learn (or show) the swarm's coordination shorthand from its real messages.

    The Emergent Substrate: reads the coordination the agents have actually
    exchanged (goal_events) and learns short codes for the phrases they repeat --
    every code decodes EXACTLY back to English, so nothing is hidden from the
    Shield or a human. Reports the achievable compression. (Agents actively
    *speaking* the shorthand is a separate opt-in; this learns + inspects it.)
    """
    from .emergent_protocol import compression_ratio, learn, shared
    store = shared()
    if show:
        book = store.book()
        click.echo(f"codebook: {book.size} codes")
    else:
        world = open_world(ctx.obj["db"])
        msgs = world.recent_event_contents(limit=limit)
        book = learn(msgs)
        store.update(book)
        ratio = compression_ratio(msgs, book)
        click.echo(f"learned {book.size} codes from {len(msgs)} messages "
                   f"({(1 - ratio) * 100:.0f}% smaller on this corpus)")
    for phrase, code in list(book.forward.items())[:10]:
        click.echo(f"  {code} = {phrase!r}")


@main.command("codec-probe")
@click.option("--limit", type=int, default=5000, help="Coordination messages to probe.")
@click.option("--encoding", default="cl100k_base", help="tiktoken encoding for the local proxy.")
@click.option("--model", default=None, help="Anthropic model for the EXACT count (needs API key).")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON.")
@click.pass_context
def codec_probe(ctx, limit: int, encoding: str, model: str | None, as_json: bool) -> None:
    """Measure whether the emergent codec saves TOKENS, not just bytes.

    The kill-switch experiment: bytes and frontier tokens do NOT move together,
    because the audit-safe sentinel codes can tokenize worse than the English they
    replace. Learns a codebook from real coordination (goal_events) and reports the
    byte delta beside the *token* delta -- and whether the compressed form actually
    costs fewer tokens. Pass --model (with an API key) for the exact Anthropic count;
    otherwise a local tiktoken proxy answers the directional question for free.
    """
    import json as _json

    from .codec_probe import measure, resolve_counter
    from .emergent_protocol import learn
    world = open_world(ctx.obj["db"])
    msgs = world.recent_event_contents(limit=limit)
    if not msgs:
        click.echo("no coordination messages to probe")
        return
    book = learn(msgs)
    try:
        counter = resolve_counter(encoding=encoding, model=model)
    except RuntimeError as e:
        raise click.ClickException(str(e)) from e
    delta = measure(msgs, book, count_tokens=counter)
    d = delta.to_dict()
    if as_json:
        click.echo(_json.dumps(d, indent=2))
        return
    click.echo(f"probed {d['n_messages']} messages, {book.size} codes")
    click.echo(f"  bytes : {d['byte_savings_pct']:+.1f}%")
    verdict = "SAVES tokens" if d["pays_off"] else "COSTS MORE tokens"
    click.echo(f"  tokens: {d['token_savings_pct']:+.1f}%   -> {verdict}")
    be = d["breakeven_messages"]
    click.echo(f"  read-coded: {d['codebook_tokens']} tokens to carry the codebook; "
               + (f"break-even after {be:.0f} reuses" if be != float("inf")
                  else "NEVER breaks even (no per-message token saving)"))


@main.command("codec-learn")
@click.option("--limit", type=int, default=5000, help="Coordination messages to learn from.")
@click.option("--encoding", default="cl100k_base", help="tiktoken encoding for the local proxy.")
@click.option("--model", default=None, help="Anthropic model for the EXACT count (needs API key).")
@click.pass_context
def codec_learn(ctx, limit: int, encoding: str, model: str | None) -> None:
    """Learn the token-aware codebook from real coordination and persist it.

    This is the codec that actually saves frontier tokens (byte-stuffed ~2-token
    codes), not just bytes. Picks token-cheap, collision-safe codes from the
    target tokenizer, learns the swarm's repeated phrases from goal_events, and
    saves the codebook for the live blackboard to measure against. Reports the
    token savings on the historical corpus -- the authoritative, cross-process
    number (the live blackboard telemetry confirms it during an actual run).
    """
    from . import emergent_tokens as et
    from .codec_probe import resolve_counter
    world = open_world(ctx.obj["db"])
    msgs = world.recent_event_contents(limit=limit)
    if not msgs:
        click.echo("no coordination messages to learn from")
        return
    try:
        counter = resolve_counter(encoding=encoding, model=model)
    except RuntimeError as e:
        raise click.ClickException(str(e)) from e
    # Candidate codes: printable ASCII + Latin/symbol ranges, filtered to the
    # tokenizer's single-token chars that don't occur in the corpus. First viable
    # one is the reserved escape; the rest are markers.
    candidates = [chr(c) for c in list(range(0x21, 0x7f)) + list(range(0xa1, 0x600))]
    pool = et.single_token_markers(counter, candidates, escape="", corpus=msgs, limit=200)
    if len(pool) < 2:
        click.echo("no token-cheap markers available for this tokenizer; codec would not help")
        return
    escape, markers = pool[0], pool[1:]
    book = et.learn(msgs, escape=escape, markers=markers)
    et.shared().update(book)
    saved = et.token_savings(msgs, book, count_tokens=counter)
    click.echo(f"learned {book.size} token-aware codes from {len(msgs)} messages")
    click.echo(f"  estimated token savings on this corpus: {saved:+.1f}%")
    click.echo("  enable [emergent_codec] to measure it live on the coordination stream")


@main.command("flywheel")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON.")
def flywheel(as_json: bool) -> None:
    """Turn the Cognitive Data Engine flywheel once over the Operating Record.

    One grounded pass: triage production failures by causal impact, mine
    self-correcting guardrails, consolidate beneficial habits into procedural
    memory, and propose process improvements -- learning from REAL outcomes where
    they've reported back. A no-op unless ``[data_engine]`` is enabled.
    """
    import json as _json

    from .flywheel import maybe_run
    rep = maybe_run()
    if as_json:
        click.echo(_json.dumps({
            "n_episodes": rep.n_episodes,
            "guardrails": [g.to_dict() for g in rep.guardrails],
            "memories": [m.to_dict() for m in rep.memories],
            "hypotheses": [{"swap": f"{h.baseline_action}->{h.candidate_action}",
                            "predicted_lift": h.predicted_lift} for h in rep.hypotheses],
            "predicted_lift": rep.predicted_lift,
        }))
        return
    if not rep.acted:
        click.echo("Flywheel: nothing to learn yet "
                   "(data engine off, or no failures/habits in the corpus).")
        return
    click.echo(click.style(f"Flywheel — one turn over {rep.n_episodes} episodes", bold=True))
    if rep.guardrails:
        click.echo(f"  guardrails learned: {len(rep.guardrails)} "
                   f"(recoverable lift ~{rep.predicted_lift:.2f})")
        for g in rep.guardrails[:5]:
            click.echo(f"    avoid '{g.action}' (severity {g.severity:.2f})")
    if rep.memories:
        click.echo(f"  habits consolidated: {len(rep.memories)}")
        for m in rep.memories[:5]:
            click.echo(f"    prefer '{m.action}' (strength {m.strength:.2f})")
    if rep.hypotheses:
        click.echo(f"  improvements proposed: {len(rep.hypotheses)}")
        for h in rep.hypotheses[:5]:
            click.echo(f"    swap '{h.baseline_action}' -> '{h.candidate_action}' "
                       f"(predicted +{h.predicted_lift:.2f})")


@main.command("cost-retro")
@click.option("--top", type=int, default=10, help="How many costliest goals to show.")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON.")
@click.pass_context
def cost_retro(ctx, top: int, as_json: bool) -> None:
    """Cost retrospective: where spend went, and what to do about it.

    Reads recorded per-goal spend and reports the costliest goals, how much
    went to failed work, how concentrated spend is, and actionable
    observations. Read-only.
    """
    import json as _json

    from .cost_retrospective import retrospective
    world = open_world(ctx.obj["db"])
    rep = retrospective(world, top_n=top)
    if as_json:
        click.echo(_json.dumps(rep))
        return
    click.echo(click.style(
        f"Cost retrospective — ${rep['total_spend']:.2f} across "
        f"{rep['priced_goals']} priced goal(s)", bold=True))
    if rep["failed_spend"]:
        click.echo(f"  failed work: ${rep['failed_spend']:.2f} "
                   f"({rep['failed_share']:.0%})")
    if rep["top_goals"]:
        click.echo(click.style("\nCostliest goals", bold=True))
        for r in rep["top_goals"]:
            flag = " [FAILED]" if r["failed"] else ""
            click.echo(f"  #{r['goal_id']} ${r['cost']:.2f} "
                       f"({r['episodes']} ep){flag}  {r['title']}")
    click.echo(click.style("\nObservations", bold=True))
    for o in rep["observations"]:
        click.echo(f"  • {o}")


@main.command("charts")
@click.option("--days", type=int, default=7, help="How many days to chart.")
@click.option("--plain", is_flag=True, help="Force plain ASCII (no rich panels).")
@click.pass_context
def charts(ctx, days: int, plain: bool) -> None:
    """Inline terminal charts: spend/day, goal throughput, tool latency.

    Sparklines + bars drawn from recorded data — the usage ledger (spend),
    the world model (done/failed per day), and the tool-latency profile.
    Uses ``rich`` panels when installed; falls back to plain ASCII. Sections
    with no data say so. Read-only.
    """
    from . import terminal_charts, tool_latency
    world = open_world(ctx.obj["db"])
    report = tool_latency.report()
    if plain:
        click.echo(terminal_charts.render_dashboard(world, None, report, days=days))
        return
    out = terminal_charts.render_dashboard_rich(world, None, report, days=days)
    if isinstance(out, str):
        click.echo(out)
    else:
        from rich.console import Console
        Console().print(out)


@main.group("canary")
def canary_group() -> None:
    """Record / compare cost-perf metric snapshots per release."""


def _parse_metrics(pairs: tuple[str, ...]) -> dict:
    out: dict = {}
    for p in pairs:
        if "=" not in p:
            raise click.ClickException(f"--metric must be name=value, got {p!r}")
        name, _, val = p.partition("=")
        try:
            out[name.strip()] = float(val)
        except ValueError as e:
            raise click.ClickException(f"metric {name!r} value not numeric: {val!r}") from e
    return out


@canary_group.command("record")
@click.argument("release")
@click.option("--metric", "metrics", multiple=True,
              help="name=value (repeatable), e.g. --metric p95_latency_s=3.4")
def canary_record(release: str, metrics: tuple[str, ...]) -> None:
    """Record RELEASE's metric snapshot (cost/latency/success_rate/...)."""
    from .release_canary import CanaryStore
    parsed = _parse_metrics(metrics)
    if not parsed:
        raise click.ClickException("at least one --metric is required")
    CanaryStore().record(release, parsed)
    click.echo(f"recorded {len(parsed)} metric(s) for release {release!r}")


@canary_group.command("compare")
@click.argument("baseline")
@click.argument("candidate")
@click.option("--tolerance", type=float, default=0.10,
              help="Relative move allowed before flagging a regression.")
def canary_compare(baseline: str, candidate: str, tolerance: float) -> None:
    """Compare CANDIDATE release metrics against BASELINE; exit 1 on regression."""
    from .release_canary import CanaryStore, compare, render
    store = CanaryStore()
    base, cand = store.get(baseline), store.get(candidate)
    if base is None:
        raise click.ClickException(f"no recorded metrics for baseline {baseline!r}")
    if cand is None:
        raise click.ClickException(f"no recorded metrics for candidate {candidate!r}")
    result = compare(base, cand, tolerance=tolerance)
    click.echo(render(result))
    if not result.passed:
        raise SystemExit(1)


@main.command()
@click.option("--sample", "sample", nargs=2, type=str, default=None,
              metavar="CONFIDENCE CORRECT",
              help="Record one labeled sample: verifier confidence (0-1) and "
                   "whether the answer was actually correct (true/false). "
                   "Build the set across calls, then run with no args to assess.")
@click.option("--json", "as_json", is_flag=True, help="Emit the verdict as JSON.")
def calibrate(sample, as_json) -> None:
    """Assess verifier calibration -- the self-improvement safety interlock.

    The verifier's confidence is the label the trajectory-donation flywheel
    learns from, so a drifted verifier would teach the system its own mistakes.
    With ``--sample`` append one ``(confidence, ground_truth)`` pair to the
    calibration set; with no arguments, assess the set and persist the verdict
    that gates donation. If the verifier no longer separates correct from
    incorrect answers (and ``[calibration] enforce`` is on), learning freezes.
    """
    import json as _json

    from . import calibration

    if sample is not None:
        conf_s, correct_s = sample
        try:
            conf = float(conf_s)
        except ValueError as e:
            raise click.ClickException(
                f"confidence must be a number in [0,1], got {conf_s!r}"
            ) from e
        correct = correct_s.strip().lower() in {"1", "true", "yes", "y", "pass"}
        ok = calibration.record_sample(conf, correct, source="cli")
        click.echo("recorded calibration sample" if ok else "failed to record sample")
        return

    report = calibration.run_assessment()
    if as_json:
        click.echo(_json.dumps(report.to_dict(), indent=2))
        return
    status = (
        click.style("ADEQUATE", fg="green") if report.adequate
        else click.style("INADEQUATE", fg="red")
    )
    click.echo(click.style("Verifier calibration", bold=True))
    click.echo(f"  status:          {status}")
    click.echo(
        f"  samples:         {report.n} "
        f"({report.n_correct} correct / {report.n_incorrect} incorrect)"
    )
    click.echo(f"  discrimination:  {report.discrimination:.3f}")
    click.echo(f"  brier score:     {report.brier:.3f}")
    click.echo(f"  {report.reason}")
    if not report.adequate:
        from .config import get_calibration
        if get_calibration()["enforce"]:
            click.echo(click.style(
                "  learning is FROZEN (trajectory donation gated) until this passes.",
                fg="yellow",
            ))
        else:
            click.echo("  note: [calibration] enforce is off, so learning is not frozen.")


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


@main.group()
def tenant() -> None:
    """Provision and manage tenants (hosted control plane)."""


@tenant.command("create")
@click.argument("tenant_id")
@click.option("--plan", default="free", help="Plan name (free/pro/enterprise/...).")
@click.option("--name", "display_name", default="", help="Human display name.")
@click.option("--max-daily-dollars", type=float, default=0.0,
              help="Per-tenant daily spend cap (USD); 0 = unlimited.")
def tenant_create(tenant_id: str, plan: str, display_name: str,
                  max_daily_dollars: float) -> None:
    """Provision a tenant + its isolated workspace."""
    from .tenant_registry import create_tenant
    try:
        rec = create_tenant(tenant_id, plan=plan, display_name=display_name,
                             max_daily_dollars=max_daily_dollars)
    except ValueError as e:
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(2)
    click.echo(f"created tenant {rec.id!r} (plan {rec.plan}, status {rec.status})")


@tenant.command("list")
def tenant_list() -> None:
    """List provisioned tenants."""
    from .tenant_registry import list_tenants, tenant_spend_today
    rows = list_tenants()
    if not rows:
        click.echo("no tenants. create one with `maverick tenant create`")
        return
    for t in rows:
        cap = f"${t.max_daily_dollars:g}/day" if t.max_daily_dollars else "unlimited"
        # Surface tenants that are at/over today's spend cap -- enforcement
        # happens at serve time, but an operator had no way to SEE which tenants
        # are currently over quota from the CLI (user-testing finding). Only
        # capped tenants are checked (a ledger read each), so unlimited tenants
        # (the common case) cost nothing extra.
        flag = ""
        if t.max_daily_dollars > 0:
            spent = tenant_spend_today(t.id)
            if spent >= t.max_daily_dollars:
                flag = f"  [OVER QUOTA ${spent:.2f}/${t.max_daily_dollars:g}]"
        click.echo(f"  {t.id}  [{t.status}]  plan={t.plan}  quota={cap}{flag}")


@tenant.command("suspend")
@click.argument("tenant_id")
def tenant_suspend(tenant_id: str) -> None:
    """Suspend a tenant (its requests are refused until resumed)."""
    from .tenant_registry import UnknownTenant, suspend_tenant
    try:
        suspend_tenant(tenant_id)
    except UnknownTenant:
        click.echo(f"ERROR: no such tenant {tenant_id!r}", err=True)
        sys.exit(2)
    click.echo(f"suspended {tenant_id!r}")


@tenant.command("resume")
@click.argument("tenant_id")
def tenant_resume(tenant_id: str) -> None:
    """Resume a suspended tenant."""
    from .tenant_registry import UnknownTenant, resume_tenant
    try:
        resume_tenant(tenant_id)
    except UnknownTenant:
        click.echo(f"ERROR: no such tenant {tenant_id!r}", err=True)
        sys.exit(2)
    click.echo(f"resumed {tenant_id!r}")


@tenant.command("quota")
@click.argument("tenant_id")
@click.argument("max_daily_dollars", type=float)
def tenant_quota(tenant_id: str, max_daily_dollars: float) -> None:
    """Set a tenant's daily spend cap (USD; 0 = unlimited)."""
    import math

    from .tenant_registry import UnknownTenant, set_quota
    # A negative cap was silently clamped to 0 (= UNLIMITED), so a typo'd `-5`
    # quietly removed the cap; nan/inf likewise slipped past as "unlimited" /
    # "$inf/day" -- both disable the cap (user-testing finding). Require a
    # finite, non-negative amount; use 0 for unlimited.
    if not math.isfinite(max_daily_dollars) or max_daily_dollars < 0:
        click.echo(f"ERROR: quota must be a finite, non-negative amount "
                   f"(got {max_daily_dollars:g}); use 0 for unlimited.", err=True)
        sys.exit(2)
    try:
        rec = set_quota(tenant_id, max_daily_dollars)
    except UnknownTenant:
        click.echo(f"ERROR: no such tenant {tenant_id!r}", err=True)
        sys.exit(2)
    # Render 0 as "unlimited" to match `tenant list`; printing "$0/day" while the
    # listing said "unlimited" was a contradiction in the same value.
    cap = f"${rec.max_daily_dollars:g}/day" if rec.max_daily_dollars else "unlimited"
    click.echo(f"{rec.id!r} quota -> {cap}")


@tenant.command("delete")
@click.argument("tenant_id")
@click.option("--purge", is_flag=True,
              help="Also delete the tenant's data directory (irreversible).")
@click.option("--yes", is_flag=True, help="Skip the confirmation prompt.")
def tenant_delete(tenant_id: str, purge: bool, yes: bool) -> None:
    """Remove a tenant from the registry (optionally purging its data)."""
    from .tenant_registry import delete_tenant
    if purge and not yes and not click.confirm(
        f"PURGE all data for tenant {tenant_id!r}? This cannot be undone."
    ):
        click.echo("aborted")
        return
    if delete_tenant(tenant_id, purge=purge):
        click.echo(f"deleted {tenant_id!r}" + (" (data purged)" if purge else ""))
    else:
        click.echo(f"ERROR: no such tenant {tenant_id!r}", err=True)
        sys.exit(2)


@main.group()
def billing() -> None:
    """Rate metered usage into invoices and inspect plan entitlements."""


@billing.command("invoice")
@click.argument("tenant_id")
@click.option("--since", default=None, help="Start day (YYYY-MM-DD, inclusive).")
@click.option("--until", default=None, help="End day (YYYY-MM-DD, inclusive).")
@click.option("--markup-pct", type=float, default=0.0, help="Markup on provider cost.")
@click.option("--min-charge", type=float, default=0.0, help="Minimum invoice total.")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON.")
def billing_invoice(tenant_id: str, since: str | None, until: str | None,
                    markup_pct: float, min_charge: float, as_json: bool) -> None:
    """Generate an invoice for a tenant from its metered usage."""
    import json as _json

    from .audit.events import is_valid_day
    from .billing import RateCard, generate_invoice
    from .tenant_registry import get_tenant, list_tenants
    # Period bounds compare lexically against YYYY-MM-DD ledger keys, so a typo'd
    # --since/--until ("2026-6-1", "june") silently fell out of range and minted
    # a misleading empty invoice. Reject anything that isn't a real calendar day.
    for _label, _val in (("--since", since), ("--until", until)):
        if _val is not None and not is_valid_day(_val):
            click.echo(f"ERROR: {_label} must be a valid YYYY-MM-DD date (got {_val!r}).",
                       err=True)
            sys.exit(2)
    inv = generate_invoice(
        tenant_id, RateCard(markup_pct=markup_pct, minimum_charge=min_charge),
        since=since, until=until,
    )
    # A typo'd tenant id reads an absent ledger and rates to an empty $0 invoice
    # that reads like a real "owes nothing" statement. Flag only the genuinely
    # suspect case -- an EMPTY invoice for a tenant a provisioned roster has
    # never heard of -- as an error. We still invoice (a) any tenant that has
    # usage, so a deleted-but-unpurged tenant's surviving ledger can be billed a
    # final time, and (b) every tenant when no roster exists at all (the opt-in
    # registry is absent in single-tenant deployments), leaving those unchanged.
    if not inv.line_items and list_tenants() and get_tenant(tenant_id) is None:
        click.echo(
            f"ERROR: no such tenant {tenant_id!r}, and no metered usage to bill. "
            "Check the tenant id (or widen --since/--until).", err=True,
        )
        sys.exit(2)
    if as_json:
        click.echo(_json.dumps(inv.to_dict(), indent=2))
        return
    click.echo(f"Invoice for {tenant_id!r}  {inv.period_start or '…'} → {inv.period_end or '…'}")
    for li in inv.line_items:
        click.echo(f"  {li.day}  {li.principal:<24} ${li.charge:.4f} "
                   f"({li.in_tokens}+{li.out_tokens} tok)")
    if not inv.line_items:
        click.echo("  (no metered usage in this period)")
    click.echo(f"  {'-' * 40}")
    click.echo(f"  TOTAL: ${inv.total:.2f} {inv.currency}")


@billing.command("entitlements")
@click.argument("tenant_id")
def billing_entitlements(tenant_id: str) -> None:
    """Show a tenant's plan entitlements (features + limits)."""
    from .billing import entitlements_for
    from .tenant_registry import get_tenant
    rec = get_tenant(tenant_id)
    plan = rec.plan if rec else "free"
    ent = entitlements_for(plan)
    click.echo(f"{tenant_id!r}  plan={plan}")
    click.echo(f"  features: {', '.join(sorted(ent.features)) or '(none)'}")
    cap = f"${ent.max_daily_dollars:g}/day" if ent.max_daily_dollars else "unlimited"
    goals = ent.max_concurrent_goals or "unlimited"
    click.echo(f"  max spend/day: {cap}   max concurrent goals: {goals}")


@main.group()
def diag() -> None:
    """Diagnostics: circuit breakers, rate-limit predictions, run health, cost-by-tag."""


@diag.command("circuits")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON.")
def diag_circuits(as_json: bool) -> None:
    """Show the provider circuit-breaker states (closed/open/half-open)."""
    import json as _json

    from .circuit_breaker import snapshot
    snaps = snapshot()
    if as_json:
        click.echo(_json.dumps(snaps, indent=2))
        return
    if not snaps:
        click.echo("no circuit breakers tripped this process.")
        return
    for s in snaps:
        click.echo(f"  {s.get('key')}: {s.get('state')} "
                   f"(failures={s.get('consecutive_failures', 0)})")


@diag.command("ratelimits")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON.")
def diag_ratelimits(as_json: bool) -> None:
    """Show recent per-provider call rates (feeds the rate-limit predictor)."""
    import json as _json

    from .rate_limit_predictor import report
    rows = report()
    if as_json:
        click.echo(_json.dumps(rows, indent=2))
        return
    if not rows:
        click.echo("no provider calls recorded yet this process.")
        return
    for r in rows:
        click.echo(f"  {r.get('provider')}: {r.get('recorded', 0)} call(s) in window")


@diag.command("health")
@click.argument("goal_id", type=int)
def diag_health(goal_id: int) -> None:
    """Compute a 0-100 health score for a finished goal from its episode."""
    from .health_score import compute_health, render
    from .world_model import DEFAULT_DB, WorldModel
    w = WorldModel(DEFAULT_DB)
    g = w.get_goal(goal_id)
    if g is None:
        click.echo(f"ERROR: no such goal {goal_id}", err=True)
        sys.exit(2)
    eps = w.list_episodes(goal_id=goal_id, limit=50)
    in_tok = sum(getattr(e, "input_tokens", 0) for e in eps)
    out_tok = sum(getattr(e, "output_tokens", 0) for e in eps)
    success = g.status == "done"
    h = compute_health(success=success, in_tok=in_tok, out_tok=out_tok)
    click.echo(f"goal #{goal_id} ({g.status}):")
    click.echo(render(h))


@diag.command("replay")
@click.argument("trace_file", type=click.Path(exists=True))
@click.option("--kind", default=None, help="Only show events of this kind.")
def diag_replay(trace_file: str, kind: str | None) -> None:
    """Read a replayable run trace (written when MAVERICK_TRACE_DIR is set)."""
    from .replay_trace import read_trace
    events = read_trace(trace_file)
    shown = 0
    for e in events:
        if kind and e.get("kind") != kind:
            continue
        shown += 1
        click.echo(f"  [{e.get('seq')}] {e.get('kind')}  "
                   f"{e.get('agent', '')}: {str(e.get('content', ''))[:100]}")
    click.echo(f"  ({shown} of {len(events)} event(s))")


@diag.command("cost-by-tag")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON.")
def diag_cost_by_tag(as_json: bool) -> None:
    """Split run cost across tags (from priced episodes)."""
    import json as _json

    from .cost_by_tag import gather, render
    from .world_model import DEFAULT_DB, WorldModel
    buckets = gather(WorldModel(DEFAULT_DB))
    if as_json:
        click.echo(_json.dumps(buckets, indent=2))
        return
    click.echo(render(buckets))


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
@click.option("--domain", default=None,
              help="Run as a specific domain agent's specialist (see "
                   "`maverick compartments` for available domains).")
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
    domain, coding_mode, best_of_n, fail_to_pass, pass_to_pass, dry_cost,
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
        except (FileNotFoundError, ValueError) as e:
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

    # Refuse BEFORE creating the goal row -- both of these used to surface
    # after `goal #N created`, leaving an orphan blocked/failed row per
    # attempt (platform-test finding).
    from . import killswitch as _ks
    try:
        _ks.check()
    except _ks.Halted:
        click.echo(
            "Stopped: Maverick is halted (a HALT file is present).\n"
            "Run `maverick unhalt` to clear it, then try again.",
            err=True,
        )
        sys.exit(3)  # distinct from misuse (2) so scripts can tell "refused"
    # Refuse a SUSPENDED tenant here too. The channel/HTTP server path enforces
    # assert_tenant_active (server.py), but the CLI `start` path never did, so
    # `maverick start` ran goals freely for a suspended tenant (user-testing
    # finding). No-op for None tenant / no registry, so single-tenant flows are
    # unchanged. Same pre-goal-creation chokepoint as the killswitch above.
    from .paths import current_tenant_id as _ctid
    from .tenant_registry import TenantSuspended, assert_tenant_active
    try:
        assert_tenant_active(_ctid())
    except TenantSuspended as e:
        click.echo(f"Stopped: {e}", err=True)
        sys.exit(3)
    from . import providers as _providers
    from .config import load_config as _load_config
    _specs = {
        s for s in (_load_config().get("models") or {}).values()
        if isinstance(s, str) and s
    }
    _specs.add(ctx.obj["model"] or _kernel().DEFAULT_MODEL)
    _sdk_msgs = _providers.missing_sdks(sorted(_specs))
    if _sdk_msgs:
        for m in _sdk_msgs:
            click.echo(f"ERROR: {m}", err=True)
        sys.exit(2)

    k = _kernel()
    world = open_world(ctx.obj["db"])
    goal_id = world.create_goal(title, description)
    click.echo(f"goal #{goal_id} created: {title}")
    llm = k.LLM(model=ctx.obj["model"] or k.DEFAULT_MODEL)
    # Honor [budget] in config.toml (start used to build Budget() directly,
    # so config caps were silently ignored). Precedence: built-in defaults
    # < config < explicit CLI flags. A None flag passes through as "unset".
    import types as _types

    from .budget import budget_from_config
    from .orchestrator import _budget_task_class
    bud = budget_from_config(
        defaults={"max_dollars": 5.0, "max_wall_seconds": 3600.0},
        # Learned per-class default cap (lowest precedence; opt-in via
        # [budget] self_tuning). Department runs use their own class so
        # finance runs are sized by finance history.
        task_class=_budget_task_class(
            _types.SimpleNamespace(title=title), domain,
        ),
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
    stop_poll = threading.Event()
    poller = _maybe_start_progress_poller(world.path, goal_id, stop_poll)

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
                sandbox=sandbox, max_depth=max_depth, domain=domain,
            )
        # Capture the kernel's final verdict before the DB is closed so the
        # exit code can reflect it (see _run_outcome_blocked).
        _blocked = _run_outcome_blocked(world, goal_id)
    finally:
        stop_poll.set()
        if poller is not None:
            poller.join(timeout=2.0)
        # Close so WorldModel.close()'s WAL TRUNCATE checkpoint runs; the
        # poller thread (already joined) used its own connection.
        world.close()
    click.echo("")
    click.echo(result)
    if _blocked:
        # Exit nonzero so a script / CI can tell a halted or paused run from a
        # clean success; the human-readable reason is already printed above.
        # (start used to exit 0 for every outcome -- user-testing finding.)
        sys.exit(2)


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
    except (FileNotFoundError, ValueError) as e:
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
    from .marketplace_ratings import RatingsLedger, stars_bar
    ledger = RatingsLedger()
    for e in entries:
        mark = " [verified]" if e.verified else ""
        rating = f"  {stars_bar(e.rating, e.ratings_count)}" if e.ratings_count else ""
        click.echo(f"  {e.name}{mark}  v{e.version}{rating}")
        if e.summary:
            click.echo(f"    {e.summary}")
        mine = ledger.my_rating("templates", e.name)
        if mine:
            click.echo(f"    your rating: {stars_bar(mine['stars'], 0)}")
    click.echo("")
    click.echo("install one with:  maverick template add <name>")
    click.echo("rate one with:     maverick template rate <name> <stars 1-5>")


@template.command("rate")
@click.argument("name")
@click.argument("stars", type=int)
@click.option("--comment", default="", help="Optional short note (kept local).")
def template_rate(name: str, stars: int, comment: str) -> None:
    """Rate a marketplace template 1-5 stars (stored locally).

    Your ratings annotate `browse` output and can be exported for an index
    submission with `maverick template ratings-export`.
    """
    from .marketplace_ratings import RatingsLedger, stars_bar
    try:
        entry = RatingsLedger().rate("templates", name, stars, comment)
    except ValueError as e:
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(2)
    click.echo(f"rated {name}: {stars_bar(entry['stars'], 0)}")


@template.command("ratings-export")
def template_ratings_export() -> None:
    """Print your local ratings as the JSON fragment an index PR expects."""
    from .marketplace_ratings import RatingsLedger
    click.echo(RatingsLedger().export_for_submission())


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
    # Friendly preflight (round-3 platform-test finding: an unconfigured
    # install got a raw anthropic-SDK TypeError traceback here), and route
    # through the configured role models instead of hard DEFAULT_MODEL
    # (kernel rule 2) -- debaters argue at the analyst tier.
    _require_llm_key()
    from .llm import model_for_role
    k = _kernel()
    llm = k.LLM(model=ctx.obj["model"] or model_for_role("analyst"))
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


@main.command("schema-plan")
def schema_plan_cmd() -> None:
    """Show pending world-model schema migrations + whether they're hot-safe.

    Classifies each pending statement online (non-blocking) vs offline (table
    rewrite / data backfill) so you know before upgrading whether a
    maintenance window is needed. Exits 1 when the migration table fails its
    structural lint.
    """
    from .schema_migrations import plan, render, validate
    from .world_model import DEFAULT_DB, SCHEMA_VERSION, WorldModel
    problems = validate()
    if problems:
        for pb in problems:
            click.echo(f"LINT: {pb}", err=True)
        sys.exit(1)
    try:
        w = WorldModel(DEFAULT_DB)
        current = w.conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()[0]
    except Exception:
        current = SCHEMA_VERSION  # no DB yet -> nothing pending
    click.echo(render(plan(int(current), SCHEMA_VERSION)))


@main.command("config-lint")
def config_lint_cmd() -> None:
    """Validate ~/.maverick/config.toml: unknown sections/keys + obvious type
    mistakes, with closest-match suggestions. Exits 1 if any error-level finding."""
    from .config import config_path, load_config
    from .config_lint import format_findings, lint_config
    # load_config() is deliberately fail-soft: a corrupt config.toml yields {}
    # with only a warning, so linting it would find nothing and print
    # "config OK" -- the one tool meant to catch a broken config blessing a
    # file in which every setting is being dropped (round-4 finding; mirrors
    # health._check_config). Parse the raw file FIRST so a syntax error is a
    # hard lint failure, not invisible.
    p = config_path()
    if not p.exists():
        # No config at all is a legitimate state (Maverick runs on built-in
        # defaults), but the file-less path used to fall through to
        # load_config() == {} and print "config OK" -- as if a real config had
        # been validated. Say plainly there's nothing to lint instead of
        # blessing a non-existent file (user-testing finding).
        click.echo(
            f"no config file at {p}; Maverick is using built-in defaults. "
            "Create one with `maverick init` (nothing to lint yet)."
        )
        return
    try:
        import tomllib
    except ModuleNotFoundError:  # 3.10
        import tomli as tomllib
    try:
        with open(p, "rb") as f:
            tomllib.load(f)
    except (tomllib.TOMLDecodeError, OSError, UnicodeDecodeError) as e:
        click.echo(
            f"error: {p} is not valid TOML -- every setting in it is being "
            f"IGNORED ({type(e).__name__}: {e})", err=True,
        )
        click.echo("fix the syntax above, or back it up and re-run `maverick init`.")
        sys.exit(1)
    try:
        cfg = load_config() or {}
    except Exception as e:
        click.echo(f"could not load config: {e}", err=True)
        sys.exit(1)
    findings = lint_config(cfg)
    click.echo(format_findings(findings))
    if any(getattr(f, "severity", "") == "error" for f in findings):
        sys.exit(1)


@main.command("costs")
@click.option("--limit", default=30, show_default=True, help="Rows to show.")
def costs_cmd(limit: int) -> None:
    """Cross-run spend, by day, from recorded episodes (the persisted ledger)."""
    from datetime import datetime, timezone

    from .cost_report import format_report
    from .world_model import DEFAULT_DB, WorldModel
    w = WorldModel(DEFAULT_DB)
    rows: list[dict] = []
    try:
        for ep in w.list_episodes(limit=1_000_000):
            if ep.cost_dollars and ep.ended_at:
                day = datetime.fromtimestamp(ep.ended_at, tz=timezone.utc).strftime("%Y-%m-%d")
                rows.append({"dollars": ep.cost_dollars, "day": day})
    finally:
        w.close()
    click.echo(format_report(rows, by="day", top=limit))


@main.command("migrate")
@click.option("--apply", "do_apply", is_flag=True,
              help="Apply mechanical rewrites (after a timestamped backup). "
                   "Default is a dry run.")
@click.option("--config", "config_path", default=None,
              help="Path to config.toml (default: the active deployment's).")
def migrate_cmd(do_apply: bool, config_path: str | None) -> None:
    """Walk an existing config forward across versions.

    Reports migration advisories (real upgrade paths), lints unknown config
    sections (silent-no-op typos), and -- with --apply -- performs mechanical
    key renames behind a timestamped backup. Dry-run by default.
    """
    from pathlib import Path as _Path

    from .migrate import migrate, render
    report = migrate(_Path(config_path) if config_path else None, apply=do_apply)
    click.echo(render(report))


@main.command("plan-reflect")
@click.argument("goal")
@click.option("--max-iterations", default=3, show_default=True, type=int,
              help="Max plan->execute->reflect passes before stopping.")
@click.option("--max-dollars", default=2.0, show_default=True, type=float,
              help="Spend cap for the whole loop.")
@click.pass_context
def plan_reflect(ctx, goal: str, max_iterations: int, max_dollars: float) -> None:
    """Run the plan-execute-reflect loop on GOAL and print the trace.

    A planner breaks GOAL into steps, an executor runs each, and a reflector
    decides DONE / REVISE / CONTINUE -- looping until the goal is met, the
    iteration cap is reached, or the budget runs out.
    """
    from .budget import Budget
    from .plan_execute_reflect import run_plan_execute_reflect
    # Same preflight + role routing as `debate` (round-3 finding): planning
    # belongs to the orchestrator tier, and a missing provider must refuse
    # cleanly, not traceback inside the anthropic client constructor.
    _require_llm_key()
    from .llm import model_for_role
    k = _kernel()
    llm = k.LLM(model=ctx.obj["model"] or model_for_role("orchestrator"))
    result = run_plan_execute_reflect(
        goal,
        planner_complete=llm.complete,
        executor_complete=llm.complete,
        reflector_complete=llm.complete,
        max_iterations=max_iterations,
        budget=Budget(max_dollars=max_dollars),
    )
    click.echo(f"Plan ({len(result.plan)} steps): {', '.join(result.plan) or '(empty)'}")
    for r in result.results:
        click.echo(f"\n[{r.step}]\n{r.output}")
    click.echo("\n" + "=" * 48)
    for i, refl in enumerate(result.reflections, 1):
        click.echo(f"reflect {i}: {refl.status} -- {refl.notes}")
    click.echo(f"\nStatus: {result.status} "
               f"[{result.iterations} iteration(s), ${result.total_dollars:.4f}]")


@main.command()
@click.option("--idle-sleep", default=2.0, show_default=True,
              help="Seconds to wait when the queue is empty.")
@click.option("--once", is_flag=True,
              help="Drain ready jobs and exit (for cron / systemd timers).")
def worker(idle_sleep: float, once: bool) -> None:
    """Run the background job worker.

    Drains the job queue (``~/.maverick/jobs.db``) and runs jobs armed with
    ``maverick schedule add``. Runs until interrupted (Ctrl-C / SIGTERM).

    With ``--once``, run all currently-ready jobs and exit instead of staying
    resident -- run it from system cron or a systemd timer for scheduling
    without a persistent daemon.
    """
    from .worker import Worker
    w = Worker(idle_sleep=idle_sleep)
    if once:
        n = w.drain()
        click.echo(f"drained {n} job(s)")
        return
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


@schedule.command("goal")
@click.argument("cron_expr")
@click.argument("text")
@click.option("--title", default=None,
              help="Short goal title (default: derived from TEXT).")
def schedule_goal(cron_expr: str, text: str, title: str | None) -> None:
    """Arm a recurring autonomous goal: run TEXT as a FRESH goal on CRON_EXPR.

    Unlike `schedule add run_goal` (which re-runs one fixed goal id), every fire
    creates a new goal from TEXT -- a true recurring task. Drain the queue with
    `maverick worker`; manage it with `schedule list` / `schedule rm`.

    Example: maverick schedule goal "0 9 * * 1-5" "Summarize my overnight emails"
    """
    from .job_queue import JobQueue
    from .scheduler import CronError, next_run, schedule_cron
    if not text.strip():
        click.echo("ERROR: goal TEXT must not be empty.", err=True)
        sys.exit(2)
    try:
        next_run(cron_expr)  # validate up front
    except CronError as e:
        click.echo(f"ERROR: bad cron expression: {e}", err=True)
        sys.exit(2)
    payload: dict = {"text": text, "__cron__": cron_expr}
    if title:
        payload["title"] = title
    job_id, run_at = schedule_cron(JobQueue(), cron_expr, "start_goal", payload)
    from datetime import datetime
    when = datetime.fromtimestamp(run_at).strftime("%Y-%m-%d %H:%M:%S")
    click.echo(f"scheduled goal job {job_id}; next run {when}")


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
@click.option("--cost", is_flag=True,
              help="Include persisted spend totals and recent run costs.")
@click.pass_context
def status(ctx, cost: bool) -> None:
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
    if cost:
        total = world.total_spend()
        click.echo(click.style("Spend", bold=True))
        click.echo(f"  ${total['dollars']:.4f}  across {total['runs']} completed run(s)")
        click.echo(
            f"  {total['input_tokens']:,} input tokens  /  "
            f"{total['output_tokens']:,} output tokens"
        )
        recent = world.list_episodes(limit=5)
        if recent:
            click.echo("  recent:")
            for e in recent:
                outcome = e.outcome or "running"
                click.echo(f"    ep #{e.id} (goal {e.goal_id}) [{outcome}]  ${e.cost_dollars:.4f}")
        click.echo("")
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
@click.option("-n", "--limit", default=10, show_default=True, type=int,
              help="Max recent goals to include.")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON.")
@click.pass_context
def ps(ctx, limit: int, as_json: bool) -> None:
    """List the runtime's processes: recent goals + scheduled jobs.

    A unified, read-only view across the two execution surfaces -- the world
    model's goals (last activity) and the cron/job queue (next run) -- so you
    can see what the runtime is doing or about to do in one place. Goals alone:
    `maverick status`; scheduled jobs alone: `maverick schedule list`.
    """
    import datetime as _dt
    import json as _json

    from .world_model import open_world

    def _when(ts: float | None) -> str:
        if not ts:
            return ""
        return _dt.datetime.fromtimestamp(
            ts, _dt.timezone.utc).strftime("%Y-%m-%d %H:%M")

    procs: list[dict] = []
    try:
        world = open_world(ctx.obj["db"])
        for g in world.list_goals(limit=limit, order="desc"):
            procs.append({"type": "goal", "id": g.id, "state": g.status,
                          "when": _when(g.updated_at), "what": g.title})
    except Exception:  # fail-soft: a missing/locked world shouldn't crash ps
        pass
    try:
        from .job_queue import JobQueue
        for j in JobQueue().list(status="pending"):
            cron = j.payload.get("__cron__")
            what = j.kind + (f"  [{cron}]" if cron else "")
            procs.append({"type": "job", "id": j.id, "state": j.status,
                          "when": _when(j.run_at), "what": what})
    except Exception:
        pass

    if as_json:
        click.echo(_json.dumps(procs, default=str))
        return
    if not procs:
        click.echo("no goals or scheduled jobs.")
        return
    click.echo(f"{'TYPE':4}  {'ID':>5}  {'STATE':9}  {'WHEN (UTC)':16}  WHAT")
    for p in procs:
        what = _strip_terminal_control(str(p["what"]))
        click.echo(f"{p['type']:4}  {p['id']!s:>5}  {p['state']:9}  "
                   f"{p['when']:16}  {what}")


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
@click.option("--sandbox", "sandbox_backend", default=None,
              type=click.Choice(["local", "docker", "podman", "devcontainer",
                                 "kubernetes", "ssh", "firecracker"]),
              help="Sandbox backend for this resume (default: the [sandbox] config).")
@click.pass_context
@_humane_errors
def resume(ctx, goal_id_arg, goal_id, max_depth: int, max_dollars, max_wall_seconds,
           sandbox_backend) -> None:
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
    # --sandbox overrides it, so an operator who ran `start --sandbox docker`
    # keeps the same isolation on resume (user-testing finding); None = config.
    sandbox = k.build_sandbox(backend=sandbox_backend)
    result = k.run_goal_sync(llm, world, bud, goal_id,
                             sandbox=sandbox, max_depth=max_depth,
                             resume=True)
    click.echo(result)


@main.command()
@click.argument("goal_id", type=int)
@click.option("--to-step", type=int, default=None,
              help="Rewind to this checkpoint step (the agent re-runs from here).")
@click.option("--fork", is_flag=True,
              help="Restart from the step as a NEW goal, leaving the original intact.")
@click.option("--list", "list_only", is_flag=True,
              help="List the checkpoint steps available to rewind to.")
@click.pass_context
@_humane_errors
def rewind(ctx, goal_id: int, to_step, fork: bool, list_only: bool) -> None:
    """Restart a goal from an earlier checkpoint (durable execution).

    \b
      maverick rewind 7 --list                # which steps can I go back to?
      maverick rewind 7 --to-step 12          # re-run goal 7 from step 12
      maverick rewind 7 --to-step 12 --fork   # try a different branch as a new goal

    Requires durable execution ([durable] enabled) to have checkpointed the run.
    After rewinding, continue the run with `maverick resume`.
    """
    from . import checkpoint as ckpt_mod
    world = open_world(ctx.obj["db"])
    if not world.get_goal(goal_id):
        click.echo(f"no such goal #{goal_id}. See `maverick status`.", err=True)
        sys.exit(2)
    ck = ckpt_mod.Checkpointer(world)
    found = ck.orchestrator_for(goal_id)
    if found is None:
        click.echo(f"goal #{goal_id} has no checkpoints "
                   "(durable execution off, or it was never run with it on).")
        return
    agent_id, episode_id = found
    if list_only or to_step is None:
        steps = ck.list_steps(goal_id, agent_id, episode_id)
        if not steps:
            click.echo(f"goal #{goal_id}: no checkpoint steps recorded.")
        else:
            click.echo(f"goal #{goal_id} checkpoint steps available: "
                       f"{steps[0]}..{steps[-1]} ({len(steps)} kept)")
            click.echo(f"rewind with `maverick rewind {goal_id} --to-step N [--fork]`")
        return
    res = ckpt_mod.rewind(world, goal_id, to_step, fork=fork)
    click.echo(res.detail)
    if not res.ok:
        sys.exit(1)


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
    from .skills import available_skills, builtin_skills_dir
    items = available_skills()
    if not items:
        click.echo(f"no skills yet (in {builtin_skills_dir()} or ~/.maverick/skills).")
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


@plugin.command("reload")
@click.argument("dist_name")
def plugin_reload(dist_name: str) -> None:
    """Hot-reload a plugin distribution's code (no process restart).

    Drops DIST_NAME's entry-point modules from the import cache so the next
    discovery pass re-imports the current code on disk. Already-instantiated
    tools/channels keep running old code until their owner rebuilds them.
    """
    from .plugins import reload_plugin
    dropped = reload_plugin(dist_name)
    if not dropped:
        click.echo(f"no maverick entry points found for distribution {dist_name!r} "
                   "(is it installed and allowlisted?)")
        sys.exit(1)
    click.echo(f"reloaded {dist_name}: dropped {len(dropped)} module(s)")
    for m in dropped:
        click.echo(f"  - {m}")


@plugin.command("lock")
def plugin_lock_cmd() -> None:
    """Pin the active plugin distributions' versions to plugins.lock.

    Discovery verifies installed versions against the lock per
    [plugins] lock_policy = "off" | "warn" | "enforce".
    """
    from .plugin_lock import lock_path, write_lock
    pins = write_lock()
    if not pins:
        click.echo("no plugin distributions found to pin.")
        return
    click.echo(f"pinned {len(pins)} plugin distribution(s) -> {lock_path()}")
    for name, version in sorted(pins.items()):
        click.echo(f"  {name} == {version}")


@plugin.command("verify")
def plugin_verify_cmd() -> None:
    """Verify installed plugin versions against plugins.lock."""
    from .plugin_lock import verify_lock
    report = verify_lock()
    if report.get("unlocked"):
        click.echo("no plugins.lock (run `maverick plugin lock` to pin). OK")
        return
    for name, pinned, installed in report["drifted"]:
        click.echo(f"  DRIFT {name}: locked {pinned}, installed {installed}")
    for name in report["missing"]:
        click.echo(f"  MISSING {name} (pinned but not installed)")
    for name in report["unpinned"]:
        click.echo(f"  unpinned {name} (installed but not in the lock)")
    if report["ok"]:
        click.echo("plugins.lock OK")
    else:
        click.echo("plugins.lock FAIL")
        sys.exit(1)


@plugin.command("stats")
def plugin_stats_cmd() -> None:
    """Show local plugin-tool usage counts (opt-in [plugins] telemetry)."""
    import time as _time

    from .plugin_telemetry import enabled as _ptel_enabled
    from .plugin_telemetry import stats as _ptel_stats
    data = _ptel_stats()
    if not _ptel_enabled():
        click.echo("plugin telemetry is OFF ([plugins] telemetry = true to enable).")
    if not data:
        click.echo("no plugin tool calls recorded.")
        return
    for name, entry in sorted(data.items(), key=lambda kv: -kv[1].get("calls", 0)):
        last = entry.get("last_used")
        ago = f"{(_time.time() - last) / 86400:.0f}d ago" if last else "never"
        dist = f" [{entry['dist']}]" if entry.get("dist") else ""
        click.echo(f"  {name}{dist}: {entry.get('calls', 0)} call(s), last {ago}")


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
    click.echo(f"installed: {s.path.stem} -> {s.path}")


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
    click.echo(f"installed: {s.path.stem} -> {s.path}")


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

    # Step 4b: remove derived per-user preference notes from the dreaming
    # store. These live outside world.db, so the SQL cascade above cannot
    # erase them; use the concrete matched conversation user_ids so CLI
    # family erasure (local -> local:<uuid>) removes every scoped note.
    removed_user_notes = 0
    try:
        from . import user_notes as _user_notes
        removed_user_notes = _user_notes.erase_notes(
            channel, {c.user_id for c in convs if c.user_id},
        )
    except Exception as exc:  # pragma: no cover - defensive
        click.echo(
            f"warning: erased the database but could not scrub user notes "
            f"({type(exc).__name__}: {exc}); they may retain prior preferences.",
            err=True,
        )

    # Step 4c: scrub explicitly user-scoped global facts. Facts are global
    # key/value pairs with no per-user attribution, so erase only touches
    # facts deliberately keyed as user:<channel>:<user_id>:<name>. Arbitrary
    # substring matching is unsafe for short/common user ids because it can
    # delete unrelated operator knowledge or other users' data.
    fact_subject = _fact_subject_token(channel, user)
    scrubbed_fact_keys = world.delete_facts_matching(fact_subject)

    # Step 4d: the optional LLM cache (MAVERICK_LLM_CACHE=1) is content-
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
        user_notes_scrubbed=removed_user_notes,
    )

    click.echo(
        f"erased {len(convs)} conversation(s), {removed_turns} turn(s), "
        f"{len(goal_ids)} goal(s) and all linked rows, "
        f"{removed_attachments} attachment file(s), "
        f"{audit_scrubbed} audit event(s) scrubbed, "
        f"{len(scrubbed_fact_keys)} fact(s) scrubbed, "
        f"{removed_user_notes} user note(s) scrubbed"
    )
    if scrubbed_fact_keys:
        click.echo(
            "  facts removed (global key/value, scoped with user:<channel>:<user_id>: "
            f"prefix): {', '.join(scrubbed_fact_keys)}"
        )


@main.command("erase-verify")
@click.option("--channel", required=True, help="Channel name (e.g. telegram, sms).")
@click.option("--user", required=True, help="The channel user_id to verify.")
@click.option("--tenant", default=None, help="Tenant data plane (default: active).")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON.")
def erase_verify(channel: str, user: str, tenant: str | None, as_json: bool) -> None:
    """Verify a (channel, user_id) was fully erased: zero residual records.

    Right-to-erasure proof (GDPR Art. 17): reuses the DSAR export, whose
    subject-matching agrees with the erase path, so any residual count is an
    incomplete erasure. Read-only; run it after `maverick erase`.
    """
    import json as _json

    from .erasure_verify import verify_erasure
    report = verify_erasure(user, channel=channel, tenant=tenant)
    if as_json:
        click.echo(_json.dumps(report, default=str))
        if not report["clean"]:
            raise SystemExit(1)
        return
    if report["clean"]:
        click.echo(click.style(
            f"CLEAN: no residual data for {channel}:{user}", fg="green"))
        return
    click.echo(click.style(
        f"RESIDUAL DATA for {channel}:{user} — erasure incomplete:", fg="red"))
    for store, n in sorted(report["residual"].items()):
        click.echo(f"  {store}: {n}")
    raise SystemExit(1)


@main.command("compliance")
@click.option("--format", "fmt", type=click.Choice(["text", "json"]), default="text",
              help="Output format.")
@click.option("--strict", is_flag=True,
              help="Exit non-zero if any control needs action (gate CI / deploys).")
@click.option("--framework", type=click.Choice(["eu", "us", "all"]), default="all",
              help="Filter to a jurisdiction's frameworks (default: all).")
@click.pass_context
def compliance_cmd(ctx, fmt: str, strict: bool, framework: str) -> None:
    """Report GDPR + EU AI Act + US-framework control coverage for this deployment.

    Maps each active control to the article/framework it supports (EU AI Act,
    GDPR, NIST AI RMF, Colorado AI Act, NYC Local Law 144, EEOC, CCPA) and flags
    opt-in controls that are off. Control coverage only -- not a legal attestation.

    With --strict, exits non-zero if any control is "action needed", so a
    regulated deployment can fail a CI job / release gate when its posture
    regresses (the report still prints first).
    """
    from .compliance import (
        compliance_report,
        render_report_json,
        render_report_text,
    )
    checks = compliance_report()
    if framework != "all":
        checks = [c for c in checks if c.framework == framework]
    click.echo(
        render_report_json(checks) if fmt == "json" else render_report_text(checks)
    )
    if strict:
        needs_action = [c.control for c in checks if c.status == "action_needed"]
        if needs_action:
            raise click.ClickException(
                f"{len(needs_action)} control(s) need action: "
                + ", ".join(needs_action)
            )


@main.group("finance")
def finance_grp() -> None:
    """Finance suite: the CFO-office control plane (finance-agent-suite)."""


@finance_grp.command("status")
@click.option("--format", "fmt", type=click.Choice(["text", "json"]), default="text",
              help="Output format.")
@click.option("--strict", is_flag=True,
              help="Exit non-zero if any control needs action (gate CI / deploys).")
def finance_status_cmd(fmt: str, strict: bool) -> None:
    """Report finance control coverage (SoD, maker-checker, DoA tiers, book of
    record, sanctions, encryption, egress, regimes).

    Control coverage only -- not an audit opinion. Agents draft; humans post, pay,
    file, and certify. With --strict, exits non-zero if any control needs action.
    """
    from .finance.status import (
        finance_status,
        render_status_json,
        render_status_text,
    )
    checks = finance_status()
    click.echo(
        render_status_json(checks) if fmt == "json" else render_status_text(checks)
    )
    if strict:
        needs_action = [c.control for c in checks if c.status == "action_needed"]
        if needs_action:
            raise click.ClickException(
                f"{len(needs_action)} finance control(s) need action: "
                + ", ".join(needs_action)
            )


@finance_grp.command("lint-sod")
def finance_lint_sod_cmd() -> None:
    """Lint the finance roster for segregation-of-duties conflicts (CI gate)."""
    from .domain import builtin_dir, load_domains, user_dir
    from .finance.sod_linter import lint_roster
    packs = {n: p for n, p in {**load_domains(builtin_dir()),
                               **load_domains(user_dir())}.items()
             if n.startswith("finance_")}
    conflicts = lint_roster(packs)
    if not conflicts:
        click.echo(f"OK: {len(packs)} finance packs are segregation-of-duties clean.")
        return
    for c in conflicts:
        click.echo(f"SoD CONFLICT: {c}", err=True)
    raise click.ClickException(f"{len(conflicts)} SoD conflict(s)")


@main.command()
@click.option("--max-goals", default=50, show_default=True,
              help="How many recent finished goals to replay.")
@click.option("--rehearse", is_flag=True,
              help="After consolidating, RUN the queued rehearsal cases as "
                   "real (budgeted) practice goals. Spends tokens; gated by "
                   "the calibration interlock.")
@click.option("--rehearse-budget", default=1.0, show_default=True,
              help="Max $ per rehearsal case.")
@click.option("--dry-run", is_flag=True,
              help="Run the full cycle against TEMP COPIES of every learned "
                   "store and report what WOULD change, writing nothing.")
@click.option("--list-snapshots", "list_snaps", is_flag=True,
              help="List learning-state snapshots available for --rollback.")
@click.option("--rollback", default=None, metavar="SNAPSHOT",
              help="Restore every learned store from a snapshot "
                   "('latest' or a name from --list-snapshots), then exit.")
@click.option("--donations-dir", default=None, type=click.Path(),
              help="Also replay donated trajectory records from this "
                   "directory (fleet-level aggregation on a central "
                   "instance).")
@click.pass_context
def dream(ctx, max_goals: int, rehearse: bool, rehearse_budget: float,
          dry_run: bool, list_snaps: bool, rollback: str | None,
          donations_dir: str | None) -> None:
    """Run one offline dreaming cycle (experience consolidation).

    Replays recent successes and failure reflexions, groups them by
    department (domain packs), distills recurring wins into learned skills,
    consolidates recurring failures into dream insights (recalled on future
    similar goals), retires learned skills with a decayed track record, and
    prunes stale near-duplicate reflexions. The consolidation pass is
    deterministic and LLM-free -- costs no tokens. Requires [dreaming]
    enable = true or MAVERICK_DREAMING=1; run from cron/systemd nightly.

    With --rehearse (and [dreaming] rehearse = true to queue cases), the
    biggest recurring failure patterns are re-run as budgeted practice goals
    (titled "[rehearsal] ...") so the next real attempt starts from a system
    that has already practiced. Refused while verifier calibration is frozen.
    """
    from . import dreaming
    if list_snaps:
        snaps = dreaming.list_snapshots()
        click.echo("\n".join(snaps) if snaps else "(no snapshots yet)")
        return
    if rollback:
        try:
            restored = dreaming.rollback_learning_state(rollback)
        except ValueError as e:
            raise click.ClickException(str(e)) from e
        if not restored:
            raise click.ClickException("no snapshots to roll back to.")
        click.echo("Restored learned state from snapshot: "
                   + ", ".join(restored))
        return
    if not dreaming.enabled():
        raise click.ClickException(
            "dreaming is disabled. Set MAVERICK_DREAMING=1 or add\n"
            "  [dreaming]\n  enable = true\nto ~/.maverick/config.toml."
        )
    world = open_world(ctx.obj["db"])
    if dry_run:
        report = dreaming.dream_cycle_dry(
            world, max_goals=max_goals, donations_dir=donations_dir,
        )
        click.echo("(dry run -- nothing written) " + report.summary())
        return
    # Learning rollback, half 1: snapshot every learned store before this
    # cycle mutates anything, so `--rollback latest` can undo it wholesale.
    cfg = dreaming.settings()
    if cfg.get("snapshots", True):
        snap = dreaming.snapshot_learning_state(
            keep_last=int(cfg.get("snapshot_keep_last", 5)),
        )
        if snap is not None:
            click.echo(f"[snapshot: {snap.name}]")
    report = dreaming.dream_cycle(
        world, max_goals=max_goals, donations_dir=donations_dir,
    )
    click.echo(report.summary())
    # Cognitive Data Engine: turn the flywheel as part of the nightly cycle --
    # triage failures by causal impact, mine self-correcting guardrails,
    # consolidate beneficial habits, propose improvements, all grounded in real
    # outcomes. No-op unless [data_engine] is enabled; never breaks dreaming.
    try:
        from . import data_engine
        if data_engine.enabled():
            from .flywheel import maybe_run
            fw = maybe_run()
            if fw.acted:
                click.echo(
                    f"[flywheel] {len(fw.guardrails)} guardrails, {len(fw.memories)} "
                    f"habits, {len(fw.hypotheses)} improvements "
                    f"(recoverable lift ~{fw.predicted_lift:.2f})")
    except Exception:  # pragma: no cover -- the flywheel must never break dreaming
        pass
    if not rehearse:
        return
    cases = dreaming.load_rehearsals()
    if not cases:
        click.echo("Rehearsal: no queued cases (enable [dreaming] rehearse "
                   "so dream cycles queue recurring failures).")
        return
    from .budget import Budget
    from .llm import LLM, model_for_role
    from .orchestrator import run_goal
    from .sandbox import build_sandbox

    llm = LLM(model=ctx.obj["model"] or model_for_role("orchestrator"))
    sandbox = build_sandbox()
    cases_by_prompt = {str(c.get("prompt", "")): c for c in cases}

    async def _practice(prompt: str) -> str:
        case = cases_by_prompt.get(prompt, {})
        gid = world.create_goal(
            f"[rehearsal] {prompt[:200]}",
            "Dream-time rehearsal of a previously-failing goal pattern.",
        )
        return await run_goal(
            llm=llm, world=world, budget=Budget(max_dollars=rehearse_budget),
            goal_id=gid, sandbox=sandbox, domain=case.get("domain"),
        )

    async def _score(prompt: str, output: str) -> float:
        # Verifier-scored rehearsal: completion alone is a weak signal, so a
        # case only counts as practiced when the calibrated verifier rates
        # the answer too. Scoring spends from its own small budget.
        from .verifier import verify_proposal
        v = await verify_proposal(
            prompt, output, llm, Budget(max_dollars=max(0.25, rehearse_budget / 4)),
        )
        return float(getattr(v, "confidence", 0.0) or 0.0)

    try:
        passed, total = asyncio.run(dreaming.rehearse(_practice, scorer=_score))
    except dreaming.RehearsalFrozen as e:
        raise click.ClickException(str(e)) from e
    click.echo(f"Rehearsal: {passed}/{total} previously-failing pattern(s) "
               "now complete (verifier-scored).")


@main.command("demo")
def demo_cmd() -> None:
    """The two-minute tour: watch the workforce learn, prove it, no API key.

    Seeds a throwaway world (finance goals, repeated failures), runs a real
    dream cycle (consolidation), a real hindsight replay (before vs after
    learning), and the value report -- entirely deterministic and LLM-free,
    in a temp directory that is deleted afterwards. Nothing touches your
    real ~/.maverick state.
    """
    import tempfile
    from pathlib import Path as _P

    from . import dreaming, hindsight, reflexion, workforce_value
    from .world_model import WorldModel

    tmp = _P(tempfile.mkdtemp(prefix="maverick-demo-"))
    try:
        world = WorldModel(tmp / "world.db")
        # A quarter's worth of finance work: wins land, one pattern keeps
        # failing -- the raw material every real deployment produces.
        for title in ("Reconcile the March ledger totals",
                      "Reconcile the April ledger totals",
                      "Reconcile the May ledger totals"):
            gid = world.create_goal(title, domain="finance_sox")
            eid = world.start_episode(gid)
            world.end_episode(eid, "tied out", "success")
            world.set_goal_status(gid, "done", result="tied out")
        for title in ("Reconcile the partner ledger feed",
                      "Reconcile the quarterly partner ledger"):
            gid = world.create_goal(title, domain="finance_sox")
            world.set_goal_status(gid, "blocked", result="partner feed lagged")
        state = tmp / "state"
        rpath = state / "reflexions.ndjson"
        for goal in ("Reconcile the partner ledger feed",
                     "Reconcile the quarterly partner ledger"):
            reflexion.record(goal_text=goal, failure_class="agent_error",
                             failure_msg="partner feed lagged a day",
                             reflection="wait for the partner close before "
                                        "reconciling the feed",
                             domain="finance_sox", path=rpath)
        click.echo("1) DREAM -- consolidate the quarter's experience:")
        report = dreaming.dream_cycle(
            world, reflexion_path=rpath,
            insights_path=state / "insights.ndjson",
            skill_store=state / "learned-skills",
            skill_stats_path=tmp / "skill_stats.json",
            rehearsals_path=tmp / "rehearsals.ndjson",
            user_notes_path=tmp / "user_notes.ndjson",
            settings_override={"enable": True, "min_cluster": 2,
                               "prune": False, "user_notes": False},
        )
        click.echo("   " + report.summary())
        click.echo("\n2) HINDSIGHT -- did learning help on the failures?")
        empty = tmp / "before"
        empty.mkdir()
        h = hindsight.replay(world, before=empty, after=state)
        click.echo("   " + h.summary().replace("\n", "\n   "))
        click.echo("\n3) PROOF -- the value report:")
        v = workforce_value.compute(world, window_days=365, human_cost=120.0)
        click.echo("   " + workforce_value.format_report(v)
                   .replace("\n", "\n   "))
        click.echo("\nDeterministic, token-free, and every step above is "
                   "audited/reversible in a real deployment.")
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


@main.command("forward")
@click.option("--days", default=30, show_default=True,
              help="Horizon: obligations due within N days.")
@click.pass_context
def forward_cmd(ctx, days: int) -> None:
    """The forward ledger (v1): every known upcoming obligation, pre-staged.

    Lists pending/active goals with deadlines inside the horizon -- overdue
    first -- with the blockers a human will be asked for (open questions),
    so decisions arrive prepared instead of discovered late.
    """
    import time as _time
    world = open_world(ctx.obj["db"])
    now = _time.time()
    horizon = now + days * 86400.0
    rows = []
    for g in world.list_goals(limit=2000):
        if g.status not in ("pending", "active"):
            continue
        if not g.deadline or g.deadline > horizon:
            continue
        qs = world.open_questions(g.id)
        rows.append((g.deadline, g, len(qs)))
    if not rows:
        click.echo(f"No goal deadlines within {days} day(s). "
                   "(Set deadlines on goals to populate the forward ledger.)")
        return
    rows.sort(key=lambda r: r[0])
    for deadline, g, nq in rows:
        delta = (deadline - now) / 86400.0
        when = f"OVERDUE {-delta:.1f}d" if delta < 0 else f"due in {delta:.1f}d"
        title = _strip_terminal_control(g.title)[:70]
        dept = f" [{_strip_terminal_control(g.domain)}]" if g.domain else ""
        blocked = f"  ({nq} question(s) awaiting you)" if nq else ""
        click.echo(f"#{g.id:<5} {when:<16} {title}{dept}{blocked}")


@main.group("tax")
def tax_group() -> None:
    """Tax preparation pipeline: uploaded documents -> first-pass draft return."""


@tax_group.command("prepare")
@click.argument("docs_dir", type=click.Path(exists=True, file_okay=False))
@click.option("--filing-status", type=click.Choice(["single", "mfj", "hoh"]),
              default="single", show_default=True,
              help="Filing status for the first-pass computation.")
@click.option("--dependents", default=0, show_default=True,
              help="Qualifying children under 17 (child tax credit).")
@click.option("--state", "state_code", default=None, metavar="XX",
              help="Resident state for the state return (default: inferred "
                   "from W-2 box 15).")
@click.option("--estimated-payments", default=0.0, show_default=True,
              help="Federal estimated tax already paid (Form 1040-ES).")
@click.option("--prior-year-overpayment", default=0.0, show_default=True,
              help="Prior-year overpayment applied to this year.")
@click.option("--taxpayer-65", is_flag=True,
              help="Taxpayer is 65 or older (additional standard deduction).")
@click.option("--spouse-65", is_flag=True,
              help="Spouse is 65 or older (MFJ; additional standard deduction).")
@click.option("--taxpayer-blind", is_flag=True,
              help="Taxpayer is blind (additional standard deduction).")
@click.option("--spouse-blind", is_flag=True,
              help="Spouse is blind (MFJ; additional standard deduction).")
@click.option("--format", "fmt", type=click.Choice(["text", "json"]),
              default="text", show_default=True,
              help="Output format: human review package or structured JSON "
                   "for programmatic intake.")
@click.option("--out", "out_path", type=click.Path(), default=None,
              help="Also write the review package to this file.")
def tax_prepare(docs_dir: str, filing_status: str, dependents: int,
                state_code: str | None, estimated_payments: float,
                prior_year_overpayment: float,
                taxpayer_65: bool, spouse_65: bool, taxpayer_blind: bool,
                spouse_blind: bool, fmt: str, out_path: str | None) -> None:
    """Turn a folder of uploaded documents into a first-pass draft return.

    Reads every ``*.txt`` document in DOCS_DIR (text exports of the client's
    W-2s, 1099s, etc. -- extraction agents handle PDFs upstream), classifies
    and extracts each one deterministically, assembles the workpaper, runs
    the TY2025 federal first pass AND the resident-state first pass (no-tax
    and flat-rate states computed; graduated states handed to the preparer /
    tax engine), and prints the preparer review package: every line cited to
    its source document, every out-of-scope item flagged as an OPEN ITEM.
    A credentialed preparer reviews, completes, and signs -- this never
    files anything.
    """
    from . import tax_constants, tax_prep
    try:
        from .config import get_tax
        if get_tax()["auto_update"]:
            status, detail = tax_constants.check_for_update()
            if status == "applied":
                click.echo(f"[tax] {detail}")
    except Exception:  # the update channel must never block a prep run
        pass
    federal, state_tables, provenance = tax_constants.active_constants()
    docs = []
    for p in sorted(Path(docs_dir).glob("*.txt")):
        text = p.read_text(encoding="utf-8", errors="replace")
        docs.append(tax_prep.extract(text, label=p.name))
    wp = tax_prep.Workpaper(filing_status=filing_status,
                            dependents_under_17=dependents, docs=docs,
                            state=(state_code or ""),
                            estimated_payments=estimated_payments,
                            prior_year_overpayment=prior_year_overpayment,
                            taxpayer_65_or_older=taxpayer_65,
                            spouse_65_or_older=spouse_65,
                            taxpayer_blind=taxpayer_blind,
                            spouse_blind=spouse_blind)
    draft = tax_prep.compute_first_pass(wp, constants=federal)
    state = (tax_prep.compute_state_first_pass(
                 wp, tax_prep.infer_state(wp), federal=draft,
                 constants=state_tables)
             if docs else None)
    if fmt == "json":
        import json
        data = tax_prep.review_package_dict(draft, state)
        data["constants"] = f"TY{federal['year']} {provenance}"
        package = json.dumps(data, indent=2)
    else:
        package = tax_prep.render_review_package(draft, state)
        package += f"\n\nConstants: TY{federal['year']} {provenance}"
    click.echo(package)
    if out_path:
        Path(out_path).write_text(package + "\n", encoding="utf-8")
        click.echo(f"\nWrote review package -> {out_path}")


@tax_group.command("backtest")
@click.argument("cases_dir", type=click.Path(exists=True, file_okay=False))
@click.option("--tolerance", default=None, type=float,
              help="Dollar tolerance for an in-scope line match "
                   "(default $1.00).")
@click.option("--format", "fmt", type=click.Choice(["text", "json"]),
              default="text", show_default=True,
              help="Output format: human report or structured JSON.")
@click.option("--out", "out_path", type=click.Path(), default=None,
              help="Also write the back-test report to this file.")
def tax_backtest(cases_dir: str, tolerance: float | None, fmt: str,
                 out_path: str | None) -> None:
    """Measure first-pass accuracy against a firm's PRIOR FILED returns.

    Point this at a folder of case subdirectories -- each holding a client's
    source ``*.txt`` documents plus a ``filed.json`` with the figures the firm
    actually filed -- and it runs the deterministic pipeline on every case and
    reports how close the draft lands. Returns carrying items the engine
    deliberately doesn't compute (Schedule C/D/E, itemized, graduated-state,
    unsupported status) are listed OUT OF SCOPE and excluded from the accuracy
    number, so "matched N of M in-scope within $T" is an honest signal a firm
    can act on in an afternoon -- on its own data, not synthetic samples.
    """
    from . import tax_backtest as bt
    tol = bt.DEFAULT_TOLERANCE if tolerance is None else tolerance
    report = bt.run_backtest_dir(cases_dir, tolerance=tol)
    if fmt == "json":
        import json
        text = json.dumps(bt.backtest_dict(report), indent=2)
    else:
        text = bt.render_backtest(report)
    click.echo(text)
    if out_path:
        Path(out_path).write_text(text + "\n", encoding="utf-8")
        click.echo(f"\nWrote back-test report -> {out_path}")


@tax_group.command("onboard")
@click.argument("profile", type=click.Path(exists=True, dir_okay=False))
def tax_onboard(profile: str) -> None:
    """Scope a firm's pilot from its intake profile (a TOML file).

    Sorts every state the firm serves into computed-first-pass (no-tax / flat)
    vs handed-off (graduated -- their tax engine owns it), resolves the firm's
    document-label taxonomy to the canonical types, and prints a ready-to-pilot
    verdict with blockers (must fix) separated from warnings. Run this first to
    set expectations, then `maverick tax backtest` to prove accuracy on the
    firm's own prior filed returns -- together they make "intake in days"
    concrete. Exits non-zero when there are blockers.
    """
    from . import tax_onboarding as ob
    rep = ob.assess_readiness(ob.load_profile(profile))
    click.echo(ob.render_readiness(rep))
    if not rep.ready_to_pilot:
        raise click.ClickException("onboarding blockers must be resolved "
                                   "before intake (see above)")


@tax_group.command("update")
@click.option("--file", "bundle_file", type=click.Path(exists=True),
              default=None, help="Apply a signed constants bundle from a "
              "file (air-gapped transport).")
@click.option("--url", default=None,
              help="Check this URL instead of [tax] update_url.")
@click.option("--status", "show_status", is_flag=True,
              help="Show the applied constants version and exit.")
@click.option("--rollback", "do_rollback", is_flag=True,
              help="Restore the previously applied constants bundle.")
def tax_update(bundle_file: str | None, url: str | None,
               show_status: bool, do_rollback: bool) -> None:
    """Update the tax computation constants from a SIGNED publisher bundle.

    New tax law ships as a content release, not a code release: the bundle
    is Ed25519-verified against [tax] trusted_constants_pubkeys
    (fail-closed), sanity-validated (rates, brackets, state codes), and
    downgrade-protected before it can replace the tables. With [tax]
    auto_update + update_url configured, `maverick tax prepare` runs this
    check automatically (throttled), so a published law change reaches
    every prep run without an upgrade. The previous bundle is kept for
    --rollback; every apply writes an audit row.
    """
    from . import tax_constants
    if show_status:
        federal, _, provenance = tax_constants.active_constants()
        click.echo(f"TY{federal['year']} constants: {provenance}")
        return
    if do_rollback:
        ok, reason = tax_constants.rollback()
        if not ok:
            raise click.ClickException(reason)
        click.echo(reason)
        return
    if bundle_file:
        ok, reason = tax_constants.apply_bundle_file(bundle_file)
        if not ok:
            raise click.ClickException(reason)
        click.echo(reason)
        return
    status, detail = tax_constants.check_for_update(url=url, force=True)
    if status == "error":
        raise click.ClickException(detail)
    click.echo(f"{status}: {detail}")


@main.command("proof")
@click.option("--days", default=90, show_default=True,
              help="Window to report over.")
@click.option("--human-cost", default=None, type=float,
              help="Your fully-loaded cost of one comparable human "
                   "deliverable (defaults conservative).")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON.")
@click.option("--fleet", is_flag=True,
              help="Also break down ingested fleet experience per vendor.")
@click.pass_context
def proof(ctx, days: int, human_cost, as_json: bool, fleet: bool) -> None:
    """The workforce value report: did the AI workforce pay for itself AND
    get better?

    Assembles throughput (deliverables), economics (agent cost vs your
    human-baseline -> cost avoided + ROI), the capability improvement curve
    (from `maverick hindsight --ledger` runs), and governance (signed audit
    chain) into one read-only report -- per department. The artifact a POC
    ends on and a diligence team runs. Measures only; changes nothing.
    """
    from . import workforce_value
    world = open_world(ctx.obj["db"])
    v = workforce_value.compute(world, window_days=days, human_cost=human_cost)
    if as_json:
        import json as _json
        click.echo(_json.dumps(workforce_value.to_dict(v), indent=2))
    else:
        click.echo(workforce_value.format_report(v))
    if fleet:
        by_vendor = workforce_value.fleet_breakdown()
        if not by_vendor:
            click.echo("\n(fleet: no ingested external experience yet)")
        else:
            click.echo("\nBy vendor (fleet-ingested):")
            for vendor, c in sorted(by_vendor.items()):
                click.echo(f"  {vendor:<20} {c['deliverables']} deliverable(s), "
                           f"{c['failures']} failure(s)")


@main.command("fleet-memory")
@click.option("--register", default=None, metavar="VENDOR:AGENT_ID",
              help="Register an external agent on the fleet roster.")
@click.option("--description", default="", help="Roster description.")
def fleet_memory_cmd(register: str | None, description: str) -> None:
    """The agent-agnostic learning plane (Learning System of Record).

    External agents (Agentforce, Copilot, custom, OSS runtimes) deposit
    experience into and recall from Maverick's governed memory via the MCP /
    REST surface; this command manages the roster and shows the console
    view. Requires [fleet_memory] enable = true.
    """
    from . import fleet_memory
    if register:
        vendor, _, agent_id = register.partition(":")
        if not agent_id:
            raise click.ClickException("--register takes VENDOR:AGENT_ID")
        if not fleet_memory.register_agent(agent_id, vendor,
                                           description=description):
            raise click.ClickException(
                "registration failed (ids must be alphanumeric/._- , <=64 chars)")
        click.echo(f"registered {vendor}:{agent_id}")
        return
    st = fleet_memory.status()
    if not st["agents"]:
        click.echo("fleet roster is empty -- add agents with "
                   "`maverick fleet-memory --register vendor:agent-id`")
        return
    for a in st["agents"]:
        src = a["source"]
        counts = st["ingested"].get(src, {})
        click.echo(f"{src:<40} ingested: {counts.get('success', 0)} success / "
                   f"{counts.get('failure', 0)} failure")


@main.group("record")
def record_grp() -> None:
    """The Operating Record: the firm's decisions as a system of record."""


@record_grp.command("stats")
@click.option("--limit", default=500, show_default=True)
@click.pass_context
def record_stats(ctx, limit: int) -> None:
    """Summarize the Operating Record (decisions, approvals, departments)."""
    from . import operating_record as orec
    world = open_world(ctx.obj["db"])
    s = orec.stats(orec.assemble(world, limit=limit))
    click.echo(f"records: {s.n_records}  goals: {s.n_goals}  approvals: "
               f"{s.n_approvals}  human decisions: {s.n_human_decisions}")
    for dept, n in sorted(s.departments.items(), key=lambda kv: -kv[1])[:12]:
        click.echo(f"  {dept:<24} {n}")


@record_grp.command("search")
@click.argument("text")
@click.option("--department", default="")
@click.option("--actor", default="")
@click.pass_context
def record_search(ctx, text: str, department: str, actor: str) -> None:
    """Every decision that touched X (subject substring match)."""
    from . import operating_record as orec
    world = open_world(ctx.obj["db"])
    hits = orec.query(orec.assemble(world), text=text,
                      department=department, actor=actor)
    for r in hits[:50]:
        click.echo(f"[{r.kind}] {r.subject}  -> {r.outcome}  "
                   f"(actor={r.actor}, ${r.cost_dollars:.2f})")
    click.echo(f"{len(hits)} matching record(s)")


@record_grp.command("export")
@click.argument("out", type=click.Path())
@click.option("--limit", default=500, show_default=True)
@click.pass_context
def record_export(ctx, out: str, limit: int) -> None:
    """Export the operating mind as a SIGNED, portable capsule."""
    from . import operating_record as orec
    world = open_world(ctx.obj["db"])
    try:
        path = orec.export_capsule(world, out, limit=limit)
    except RuntimeError as e:
        raise click.ClickException(str(e)) from e
    ok, reason = orec.verify_capsule(path)
    click.echo(f"capsule -> {path} (self-check: {reason})")
    if not ok:
        raise click.ClickException("capsule failed its own verification")


@record_grp.command("verify")
@click.argument("capsule", type=click.Path(exists=True))
def record_verify(capsule: str) -> None:
    """Verify a capsule's signature + integrity offline."""
    from . import operating_record as orec
    ok, reason = orec.verify_capsule(capsule)
    click.echo(reason)
    if not ok:
        raise click.ClickException("verification failed")


@main.command("hindsight")
@click.option("--before", default="latest",
              help="Older learned-state snapshot to compare against "
                   "('latest' = most recent dream snapshot, or a snapshot "
                   "name from `maverick dream --list-snapshots`).")
@click.option("--limit", default=100, show_default=True,
              help="How many recent goals to replay.")
@click.option("--all-goals", is_flag=True,
              help="Replay all recent goals, not just failed ones.")
@click.option("--ledger", is_flag=True,
              help="Append the result to the signed hindsight ledger.")
@click.option("--strict", is_flag=True,
              help="Exit non-zero if any coverage regression is found "
                   "(a learning-regression CI gate).")
@click.pass_context
def hindsight(ctx, before: str, limit: int, all_goals: bool, ledger: bool,
              strict: bool) -> None:
    """Did today's learned state get better or WORSE on past work?

    Replays recent goals against a prior learned-state snapshot and today's
    state, comparing whether each goal is still covered by a recalled lesson
    (reflexion / dream insight / learned skill). Surfaces *regressions* --
    goals a retired skill, expired insight, or pruned reflexion no longer
    covers. Deterministic and read-only (no agent re-runs, no tokens);
    snapshots come from `maverick dream`.
    """
    from . import dreaming
    from . import hindsight as _h
    snaps = dreaming.list_snapshots()
    if not snaps:
        raise click.ClickException(
            "no learned-state snapshots yet -- run `maverick dream` "
            "(it snapshots before each cycle) at least twice first."
        )
    chosen = snaps[-1] if before == "latest" else before
    if chosen not in snaps:
        raise click.ClickException(
            f"no such snapshot {chosen!r}. Available: {', '.join(snaps)}"
        )
    snap_dir = dreaming.snapshots_dir() / chosen
    world = open_world(ctx.obj["db"])
    report = _h.replay(
        world, before=snap_dir, after=None, limit=limit,
        status=None if all_goals else "blocked",
    )
    click.echo(report.summary())
    if ledger:
        _h.write_ledger(report, before_label=chosen)
        click.echo("[recorded to the signed hindsight ledger]")
    if strict and report.regressed:
        raise click.ClickException(
            f"{len(report.regressed)} learning regression(s) detected"
        )


@main.command("domains-lint")
@click.option("--ci", is_flag=True,
              help="Exit non-zero when any pack has an ERROR-level finding.")
@click.option("--warnings", "show_warnings", is_flag=True,
              help="Also print warning-level findings (quality gaps).")
def domains_lint(ci: bool, show_warnings: bool) -> None:
    """Lint every domain pack (built-in + operator) for envelope and
    quality gaps.

    Errors weaken the safety envelope (empty tool allowlist = ALL tools,
    missing/unknown max_risk); warnings are pack-quality gaps (thin persona,
    no knowledge sources, no deny list). Operator packs in the workspace
    domains dir are linted alongside the built-ins.
    """
    from .domain import available_domains, lint_profile
    domains = available_domains()
    n_err = n_warn = 0
    for name in sorted(domains):
        errors, warnings = lint_profile(domains[name])
        n_err += len(errors)
        n_warn += len(warnings)
        for e in errors:
            click.echo(f"ERROR  {name}: {e}", err=True)
        if show_warnings:
            for w in warnings:
                click.echo(f"warn   {name}: {w}")
    click.echo(f"{len(domains)} pack(s): {n_err} error(s), {n_warn} warning(s)"
               + ("" if show_warnings else " (use --warnings to list them)"))
    if ci and n_err:
        raise click.ClickException(f"{n_err} pack error(s)")


@main.command("insights-export")
@click.argument("out", type=click.Path())
@click.option("--max", "max_insights", default=50, show_default=True,
              help="How many of the most recent insights to bundle.")
def insights_export(out: str, max_insights: int) -> None:
    """Export local dream insights as a SIGNED bundle for a trusted peer.

    Federated insight exchange: only consolidated lessons cross the boundary
    (never raw trajectories or user content). The bundle is signed with this
    instance's Ed25519 audit key; give the peer your public key (printed
    here) to add to their [dreaming] trusted_insight_pubkeys. Transport is
    yours: move the file however your security policy allows.
    """
    from .insight_exchange import export_insights
    try:
        path = export_insights(out, max_insights=max_insights)
    except RuntimeError as e:
        raise click.ClickException(str(e)) from e
    import json as _json
    bundle = _json.loads(Path(path).read_text(encoding="utf-8"))
    click.echo(f"Wrote {len(bundle['insights'])} insight(s) -> {path}")
    click.echo(f"Your public key (for the peer's trusted_insight_pubkeys):\n"
               f"  {bundle['peer_key']}")


@main.command("insights-import")
@click.argument("bundle", type=click.Path(exists=True))
def insights_import(bundle: str) -> None:
    """Import a peer's signed insight bundle (fail-closed verification).

    Requires the peer's public key in [dreaming] trusted_insight_pubkeys;
    unsigned, untrusted, or tampered bundles are rejected outright. Each
    imported lesson is redacted, Shield-scanned, provenance-tagged, and
    merged through the same dedup gate local dreaming uses.
    """
    from .insight_exchange import import_insights
    from .orchestrator import _build_shield
    imported, reason = import_insights(bundle, shield=_build_shield())
    if reason != "ok":
        raise click.ClickException(reason)
    click.echo(f"Imported {imported} peer insight(s).")


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
            raise click.ClickException(f"could not write {output}: {e}") from e
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


def _require_day_opt(day: str | None) -> None:
    """Reject a ``--day`` that isn't a literal YYYY-MM-DD before it becomes a path.

    ``day`` is resolved to ``<audit_dir>/<day>.ndjson``; a value like
    ``../../etc/passwd`` would otherwise escape the audit dir. The writer/export
    layer refuses it too (a backstop for non-CLI callers); this just turns it
    into a friendly CLI error + exit 2, matching ``--since``/``--until``.
    """
    from .audit.events import is_valid_day
    if day is not None and not is_valid_day(day):
        click.echo("error: --day must be YYYY-MM-DD", err=True)
        sys.exit(2)


@audit.command("tail")
@click.option("-n", "--num", default=50, type=int, help="Lines to tail.")
@click.option("--day", default=None, help="YYYY-MM-DD (default: today).")
def audit_tail(num: int, day: str | None) -> None:
    """Print the last N audit events."""
    import json as _json

    _require_day_opt(day)
    from .audit import default_audit_log
    for ev in default_audit_log().tail(num, day=day):
        click.echo(_json.dumps(ev, default=str))


@audit.command("grep")
@click.argument("pattern")
@click.option("--day", default=None, help="YYYY-MM-DD (default: today).")
def audit_grep(pattern: str, day: str | None) -> None:
    """Regex grep over today's audit log."""
    import json as _json

    _require_day_opt(day)
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

    _require_day_opt(day)
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
        anchor_dir = audit_dir
        day_file = audit_dir / f"{d}.ndjson"
        from .audit.signing import _have_crypto
        audit_dir_empty = not audit_dir.exists() or not any(audit_dir.iterdir())
        if not day_file.exists() and _have_crypto() and audit_dir_empty:
            # A completely absent/empty audit directory means no audit events
            # have ever been recorded for this tenant, so the requested day is
            # cleanly empty. If the directory contains any audit artifacts
            # (keys, anchors, other day-files, etc.), keep verifying the
            # requested path so verify_chain() can report a missing_file break
            # instead of allowing deletion of an unanchored day-file to pass.
            click.echo(f"no audit entries for {d} (nothing recorded that day).")
            paths = []
        else:
            paths = [day_file]

    if not pubkey:
        click.echo(
            "warning: no --pubkey given; trusting a locally-held key. For "
            "third-party tamper-evidence, pass the externally-held pubkey.",
            err=True,
        )

    any_break = False
    for path in paths:
        breaks = verify_chain(path, pubkey_hex=pubkey)
        if breaks and all(b.reason == "unsigned" for b in breaks):
            # Default deployment: signing was never on. One actionable line
            # instead of per-row tamper vocabulary -- but still exit 1, so
            # automation cannot pass unverifiable evidence as clean.
            any_break = True
            click.echo(
                f"UNVERIFIABLE: {path} — {len(breaks)} unsigned row(s); audit "
                "signing is off. Set [audit] sign = true in "
                "~/.maverick/config.toml (or MAVERICK_AUDIT_SIGN=1) so future "
                "rows are hash-chained and tamper-evident.",
                err=True,
            )
        elif breaks:
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


@audit.command("seal")
@click.option("--dry-run", is_flag=True,
              help="Show which segments would be sealed; write nothing.")
def audit_seal(dry_run: bool) -> None:
    """Encrypt closed audit day-files at rest (confidentiality for the log).

    Seals every day-file dated before today in place with AES-256-GCM. The current
    day-file (live append) and the anchor ledger stay plaintext, and the readers +
    'audit verify' transparently decrypt sealed segments. Requires at-rest
    encryption to be enabled ([encryption] at_rest / MAVERICK_ENCRYPT_AT_REST).
    """
    from .audit.sealing import seal_closed_segments
    from .crypto_at_rest import EncryptionUnavailable
    try:
        report = seal_closed_segments(dry_run=dry_run)
    except EncryptionUnavailable as e:
        raise click.ClickException(str(e)) from e
    for name, status in sorted(report.items()):
        click.echo(f"  {name}: {status}")
    done = sum(1 for s in report.values() if s in ("sealed", "would seal"))
    click.echo(f"{'Would seal' if dry_run else 'Sealed'} {done} segment(s).")


@audit.command("export")
@click.option("--format", "fmt", type=click.Choice(["json", "cef"]), default="json",
              help="Output format for SIEM ingestion (default: json).")
@click.option("--day", default=None, help="YYYY-MM-DD (default: today).")
@click.option("--all", "all_days", is_flag=True,
              help="Export every YYYY-MM-DD.ndjson day-file in the audit dir.")
@click.option("--since", default=None,
              help="Start of an inclusive YYYY-MM-DD window (e.g. an incident).")
@click.option("--until", default=None,
              help="End of the inclusive YYYY-MM-DD window.")
@click.option("--tenant", default=None,
              help="Tenant whose audit dir to export (default: active/none).")
@click.option("-o", "--output", "output", default=None, type=click.Path(),
              help="Write to FILE (mode 0600; may contain PII). Default: stdout.")
def audit_export(
    fmt: str, day: str | None, all_days: bool, since: str | None,
    until: str | None, tenant: str | None, output: str | None,
) -> None:
    """Export the audit log as JSONL or ArcSight CEF for a SIEM.

    Read-only re-emission of the tamper-evident NDJSON log; it never mutates
    the log or the signing chain. By default it exports today's day-file;
    ``--since``/``--until`` export an inclusive date window (for incident
    backfill) and ``--all`` sweeps every day-file. An empty/missing log exits 0
    (a note goes to stderr) so cron/automation never fails on a quiet day.
    """
    import datetime as _dt
    import os as _os
    from pathlib import Path as _Path

    _require_day_opt(day)
    for _label, _val in (("--since", since), ("--until", until)):
        if _val is not None:
            try:
                _parsed = _dt.datetime.strptime(_val, "%Y-%m-%d")
            except ValueError:
                click.echo(f"ERROR: {_label} must be YYYY-MM-DD", err=True)
                sys.exit(2)
            if _parsed.strftime("%Y-%m-%d") != _val:
                click.echo(f"ERROR: {_label} must be YYYY-MM-DD", err=True)
                sys.exit(2)

    from .audit.export import audit_event_paths, iter_audit_events, to_cef, to_jsonl

    render = to_cef if fmt == "cef" else to_jsonl
    lines = (render(ev) for ev in iter_audit_events(
        day=day, all_days=all_days, since=since, until=until, tenant=tenant,
    ))

    if output:
        output_path = _Path(output)
        output_resolved = output_path.resolve(strict=False)
        source_paths = audit_event_paths(
            day=day, all_days=all_days, since=since, until=until, tenant=tenant,
        )
        for source_path in source_paths:
            if (output_resolved == source_path.resolve(strict=False)
                    or (output_path.exists() and source_path.exists()
                        and _os.path.samefile(output_path, source_path))):
                raise click.ClickException(
                    "refusing to write audit export over a source audit log file"
                )

        # 0600 from creation: the export may contain PII, mirroring the
        # writer's own day-file permissions.
        fd = _os.open(output, _os.O_WRONLY | _os.O_CREAT | _os.O_TRUNC, 0o600)
        n = 0
        with _os.fdopen(fd, "w", encoding="utf-8") as f:
            for line in lines:
                f.write(line + "\n")
                n += 1
        if n == 0:
            click.echo("no audit events to export", err=True)
        else:
            click.echo(f"exported {n} event(s) to {output}", err=True)
        return

    n = 0
    for line in lines:
        click.echo(line)
        n += 1
    if n == 0:
        click.echo("no audit events to export", err=True)


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
            raise click.ClickException("--month must be YYYY-MM (e.g. 2026-05)") from None
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
        raise click.ClickException(f"could not write {out_path}: {e}") from e
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

    _require_day_opt(day)
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
    "encryption_at_rest",
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


# ----- Enterprise (regulated-deployment) posture -----------------------

@main.group("enterprise")
def enterprise_group() -> None:
    """Enterprise (regulated-deployment) posture."""


@enterprise_group.command("verify")
@click.option("--format", "fmt", type=click.Choice(["text", "json"]), default="text",
              help="Output format.")
def enterprise_verify(fmt: str) -> None:
    """Actively verify the regulated-deployment guarantees (exits non-zero if any fail).

    Unlike 'maverick compliance' (which maps configured controls to articles),
    this *exercises* the load-bearing guarantees: it proves the egress lock
    refuses a cloud provider and that at-rest sealing round-trips on this box,
    upgrading "the flag is on" to "the boundary holds." Wire it into CI / a
    deploy gate the same way as 'maverick compliance --strict'.
    """
    from .deployment import all_passed, render_json, render_text, verify_deployment
    checks = verify_deployment()
    click.echo(render_json(checks) if fmt == "json" else render_text(checks))
    if not all_passed(checks):
        sys.exit(1)


@main.command("ropa")
@click.option("--format", "fmt", type=click.Choice(["text", "json"]), default="text",
              help="Output format.")
@click.option("--output", "-o", type=click.Path(), default=None,
              help="Write to file (default stdout).")
def ropa_cmd(fmt: str, output) -> None:
    """Generate a GDPR Art. 30 record-of-processing scaffold for this deployment.

    Pre-fills the technical half from the live config and schema -- personal-data
    categories, recipients / international transfers (from the egress lock),
    retention, and the active Art. 32 security measures -- and marks the
    organizational fields (controller, DPO, lawful basis, purposes) for the
    controller to complete. A scaffold for a DPO to finish, not a legal
    attestation.
    """
    from .ropa import generate_ropa, render_ropa_json, render_ropa_text
    record = generate_ropa()
    payload = render_ropa_json(record) if fmt == "json" else render_ropa_text(record)
    if output:
        try:
            fd = os.open(str(output), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload + "\n")
        except OSError as e:
            raise click.ClickException(f"could not write {output}: {e}") from e
        click.echo(f"wrote {output}")
    else:
        click.echo(payload)


@main.command("dpia")
@click.option("--format", "fmt", type=click.Choice(["text", "json"]), default="text",
              help="Output format.")
@click.option("--output", "-o", type=click.Path(), default=None,
              help="Write to file (default stdout).")
def dpia_cmd(fmt: str, output) -> None:
    """Generate a GDPR Art. 35 DPIA scaffold for this deployment.

    Pre-fills the processing description (consistent with 'maverick ropa') and a
    risk register of the agent-on-personal-data risks -- each mapped to the
    Maverick control that mitigates it and whether that control is active right
    now -- leaving necessity/proportionality and residual-risk sign-off to the
    controller. A scaffold for a DPO to finish, not a completed DPIA.
    """
    from .dpia import generate_dpia, render_dpia_json, render_dpia_text
    dpia = generate_dpia()
    payload = render_dpia_json(dpia) if fmt == "json" else render_dpia_text(dpia)
    if output:
        try:
            fd = os.open(str(output), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload + "\n")
        except OSError as e:
            raise click.ClickException(f"could not write {output}: {e}") from e
        click.echo(f"wrote {output}")
    else:
        click.echo(payload)


@main.command("ai-act")
@click.option("--format", "fmt", type=click.Choice(["text", "json"]), default="text",
              help="Output format.")
def ai_act_cmd(fmt: str) -> None:
    """Classify this deployment under the EU AI Act (self-assessment).

    Reports the live Art. 50 transparency posture and hands you a checklist of
    the prohibited (Art. 5) and high-risk (Annex III) categories plus the
    obligations each tier triggers. A conversational agent that discloses it is
    AI is limited-risk by default -- but you must rule out those lists for your
    use case. A self-assessment aid, not a legal classification.
    """
    from .ai_act import assess_ai_act, render_ai_act_json, render_ai_act_text
    report = assess_ai_act()
    click.echo(render_ai_act_json(report) if fmt == "json" else render_ai_act_text(report))


@main.command("controls")
@click.argument("query", nargs=-1, required=True)
@click.option("--limit", type=int, default=5, help="Max controls to return.")
def controls_cmd(query: tuple[str, ...], limit: int) -> None:
    """Find the privacy/security control(s) for a risk, with framework citations.

    Example: maverick controls vendor has no DPA
    """
    from .controls import find_controls, render_control
    hits = find_controls(" ".join(query), limit=limit)
    if not hits:
        raise click.ClickException(f"no controls matched {' '.join(query)!r}")
    click.echo("\n".join(render_control(c) for c in hits))


@main.command("hunt")
@click.option("--format", "fmt", type=click.Choice(["text", "json"]), default="text",
              help="Output format.")
@click.option("--since", default=None, help="Only events on/after this UTC date (YYYY-MM-DD).")
@click.option("--until", default=None, help="Only events on/before this UTC date (YYYY-MM-DD).")
@click.option("--strict", is_flag=True,
              help="Exit non-zero if any attack signal is found (gate CI / monitoring).")
def hunt_cmd(fmt: str, since: str | None, until: str | None, strict: bool) -> None:
    """Hunt the audit trail for attacks by/against agents.

    Sweeps the audit log for security signals -- shield blocks (prompt
    injection), blocked egress (exfiltration attempts), capability/governance
    denials (escalation), the kill switch -- and reports them risk-ranked. With
    --strict, exits non-zero when any signal is present, so it can gate a
    monitoring job.
    """
    from .threat_hunt import hunt, render_report_json, render_report_text
    report = hunt(all_days=(since is None and until is None), since=since, until=until)
    click.echo(render_report_json(report) if fmt == "json" else render_report_text(report))
    if strict and report.findings:
        raise click.ClickException(
            f"{len(report.findings)} attack signal type(s) found "
            f"(risk: {report.risk_rating})"
        )


@main.command("remediate")
@click.option("--apply", "do_apply", is_flag=True,
              help="Apply the auto-fixable remediations (needs enterprise mode + "
                   "[security] auto_fix opt-in).")
@click.option("--format", "fmt", type=click.Choice(["text", "json"]), default="text",
              help="Output format.")
def remediate_cmd(do_apply: bool, fmt: str) -> None:
    """Assess security posture and (bounded) auto-fix it.

    Reports control gaps + active breach signals and the remediation plan.
    Low-risk, reversible fixes to Maverick's OWN config are auto-applied with
    --apply -- but only under enterprise mode + a [security] auto_fix opt-in;
    everything behaviour-changing is proposed for a human. Every applied fix is
    audited and reports how to undo it.
    """
    from .remediation import (
        apply_remediation,
        plan,
        render_plan_json,
        render_plan_text,
    )
    p = plan()
    click.echo(render_plan_json(p) if fmt == "json" else render_plan_text(p))
    if not do_apply:
        return
    click.echo("")
    applied_any = False
    for g in p.gaps:
        if not g.auto:
            continue
        res = apply_remediation(g, dry_run=False)
        if res.applied:
            applied_any = True
            click.echo(f"  applied: {g.title}  (undo: {res.undo})")
        else:
            click.echo(f"  skipped: {g.title}  ({res.reason})")
    if not applied_any:
        click.echo("  (nothing auto-applied)")


# ----- Compliance assessments (PIA / AIRA / vendor risk) ---------------

@main.group("assess")
def assess_group() -> None:
    """Conduct compliance assessments of a subject.

    Privacy: PIA, AIRA, vendor risk. Security: HIPAA, SOC 2, PCI DSS.
    Run 'maverick assess templates' for the full set.
    """


@assess_group.command("templates")
def assess_templates() -> None:
    """List the available assessment types."""
    from .assessment import list_templates
    for t in list_templates():
        click.echo(
            f"  {t.type:12} {t.title}  "
            f"({t.framework}; {len(t.questions)} questions)"
        )


@assess_group.command("questions")
@click.argument("assessment_type")
@click.option("--format", "fmt", type=click.Choice(["text", "json"]), default="text",
              help="Output format.")
def assess_questions(assessment_type: str, fmt: str) -> None:
    """Print an assessment's questionnaire (so you -- or the agent -- can answer it)."""
    from .assessment import get_template, render_questions_json, render_questions_text
    tpl = get_template(assessment_type)
    if tpl is None:
        raise click.ClickException(
            f"unknown assessment type {assessment_type!r}; see 'maverick assess templates'"
        )
    click.echo(render_questions_json(tpl) if fmt == "json" else render_questions_text(tpl))


@assess_group.command("score")
@click.argument("assessment_type")
@click.option("--subject", required=True,
              help="What is being assessed (the vendor / system / activity).")
@click.option("--answers", "answers_file", required=True,
              type=click.Path(exists=True),
              help="JSON {question_id: answer}; answer is yes/no/na/unknown "
                   "or {\"answer\":..., \"note\":...}.")
@click.option("--format", "fmt", type=click.Choice(["text", "json"]), default="text",
              help="Output format.")
@click.option("--no-save", is_flag=True, help="Don't persist the assessment.")
def assess_score(assessment_type: str, subject: str, answers_file: str,
                 fmt: str, no_save: bool) -> None:
    """Score a completed answer set into findings + a risk rating, and save it."""
    import json as _json

    from .assessment import (
        AssessmentSession,
        get_template,
        render_result_json,
        render_result_text,
        save_session,
    )
    if get_template(assessment_type) is None:
        raise click.ClickException(
            f"unknown assessment type {assessment_type!r}; see 'maverick assess templates'"
        )
    try:
        raw = _json.loads(Path(answers_file).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise click.ClickException(f"could not read answers: {e}") from e
    if not isinstance(raw, dict):
        raise click.ClickException("answers file must be a JSON object {question_id: answer}")
    session = AssessmentSession(type=assessment_type, subject=subject)
    for qid, val in raw.items():
        answer = val.get("answer") if isinstance(val, dict) else val
        note = val.get("note", "") if isinstance(val, dict) else ""
        try:
            session.record(str(qid), str(answer), str(note))
        except (KeyError, ValueError) as e:
            raise click.ClickException(str(e)) from e
    result = session.evaluate()
    click.echo(render_result_json(result) if fmt == "json" else render_result_text(result))
    if not no_save:
        click.echo(f"\nsaved: {save_session(session)}")


@assess_group.command("list")
def assess_list() -> None:
    """List saved assessments, newest first."""
    from .assessment import list_saved
    rows = list_saved()
    if not rows:
        click.echo("No saved assessments.")
        return
    for r in rows:
        click.echo(
            f"  {r['id']:20} {r['type']:12} {r['risk_rating']:8} "
            f"{r['findings']} finding(s)  {r['subject']}"
        )


@assess_group.command("show")
@click.argument("assessment_id")
@click.option("--format", "fmt", type=click.Choice(["text", "json"]), default="text",
              help="Output format.")
def assess_show(assessment_id: str, fmt: str) -> None:
    """Show a saved assessment by id."""
    import json as _json

    from .assessment import AssessmentResult, Finding, load_saved, render_result_text
    data = load_saved(assessment_id)
    if data is None:
        raise click.ClickException(f"no saved assessment {assessment_id!r}")
    if fmt == "json":
        click.echo(_json.dumps(data, indent=2, default=str))
        return
    res = data["result"]
    result = AssessmentResult(
        type=res["type"], subject=res["subject"], risk_rating=res["risk_rating"],
        findings=[Finding(**f) for f in res["findings"]],
        answered=res["answered"], total=res["total"],
    )
    click.echo(render_result_text(result))


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
            raise click.ClickException(f"could not write {output}: {e}") from e
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
@click.option("--usage-days", type=int, default=None,
              help="Override [retention].usage_days (cost-ledger buckets).")
def retention_enforce_cmd(
    dry_run: bool,
    audit_days: int | None,
    episodes_days: int | None,
    events_days: int | None,
    usage_days: int | None,
) -> None:
    """Apply retention rules to the audit log and world model."""
    import json as _json

    from .audit.retention import enforce
    # CLI overrides take precedence if any are set; otherwise read config.
    cfg: dict | None = None
    if any(v is not None for v in (audit_days, episodes_days, events_days, usage_days)):
        cfg = {}
        if audit_days is not None:
            cfg["audit_days"] = audit_days
        if episodes_days is not None:
            cfg["episodes_days"] = episodes_days
        if events_days is not None:
            cfg["events_days"] = events_days
        if usage_days is not None:
            cfg["usage_days"] = usage_days
    report = enforce(config=cfg, dry_run=dry_run)
    click.echo(_json.dumps(report, default=str, indent=2))


@main.group("encryption")
def encryption_group() -> None:
    """At-rest encryption maintenance (see docs/encryption.md)."""


@encryption_group.command("migrate")
@click.option("--dry-run", is_flag=True,
              help="Report what would be sealed without writing.")
@click.pass_context
def encryption_migrate_cmd(ctx, dry_run: bool) -> None:
    """Seal existing plaintext in the world DB (turns, facts, messages, questions).

    Enabling encryption only seals NEW writes; this seals data written before it
    was on. Idempotent and safe to re-run. Requires at-rest encryption enabled.
    """
    from pathlib import Path

    from .crypto_at_rest import EncryptionUnavailable
    from .encryption_migrate import migrate_world_db
    try:
        report = migrate_world_db(Path(ctx.obj["db"]), dry_run=dry_run)
    except EncryptionUnavailable as e:
        raise click.ClickException(str(e)) from e
    verb = "would seal" if dry_run else "sealed"
    for key in sorted(report):
        click.echo(f"  {key}: {verb} {report[key]}")
    click.echo(
        f"{verb} {sum(report.values())} value(s) total"
        + (" (dry run)" if dry_run else "")
    )


@main.group("local-runtime")
def local_runtime_group() -> None:
    """Plan the local model-server runtime (vLLM / TGI / llama.cpp)."""


@local_runtime_group.command("plan")
def local_runtime_plan() -> None:
    """Print the server command Maverick WOULD run -- nothing is started.

    Composes the argv (and any env toggles) from [local_runtime] in
    ~/.maverick/config.toml plus MAVERICK_LOCAL_RUNTIME_* overrides.
    """
    import shlex

    from .local_runtime import Launcher, LocalRuntimeError
    try:
        launcher = Launcher()
        argv, env = launcher.plan()
    except LocalRuntimeError as e:
        raise click.ClickException(str(e)) from e
    if not launcher.cfg["enabled"]:
        click.echo("# local runtime is DISABLED ([local_runtime] enabled = false); dry plan only")
    for key in sorted(env):
        click.echo(f"{key}={env[key]} \\")
    click.echo(shlex.join(argv))


if __name__ == "__main__":
    main()
