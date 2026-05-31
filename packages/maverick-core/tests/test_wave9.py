"""Wave 9: SWE-bench Pro prep — coding mode fixes, polyglot, isolation."""
from __future__ import annotations

import pytest

# ---- #1: orchestrator gets coding-mode template ----

class TestOrchestratorGetsCodingModeTemplate:
    def test_orchestrator_in_coding_mode_uses_coder_template(
        self, tmp_path, monkeypatch,
    ):
        from maverick.agent import Agent
        from maverick.blackboard import Blackboard
        from maverick.budget import Budget
        from maverick.sandbox import LocalBackend
        from maverick.swarm import SwarmContext
        from maverick.world_model import WorldModel

        monkeypatch.setenv("MAVERICK_CODING_MODE", "1")
        world = WorldModel(tmp_path / "w.db")
        gid = world.create_goal("test", "")
        ctx = SwarmContext(
            llm=None, world=world, budget=Budget(),
            blackboard=Blackboard(),
            sandbox=LocalBackend(workdir=tmp_path),
            goal_id=gid, max_depth=1,
        )
        agent = Agent(ctx=ctx, role="orchestrator", brief="fix bug", depth=0)
        # Wave 9: the orchestrator's system prompt is now the coder
        # template when coding mode is on. Detect via the unique
        # phrase from CODER_CODING_MODE_TEMPLATE.
        assert "unified diff" in agent.system
        assert "diff" in agent.system
        # And it should NOT be the prose-y orchestrator template.
        assert "synthesize" not in agent.system.lower()

    def test_orchestrator_off_coding_mode_still_prose(
        self, tmp_path, monkeypatch,
    ):
        from maverick.agent import Agent
        from maverick.blackboard import Blackboard
        from maverick.budget import Budget
        from maverick.sandbox import LocalBackend
        from maverick.swarm import SwarmContext
        from maverick.world_model import WorldModel

        monkeypatch.delenv("MAVERICK_CODING_MODE", raising=False)
        world = WorldModel(tmp_path / "w.db")
        gid = world.create_goal("test", "")
        ctx = SwarmContext(
            llm=None, world=world, budget=Budget(),
            blackboard=Blackboard(),
            sandbox=LocalBackend(workdir=tmp_path),
            goal_id=gid, max_depth=1,
        )
        agent = Agent(ctx=ctx, role="orchestrator", brief="x", depth=0)
        # Back-compat: prose orchestrator template.
        assert "synthesize" in agent.system.lower() or "decompose" in agent.system.lower()


# ---- extract_unified_diff: stricter ----

class TestExtractUnifiedDiffStrict:
    def test_prose_with_dash_dash_a_returns_none(self):
        from maverick.coding_mode import extract_unified_diff
        # No `+++ b/`, no `@@` → not a real diff. Prior version
        # accepted this and fed prose to git apply.
        text = "I think we should edit --- a/foo.py for clarity."
        assert extract_unified_diff(text) is None

    def test_diff_requires_at_at(self):
        from maverick.coding_mode import extract_unified_diff
        # Header-only without @@ hunk → not a diff.
        text = "--- a/foo.py\n+++ b/foo.py\n"
        assert extract_unified_diff(text) is None

    def test_valid_minimal_diff_passes(self):
        from maverick.coding_mode import extract_unified_diff
        text = (
            "--- a/foo.py\n+++ b/foo.py\n"
            "@@ -1 +1 @@\n-old\n+new\n"
        )
        assert "+++ b/foo.py" in (extract_unified_diff(text) or "")

    def test_strips_markdown_fences(self):
        from maverick.coding_mode import extract_unified_diff
        text = (
            "Here's the patch:\n"
            "```diff\n"
            "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-old\n+new\n"
            "```\n"
        )
        out = extract_unified_diff(text)
        assert out is not None
        assert "```" not in out

    def test_multi_file_diff_kept_together(self):
        from maverick.coding_mode import extract_unified_diff
        text = (
            "--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-1\n+2\n"
            "--- a/y.py\n+++ b/y.py\n@@ -1 +1 @@\n-3\n+4\n"
        )
        out = extract_unified_diff(text)
        assert "x.py" in out
        assert "y.py" in out


# ---- polyglot runner detection + dispatch ----

