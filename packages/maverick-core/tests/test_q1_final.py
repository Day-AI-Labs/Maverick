"""Final Q1 2026 batch: openai prompt-caching wiring, dep_graph, ast_edit, index audit, wizard --resume."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


# ---------- openai_provider prompt-caching extraction ----------

def test_openai_provider_records_cache_read_tokens():
    """When usage.prompt_tokens_details.cached_tokens is present, it
    flows into budget as cache_read_tok and billable input = full - cached.
    """
    try:
        from openai import OpenAI  # noqa: F401
    except ImportError:
        pytest.skip("openai SDK not installed")
    from maverick.budget import Budget
    from maverick.providers.openai_provider import OpenAIClient

    # Build a fake response shape matching the SDK's pydantic model.
    fake_choice = MagicMock()
    fake_choice.message.content = "hi"
    fake_choice.message.tool_calls = None
    fake_choice.finish_reason = "stop"

    fake_usage = MagicMock()
    fake_usage.prompt_tokens = 1000
    fake_usage.completion_tokens = 50
    # OpenAI-style cached tokens.
    fake_usage.prompt_tokens_details.cached_tokens = 400
    # Make sure the DeepSeek-shaped attr isn't preferred when OpenAI's is set.
    fake_usage.prompt_cache_hit_tokens = 999

    fake_resp = MagicMock()
    fake_resp.choices = [fake_choice]
    fake_resp.usage = fake_usage

    budget = Budget(max_dollars=10.0)
    OpenAIClient._from_response(fake_resp, budget, model="gpt-5.4")

    # full=1000, cached=400 -> billable=600 to input_tokens; cached -> cache_read_tokens.
    assert budget.input_tokens == 600
    assert budget.cache_read_tokens == 400
    assert budget.output_tokens == 50


def test_openai_provider_records_deepseek_cache_hit_tokens():
    """DeepSeek puts cached count under prompt_cache_hit_tokens."""
    try:
        from openai import OpenAI  # noqa: F401
    except ImportError:
        pytest.skip("openai SDK not installed")
    from maverick.budget import Budget
    from maverick.providers.openai_provider import OpenAIClient

    fake_choice = MagicMock()
    fake_choice.message.content = "hi"
    fake_choice.message.tool_calls = None
    fake_choice.finish_reason = "stop"

    fake_usage = MagicMock()
    fake_usage.prompt_tokens = 2000
    fake_usage.completion_tokens = 100
    # DeepSeek shape: OpenAI-style details absent, fall through to *_hit_tokens.
    fake_usage.prompt_tokens_details = None
    fake_usage.prompt_cache_hit_tokens = 800

    fake_resp = MagicMock()
    fake_resp.choices = [fake_choice]
    fake_resp.usage = fake_usage

    budget = Budget(max_dollars=10.0)
    OpenAIClient._from_response(fake_resp, budget, model="deepseek-chat")

    assert budget.input_tokens == 1200
    assert budget.cache_read_tokens == 800
    assert budget.output_tokens == 100


def test_openai_provider_no_cache_data_records_full_input():
    """When no cache fields, full prompt_tokens count as billable."""
    try:
        from openai import OpenAI  # noqa: F401
    except ImportError:
        pytest.skip("openai SDK not installed")
    from maverick.budget import Budget
    from maverick.providers.openai_provider import OpenAIClient

    fake_choice = MagicMock()
    fake_choice.message.content = "hi"
    fake_choice.message.tool_calls = None
    fake_choice.finish_reason = "stop"

    fake_usage = MagicMock()
    fake_usage.prompt_tokens = 500
    fake_usage.completion_tokens = 50
    fake_usage.prompt_tokens_details = None
    # Explicitly delete the DeepSeek attr so getattr returns the default.
    del fake_usage.prompt_cache_hit_tokens

    fake_resp = MagicMock()
    fake_resp.choices = [fake_choice]
    fake_resp.usage = fake_usage

    budget = Budget(max_dollars=10.0)
    OpenAIClient._from_response(fake_resp, budget, model="gpt-5.4")

    assert budget.input_tokens == 500
    assert budget.cache_read_tokens == 0
    assert budget.output_tokens == 50


# ---------- dep_graph tool ----------

@pytest.fixture
def small_repo(tmp_path):
    """A tiny three-file Python repo for the dep_graph tool to chew on."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "a.py").write_text(
        "from pkg.b import helper\n\n"
        "def alpha():\n"
        "    return helper()\n"
    )
    (tmp_path / "pkg" / "b.py").write_text(
        "import os\n\n"
        "def helper():\n"
        "    return os.getcwd()\n\n"
        "class B:\n"
        "    pass\n"
    )
    (tmp_path / "main.py").write_text(
        "from pkg.a import alpha\n\n"
        "def main():\n"
        "    alpha()\n"
    )
    return tmp_path


