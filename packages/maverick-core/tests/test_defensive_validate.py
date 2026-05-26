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

    def test_conftest_blocked(self):
        from maverick.coding_mode import defensive_validate
        patch = (
            "diff --git a/src/conftest.py b/src/conftest.py\n"
            "--- a/src/conftest.py\n+++ b/src/conftest.py\n@@ -1 +1 @@\n-x\n+y\n"
        )
        result = defensive_validate(patch)
        assert not result.ok
        assert any("conftest" in p for p in result.blocked_paths)

    def test_setup_py_blocked(self):
        from maverick.coding_mode import defensive_validate
        patch = (
            "diff --git a/setup.py b/setup.py\n"
            "--- a/setup.py\n+++ b/setup.py\n@@ -1 +1 @@\n-x\n+y\n"
        )
        result = defensive_validate(patch)
        assert not result.ok

    def test_pyproject_blocked(self):
        from maverick.coding_mode import defensive_validate
        patch = (
            "diff --git a/pyproject.toml b/pyproject.toml\n"
            "--- a/pyproject.toml\n+++ b/pyproject.toml\n@@ -1 +1 @@\n-x\n+y\n"
        )
        result = defensive_validate(patch)
        assert not result.ok

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
