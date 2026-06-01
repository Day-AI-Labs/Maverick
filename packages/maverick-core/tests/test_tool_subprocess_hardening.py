"""Tool subprocesses must run with secrets scrubbed and freeform media args
filtered.

Council (Security seat, findings #1-#3): ~10 tools shelled out directly with
the full os.environ (leaking provider keys to the child) and several appended
a model-controlled freeform args[] to argv (pandoc --lua-filter = code exec,
ffmpeg -i /etc/passwd = arbitrary file read). PR3 adds:
  - tools.scrub_child_env(): child env via sandbox.local.scrub_env (no secrets)
  - tools.safe_media_args(): drop dangerous flags from freeform args by
    default; MAVERICK_ALLOW_RAW_MEDIA_ARGS=1 opts back in.
"""
from __future__ import annotations

import pytest
from maverick.tools import safe_media_args, scrub_child_env


def test_scrub_child_env_strips_secrets(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
    monkeypatch.setenv("STRIPE_API_KEY", "sk_live_x")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_x")
    monkeypatch.setenv("PATH", "/usr/bin")
    env = scrub_child_env()
    assert "ANTHROPIC_API_KEY" not in env
    assert "STRIPE_API_KEY" not in env
    assert "GITHUB_TOKEN" not in env
    assert "PATH" in env  # benign infra var preserved


@pytest.mark.parametrize("bad", [
    "--lua-filter=/tmp/evil.lua",
    "--template=/tmp/t.html",
    "--pdf-engine=weasyprint",
    "concat:/etc/passwd|/etc/shadow",
    "--metadata-file=/tmp/m.yaml",
    "--include-in-header=/tmp/h",
    "--resource-path=/etc",
    "--extract-media=/tmp",
])
def test_safe_media_args_drops_selfcontained_dangerous_flags(bad, monkeypatch):
    monkeypatch.delenv("MAVERICK_ALLOW_RAW_MEDIA_ARGS", raising=False)
    out = safe_media_args(["-quality", "90", bad])
    assert bad not in out
    assert "-quality" in out and "90" in out  # benign survive


@pytest.mark.parametrize("flag,value", [
    ("-i", "/etc/passwd"),
    ("--input", "/etc/shadow"),
    ("--lua-filter", "/tmp/evil.lua"),
    ("-filter_complex", "movie=/etc/passwd"),
    ("--template", "/tmp/t.html"),
])
def test_safe_media_args_drops_flag_AND_its_value(flag, value, monkeypatch):
    """A bare dangerous flag takes the next token as its value -- both must go,
    or the path it points at is still smuggled onto argv."""
    monkeypatch.delenv("MAVERICK_ALLOW_RAW_MEDIA_ARGS", raising=False)
    out = safe_media_args(["-strip", flag, value, "-quality", "80"])
    assert flag not in out
    assert value not in out
    assert "-strip" in out and "-quality" in out and "80" in out


def test_safe_media_args_passthrough_when_opted_in(monkeypatch):
    monkeypatch.setenv("MAVERICK_ALLOW_RAW_MEDIA_ARGS", "1")
    raw = ["-i", "/etc/passwd", "--lua-filter=x.lua"]
    assert safe_media_args(raw) == raw


def test_safe_media_args_handles_none_and_empty():
    assert safe_media_args(None) == []
    assert safe_media_args([]) == []


def test_benign_resize_args_survive(monkeypatch):
    monkeypatch.delenv("MAVERICK_ALLOW_RAW_MEDIA_ARGS", raising=False)
    # A normal imagemagick operator chain must pass through untouched.
    out = safe_media_args(["-resize", "50%", "-rotate", "90", "-strip"])
    assert out == ["-resize", "50%", "-rotate", "90", "-strip"]


def test_subprocess_tools_import_scrub_helper():
    """Every shell-out tool must keep the child env scrubbed of secrets.

    Two acceptable ways now: (a) route through the sandbox chokepoint via
    ``sandbox_run`` (which scrubs the env / mediates exec), or (b) for tools
    that still shell out directly, reference the scrub helper. No tool may
    reintroduce raw ``os.environ`` inheritance."""
    import pathlib

    import maverick.tools as T
    tdir = pathlib.Path(T.__file__).parent
    for name in ["git_advanced", "preview_diff", "apply_patch", "ffmpeg_tool",
                 "imagemagick_tool", "pandoc_tool", "ocr", "a11y", "android", "ios_sim"]:
        src = (tdir / f"{name}.py").read_text()
        assert (
            "sandbox_run" in src
            or "scrub_child_env" in src
            or "scrub_env" in src
            or "sandbox.exec" in src
        ), f"{name} no longer scrubs the child env nor routes through the sandbox"


class _RecordingSandbox:
    """Minimal sandbox stub: records exec() commands, returns a canned result."""

    def __init__(self, workdir, stdout="", exit_code=0):
        from pathlib import Path
        self.workdir = Path(workdir)
        self.commands: list[str] = []
        self._stdout = stdout
        self._exit = exit_code

    def exec(self, cmd, timeout=None):
        from maverick.sandbox.local import ExecResult
        self.commands.append(cmd)
        return ExecResult(stdout=self._stdout, stderr="", exit_code=self._exit)


def test_imagemagick_routes_command_through_sandbox_exec(tmp_path, monkeypatch):
    """With a sandbox wired in, the tool must drive sandbox.exec, not the host."""
    monkeypatch.setattr("shutil.which", lambda b: "/usr/bin/magick" if b == "magick" else None)

    def _boom(*a, **k):
        raise AssertionError("subprocess.run must not be called when a sandbox is wired in")

    monkeypatch.setattr("subprocess.run", _boom)
    from maverick.tools.imagemagick_tool import imagemagick_tool

    sb = _RecordingSandbox(tmp_path)
    out = imagemagick_tool(sb).fn({
        "op": "resize", "input_path": "a.png", "output_path": "b.png", "width": 800,
    })
    assert "wrote" in out
    assert len(sb.commands) == 1
    assert "magick" in sb.commands[0] and "-resize" in sb.commands[0]


def test_pandoc_string_op_feeds_stdin_through_sandbox(tmp_path, monkeypatch):
    """markdown_to_html feeds text via the base64 stdin pipe, through the sandbox."""
    monkeypatch.setattr("shutil.which", lambda b: "/usr/bin/pandoc")
    monkeypatch.setattr("subprocess.run", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("must route through sandbox.exec")))
    from maverick.tools.pandoc_tool import pandoc_tool

    sb = _RecordingSandbox(tmp_path, stdout="<p>Hello</p>\n")
    out = pandoc_tool(sb).fn({"op": "markdown_to_html", "text": "Hello"})
    assert "<p>Hello</p>" in out
    assert sb.commands and "base64 -d" in sb.commands[0] and "pandoc" in sb.commands[0]


def test_media_tools_route_through_sandbox_chokepoint():
    """The sandboxable media tools must mediate shell via ``sandbox_run``,
    not call subprocess directly (CLAUDE.md rule #4). The host-local tools
    (clipboard/android/ios_sim) are intentionally excluded — they drive
    host-only resources and cannot run inside the sandbox."""
    import pathlib

    import maverick.tools as T
    tdir = pathlib.Path(T.__file__).parent
    for name in ["ffmpeg_tool", "imagemagick_tool", "pandoc_tool", "ocr", "a11y"]:
        src = (tdir / f"{name}.py").read_text()
        assert "sandbox_run" in src, f"{name} must route shell through sandbox_run"
        # No leftover direct host subprocess invocation.
        assert "subprocess.run(" not in src, (
            f"{name} still calls subprocess.run directly; route via sandbox_run"
        )
