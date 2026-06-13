"""Contract tests for the mobile-skills feasibility scaffold.

Pins the two properties the scaffold's honesty depends on: the chosen skill
module really is loadable in isolation (zero intra-package imports — the
whole reason it can run under Pyodide/Kivy), and the committed HTML
references only vendored/relative paths (no CDN hot-links).
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[1]
_MODULE = _REPO_ROOT / "packages" / "maverick-core" / "maverick" / "disagreement.py"
_HTML = _HERE / "pyodide-runner" / "index.html"

_ISOLATION_PROBE = """
import importlib.util
spec = importlib.util.spec_from_file_location("disagreement", {path!r})
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
assert mod.answer_entropy(["a", "a", "a"]) == 0.0
assert abs(mod.answer_entropy(["a", "b", "c"]) - 1.0) < 1e-9
assert 0.0 < mod.answer_entropy(["a", "a", "b"]) < 1.0
print("ok")
"""


def test_pure_module_imports_cleanly_in_isolation():
    # Fresh interpreter, module loaded by file path with no package context
    # and no repo on sys.path: exactly how Pyodide and the Kivy shell load it.
    proc = subprocess.run(
        [sys.executable, "-I", "-c", _ISOLATION_PROBE.format(path=str(_MODULE))],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "ok"


def test_module_really_has_no_intra_package_imports():
    source = _MODULE.read_text()
    assert not re.search(r"^\s*(from|import)\s+maverick", source, re.MULTILINE)
    assert not re.search(r"^\s*from\s+\.", source, re.MULTILINE)


def test_html_references_only_vendored_paths():
    html = _HTML.read_text()
    # Every load target (script src, fetch path, Pyodide indexURL) must be
    # relative — no CDN / remote loads in the committed artifact.
    targets = re.findall(r'src="([^"]+)"', html)
    targets += re.findall(r'indexURL: "([^"]+)"', html)
    targets += re.findall(r'SKILL_MODULE = "([^"]+)"', html)
    assert targets, "expected load targets in the runner page"
    for target in targets:
        assert target.startswith(("./", "../")), target
    # Pyodide comes from the vendored layout; the skill from the repo.
    assert 'src="./vendor/pyodide/pyodide.js"' in html
    assert 'indexURL: "./vendor/pyodide/"' in html
    assert "../../../packages/maverick-core/maverick/disagreement.py" in html


def test_vendor_readme_has_pinned_release_and_todo_checksum():
    text = (_HERE / "pyodide-runner" / "vendor" / "README.md").read_text()
    assert "pyodide-0.26.4.tar.bz2" in text
    assert "TODO" in text and "sha256" in text  # explicit fill-on-download, no fake pin


def test_kivy_main_runs_without_kivy():
    # The honest fallback: no Kivy in this env -> terminal output, exit 0.
    proc = subprocess.run(
        [sys.executable, str(_HERE / "kivy-shell" / "main.py")],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert "entropy=" in proc.stdout


def test_buildozer_spec_is_pure_python_and_offline():
    spec = (_HERE / "kivy-shell" / "buildozer.spec").read_text()
    assert re.search(r"^requirements = python3,kivy$", spec, re.MULTILINE)
    assert re.search(r"^android\.permissions =\s*$", spec, re.MULTILINE)  # no INTERNET
    assert "buildozer android debug" in spec  # maintainer instructions inline
