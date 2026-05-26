"""repo_map tool — give the agent a structured codebase view.

Aider's `--map` and OpenHands' "Locator" sub-agent both materially
help on SWE-bench by short-circuiting the "ls; grep; ls; grep" loop
the agent burns turns on at start. We ship the same here.

Returns a compressed view of the workdir:
  - top-level files + directories (depth 1)
  - one-line "what's in here" for top-level dirs (depth 2 listing)
  - language detection (presence of pyproject.toml / package.json /
    Cargo.toml / etc) so the agent picks the right test runner

The tool is opt-in: the agent must invoke `repo_map` (it's not
auto-injected into context). That keeps token usage bounded.
"""
from __future__ import annotations

from pathlib import Path

from . import Tool


_MAX_TOP_ENTRIES = 80
_MAX_NESTED_PER_DIR = 30
_IGNORE_DIRS = {
    ".git", "node_modules", ".venv", "venv", "__pycache__",
    "dist", "build", "target", ".pytest_cache", ".mypy_cache",
    ".tox", ".idea", ".vscode", "coverage",
}


def _detect_languages(root: Path) -> list[str]:
    markers = {
        "Python (pyproject)": "pyproject.toml",
        "Python (setup.py)":  "setup.py",
        "Python (requirements)": "requirements.txt",
        "Node":               "package.json",
        "Rust":               "Cargo.toml",
        "Go":                 "go.mod",
        "Ruby":               "Gemfile",
        "Java (gradle)":      "build.gradle",
        "Java (maven)":       "pom.xml",
        "Make":               "Makefile",
        "Docker":             "Dockerfile",
    }
    hits = []
    for label, fname in markers.items():
        if (root / fname).exists():
            hits.append(label)
    return hits


def repo_map(sandbox) -> Tool:
    """Build the repo_map Tool bound to `sandbox.workdir`."""
    def fn(args: dict) -> str:
        root = Path(getattr(sandbox, "workdir", ".")).expanduser()
        if not root.exists():
            return f"ERROR: workdir {root} does not exist"
        lines: list[str] = [f"Repo map for {root}:"]

        langs = _detect_languages(root)
        if langs:
            lines.append("Languages / build systems: " + ", ".join(langs))

        # Top-level directory listing.
        try:
            entries = sorted(root.iterdir(), key=lambda p: (not p.is_dir(), p.name))
        except OSError:
            return f"ERROR: cannot list {root}"
        entries = [e for e in entries if e.name not in _IGNORE_DIRS][:_MAX_TOP_ENTRIES]

        for entry in entries:
            if entry.is_dir():
                # One-line summary: top N files within.
                try:
                    children = sorted(
                        x.name for x in entry.iterdir()
                        if x.name not in _IGNORE_DIRS
                    )[:_MAX_NESTED_PER_DIR]
                except OSError:
                    children = ["(unreadable)"]
                preview = ", ".join(children[:8])
                if len(children) > 8:
                    preview += f", ... ({len(children)} total)"
                lines.append(f"  {entry.name}/    {preview}")
            else:
                size = entry.stat().st_size if entry.exists() else 0
                size_h = (
                    f"{size}B" if size < 1024
                    else f"{size // 1024}KB" if size < 1024 * 1024
                    else f"{size // (1024 * 1024)}MB"
                )
                lines.append(f"  {entry.name}    [{size_h}]")

        # Test discovery hint.
        test_dirs = [d.name for d in root.iterdir()
                     if d.is_dir() and d.name in ("tests", "test")]
        if test_dirs:
            lines.append(f"\nTest dir(s): {', '.join(test_dirs)}")
        elif any(f.name.startswith("test_") for f in root.iterdir() if f.is_file()):
            lines.append("\nTests look colocated (test_*.py at root level)")

        # README hint.
        for readme in ("README.md", "README.rst", "README"):
            if (root / readme).exists():
                lines.append(f"\n{readme} present (use read_file to read)")
                break

        return "\n".join(lines)

    return Tool(
        name="repo_map",
        description=(
            "Get a one-shot structured view of the working directory: "
            "top-level files + dirs, detected language / build system, "
            "test layout hint. Call ONCE near the start of a coding "
            "task to orient yourself; avoid re-calling on every turn."
        ),
        input_schema={"type": "object", "properties": {}},
        fn=fn,
    )
