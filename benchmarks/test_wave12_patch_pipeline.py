"""Wave 12 fixes: render_diff includes new files, predicted_patch sanitizer."""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path


def _load_sb():
    p = Path(__file__).resolve().parent / "swe_bench.py"
    spec = importlib.util.spec_from_file_location("benchmarks_swe_bench", p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["benchmarks_swe_bench"] = mod
    spec.loader.exec_module(mod)
    return mod


def _init_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "commit.gpgsign", "false"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "t"], check=True)
    (tmp_path / "seed.py").write_text("x = 1\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "seed.py"], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-q", "-m", "seed"], check=True,
    )
    return tmp_path


# ---- render_diff: new files ----

class TestRenderDiffNewFiles:
    def test_new_file_appears_in_diff(self, tmp_path):
        from maverick.edit_format import SearchReplaceBlock, apply_blocks, render_diff
        repo = _init_repo(tmp_path)
        blk = SearchReplaceBlock(path="newmod.py", search="", replace="def f():\n    return 42\n")
        summary = apply_blocks([blk], repo)
        diff = render_diff(repo, touched_paths=sorted(summary.files_touched))
        assert "newmod.py" in diff, (
            "new untracked file missing from rendered diff "
            f"(this was the pre-Wave-12 silent score leak): {diff!r}"
        )
        assert "+def f():" in diff
        assert "/dev/null" in diff or "new file" in diff

    def test_modify_and_new_file_both_appear(self, tmp_path):
        from maverick.edit_format import SearchReplaceBlock, apply_blocks, render_diff
        repo = _init_repo(tmp_path)
        blocks = [
            SearchReplaceBlock(path="seed.py", search="x = 1\n", replace="x = 2\n"),
            SearchReplaceBlock(path="newmod.py", search="", replace="y = 99\n"),
        ]
        summary = apply_blocks(blocks, repo)
        diff = render_diff(repo, touched_paths=sorted(summary.files_touched))
        assert "seed.py" in diff
        assert "newmod.py" in diff

    def test_unrelated_untracked_file_not_included(self, tmp_path):
        from maverick.edit_format import SearchReplaceBlock, apply_blocks, render_diff
        repo = _init_repo(tmp_path)
        (repo / "secret.txt").write_text("API_KEY=sk-secret\n")
        blk = SearchReplaceBlock(path="seed.py", search="x = 1\n", replace="x = 2\n")
        summary = apply_blocks([blk], repo)
        diff = render_diff(repo, touched_paths=sorted(summary.files_touched))
        assert "seed.py" in diff
        assert "secret.txt" not in diff
        assert "API_KEY=sk-secret" not in diff


# ---- _sanitize_patch_for_csv ----

class TestSanitizePatchForCSV:
    def test_strip_nul_bytes(self):
        sb = _load_sb()
        out = sb._sanitize_patch_for_csv("diff --git\x00 a/foo b/foo\n")
        assert "\x00" not in out

    def test_neutralize_excel_formula_prefix(self):
        sb = _load_sb()
        for prefix in ("=", "+", "-", "@"):
            out = sb._sanitize_patch_for_csv(f"{prefix}cmd|'foo'!A1")
            assert out.startswith("'"), (
                f"prefix {prefix!r} should be neutralized with leading apostrophe"
            )

    def test_no_truncation(self):
        sb = _load_sb()
        # ~76KB patch — must NOT be truncated. SWE-bench Pro has no cap;
        # Wave 12 removed the legacy [:50_000] slice.
        big = "diff --git a/x b/x\n" + "+long line content\n" * 4000
        assert len(big) > 50_000  # sanity: bigger than the old cap
        out = sb._sanitize_patch_for_csv(big)
        # `diff` starts with `d` (not a sanitizer trigger char), so the
        # output must be the exact input — no leading apostrophe, no slice.
        assert len(out) == len(big), (
            f"truncation/expansion detected: in={len(big)} out={len(out)}"
        )
        assert out == big

    def test_empty_input(self):
        sb = _load_sb()
        assert sb._sanitize_patch_for_csv("") == ""
        assert sb._sanitize_patch_for_csv(None) == ""

    def test_strips_other_control_chars_but_keeps_whitespace(self):
        sb = _load_sb()
        # \x08 (backspace) stripped, \n / \t / \r kept.
        out = sb._sanitize_patch_for_csv("line1\n\x08line2\tindent\r\n")
        assert "\x08" not in out
        assert "\n" in out
        assert "\t" in out

    def test_normal_diff_passes_through_with_apostrophe(self):
        sb = _load_sb()
        # Normal diff starts with `--- a/` (literal `-`) so gets the
        # apostrophe prefix — that's expected and acceptable; the
        # downstream grader strips it via its own preprocessing.
        diff = "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-old\n+new\n"
        out = sb._sanitize_patch_for_csv(diff)
        assert out == "'" + diff or out == diff