def test_dep_graph_summary(small_repo):
    from maverick.tools.dep_graph import dep_graph

    class _Sandbox:
        workdir = str(small_repo)

    tool = dep_graph(_Sandbox())
    out = tool.fn({"view": "summary"})
    # 3 files with code + pkg/__init__.py (empty) = 4.
    assert "python files: 4" in out
    assert "top-level symbols" in out
    assert "import statements" in out


def test_dep_graph_import_graph(small_repo):
    from maverick.tools.dep_graph import dep_graph

    class _Sandbox:
        workdir = str(small_repo)

    out = dep_graph(_Sandbox()).fn({"view": "import_graph"})
    # main.py imports from pkg.a, pkg/a.py imports from pkg.b, pkg/b.py imports os.
    assert "main.py" in out and "pkg.a::alpha" in out
    assert "pkg/a.py" in out and "pkg.b::helper" in out
    assert "pkg/b.py" in out and "os" in out


def test_dep_graph_callers(small_repo):
    from maverick.tools.dep_graph import dep_graph

    class _Sandbox:
        workdir = str(small_repo)

    out = dep_graph(_Sandbox()).fn({"view": "callers", "symbol": "helper"})
    # pkg/a.py calls helper().
    assert "pkg/a.py" in out


def test_dep_graph_unknown_view():
    from maverick.tools.dep_graph import dep_graph

    class _Sandbox:
        workdir = "."

    out = dep_graph(_Sandbox()).fn({"view": "garbage"})
    assert "ERROR" in out


# ---------- ast_edit tool ----------

@pytest.fixture
def ast_workdir(tmp_path):
    (tmp_path / "module.py").write_text(
        '"""A test module."""\n'
        "import os\n"
        "\n"
        "def alpha(x):\n"
        "    return x + 1\n"
        "\n"
        "class Beta:\n"
        "    def m(self):\n"
        "        return alpha(1)\n"
    )
    return tmp_path


def test_ast_edit_info(ast_workdir):
    from maverick.tools.ast_edit import ast_edit

    class _Sandbox:
        workdir = str(ast_workdir)

    out = ast_edit(_Sandbox()).fn({"op": "info", "path": "module.py"})
    assert "alpha" in out
    assert "Beta" in out
    assert "import os" in out


def test_ast_edit_rename_symbol(ast_workdir):
    from maverick.tools.ast_edit import ast_edit

    class _Sandbox:
        workdir = str(ast_workdir)

    out = ast_edit(_Sandbox()).fn({
        "op": "rename_symbol", "path": "module.py",
        "old_name": "alpha", "new_name": "renamed",
    })
    assert "wrote module.py" in out
    body = (ast_workdir / "module.py").read_text()
    assert "def renamed" in body
    assert "alpha" not in body
    # Class method's call to alpha() was renamed too (whole-word).
    assert "renamed(1)" in body


def test_ast_edit_rename_rejects_invalid_identifier(ast_workdir):
    from maverick.tools.ast_edit import ast_edit

    class _Sandbox:
        workdir = str(ast_workdir)

    out = ast_edit(_Sandbox()).fn({
        "op": "rename_symbol", "path": "module.py",
        "old_name": "alpha", "new_name": "not-an-identifier",
    })
    assert "ERROR" in out
    # File unchanged.
    assert "def alpha" in (ast_workdir / "module.py").read_text()


def test_ast_edit_add_import_idempotent(ast_workdir):
    from maverick.tools.ast_edit import ast_edit

    class _Sandbox:
        workdir = str(ast_workdir)

    tool = ast_edit(_Sandbox())
    out1 = tool.fn({"op": "add_import", "path": "module.py",
                    "import_line": "import sys"})
    assert "wrote" in out1
    body1 = (ast_workdir / "module.py").read_text()
    assert "import sys" in body1
    tool.fn({"op": "add_import", "path": "module.py",
             "import_line": "import sys"})
    body2 = (ast_workdir / "module.py").read_text()
    # Second add is a no-op (length unchanged).
    assert body1 == body2


