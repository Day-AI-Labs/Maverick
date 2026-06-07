"""Self-edit tool: propose-only, path-confined diffs (ROADMAP 2027 H2)."""
from __future__ import annotations

import maverick.tools.self_edit as se
from maverick.tools.self_edit import _apply_edit, self_edit


def _confine_to(monkeypatch, root):
    monkeypatch.setattr(se, "_allowed_roots", lambda: [root])


def test_apply_edit_unique_match():
    new, msg = _apply_edit("a b c", "b", "X")
    assert new == "a X c" and msg == "ok"


def test_apply_edit_rejects_ambiguous():
    new, msg = _apply_edit("x x x", "x", "y")
    assert new is None and "ambiguous" in msg


def test_apply_edit_rejects_absent():
    new, msg = _apply_edit("abc", "zzz", "y")
    assert new is None and "not present" in msg


def test_propose_does_not_write(tmp_path, monkeypatch):
    _confine_to(monkeypatch, tmp_path)
    f = tmp_path / "mod.py"
    f.write_text("value = 1\n", encoding="utf-8")
    out = self_edit().fn({"op": "propose", "path": str(f),
                          "find": "value = 1", "replace": "value = 2"})
    assert "PROPOSED" in out and "+value = 2" in out
    assert f.read_text(encoding="utf-8") == "value = 1\n"  # unchanged


def test_self_edit_not_registered_by_default():
    from maverick.tools import base_registry

    class _World:
        pass

    class _Sandbox:
        pass

    reg = base_registry(_World(), _Sandbox())
    assert "self_edit" not in {tool.name for tool in reg.all()}


def test_apply_dry_run_without_confirm(tmp_path, monkeypatch):
    _confine_to(monkeypatch, tmp_path)
    f = tmp_path / "mod.py"
    f.write_text("value = 1\n", encoding="utf-8")
    out = self_edit().fn({"op": "apply", "path": str(f),
                          "find": "value = 1", "replace": "value = 2"})
    assert "DRY RUN" in out
    assert f.read_text(encoding="utf-8") == "value = 1\n"  # still unchanged


def test_apply_with_confirm_still_does_not_write(tmp_path, monkeypatch):
    _confine_to(monkeypatch, tmp_path)
    f = tmp_path / "mod.py"
    f.write_text("value = 1\n", encoding="utf-8")
    out = self_edit().fn({"op": "apply", "path": str(f), "find": "value = 1",
                          "replace": "value = 2", "confirm": True})
    assert "DRY RUN" in out and "cannot write files" in out
    assert f.read_text(encoding="utf-8") == "value = 1\n"


def test_stringy_confirm_fails_closed(tmp_path, monkeypatch):
    _confine_to(monkeypatch, tmp_path)
    f = tmp_path / "mod.py"
    f.write_text("value = 1\n", encoding="utf-8")
    out = self_edit().fn({"op": "apply", "path": str(f), "find": "value = 1",
                          "replace": "value = 2", "confirm": "true"})
    assert "DRY RUN" in out  # stringy 'true' must not authorise a write
    assert f.read_text(encoding="utf-8") == "value = 1\n"


def test_path_outside_confinement_rejected(tmp_path, monkeypatch):
    _confine_to(monkeypatch, tmp_path / "allowed")
    (tmp_path / "allowed").mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("data", encoding="utf-8")
    out = self_edit().fn({"op": "apply", "path": str(outside), "find": "data",
                          "replace": "x", "confirm": True})
    assert out.startswith("ERROR") and "path-confined" in out
    assert outside.read_text(encoding="utf-8") == "data"
