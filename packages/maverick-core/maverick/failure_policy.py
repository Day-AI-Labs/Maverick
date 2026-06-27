"""Failure-policy classification lint (auditability).

Every broad exception handler in the audit-integrity subsystem must declare its
intended failure mode, so an auditor (or a reviewer) can see — machine-checked —
whether an error path:

  - ``fail_closed``           — denies / stops / raises / reports a break;
  - ``fail_soft_with_audit``  — degrades but logs or records the degradation;
  - ``best_effort``           — swallows an optional optimization, safe to drop.

A "broad" handler is ``except Exception``, ``except BaseException``, or a bare
``except:``. The declaration is a marker comment

    # failure-policy: <fail_closed | fail_soft_with_audit | best_effort>

on the ``except`` line (as a trailing comment) or on the line immediately above
it. Anything after the class token (e.g. ``-- reason``) is free text.

Scope is **intentionally narrow** — the audit-log subsystem (``maverick/audit``),
where a silently-swallowed error is a genuine tamper-evidence gap. flake8-bugbear
stays off repo-wide on purpose (127 latent, mostly-intentional findings); this is
a targeted gate, not a codebase-wide except-handler sweep. Expand coverage by
adding paths to ``SCOPED_FILES`` — every added file must then have all of its
broad handlers classified.

CLI: ``python -m maverick.failure_policy --ci`` exits non-zero on any unmarked or
mis-marked handler in scope.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

CLASSES = ("fail_closed", "fail_soft_with_audit", "best_effort")
MARKER = "# failure-policy:"

_PKG = Path(__file__).resolve().parent
# Intentionally narrow: the audit-integrity subsystem. Add paths to widen.
SCOPED_FILES: list[Path] = sorted((_PKG / "audit").glob("*.py"))


def _is_broad(handler: ast.ExceptHandler) -> bool:
    """True for ``except:`` / ``except Exception`` / ``except BaseException``
    (alone or as one arm of a tuple)."""
    t = handler.type
    if t is None:
        return True  # bare except:
    names: list[str] = []
    if isinstance(t, ast.Name):
        names = [t.id]
    elif isinstance(t, ast.Tuple):
        names = [e.id for e in t.elts if isinstance(e, ast.Name)]
    return "Exception" in names or "BaseException" in names


def _marker_class(lines: list[str], lineno: int) -> str | None:
    """The declared class for a handler at 1-based ``lineno``, or None.

    Accepts the marker on the ``except`` line itself or the line directly above.
    """
    for ln in (lineno, lineno - 1):
        if 1 <= ln <= len(lines) and MARKER in lines[ln - 1]:
            after = lines[ln - 1].split(MARKER, 1)[1].strip()
            return after.split()[0] if after else ""
    return None


def scan_file(path: Path) -> list[tuple[int, str]]:
    """Return ``[(lineno, problem)]`` for unmarked / mis-marked broad handlers."""
    src = path.read_text(encoding="utf-8")
    lines = src.splitlines()
    try:
        tree = ast.parse(src)
    except SyntaxError as e:  # pragma: no cover -- scoped files always parse
        return [(getattr(e, "lineno", 0) or 0, f"syntax error: {e}")]
    problems: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and _is_broad(node):
            cls = _marker_class(lines, node.lineno)
            if cls is None:
                problems.append(
                    (node.lineno, "broad except without a # failure-policy: marker"))
            elif cls not in CLASSES:
                problems.append(
                    (node.lineno,
                     f"invalid failure-policy class {cls!r} (want one of {CLASSES})"))
    return problems


def scan(files: list[Path] | None = None) -> dict[Path, list[tuple[int, str]]]:
    files = SCOPED_FILES if files is None else files
    return {p: probs for p in files if (probs := scan_file(p))}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    issues = scan()
    if not issues:
        print(f"failure-policy: OK ({len(SCOPED_FILES)} scoped files, "
              "all broad excepts classified)")
        return 0
    for path, probs in issues.items():
        for lineno, msg in probs:
            print(f"{path}:{lineno}: {msg}")
    total = sum(len(v) for v in issues.values())
    print(f"failure-policy: {total} unclassified/invalid handler(s) in scope "
          "(add a `# failure-policy: <class>` marker)")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
