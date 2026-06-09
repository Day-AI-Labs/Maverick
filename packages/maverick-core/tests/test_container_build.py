"""container_build: sandbox-mediated docker build with validated argv."""
from __future__ import annotations

from maverick.tools.container_build import container_build


class _Res:
    def __init__(self, code=0, out="Successfully built abc123", err=""):
        self.exit_code, self.stdout, self.stderr = code, out, err


class _FakeSandbox:
    """Records the shell command sandbox_run hands to exec()."""

    def __init__(self, res=None):
        self.cmd = None
        self._res = res or _Res()

    def exec(self, cmd, timeout=None):
        self.cmd = cmd
        return self._res


def _ctx(tmp_path):
    (tmp_path / "Dockerfile").write_text("FROM scratch\n")
    return str(tmp_path)


def test_build_issues_validated_docker_command(tmp_path):
    sb = _FakeSandbox()
    out = container_build(sb).fn({
        "op": "build", "context": _ctx(tmp_path), "tag": "myapp:dev",
        "build_args": {"VERSION": "1.2"},
    })
    assert "docker build" in sb.cmd
    assert "-t myapp:dev" in sb.cmd
    assert "--build-arg VERSION=1.2" in sb.cmd
    assert "docker build ok for myapp:dev" in out


def test_build_reports_failure(tmp_path):
    sb = _FakeSandbox(_Res(code=1, out="step 2/3", err="boom"))
    out = container_build(sb).fn({"op": "build", "context": _ctx(tmp_path), "tag": "x:y"})
    assert "FAILED (exit 1)" in out and "boom" in out


def test_validation_rejects_bad_tag_and_missing_context(tmp_path):
    sb = _FakeSandbox()
    assert container_build(sb).fn({"op": "build", "context": _ctx(tmp_path), "tag": "Bad Tag!"}).startswith("ERROR")
    assert container_build(sb).fn({"op": "build", "context": "/no/such/dir", "tag": "x"}).startswith("ERROR")
    # bad build-arg key
    bad = container_build(sb).fn({"op": "build", "context": _ctx(tmp_path), "tag": "x",
                                  "build_args": {"bad key": "v"}})
    assert bad.startswith("ERROR")


def test_missing_dockerfile(tmp_path):
    sb = _FakeSandbox()
    out = container_build(sb).fn({"op": "build", "context": str(tmp_path), "tag": "x"})
    assert "Dockerfile not found" in out


def test_registered():
    from maverick.tools import base_registry

    class _W:
        pass

    names = set(getattr(base_registry(world=_W(), sandbox=_FakeSandbox()), "_tools", {}).keys())
    assert "container_build" in names
