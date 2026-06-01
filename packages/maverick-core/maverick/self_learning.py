"""Self-learning: acquire new capabilities on demand, mid-run.

When the agent hits a capability gap ("I need to send an SMS but have no
tool for it"), this module is the machinery that lets it close the gap
without a human editing config:

  1. SEARCH the federated catalog (skills / mcp / plugins) for an
     existing capability that matches the need.
  2. ACQUIRE safe in-loop capabilities:
       - skills  -> install_from_catalog (hash-pinned, safe).
       - tools   -> GENERATE a Python tool module, validate it, and
                    register it into the live run.
       - apis    -> route through the built-in openapi_runner.
     MCP servers must be added by an operator in config; the agent-facing
     learn_capability tool never persists or hot-starts model-supplied
     subprocess commands.
  3. PERSIST what was learned to ~/.maverick/learned.ndjson and, for
     generated tools, to ~/.maverick/generated_tools/<name>.py so the
     NEXT run already has the capability.

Two entry points exercise this:
  - ``preflight()``       — orchestrator pre-acquisition before a run.
  - the ``learn_capability`` tool (maverick.tools.learn) — in-loop, the
    agent calls it when it realizes it is missing something.

SAFETY / KERNEL RULES
---------------------
The whole feature is OFF by default (kernel rule 1: the kernel runs
without extra persisted state). Turn it on with ``MAVERICK_SELF_LEARNING=1``
or ``[self_learning] enable = true``. Because "create a tool" means
generating and executing fresh in-process code, enabling it is an
explicit, opt-in trust decision. Generated source is scanned through the
Shield (when installed) before it is ever imported, and the generation
LLM call is metered against the run Budget (kernel rule 3).
"""
from __future__ import annotations

import ast
import importlib.util
import json
import logging
import os
import re
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

LEARNED_PATH = Path.home() / ".maverick" / "learned.ndjson"
GENERATED_TOOLS_DIR = Path.home() / ".maverick" / "generated_tools"

# A generated tool module must be addressable as a plain identifier and
# must not shadow a stdlib / kernel module name when imported.
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,40}$")
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")
_lock = threading.Lock()


# --------------------------------------------------------------------------
# config / gating
# --------------------------------------------------------------------------
def enabled() -> bool:
    """Whether the self-learning loop is active. Off by default."""
    env = os.environ.get("MAVERICK_SELF_LEARNING", "").strip().lower()
    if env in {"1", "true", "yes", "on"}:
        return True
    if env in {"0", "false", "no", "off"}:
        return False
    try:
        from .config import get_self_learning
        return bool(get_self_learning()["enable"])
    except Exception:  # pragma: no cover -- config never blocks a run
        return False


def settings() -> dict:
    """Resolved ``[self_learning]`` settings with defaults filled in."""
    try:
        from .config import get_self_learning
        return get_self_learning()
    except Exception:  # pragma: no cover
        return {
            "enable": False, "preflight": True, "create_tools": True,
            "max_acquisitions": 5,
        }


# --------------------------------------------------------------------------
# learned-capability ledger
# --------------------------------------------------------------------------
@dataclass
class Learned:
    ts: float
    need: str
    kind: str          # skill | mcp | tool | api
    name: str
    source: str = ""
    outcome: str = "acquired"   # acquired | failed

    def to_dict(self) -> dict:
        return asdict(self)


def _redact(text: str) -> str:
    try:
        from .safety.secret_detector import redact
        return redact(str(text or ""))[0]
    except Exception:  # pragma: no cover
        return str(text or "")


def record(
    need: str, kind: str, name: str, *,
    source: str = "", outcome: str = "acquired",
    path: Path = LEARNED_PATH,
) -> bool:
    """Append a learned-capability entry. Never raises."""
    entry = Learned(
        ts=time.time(), need=_redact(need)[:300], kind=kind,
        name=name, source=source, outcome=outcome,
    )
    with _lock:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry.to_dict(), default=str) + "\n")
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
            return True
        except OSError as e:
            log.warning("self_learning: ledger write failed: %s", e)
            return False


