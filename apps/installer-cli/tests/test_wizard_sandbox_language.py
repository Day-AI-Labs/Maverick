"""pick_sandbox() lets container users pick a coding language.

0.1.4 added per-language sandbox images (sandbox._IMAGE_BY_LANGUAGE: rust ->
rust:1, go -> golang:1, ...) but nothing in the wizard let a non-Python user
reach it -- they'd land on python:3.12-slim with no cargo/go toolchain. The
wizard now asks, for container backends only, and writes [sandbox] language.

Python is the default image, so picking it (or a non-container backend) leaves
the config byte-identical to before.
"""
from __future__ import annotations

import pytest


def _answers(monkeypatch, backend_choice: str, language_choice: str | None):
    """Stub the interactive prompts: first _q_select is the backend, the
    second (if reached) is the language. _q_text is the workspace dir."""
    from maverick_installer import wizard

    picks = [backend_choice]
    if language_choice is not None:
        picks.append(language_choice)
    it = iter(picks)
    monkeypatch.setattr(wizard, "_q_select", lambda *a, **k: next(it))
    monkeypatch.setattr(wizard, "_q_text", lambda *a, **k: "/tmp/ws")
    return wizard


def test_container_backend_writes_chosen_language(monkeypatch):
    wizard = _answers(
        monkeypatch,
        "docker - Throwaway Docker container (recommended)",
        "rust       - rust:1",
    )
    cfg = wizard.pick_sandbox()
    assert cfg["backend"] == "docker"
    assert cfg["language"] == "rust"


def test_python_default_omits_language_key(monkeypatch):
    # Python is already the default image -- don't clutter the config, and keep
    # existing/Python installs producing the same [sandbox] section as before.
    wizard = _answers(
        monkeypatch,
        "docker - Throwaway Docker container (recommended)",
        "python     - python:3.12-slim (default)",
    )
    cfg = wizard.pick_sandbox()
    assert "language" not in cfg


def test_local_backend_skips_language_question(monkeypatch):
    # The language only changes a container image; local runs on the host, so
    # the question must not be asked (a second _q_select call would raise here).
    wizard = _answers(
        monkeypatch,
        "local  - Subprocess on this machine (fastest, least isolated)",
        None,
    )
    cfg = wizard.pick_sandbox()
    assert cfg["backend"] == "local"
    assert "language" not in cfg


def test_offered_languages_are_real_sandbox_keys(monkeypatch):
    # Contract: every language the wizard offers must resolve to a real image in
    # sandbox._IMAGE_BY_LANGUAGE, or the user picks a toolchain that silently
    # falls back to python:3.12-slim.
    sandbox = pytest.importorskip("maverick.sandbox")
    for key in ("python", "javascript", "go", "rust", "java", "ruby"):
        assert key in sandbox._IMAGE_BY_LANGUAGE