def test_ast_edit_remove_symbol(ast_workdir):
    from maverick.tools.ast_edit import ast_edit

    class _Sandbox:
        workdir = str(ast_workdir)

    out = ast_edit(_Sandbox()).fn({
        "op": "remove_symbol", "path": "module.py", "symbol": "alpha",
    })
    assert "wrote" in out
    body = (ast_workdir / "module.py").read_text()
    assert "def alpha" not in body
    # Class still there.
    assert "class Beta" in body


def test_ast_edit_dry_run_does_not_write(ast_workdir):
    from maverick.tools.ast_edit import ast_edit

    class _Sandbox:
        workdir = str(ast_workdir)

    before = (ast_workdir / "module.py").read_text()
    out = ast_edit(_Sandbox()).fn({
        "op": "rename_symbol", "path": "module.py",
        "old_name": "alpha", "new_name": "renamed",
        "dry_run": True,
    })
    assert "DRY RUN" in out
    after = (ast_workdir / "module.py").read_text()
    assert before == after


def test_ast_edit_rejects_path_traversal(ast_workdir):
    from maverick.tools.ast_edit import ast_edit

    class _Sandbox:
        workdir = str(ast_workdir)

    out = ast_edit(_Sandbox()).fn({
        "op": "info", "path": "../escape.py",
    })
    assert "path traversal" in out.lower()


# ---------- world-model indexes ----------

def test_world_model_v8_indices_present(tmp_path):
    """A fresh world model should have all v8 indices."""
    from maverick.world_model import WorldModel
    wm = WorldModel(tmp_path / "wm.sqlite")
    try:
        names = [
            row["name"] for row in wm.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            )
        ]
    finally:
        wm.close()
    for expected in (
        "idx_episodes_goal_started",
        "idx_episodes_started",
        "idx_goals_status_updated",
        "idx_goals_parent",
    ):
        assert expected in names, f"missing index: {expected}"


def test_world_model_indexes_doc_exists():
    p = REPO_ROOT / "docs" / "performance" / "world-model-indexes.md"
    assert p.is_file()
    body = p.read_text()
    for expected in (
        "idx_episodes_goal_started",
        "idx_episodes_started",
        "idx_goals_status_updated",
        "idx_goals_parent",
    ):
        assert expected in body


# ---------- wizard --resume ----------

def test_wizard_resume_loads_partial_state(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from maverick_installer import wizard

    cfg_dir = tmp_path / ".maverick"
    cfg_dir.mkdir()
    wizard.CONFIG_DIR = cfg_dir
    wizard.PARTIAL_STATE_PATH = cfg_dir / "wizard-partial.json"

    # Pre-populate a partial state.
    pre = {
        "deployment": "desktop",
        "providers": ["anthropic"],
        "role_models": {},
        "channels": {},
        "channel_envs": [],
        "safety": {"profile": "balanced", "block_threshold": "high",
                   "scan_input": True, "scan_tool_calls": True, "scan_output": True},
        "budget": {"max_dollars": 5.0, "max_wall_seconds": 3600.0, "max_tool_calls": 500},
        "sandbox": {"backend": "local", "workdir": "/tmp/ws", "timeout": 60},
        "capabilities": {"computer_use": False, "browser": False},
    }
    wizard.PARTIAL_STATE_PATH.write_text(json.dumps(pre))

    loaded = wizard._load_partial()
    assert loaded == pre


def test_wizard_run_accepts_resume_flag():
    import inspect

    from maverick_installer.wizard import run
    sig = inspect.signature(run)
    assert "resume" in sig.parameters
    assert sig.parameters["resume"].default is False


def test_wizard_partial_state_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from maverick_installer import wizard

    cfg_dir = tmp_path / ".maverick"
    wizard.CONFIG_DIR = cfg_dir
    wizard.PARTIAL_STATE_PATH = cfg_dir / "wizard-partial.json"

    wizard._save_partial({"deployment": "docker", "providers": ["anthropic", "openai"]})
    loaded = wizard._load_partial()
    assert loaded == {"deployment": "docker", "providers": ["anthropic", "openai"]}
    wizard._clear_partial()
    assert wizard._load_partial() is None


# ---------- dep_graph + ast_edit registered ----------

def test_q1_final_tools_registered():
    from maverick.tools import base_registry

    class _FakeSandbox:
        workdir = "."

    class _FakeWorld:
        pass

    reg = base_registry(world=_FakeWorld(), sandbox=_FakeSandbox())
    names = {t.name for t in reg.all()}
    assert "dep_graph" in names
    assert "ast_edit" in names