def history(*, limit: int = 50, path: Path = LEARNED_PATH) -> list[Learned]:
    """Most-recent-first list of learned capabilities."""
    if not path.exists():
        return []
    out: list[Learned] = []
    try:
        with open(path, encoding="utf-8") as f:
            for raw in f:
                try:
                    d = json.loads(raw)
                    out.append(Learned(**{
                        k: d.get(k) for k in (
                            "ts", "need", "kind", "name", "source", "outcome",
                        )
                    }))
                except (json.JSONDecodeError, TypeError):
                    continue
    except OSError:
        return []
    out.sort(key=lambda e: e.ts or 0.0, reverse=True)
    return out[: max(1, limit)]


# --------------------------------------------------------------------------
# catalog search
# --------------------------------------------------------------------------
def _tokens(s: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(s or "")}


@dataclass
class Candidate:
    kind: str          # singular: skill | mcp | plugin | persona
    name: str
    summary: str
    source: str
    score: float


_KIND_SINGULAR = {
    "skills": "skill", "mcp": "mcp", "plugins": "plugin", "personas": "persona",
}


_EMBED_MIN_SCORE = 0.25  # cosine floor so semantic search doesn't return noise


def _entry_text(e: Any) -> str:
    return f"{e.name} {e.summary}"


def _gather_entries(kinds: tuple[str, ...], indexes: list[str] | None):
    """Collect ``(kind_singular, CatalogEntry)`` across ``kinds``.

    Per-kind load failures are logged and skipped so an unreachable catalog
    degrades to "fewer candidates" rather than breaking a gap-search.
    """
    from . import catalog as _catalog

    out: list[tuple[str, Any]] = []
    for kind in kinds:
        if kind not in _catalog.VALID_KINDS:
            continue
        try:
            entries = _catalog.load_catalog(kind, indexes=indexes)
        except Exception as e:  # pragma: no cover -- catalog never blocks
            log.debug("self_learning: catalog %s load failed: %s", kind, e)
            continue
        for entry in entries:
            out.append((_KIND_SINGULAR.get(kind, kind), entry))
    return out


def _rank_lexical(need: str, entries: list, max_n: int) -> list[Candidate]:
    want = _tokens(need)
    scored: list[Candidate] = []
    for kind, e in entries:
        hay = _tokens(_entry_text(e))
        if not hay:
            continue
        overlap = len(want & hay)
        if overlap == 0:
            continue
        scored.append(Candidate(
            kind=kind, name=e.name, summary=e.summary, source=e.source,
            score=overlap / len(want | hay),
        ))
    scored.sort(key=lambda c: -c.score)
    return scored[: max(1, max_n)]


def _rank_embed(need: str, entries: list, max_n: int) -> list[Candidate] | None:
    """Cosine-rank ``entries`` against ``need`` using fastembed.

    Returns None (signal "fall back to lexical") when fastembed isn't
    installed or the embed call fails; otherwise a ranked list (possibly
    empty if nothing clears ``_EMBED_MIN_SCORE``).
    """
    try:
        from .skill_embeddings import _cosine, _have_fastembed, embed
    except Exception:  # pragma: no cover -- module is in-tree
        return None
    if not _have_fastembed() or not entries:
        return None
    vecs = embed([need] + [_entry_text(e) for _, e in entries])
    if not vecs or len(vecs) != len(entries) + 1:
        return None
    qv = vecs[0]
    scored: list[Candidate] = []
    for (kind, e), v in zip(entries, vecs[1:]):
        score = _cosine(qv, v)
        if score < _EMBED_MIN_SCORE:
            continue
        scored.append(Candidate(
            kind=kind, name=e.name, summary=e.summary, source=e.source,
            score=score,
        ))
    scored.sort(key=lambda c: -c.score)
    return scored[: max(1, max_n)]


def search_capabilities(
    need: str, *, kinds: tuple[str, ...] = ("skills", "mcp", "plugins"),
    max_n: int = 5, indexes: list[str] | None = None,
) -> list[Candidate]:
    """Rank catalog entries across ``kinds`` by relevance to ``need``.

    Uses embedding-based (semantic) ranking when ``fastembed`` is installed
    — so a need can match a skill that shares no surface tokens — and falls
    back to lexical token-overlap otherwise. Degrades to an empty list when
    the catalog is unreachable, so a gap-search never breaks a run.
    """
    entries = _gather_entries(kinds, indexes)
    if not entries:
        return []
    ranked = _rank_embed(need, entries, max_n)
    if ranked is None:
        ranked = _rank_lexical(need, entries, max_n)
    return ranked