class TestPolyglotRunner:
    def test_detect_pytest(self, tmp_path):
        from maverick.coding_mode import detect_test_runner
        (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
        assert detect_test_runner(tmp_path) == "pytest"

    def test_detect_jest(self, tmp_path):
        from maverick.coding_mode import detect_test_runner
        (tmp_path / "package.json").write_text('{"scripts": {"test": "jest"}}')
        assert detect_test_runner(tmp_path) == "jest"

    def test_detect_vitest(self, tmp_path):
        from maverick.coding_mode import detect_test_runner
        (tmp_path / "package.json").write_text('{"scripts": {"test": "vitest run"}}')
        assert detect_test_runner(tmp_path) == "vitest"

    def test_detect_cargo(self, tmp_path):
        from maverick.coding_mode import detect_test_runner
        (tmp_path / "Cargo.toml").write_text("[package]\nname='x'\n")
        assert detect_test_runner(tmp_path) == "cargo"

    def test_detect_gotest(self, tmp_path):
        from maverick.coding_mode import detect_test_runner
        (tmp_path / "go.mod").write_text("module x\n")
        assert detect_test_runner(tmp_path) == "gotest"

    def test_detect_unsupported(self, tmp_path):
        from maverick.coding_mode import detect_test_runner
        assert detect_test_runner(tmp_path) == "unsupported"

    def test_run_failing_tests_skips_unsupported(self, tmp_path):
        from maverick.coding_mode import run_failing_tests

        class _Sandbox:
            workdir = tmp_path

            def exec(self, cmd):  # pragma: no cover -- not called
                raise AssertionError("sandbox.exec called on unsupported runner")

        r = run_failing_tests(
            tmp_path, ["t::x"], ["t::y"], _Sandbox(),
        )
        assert r.skipped is True
        assert r.runner == "unsupported"


# ---- pytest summary regex: anchored ----

class TestPytestSummaryAnchored:
    def test_summary_at_end_wins(self):
        from maverick.coding_mode import _parse_pytest
        # Test prints "3 passed" in its own stdout, then summary at end.
        out = (
            "stdout: my test says '3 passed' which is great\n"
            "============== 1 failed, 2 passed in 0.5s ==============\n"
        )
        p, f, ok = _parse_pytest(out)
        assert ok is True
        assert p == 2
        assert f == 1

    def test_all_passed_summary(self):
        from maverick.coding_mode import _parse_pytest
        out = "============= 5 passed in 0.2s =============\n"
        p, f, ok = _parse_pytest(out)
        assert ok is True
        assert p == 5
        assert f == 0

    def test_errors_count_with_failures(self):
        from maverick.coding_mode import _parse_pytest
        out = "===== 1 failed, 1 errors, 3 passed in 0.5s =====\n"
        p, f, ok = _parse_pytest(out)
        assert ok is True
        assert p == 3
        assert f == 2  # failed + errored


# ---- Parser dispatch for non-pytest runners ----

class TestNonPytestParsers:
    def test_jest_summary(self):
        from maverick.coding_mode import _parse_jest
        out = "Tests:       1 failed, 4 passed, 5 total\n"
        p, f, ok = _parse_jest(out)
        assert ok is True
        assert p == 4
        assert f == 1

    def test_cargo_summary(self):
        from maverick.coding_mode import _parse_cargo
        out = "test result: FAILED. 3 passed; 2 failed; 0 ignored;\n"
        p, f, ok = _parse_cargo(out)
        assert ok is True
        assert p == 3
        assert f == 2

    def test_gotest_pass_fail_lines(self):
        from maverick.coding_mode import _parse_gotest
        out = "--- PASS: TestOne\n--- FAIL: TestTwo\n--- PASS: TestThree\n"
        p, f, ok = _parse_gotest(out)
        assert ok is True
        assert p == 2
        assert f == 1

    def test_maven_tests_run(self):
        from maverick.coding_mode import _parse_maven
        out = "Tests run: 10, Failures: 2, Errors: 1, Skipped: 0\n"
        p, f, ok = _parse_maven(out)
        assert ok is True
        assert p == 7
        assert f == 3


class TestCommandBuilding:
    def test_gotest_quotes_manifest_package_paths(self):
        from maverick.coding_mode import _cmd_for
        cmd = _cmd_for(
            "gotest",
            ["./...; touch /tmp/pwned #::TestFoo"],
        )
        assert isinstance(cmd, str)
        assert cmd.endswith("'./...; touch /tmp/pwned #'")


# ---- repo_map cache + token cap ----

class TestRepoMapCache:
    def test_cached_on_second_call(self, tmp_path, monkeypatch):
        from maverick.tools.repo_map import _CACHE, repo_map
        _CACHE.clear()
        (tmp_path / "x.py").write_text("")

        class _Sandbox:
            workdir = tmp_path

        tool = repo_map(_Sandbox())
        out1 = tool.fn({})
        out2 = tool.fn({})
        assert "cached" in out2.lower()
        assert out1 in out2

    def test_huge_repo_capped(self, tmp_path):
        from maverick.tools.repo_map import _CACHE, repo_map
        _CACHE.clear()
        # Create many top-level entries.
        for i in range(200):
            (tmp_path / f"file_{i:04d}_with_a_long_name.py").write_text("")

        class _Sandbox:
            workdir = tmp_path

        out = repo_map(_Sandbox()).fn({})
        assert len(out) <= 8200  # cap is 8000 + truncation footer


# ---- WorldModel.close() ----

class TestWorldModelClose:
    def test_close_closes_connection(self, tmp_path):
        from maverick.world_model import WorldModel
        wm = WorldModel(tmp_path / "w.db")
        wm.close()
        # After close, queries raise sqlite3.ProgrammingError.
        import sqlite3
        with pytest.raises(sqlite3.ProgrammingError):
            wm.conn.execute("SELECT 1")

    def test_context_manager_closes(self, tmp_path):
        from maverick.world_model import WorldModel
        with WorldModel(tmp_path / "w.db") as wm:
            wm.create_goal("x", "")
        import sqlite3
        with pytest.raises(sqlite3.ProgrammingError):
            wm.conn.execute("SELECT 1")
