"""`session clear <alias>` must find what `session import <alias>` stored.

`session import chatgpt` saves under the canonical name 'chatgpt-session',
but `session clear` passed its argument through verbatim, so `clear chatgpt`
reported "No session stored for chatgpt" right after a successful import.
clear now canonicalizes the known short aliases too.
"""
from __future__ import annotations

from click.testing import CliRunner


def test_clear_accepts_the_short_alias_used_for_import(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    from maverick.cli import main
    r = CliRunner()

    imp = r.invoke(main, ["session", "import", "chatgpt", "--token", "abc123"])
    assert imp.exit_code == 0, imp.output
    assert "chatgpt-session" in imp.output

    # The user clears with the same short name they imported with.
    clr = r.invoke(main, ["session", "clear", "chatgpt"])
    assert clr.exit_code == 0, clr.output
    assert "Cleared session for chatgpt-session" in clr.output


def test_clear_still_accepts_the_canonical_name(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    from maverick.cli import main
    r = CliRunner()
    r.invoke(main, ["session", "import", "chatgpt", "--token", "abc123"])
    clr = r.invoke(main, ["session", "clear", "chatgpt-session"])
    assert clr.exit_code == 0, clr.output
    assert "Cleared session for chatgpt-session" in clr.output


def test_clear_unknown_name_still_reports_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    from maverick.cli import main
    clr = CliRunner().invoke(main, ["session", "clear", "nope-not-stored"])
    assert clr.exit_code == 1
    assert "No session stored for nope-not-stored" in clr.output