# --------------------------------------------------------------------------
# acquire: skills
# --------------------------------------------------------------------------
def acquire_skill(name: str, *, need: str = "") -> str:
    """Install a catalog skill by name (hash-verified) and return its body.

    Returns the SKILL.md body so the caller can inject the steps into the
    live context immediately. Raises ValueError on failure (propagated to
    the agent as a tool-result string).
    """
    from .skills import install_from_catalog

    skill = install_from_catalog(name)
    record(need or name, "skill", skill.name, source=str(skill.path))
    return skill.body


# --------------------------------------------------------------------------
# acquire: MCP servers
# --------------------------------------------------------------------------
def _toml_value(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    if isinstance(v, dict):
        inner = ", ".join(f"{k} = {_toml_value(val)}" for k, val in v.items())
        return "{ " + inner + " }"
    return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'


def add_mcp_server(
    name: str, command: str, *,
    args: list[str] | None = None, env: dict[str, str] | None = None,
    need: str = "",
) -> Any:
    """Validate + persist an ``[mcp_servers.<name>]`` block to config.toml.

    Returns the validated ``MCPServerSpec``. The block is only written
    AFTER validation succeeds (the same supply-chain / shell-meta input
    checks the static config loader enforces), so a malformed spec never
    lands on disk. Hot-starting the client is the caller's job (it needs
    the running event loop).
    """
    from .config import config_path
    from .mcp_client import MCPServerSpec

    if not _NAME_RE.match(name):
        raise ValueError(
            f"mcp server name {name!r} must be lowercase id (a-z0-9_), "
            "3-42 chars, starting with a letter"
        )
    spec = MCPServerSpec(
        name=name, command=command, args=list(args or []),
        env={k: str(v) for k, v in (env or {}).items()},
    )  # __post_init__ runs the CVE-2026-30615 input validation.

    path = config_path()
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    header = f"[mcp_servers.{name}]"
    if header in existing:
        raise ValueError(f"mcp server {name!r} already configured")

    block = [header, f"command = {_toml_value(command)}"]
    if spec.args:
        block.append(f"args = {_toml_value(spec.args)}")
    if spec.env:
        block.append(f"env = {_toml_value(spec.env)}")
    body = ("" if existing.endswith("\n") or not existing else "\n") + \
        "\n" + "\n".join(block) + "\n"

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(body)
    record(need or name, "mcp", name, source=command)
    return spec


# --------------------------------------------------------------------------
# acquire: generated tools
# --------------------------------------------------------------------------
TOOL_AUTHOR_SYSTEM = """You author a single self-contained Maverick tool module in Python.

Output ONLY the module source (no markdown fences, no prose). The module MUST define:

    def make_tool():
        from maverick.tools import Tool
        return Tool(
            name="<snake_case_name>",
            description="<what it does, when to use it>",
            input_schema={"type": "object", "properties": {...}, "required": [...]},
            fn=<callable taking a dict, returning a str>,
        )

Hard rules:
- Standard library only. For HTTP use urllib.request. No third-party imports.
- fn(args: dict) -> str. Catch your own errors and return an "ERROR: ..." string; never raise out of fn.
- NEVER read environment variables, credentials, ~/.maverick, or files outside the working directory.
- NEVER run shell commands, spawn processes, delete files, or perform destructive actions.
- Be small and correct. The whole module should read like the example above."""


# Static audit of generated tool source (#424). The TOOL_AUTHOR_SYSTEM prompt
# *asks* for stdlib-only, no subprocess/file/env access — this ENFORCES it
# before the module is ever imported, so a generated (LLM-authored) module
# that strays from the contract is rejected instead of executed. This is a
# guardrail, not a true sandbox: it bounds the obvious escape surface
# (dangerous imports, eval/exec, the dunder introspection chain) but a
# determined adversary with getattr tricks could still get around an AST
# allowlist. Sandboxed validation/execution is the heavier follow-up (issue
# #424, options B/C). The feature is opt-in/full-autonomy, so this layer plus
# the Shield text scan is a deliberate, documented trade-off.
_SAFE_IMPORT_TOP = frozenset({
    "__future__", "json", "re", "math", "datetime", "urllib", "base64",
    "hashlib", "hmac", "time", "random", "string", "collections", "itertools",
    "functools", "typing", "decimal", "html", "textwrap", "statistics",
    "uuid", "csv", "io", "dataclasses", "enum", "zoneinfo",
})
_BANNED_CALLS = frozenset({
    "eval", "exec", "compile", "__import__", "open", "input", "breakpoint",
})
_BANNED_ATTRS = frozenset({
    "__globals__", "__subclasses__", "__bases__", "__mro__", "__builtins__",
    "__code__", "__closure__", "__dict__", "__class__", "__base__",
    "__getattribute__", "__reduce__", "__reduce_ex__",
})


def _module_allowed(mod: str) -> bool:
    # The tool factory legitimately does ``from maverick.tools import Tool``;
    # allow exactly that, nothing else under the kernel namespace.
    if mod == "maverick.tools":
        return True
    return mod.split(".")[0] in _SAFE_IMPORT_TOP


def audit_generated_source(source: str) -> None:
    """Reject generated tool source that breaks the stdlib-only contract.

    Raises ValueError on a disallowed import, a banned builtin call
    (eval/exec/open/...), or access to a known sandbox-escape dunder. A
    SyntaxError surfaces as a ValueError too (it's an invalid tool either way).
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        raise ValueError(f"generated tool has a syntax error: {e}") from e
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if not _module_allowed(alias.name):
                    raise ValueError(
                        f"generated tool imports disallowed module {alias.name!r}"
                    )
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level or not _module_allowed(mod):
                raise ValueError(
                    "generated tool imports disallowed module "
                    f"{mod or '<relative import>'!r}"
                )
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in _BANNED_CALLS:
                raise ValueError(
                    f"generated tool calls disallowed builtin {node.func.id!r}"
                )
        elif isinstance(node, ast.Attribute):
            if node.attr in _BANNED_ATTRS:
                raise ValueError(
                    f"generated tool accesses disallowed attribute {node.attr!r}"
                )


def _import_module_from_path(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(f"maverick_generated_{name}", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load generated tool {name!r}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # noqa: S102 -- opt-in code execution
    return module


def _shield_ok(source: str) -> tuple[bool, str]:
    """Scan generated source through the Shield. Fail-open if absent."""
    try:
        from maverick_shield import Shield  # type: ignore
    except ImportError:
        return True, ""
    try:
        verdict = Shield.from_config().scan_input(source)
    except Exception:  # pragma: no cover -- fail-open per kernel rule 1
        return True, ""
    if getattr(verdict, "allowed", True):
        return True, ""
    return False, "; ".join(getattr(verdict, "reasons", []) or ["blocked by Shield"])


def write_generated_tool(name: str, source: str, *, need: str = "") -> Any:
    """Validate generated tool ``source`` and persist it, returning the Tool.

    Validation, in order: name regex -> static AST audit -> Shield scan ->
    import (executes the module) -> ``make_tool()`` returns a well-formed
    Tool. Only after ALL of these pass is the module written to the durable
    ``generated_tools/`` dir; a tool that fails validation leaves nothing
    behind. The returned Tool is registered into the live run by the
    caller.
    """
    from .tools import Tool

    if not _NAME_RE.match(name):
        raise ValueError(
            f"tool name {name!r} must be lowercase id (a-z0-9_), 3-42 chars"
        )
    source = _strip_fences(source)
    # Enforce the stdlib-only contract BEFORE the module is imported/executed.
    audit_generated_source(source)
    ok, reason = _shield_ok(source)
    if not ok:
        raise ValueError(f"generated tool rejected by Shield: {reason}")

    GENERATED_TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    # Validate from a staging path first so a broken module never lands at
    # the durable path the loader scans on every run.
    staging = GENERATED_TOOLS_DIR / f".staging_{name}.py"
    staging.write_text(source, encoding="utf-8")
    try:
        module = _import_module_from_path(name, staging)
        if not hasattr(module, "make_tool"):
            raise ValueError("module does not define make_tool()")
        tool = module.make_tool()
        if not isinstance(tool, Tool) or not tool.name or not callable(tool.fn):
            raise ValueError("make_tool() did not return a valid Tool")
    except ValueError:
        raise
    except Exception as e:
        # SyntaxError / ImportError / a raising make_tool() — surface as a
        # single rejection the agent can read and retry against.
        raise ValueError(f"generated tool failed validation: {type(e).__name__}: {e}") from e
    finally:
        staging.unlink(missing_ok=True)

    target = GENERATED_TOOLS_DIR / f"{name}.py"
    target.write_text(source, encoding="utf-8")
    record(need or name, "tool", tool.name, source=str(target))
    return tool


def _strip_fences(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else ""
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t.strip()


def load_generated_tools() -> list[Any]:
    """Import every persisted generated tool. Best-effort, per-file isolated.

    A module that raises on import or whose ``make_tool()`` misbehaves is
    logged and skipped — one bad generated tool can't take the swarm down.
    Only consulted when self-learning is enabled (see base_registry).
    """
    from .tools import Tool

    if not GENERATED_TOOLS_DIR.exists():
        return []
    out: list[Tool] = []
    for p in sorted(GENERATED_TOOLS_DIR.glob("*.py")):
        if p.name.startswith((".", "_")):
            continue
        try:
            # Re-audit on every load: a persisted file could have been
            # tampered with on disk since it was written.
            audit_generated_source(p.read_text(encoding="utf-8"))
            module = _import_module_from_path(p.stem, p)
            tool = module.make_tool()
            if isinstance(tool, Tool) and tool.name and callable(tool.fn):
                out.append(tool)
            else:
                log.warning("generated tool %s: make_tool() invalid; skipping", p.name)
        except Exception as e:
            log.warning("generated tool %s failed to load: %s", p.name, e)
    return out


# --------------------------------------------------------------------------
# discover: REST APIs (OpenAPI specs)
# --------------------------------------------------------------------------
# Well-known locations a service tends to publish its OpenAPI/Swagger doc.
WELL_KNOWN_SPEC_PATHS = (
    "/openapi.json", "/openapi.yaml", "/swagger.json", "/v3/api-docs",
    "/api-docs", "/swagger/v1/swagger.json", "/.well-known/openapi.json",
)
SPEC_FETCH_TIMEOUT = 10.0
MAX_SPEC_BYTES = 5_000_000
_URL_RE = re.compile(r"https?://[^\s\"'<>)\]]+")


def _default_opener(url: str, *, timeout: float):
    # Route through the shared SSRF guard so a model-supplied URL can't be
    # pointed at an internal/metadata address.
    from .tools.http_fetch import guarded_urlopen
    return guarded_urlopen(url, timeout=timeout)


def _fetch_text(url: str, *, opener=None, timeout: float = SPEC_FETCH_TIMEOUT) -> str | None:
    opener = opener or _default_opener
    try:
        with opener(url, timeout=timeout) as resp:
            if getattr(resp, "status", 200) != 200:
                return None
            return resp.read(MAX_SPEC_BYTES).decode("utf-8", errors="replace")
    except Exception as e:  # pragma: no cover -- network/parse never blocks
        log.debug("self_learning: fetch %s failed: %s", url, e)
        return None


def _is_openapi_text(text: str | None) -> bool:
    """True iff ``text`` is an OpenAPI/Swagger document.

    Matches what ``openapi_runner`` will actually accept: a JSON object with
    an ``openapi``/``swagger`` key AND ``paths``. YAML specs are detected by
    a cheap structural check on the head (openapi_runner parses them when
    pyyaml is installed).
    """
    if not text:
        return False
    try:
        data = json.loads(text)
        return (
            isinstance(data, dict)
            and ("openapi" in data or "swagger" in data)
            and "paths" in data
        )
    except (json.JSONDecodeError, ValueError):
        head = text[:2000]
        return bool(re.search(r"^\s*(openapi|swagger)\s*:", head, re.MULTILINE))


def validate_spec_url(url: str, *, opener=None) -> str | None:
    """Return ``url`` if it serves an OpenAPI/Swagger doc, else None."""
    if not url.startswith(("http://", "https://")):
        return None
    return url if _is_openapi_text(_fetch_text(url, opener=opener)) else None


def probe_openapi_spec(base_url: str, *, opener=None) -> str | None:
    """Probe well-known spec locations under ``base_url``; return the first hit.

    Tries the URL itself first (it may already be a spec doc), then the
    well-known paths under both the given URL and its bare origin.
    """
    from urllib.parse import urlsplit, urlunsplit

    base = (base_url or "").rstrip("/")
    if not base:
        return None
    direct = validate_spec_url(base, opener=opener)
    if direct:
        return direct
    parts = urlsplit(base)
    roots = [base]
    if parts.scheme and parts.netloc:
        origin = urlunsplit((parts.scheme, parts.netloc, "", "", ""))
        if origin not in roots:
            roots.append(origin)
    for root in roots:
        for path in WELL_KNOWN_SPEC_PATHS:
            hit = validate_spec_url(root + path, opener=opener)
            if hit:
                return hit
    return None


def _extract_urls(text: str, *, limit: int = 10) -> list[str]:
    seen: list[str] = []
    for u in _URL_RE.findall(text or ""):
        u = u.rstrip(".,);")
        if u not in seen:
            seen.append(u)
    return seen[:limit]


def discover_openapi_spec(
    *, base_url: str = "", search_text: str = "", opener=None, max_candidates: int = 6,
) -> str | None:
    """Find an OpenAPI spec URL from a base URL and/or web-search result text.

    1. If ``base_url`` is given, probe its well-known spec locations.
    2. Otherwise scan ``search_text`` for URLs and accept the first that
       serves a spec; failing that, probe the first candidate's origin.

    Returns the spec URL or None. Every fetch goes through the SSRF guard.
    Request count is bounded by ``max_candidates`` + the well-known probe.
    """
    if base_url:
        hit = probe_openapi_spec(base_url, opener=opener)
        if hit:
            return hit
    candidates = _extract_urls(search_text)[:max_candidates]
    for u in candidates:
        if validate_spec_url(u, opener=opener):
            return u
    if candidates:
        return probe_openapi_spec(candidates[0], opener=opener)
    return None


# --------------------------------------------------------------------------
# pre-flight gap analysis (orchestrator-driven)
# --------------------------------------------------------------------------
_NEEDS_SYSTEM = """You analyse a task and list capabilities a general assistant might LACK to do it.

Output a JSON array of short capability phrases (3-6 words each), e.g.
["send an sms message", "query a postgres database"]. List only NON-obvious,
specialised capabilities (external services, niche APIs, domain tools). If the
task needs nothing special, output []. Output ONLY the JSON array."""


def _parse_needs(text: str) -> list[str]:
    t = _strip_fences(text)
    m = re.search(r"\[.*\]", t, re.DOTALL)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    return [str(x).strip() for x in data if isinstance(x, (str,)) and str(x).strip()][:10]


async def preflight(
    llm: Any, goal_text: str, budget: Any, blackboard: Any | None = None,
    *, max_acquisitions: int = 5,
) -> list[str]:
    """Before a run, map the goal to capability needs and pre-acquire skills.

    Uses one cheap LLM call to extract needs, then installs the best
    catalog SKILL match for each (hash-pinned, safe — MCP/tool creation
    stays agent-driven via the in-loop tool). Returns the names acquired.
    Never raises: any failure degrades to "acquired nothing".
    """
    from .llm import model_for_role

    acquired: list[str] = []
    try:
        resp = await llm.complete_async(
            system=_NEEDS_SYSTEM,
            messages=[{"role": "user", "content": f"Task:\n{goal_text}"}],
            budget=budget, max_tokens=256,
            model=model_for_role("summarizer"),
        )
        needs = _parse_needs(resp.text or "")
    except Exception as e:  # pragma: no cover -- preflight never blocks a run
        log.debug("self_learning preflight analysis skipped: %s", e)
        return acquired

    from .skills import load_skills
    have = {s.name for s in load_skills()}
    for need in needs:
        if len(acquired) >= max(1, max_acquisitions):
            break
        cands = [c for c in search_capabilities(need, kinds=("skills",)) if c.score >= 0.2]
        if not cands or cands[0].name in have:
            continue
        try:
            acquire_skill(cands[0].name, need=need)
            acquired.append(cands[0].name)
            have.add(cands[0].name)
            if blackboard is not None:
                blackboard.post(
                    "orchestrator", "observation",
                    f"self-learning: pre-acquired skill {cands[0].name!r} for {need!r}",
                )
        except Exception as e:
            log.debug("preflight acquire %s failed: %s", cands[0].name, e)
    return acquired


__all__ = [
    "enabled", "settings", "Learned", "record", "history",
    "Candidate", "search_capabilities", "acquire_skill", "add_mcp_server",
    "write_generated_tool", "load_generated_tools", "audit_generated_source",
    "preflight",
    "validate_spec_url", "probe_openapi_spec", "discover_openapi_spec",
    "LEARNED_PATH", "GENERATED_TOOLS_DIR", "TOOL_AUTHOR_SYSTEM",
]
