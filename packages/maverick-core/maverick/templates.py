"""Goal templates: pre-built goal bodies with variable substitution.

A template is a markdown file with optional YAML frontmatter that
captures a reusable goal pattern. Variables like ``{{ topic }}`` are
substituted from ``--param key=value`` on the CLI (or programmatically
from a dict).

Lookup order:
  1. ``~/.maverick/templates/<name>.md`` (user-installed)
  2. ``benchmarks/example-templates/<name>.md`` (bundled with the repo)

File format::

    ---
    title: Research and compare AI agent frameworks
    budget_dollars: 2.0
    budget_wall_seconds: 1200
    params:
      - topic
      - depth
    ---
    Compare {{ topic }} across {{ depth }} dimensions. Write the
    output to report.md.

The title can also contain ``{{ vars }}``.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

USER_TEMPLATES = Path.home() / ".maverick" / "templates"
log = logging.getLogger(__name__)

# Bundled templates ship in the repo; locate via relative path from the
# installed package. The agent kernel intentionally has no notion of the
# repo layout, so we try a few candidate roots.
_BUNDLED_CANDIDATES = [
    Path(__file__).parent.parent.parent.parent / "benchmarks" / "example-templates",
    Path.cwd() / "benchmarks" / "example-templates",
]


@dataclass
class Template:
    name: str
    title: str
    body: str
    budget_dollars: float = 5.0
    budget_wall_seconds: float = 3600.0
    params: list[str] = field(default_factory=list)
    path: Path | None = None
    sig: str | None = None
    pubkey: str | None = None
    verified: bool = False

    @classmethod
    def parse(cls, text: str, name: str, path: Path | None = None) -> Template:
        """Parse a template file. YAML frontmatter is optional."""
        # Normalize CRLF/CR so the LF-anchored frontmatter regex matches files
        # authored on Windows or served over HTTP with CRLF endings -- otherwise
        # their frontmatter (title/params AND budgets) is silently ignored.
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
        if m:
            front, body = m.group(1), m.group(2)
            meta = _parse_frontmatter(front)
        else:
            meta, body = {}, text
        return cls(
            name=name,
            title=str(meta.get("title", name)),
            body=body.strip(),
            budget_dollars=float(meta.get("budget_dollars", 5.0)),
            budget_wall_seconds=float(meta.get("budget_wall_seconds", 3600)),
            params=meta.get("params", []) if isinstance(meta.get("params"), list) else [],
            path=path,
            sig=meta.get("sig") if isinstance(meta.get("sig"), str) else None,
            pubkey=meta.get("pubkey") if isinstance(meta.get("pubkey"), str) else None,
        )

    def render(self, **params: str) -> tuple[str, str]:
        """Return (title, body) with variables substituted.

        Missing required params raise ValueError.
        """
        missing = [p for p in self.params if p not in params]
        if missing:
            raise ValueError(
                f"template {self.name!r} missing required params: {missing}"
            )
        return (
            _substitute(self.title, params),
            _substitute(self.body, params),
        )


def _parse_frontmatter(front: str) -> dict:
    meta: dict = {}
    current_key = None
    for line in front.splitlines():
        line = line.rstrip()
        if not line:
            continue
        if line.startswith("  - ") and current_key:
            meta.setdefault(current_key, []).append(line[4:].strip())
        elif ":" in line:
            k, _, v = line.partition(":")
            k = k.strip()
            v = v.strip()
            current_key = k
            if v:
                # Try numeric coercion for budget fields. The pattern must
                # match a real number -- the old `^[\d.]+$` accepted things
                # like "1.2.3" / "." / "5." that float() then choked on,
                # raising an uncaught ValueError out of template parse.
                if k.startswith("budget_") and re.match(r"^\d+(\.\d+)?$", v):
                    meta[k] = float(v)
                else:
                    meta[k] = v
            else:
                meta[k] = []
    return meta


_VAR = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def _substitute(text: str, params: dict[str, str]) -> str:
    return _VAR.sub(lambda m: str(params.get(m.group(1), m.group(0))), text)


def _candidate_dirs() -> list[Path]:
    # De-dup by resolved path: the two bundled candidates (package-relative
    # and cwd-relative) point at the same directory when run from a repo
    # checkout, which otherwise lists it twice -- including in the
    # "not found. Searched: [...]" error.
    out: list[Path] = []
    seen: set[Path] = set()
    for d in [USER_TEMPLATES, *(c for c in _BUNDLED_CANDIDATES if c.exists())]:
        rd = d.resolve()
        if rd in seen:
            continue
        seen.add(rd)
        out.append(d)
    return out


def list_templates() -> list[str]:
    """Return template names found across user + bundled dirs."""
    seen: set[str] = set()
    out: list[str] = []
    for d in _candidate_dirs():
        if not d.exists():
            continue
        for p in sorted(d.glob("*.md")):
            if p.stem == "README":
                continue
            if p.stem in seen:
                continue
            seen.add(p.stem)
            out.append(p.stem)
    return out


def _validate_template_name(name: str) -> None:
    """Only allow safe template IDs like ``trip-plan`` or ``research_v2``."""
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9_-]*$", name):
        raise ValueError(
            f"invalid template name {name!r}; use only letters, numbers, _ and -"
        )


def load_template(name: str) -> Template:
    """Find ``name.md`` in candidate dirs and parse it."""
    _validate_template_name(name)
    for d in _candidate_dirs():
        p = d / f"{name}.md"
        if p.exists():
            return Template.parse(p.read_text(encoding="utf-8"), name, path=p)
    raise FileNotFoundError(
        f"template {name!r} not found. Searched: {[str(d) for d in _candidate_dirs()]}"
    )


# ---- v2 community registry (federated catalog) ------------------------------
#
# Goal templates v2: discover + install templates by name from a self-hostable
# `<base>/templates/index.json` (the same federated `catalog` the skills + MCP
# registries use). A template is content (frontmatter + body), so an entry is
# fetched from `source` and verified against `sha256`, exactly like skills.


def _configured_template_indexes() -> list[str]:
    """Registry base URLs from ``[template_registries] indexes``, else the
    shared catalog default."""
    from . import catalog
    try:
        from .config import load_config
        cfg = (load_config() or {}).get("template_registries") or {}
        indexes = cfg.get("indexes")
        if isinstance(indexes, list) and indexes:
            return [str(i).rstrip("/") for i in indexes]
    except Exception:  # pragma: no cover -- never block discovery on config
        pass
    return [i.rstrip("/") for i in catalog.DEFAULT_INDEXES]


def browse_templates(*, indexes: list[str] | None = None):
    """Return the template entries available across the configured registries."""
    from . import catalog
    return catalog.load_catalog(
        "templates",
        indexes=indexes if indexes is not None else _configured_template_indexes())


def _strip_registry_budget_frontmatter(content: str) -> str:
    """Drop run-budget fields from untrusted registry template content.

    Local/user-authored templates may still declare budgets, but catalog
    templates are remote prompt content. Persisting catalog-supplied budgets
    would let an index raise spend/time limits later when the user runs the
    template, so remote installs are normalized to the parser defaults unless
    the user passes explicit CLI flags or edits the local file themselves.
    """
    # Normalize line endings first: a CRLF-served template would otherwise slip
    # past the LF-anchored regex and keep its remote budget_* lines (which
    # Template.parse, also normalized, would then honor) -- defeating the strip.
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", content, re.DOTALL)
    if not m:
        return content
    front, body = m.group(1), m.group(2)
    budget_keys = {"budget_dollars", "budget_wall_seconds"}
    kept: list[str] = []
    for line in front.splitlines():
        key = line.partition(":")[0].strip() if ":" in line else ""
        if key in budget_keys:
            continue
        kept.append(line)
    return "---\n" + "\n".join(kept).rstrip() + "\n---\n" + body


def _canonical_template_signed_bytes(template: Template) -> bytes:
    """Stable bytes for signed registry template prompt content."""
    return json.dumps(
        {
            "title": template.title,
            "body": template.body,
            "params": list(template.params),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _verify_registry_template_signature(
    template: Template, *, require_signature: bool = False
) -> bool:
    """Enforce trusted-publisher signatures for catalog template installs.

    Reuses the same operator trust anchors as catalog skills: when
    ``[skills].trusted_pubkeys`` is configured, or require_signed_catalog is
    enabled, remote templates must carry an Ed25519 signature from a trusted
    publisher. With no trust policy configured, unsigned installs remain
    allowed for backward compatibility.
    """
    from . import config as _config
    from .audit import signing

    cfg = _config.get_skills()
    trusted = cfg["trusted_pubkeys"]
    must_verify = bool(cfg["require_signed_catalog"] or trusted or require_signature)
    signed = bool(template.sig and template.pubkey)

    if not signed:
        if must_verify:
            raise ValueError(
                "template rejected: catalog template is unsigned, but trusted "
                "publishers or require_signed_catalog are configured."
            )
        return False
    if not signing._have_crypto():
        raise ValueError(
            "template rejected: cryptography is required to verify signed "
            "registry templates."
        )
    if not trusted:
        if must_verify:
            raise ValueError(
                "template rejected: signed registry template has no configured "
                "[skills].trusted_pubkeys trust anchor."
            )
        return False
    if template.pubkey not in trusted:
        raise ValueError(
            "template rejected: signed by an untrusted publisher key "
            f"{template.pubkey[:16]!r} (not in [skills].trusted_pubkeys)."
        )
    if not signing.verify_ed25519(
        template.pubkey, template.sig, _canonical_template_signed_bytes(template)
    ):
        raise ValueError(
            "template rejected: Ed25519 signature does not verify over the "
            "template's signed fields (title/params/body)."
        )
    return True


def _shield_scan_registry_template(template: Template) -> None:
    """Reject catalog templates blocked by Shield before writing them."""
    try:
        from maverick_shield import Shield  # type: ignore
    except ImportError:
        return
    try:
        verdict = Shield.from_config().scan_input(
            f"Template title: {template.title}\n\nTemplate body:\n{template.body}"
        )
    except ValueError:
        raise
    except Exception as exc:  # pragma: no cover -- scanner bugs should not brick install
        log.warning(
            "Shield raised %s during template install; failing open",
            type(exc).__name__,
        )
        return
    if not verdict.allowed:
        raise ValueError(
            f"template rejected by Shield ({verdict.severity}): "
            f"{'; '.join(verdict.reasons)}"
        )


def install_template_from_catalog(
    name: str, *, indexes: list[str] | None = None, dest: Path | None = None
) -> Template:
    """Install a template by name from the registry into ``~/.maverick/templates``.

    Resolves the entry, fetches its ``source`` (gh:/https:), verifies the pinned
    ``sha256``, strips remote budget frontmatter, enforces trusted-publisher
    signatures when configured, Shield-scans the prompt surface when Shield is
    installed, validates it parses as a Template, then writes ``<name>.md``.
    Returns the parsed Template. Raises ValueError on unknown name, hash
    mismatch, signature policy failure, or Shield rejection."""
    from . import catalog
    from .skills import _fetch_skill_source  # generic gh:/https: text fetcher

    _validate_template_name(name)
    entry = catalog.resolve(
        name, "templates",
        indexes=indexes if indexes is not None else _configured_template_indexes())
    if entry is None:
        raise ValueError(f"no template named {name!r} in the registry")
    content = _fetch_skill_source(entry.source)
    if not catalog.verify_sha256(content, entry.sha256):
        raise ValueError(
            f"content hash mismatch for {name!r}: the fetched template does not "
            "match the registry's pinned sha256. Refusing to install.")
    # Catalog templates are untrusted remote prompt content. Validate and scan
    # the rendered prompt surface before persisting, and do not persist remote
    # budget fields as future explicit run overrides.
    content = _strip_registry_budget_frontmatter(content)
    template = Template.parse(content, name)  # validate it parses before writing
    template.verified = _verify_registry_template_signature(template)
    _shield_scan_registry_template(template)
    target_dir = dest if dest is not None else USER_TEMPLATES
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / f"{name}.md").write_text(content, encoding="utf-8")
    template.path = target_dir / f"{name}.md"
    return template
