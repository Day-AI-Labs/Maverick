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

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


USER_TEMPLATES = Path.home() / ".maverick" / "templates"

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
    path: Optional[Path] = None

    @classmethod
    def parse(cls, text: str, name: str, path: Optional[Path] = None) -> "Template":
        """Parse a template file. YAML frontmatter is optional."""
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
                # Try numeric coercion for budget fields.
                if k.startswith("budget_") and re.match(r"^[\d.]+$", v):
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
    dirs = [USER_TEMPLATES]
    dirs.extend(d for d in _BUNDLED_CANDIDATES if d.exists())
    return dirs


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
