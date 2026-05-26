"""Tests for Wave 11 defensive_validate — grader brittleness rules."""
from __future__ import annotations


class TestForbiddenPaths:
    """The grader applies its test_patch AFTER ours, or refuses to
    process a patch that pins dependencies. Both cause silent failures
    we cannot recover from at submit time."""

    def test_test_file_blocked(self):
        from maverick.coding_mode import defensive_validate
        patch = (
            "diff --git a/tests/test_foo.py b/tests/test_foo.py\n"
            "--- a/tests/test_foo.py\n"
            "+++ b/tests/test_foo.py\n"
            "@@ -1 +1 @@\n"
            "-assert x == 1\n"
            "+assert x == 2\n"
        )
        result = defensive_validate(patch)
        assert not result.ok
        assert "tests/test_foo.py" in result.blocked_paths

    def test_conftest_warned_not_blocked(self):
        """Wave 12 (council F8a): conftest.py changes are no longer
        hard-blocked; the grader either accepts the edit (when the
        test_patch doesn't touch conftest) or silently drops it. Warn,
        but don't fail the candidate — real fixes do legitimately
        register fixtures here."""
        from maverick.coding_mode import defensive_validate
        patch = (
            "diff --git a/src/conftest.py b/src/conftest.py\n"
            "--- a/src/conftest.py\n+++ b/src/conftest.py\n@@ -1 +1 @@\n-x\n+y\n"
        )
        result = defensive_validate(patch)
        assert result.ok is True, "conftest is no longer hard-blocked"
        assert any("conftest" in w for w in result.warnings)
        assert result.fn_risk in ("medium", "high")

    def test_setup_py_warned_not_blocked(self):
        """Wave 12 (council F8a): setup.py warns; some fixes legitimately
        adjust entry_points or extras_require."""
        from maverick.coding_mode import defensive_validate
        patch = (
            "diff --git a/setup.py b/setup.py\n"
            "--- a/setup.py\n+++ b/setup.py\n@@ -1 +1 @@\n-x\n+y\n"
        )
        result = defensive_validate(patch)
        assert result.ok is True
        assert any("setup.py" in w for w in result.warnings)

    def test_pyproject_warned_not_blocked(self):
        """Wave 12 (council F8a): pyproject.toml warns. Many fixes touch
        [tool.*] sections, which are safe."""
        from maverick.coding_mode import defensive_validate
        patch = (
            "diff --git a/pyproject.toml b/pyproject.toml\n"
            "--- a/pyproject.toml\n+++ b/pyproject.toml\n@@ -1 +1 @@\n-x\n+y\n"
        )
        result = defensive_validate(patch)
        assert result.ok is True
        assert any("pyproject.toml" in w for w in result.warnings)

    def test_lockfile_still_blocked(self):
        """Wave 12: lock files remain hard-blocked. Modifying a lock
        file is the surest way to break the grader's dep resolution."""
        from maverick.coding_mode import defensive_validate
        for fname in ("poetry.lock", "Cargo.lock", "yarn.lock", "go.sum"):
            patch = (
                f"diff --git a/{fname} b/{fname}\n"
                f"--- a/{fname}\n+++ b/{fname}\n@@ -1 +1 @@\n-x\n+y\n"
            )
            result = defensive_validate(patch)
            assert not result.ok, f"{fname} should still be hard-blocked"

    def test_package_lock_blocked(self):
        from maverick.coding_mode import defensive_validate
        patch = (
            "diff --git a/package-lock.json b/package-lock.json\n"
            "--- a/package-lock.json\n+++ b/package-lock.json\n@@ -1 +1 @@\n-x\n+y\n"
        )
        result = defensive_validate(patch)
        assert not result.ok

    def test_production_file_allowed(self):
        from maverick.coding_mode import defensive_validate
        patch = (
            "diff --git a/src/app/models.py b/src/app/models.py\n"
            "--- a/src/app/models.py\n+++ b/src/app/models.py\n@@ -1 +1 @@\n-x\n+y\n"
        )
        result = defensive_validate(patch)
        assert result.ok

    def test_fail_to_pass_path_blocked(self):
        from maverick.coding_mode import defensive_validate
        # If FAIL_TO_PASS mentions src/foo.py::TestX::test_y, the agent
        # must not touch src/foo.py at all.
        patch = (
            "diff --git a/src/foo.py b/src/foo.py\n"
            "--- a/src/foo.py\n+++ b/src/foo.py\n@@ -1 +1 @@\n-x\n+y\n"
        )
        result = defensive_validate(
            patch, fail_to_pass=["src/foo.py::TestX::test_y"],
        )
        assert not result.ok

    def test_opaque_off_disables_all_blocks(self):
        from maverick.coding_mode import defensive_validate
        patch = (
            "diff --git a/tests/test_foo.py b/tests/test_foo.py\n"
            "--- a/tests/test_foo.py\n+++ b/tests/test_foo.py\n@@ -1 +1 @@\n-x\n+y\n"
        )
        result = defensive_validate(patch, opaque=False)
        assert result.ok


