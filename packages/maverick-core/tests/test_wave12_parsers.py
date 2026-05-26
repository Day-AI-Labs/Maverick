"""Wave 12: test-runner parser fixes.

Covers council findings F7a-F7e:
  - F7a: pytest re.search → last-match
  - F7b: jest doesn't strip ANSI
  - F7c: vitest summary differs from jest (pipe-separated)
  - F7d: gotest subtests are indented
  - F7e: gotest build failures not detected
"""
from __future__ import annotations

from maverick.coding_mode import (
    _parse_cargo,
    _parse_gotest,
    _parse_jest,
    _parse_pytest,
    _parse_vitest,
    _strip_ansi,
)


class TestAnsiStripper:
    def test_strips_color_codes(self):
        s = "\x1b[31mFAIL\x1b[0m \x1b[1;32mPASS\x1b[0m"
        assert _strip_ansi(s) == "FAIL PASS"

    def test_passes_empty(self):
        assert _strip_ansi("") == ""
        assert _strip_ansi(None) == ""


class TestPytestLastMatch:
    def test_picks_last_summary_when_pytest_re_invoked(self):
        # tox or makefile may run pytest twice in one shell call.
        out = (
            "============== 5 passed in 0.5s ==============\n"
            "stuff in between\n"
            "============== 1 failed, 3 passed in 0.3s ==============\n"
        )
        p, f, ok = _parse_pytest(out)
        assert ok
        assert p == 3
        assert f == 1


class TestJestParser:
    def test_strips_ansi_before_match(self):
        out = "\x1b[1mTests:\x1b[0m       1 failed, 4 passed, 5 total\n"
        p, f, ok = _parse_jest(out)
        assert ok and p == 4 and f == 1

    def test_handles_todo_count(self):
        out = "Tests:       1 failed, 2 todo, 4 passed, 7 total\n"
        p, f, ok = _parse_jest(out)
        assert ok and p == 4 and f == 1

    def test_beforeall_failure_without_summary(self):
        out = (
            "FAIL  src/x.test.js\n"
            "  ● Test suite failed to run\n"
            "    beforeAll hook threw an error\n"
        )
        p, f, ok = _parse_jest(out)
        assert ok
        assert f >= 1

    def test_last_match_wins(self):
        # Some reporters emit per-file Tests: lines before the summary.
        out = (
            "Tests:       0 failed, 1 passed, 1 total\n"
            "Tests:       2 failed, 3 passed, 5 total\n"
        )
        p, f, ok = _parse_jest(out)
        assert ok and p == 3 and f == 2


class TestVitestParser:
    def test_pipe_separated_summary(self):
        out = "Tests  3 failed | 5 passed (8)\n"
        p, f, ok = _parse_vitest(out)
        assert ok and p == 5 and f == 3

    def test_all_passed_simple_form(self):
        out = "Tests  5 passed (5)\n"
        p, f, ok = _parse_vitest(out)
        assert ok and p == 5 and f == 0

    def test_strips_ansi(self):
        out = "\x1b[32mTests\x1b[0m  \x1b[31m2 failed\x1b[0m | 8 passed (10)\n"
        p, f, ok = _parse_vitest(out)
        assert ok and p == 8 and f == 2

    def test_falls_back_to_jest_format(self):
        # Some monorepos route vitest through jest-style reporters.
        out = "Tests:       1 failed, 4 passed, 5 total\n"
        p, f, ok = _parse_vitest(out)
        assert ok and p == 4 and f == 1


class TestGotestParser:
    def test_indented_subtests_counted(self):
        # Subtests appear with leading whitespace under their parent.
        out = (
            "--- PASS: TestOne (0.01s)\n"
            "    --- PASS: TestOne/case_a (0.01s)\n"
            "    --- PASS: TestOne/case_b (0.01s)\n"
            "--- FAIL: TestTwo (0.02s)\n"
            "    --- FAIL: TestTwo/case_x (0.01s)\n"
        )
        p, f, ok = _parse_gotest(out)
        assert ok
        # 1 parent PASS + 2 subtest PASS = 3; 1 parent FAIL + 1 subtest FAIL = 2.
        assert p == 3
        assert f == 2

    def test_build_failure_treated_as_failure(self):
        # Compile error -> all tests for that package are skipped by go;
        # without this fix, parser would return (0, 0) ok and the
        # candidate would be scored as inconclusive.
        out = (
            "# example.com/foo\n"
            "./foo.go:10:5: undefined: bar\n"
            "FAIL    example.com/foo [build failed]\n"
        )
        p, f, ok = _parse_gotest(out)
        assert ok
        assert f >= 1

    def test_cannot_find_package(self):
        out = (
            "foo.go:1:8: cannot find package \"example.com/missing\""
            " in any of: ...\n"
        )
        p, f, ok = _parse_gotest(out)
        assert ok
        assert f >= 1


class TestCargoLastMatch:
    def test_last_crate_summary_wins(self):
        # cargo test on a workspace emits one summary per crate.
        out = (
            "test result: ok. 4 passed; 0 failed; 0 ignored;\n"
            "test result: FAILED. 3 passed; 2 failed; 0 ignored;\n"
        )
        p, f, ok = _parse_cargo(out)
        assert ok
        assert p == 3
        assert f == 2
