"""sonnet_tools SWE-bench baseline: the flat Sonnet+bash agent loop.

Hermetic by design: a fake ``anthropic`` module + a fake sandbox + monkeypatched
git helpers, so the loop wiring

    tool_use -> sandbox.exec -> tool_result -> loop -> git diff -> Row

is exercised with zero dependence on a live model, a real shell, or git in the
environment (the earlier real-git/real-subprocess version passed locally but is
exactly the kind of thing that varies across CI runners). The real git + shell
behaviour is covered by actual benchmark runs, not this unit test. swe_bench is
loaded by path, like the sibling baseline tests.
"""
import importlib.util
import sys
import types
from pathlib import Path


def _load_swe_bench():
    if "swe_bench" not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            "swe_bench", Path(__file__).resolve().parent / "swe_bench.py",
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules["swe_bench"] = module
        spec.loader.exec_module(module)
    return sys.modules["swe_bench"]


_sb = _load_swe_bench()
run_sonnet_tools = _sb.run_sonnet_tools


# ---- fake Anthropic returning content blocks (text + tool_use) ----

class _Usage:
    input_tokens = 10
    output_tokens = 5


class _TextBlock:
    type = "text"

    def __init__(self, text):
        self.text = text


class _ToolUseBlock:
    type = "tool_use"

    def __init__(self, id, name, tool_input):
        self.id = id
        self.name = name
        self.input = tool_input


class _Resp:
    def __init__(self, content):
        self.content = content
        self.usage = _Usage()


def _fake_anthropic(scripted_turns):
    """scripted_turns: list of content-lists, one per messages.create() call."""
    seq = list(scripted_turns)
    state = {"i": 0}

    class _Messages:
        def create(self, **kwargs):
            content = seq[min(state["i"], len(seq) - 1)]
            state["i"] += 1
            return _Resp(content)

    class _Anthropic:
        def __init__(self, *a, **k):
            self.messages = _Messages()

    mod = types.ModuleType("anthropic")
    mod.Anthropic = _Anthropic
    return mod


class _FakeSandbox:
    """Records the commands the loop runs; returns a canned ExecResult."""

    def __init__(self):
        self.workdir = "/tmp/maverick-fake-workdir"
        self.commands = []

    def exec(self, cmd, timeout=None):
        from maverick.sandbox.local import ExecResult
        self.commands.append(cmd)
        return ExecResult(stdout="(edited)", stderr="", exit_code=0)


def _wire(monkeypatch, scripted_turns, *, diff):
    """Mock every external boundary run_sonnet_tools touches."""
    sandbox = _FakeSandbox()
    monkeypatch.setattr("maverick.sandbox.build_sandbox", lambda: sandbox)
    monkeypatch.setattr(_sb, "_reset_workdir", lambda *a, **k: None)
    monkeypatch.setattr(_sb, "_git_diff", lambda _wd: diff)
    monkeypatch.setitem(sys.modules, "anthropic", _fake_anthropic(scripted_turns))
    return sandbox


def test_sonnet_tools_runs_loop_and_extracts_diff(monkeypatch):
    monkeypatch.delenv("MAVERICK_BENCH_DRY_RUN", raising=False)
    sandbox = _wire(
        monkeypatch,
        [
            # Turn 1: the model calls the bash tool.
            [_ToolUseBlock("tu_1", "bash", {"command": "sed -i 's/return 1/return 42/' bug.py"})],
            # Turn 2: no tool_use -> the loop ends.
            [_TextBlock("DONE")],
        ],
        diff="--- a/bug.py\n+++ b/bug.py\n@@ -1 +1 @@\n-    return 1\n+    return 42\n",
    )

    row = run_sonnet_tools("inst-tools", "make f return 42", base_commit="abc123")

    assert row.pipeline == "sonnet_tools"
    assert row.outcome == "success"
    assert row.outcome != "not-implemented"
    # The predicted patch is whatever `git diff` reported after the loop.
    assert "return 42" in row.predicted_patch
    # The bash tool_use was routed through the sandbox verbatim.
    assert sandbox.commands == ["sed -i 's/return 1/return 42/' bug.py"]
    # Two model calls were made (the tool turn + the final turn).
    assert row.tokens_in == 20
    assert row.tokens_out == 10


def test_sonnet_tools_no_edit_is_empty(monkeypatch):
    monkeypatch.delenv("MAVERICK_BENCH_DRY_RUN", raising=False)
    # Model answers immediately with no tool call -> no edits -> empty diff.
    _wire(monkeypatch, [[_TextBlock("DONE")]], diff="")

    row = run_sonnet_tools("inst-noop", "do nothing", base_commit="abc123")
    assert row.outcome == "empty"
    assert row.predicted_patch == ""


def test_sonnet_tools_dry_run(monkeypatch):
    monkeypatch.setenv("MAVERICK_BENCH_DRY_RUN", "1")
    row = run_sonnet_tools("inst-dry", "brief")
    # dry-run must not touch Anthropic and is no longer "not-implemented".
    assert row.outcome != "not-implemented"
    assert row.pipeline == "sonnet_tools"
