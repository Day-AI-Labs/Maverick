"""WASM sandbox tool: wasmtime invocation shape + WASI capability grants."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from maverick.tools.wasm_run import wasm_run


class RecordingSandbox:
    def __init__(self, workdir, *, exit_code=0, stdout="", stderr=""):
        self.workdir = str(workdir)
        self._res = SimpleNamespace(exit_code=exit_code, stdout=stdout,
                                    stderr=stderr)
        self.commands: list[str] = []

    def exec(self, cmd, timeout=None):
        self.commands.append(cmd)
        return self._res


@pytest.fixture
def have_wasmtime(monkeypatch):
    monkeypatch.setattr("maverick.tools.wasm_run.shutil.which",
                        lambda n: "/usr/bin/wasmtime" if n == "wasmtime" else None)


def test_missing_wasmtime(monkeypatch):
    monkeypatch.setattr("maverick.tools.wasm_run.shutil.which", lambda n: None)
    out = wasm_run().fn({"op": "run", "module": "m.wasm"})
    assert out.startswith("ERROR") and "wasmtime not on PATH" in out


def test_run_builds_command_with_grants(tmp_path, have_wasmtime):
    (tmp_path / "data").mkdir()
    sb = RecordingSandbox(tmp_path, stdout="42\n")
    out = wasm_run(sandbox=sb).fn({
        "op": "run", "module": "calc.wasm", "args": ["6", "7"],
        "dirs": ["data"], "env": {"MODE": "fast"},
    })
    cmd = sb.commands[0]
    assert cmd.startswith("wasmtime run")
    assert "--dir" in cmd and "/data" in cmd
    assert "--env MODE=fast" in cmd
    assert "calc.wasm -- 6 7" in cmd
    assert out.strip() == "42"


def test_module_path_confined(tmp_path, have_wasmtime):
    sb = RecordingSandbox(tmp_path)
    out = wasm_run(sandbox=sb).fn({"op": "run", "module": "../../etc/evil.wasm"})
    assert out.startswith("ERROR") and "escapes the sandbox workdir" in out
    assert sb.commands == []


def test_dash_module_rejected_without_sandbox(have_wasmtime):
    out = wasm_run().fn({"op": "run", "module": "--invoke"})
    assert out.startswith("ERROR") and "may not begin with '-'" in out


def test_invalid_env_key_rejected(tmp_path, have_wasmtime):
    sb = RecordingSandbox(tmp_path)
    out = wasm_run(sandbox=sb).fn({"op": "run", "module": "m.wasm",
                                   "env": {"BAD-KEY": "x"}})
    assert out.startswith("ERROR") and "invalid env key" in out
    assert sb.commands == []


def test_nonzero_exit_surfaces_stderr(tmp_path, have_wasmtime):
    sb = RecordingSandbox(tmp_path, exit_code=134,
                          stderr="wasm trap: out of bounds")
    out = wasm_run(sandbox=sb).fn({"op": "run", "module": "m.wasm"})
    assert out.startswith("ERROR: wasmtime (134)") and "wasm trap" in out


def test_requires_module(have_wasmtime):
    assert "requires module" in wasm_run().fn({"op": "run"})


def test_version(tmp_path, have_wasmtime):
    sb = RecordingSandbox(tmp_path, stdout="wasmtime 24.0.0\n")
    assert wasm_run(sandbox=sb).fn({"op": "version"}) == "wasmtime 24.0.0"


def test_unknown_op():
    assert wasm_run().fn({"op": "explode"}).startswith("ERROR: unknown op")


def test_registered():
    from maverick.tools import base_registry

    class _W:
        pass

    class _S:
        workdir = "."

    names = set(getattr(base_registry(world=_W(), sandbox=_S()), "_tools", {}).keys())
    assert "wasm_run" in names
