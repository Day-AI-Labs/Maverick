"""dashboard main() routes uvicorn logs through the JSON root handler in JSON
mode (audit M4): uvicorn's own plaintext access/error formatters otherwise made
a mixed JSON+text stream that breaks strict log ingestion.
"""
from __future__ import annotations

import sys

import maverick_dashboard.app as appmod


def _run_main(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(sys, "argv", ["dashboard", "--host", "127.0.0.1", "--port", "0"])
    monkeypatch.setattr("maverick.logging_config.configure_logging", lambda *a, **k: None)
    import uvicorn
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: captured.update(k))
    appmod.main()
    return captured


def test_json_mode_disables_uvicorn_log_config(monkeypatch):
    monkeypatch.setenv("MAVERICK_LOG_FORMAT", "json")
    captured = _run_main(monkeypatch)
    # None -> uvicorn does not install its plaintext formatters; access/error
    # loggers propagate to the JSON root handler.
    assert captured["log_config"] is None


def test_text_mode_keeps_uvicorn_default_log_config(monkeypatch):
    monkeypatch.setenv("MAVERICK_LOG_FORMAT", "text")
    captured = _run_main(monkeypatch)
    from uvicorn.config import LOGGING_CONFIG
    assert captured["log_config"] is LOGGING_CONFIG