class TestCheatingDetector:
    """Scale's Nov-2025 cheating detection blog: patches with >20%
    verbatim overlap to the gold are flagged. We refuse to submit
    them."""

    def test_high_overlap_rejected(self):
        from maverick.coding_mode import defensive_validate
        gold = (
            "diff --git a/foo.py b/foo.py\n"
            "@@ -1,3 +1,3 @@\n"
            "-def add(a, b):\n"
            "-    return a + b\n"
            "+def add(a, b):\n"
            "+    return a + b + 1\n"
            "+    # complete reimplementation here\n"
        )
        result = defensive_validate(gold, gold_patch=gold)
        assert not result.ok
        assert result.fn_risk == "high"

    def test_low_overlap_passes(self):
        from maverick.coding_mode import defensive_validate
        gold = "diff --git a/x.py b/x.py\n@@ -1 +1 @@\n-x = 1\n+x = 2\n"
        # Different fix entirely.
        ours = (
            "diff --git a/y.py b/y.py\n@@ -100,2 +100,2 @@\n"
            "-frobnicate(z)\n+frobnicate(z, mode='careful')\n"
        )
        result = defensive_validate(ours, gold_patch=gold)
        assert result.ok


class TestWhitespaceOnly:
    def test_whitespace_only_warned(self):
        from maverick.coding_mode import defensive_validate
        patch = (
            "diff --git a/foo.py b/foo.py\n"
            "--- a/foo.py\n+++ b/foo.py\n"
            "@@ -1 +1 @@\n"
            "-    \n"
            "+\t\n"
        )
        result = defensive_validate(patch)
        # ok=True (no forbidden paths) but flagged high-FN risk.
        assert result.fn_risk == "high"
        assert any("whitespace" in w for w in result.warnings)


class TestQuotedPaths:
    """Wave 12 (council F8c): git quotes paths with spaces / non-ASCII.
    The pre-Wave-12 \\S+ regex matched only the first whitespace-delimited
    segment, silently bypassing the test-file blocker."""

    def test_path_with_space_extracted(self):
        from maverick.coding_mode import _extract_diff_paths
        patch = (
            'diff --git "a/dir with space/foo.py" "b/dir with space/foo.py"\n'
            '--- "a/dir with space/foo.py"\n'
            '+++ "b/dir with space/foo.py"\n'
            "@@ -1 +1 @@\n-x\n+y\n"
        )
        paths = _extract_diff_paths(patch)
        assert "dir with space/foo.py" in paths

    def test_quoted_test_file_still_blocked(self):
        """The real teeth: quoted test paths must still be caught by
        the forbidden-paths blocker."""
        from maverick.coding_mode import defensive_validate
        patch = (
            'diff --git "a/tests/with space/test_foo.py" '
            '"b/tests/with space/test_foo.py"\n'
            '--- "a/tests/with space/test_foo.py"\n'
            '+++ "b/tests/with space/test_foo.py"\n'
            "@@ -1 +1 @@\n-x\n+y\n"
        )
        result = defensive_validate(patch)
        assert not result.ok, "quoted-path test files must still be blocked"


class TestTokenizedCheatingDetector:
    """Wave 12 (council F8b): token-level overlap is more meaningful
    than character-level and immune to whitespace games."""

    def test_whitespace_diff_does_not_reduce_overlap(self):
        from maverick.coding_mode import defensive_validate
        gold = (
            "diff --git a/foo.py b/foo.py\n"
            "@@ -1,2 +1,2 @@\n"
            "-def add(a, b): return a + b\n"
            "+def add(a, b): return a + b + 1\n"
        )
        # Same tokens, different formatting — should still flag.
        ours = (
            "diff --git a/foo.py b/foo.py\n"
            "@@ -1,2 +1,2 @@\n"
            "-def add(a,b):return a+b\n"
            "+def add(a , b) : return a + b + 1\n"
        )
        result = defensive_validate(ours, gold_patch=gold)
        assert not result.ok, (
            "token-level matcher should catch this; "
            "whitespace tricks don't fool it"
        )

    def test_different_implementation_passes(self):
        from maverick.coding_mode import defensive_validate
        gold = (
            "diff --git a/x.py b/x.py\n@@ -1,3 +1,3 @@\n"
            "-def f():\n-    return 1\n+def f():\n+    return 2\n"
        )
        ours = (
            "diff --git a/y.py b/y.py\n@@ -1,3 +1,3 @@\n"
            "-class Helper:\n-    pass\n"
            "+class Helper:\n"
            "+    def transform(self, payload): return payload.upper()\n"
        )
        result = defensive_validate(ours, gold_patch=gold)
        assert result.ok


class TestASTCheck:
    def test_clean_python_passes(self, tmp_path):
        from maverick.coding_mode import _ast_check_python_files
        (tmp_path / "ok.py").write_text("def f():\n    return 1\n")
        errors = _ast_check_python_files(tmp_path, ["ok.py"])
        assert errors == []

    def test_syntax_error_caught(self, tmp_path):
        from maverick.coding_mode import _ast_check_python_files
        (tmp_path / "broken.py").write_text("def f(:\n    return 1\n")
        errors = _ast_check_python_files(tmp_path, ["broken.py"])
        assert len(errors) == 1
        assert "broken.py" in errors[0]

    def test_non_python_skipped(self, tmp_path):
        from maverick.coding_mode import _ast_check_python_files
        (tmp_path / "broken.js").write_text("function f({ {{{")
        errors = _ast_check_python_files(tmp_path, ["broken.js"])
        assert errors == []

    def test_missing_file_ignored(self, tmp_path):
        from maverick.coding_mode import _ast_check_python_files
        errors = _ast_check_python_files(tmp_path, ["nonexistent.py"])
        assert errors == []
