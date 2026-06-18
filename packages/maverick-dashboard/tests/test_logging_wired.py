"""The dashboard must apply Maverick's shared logging config on startup (JSON
option + correlation-id filter + secret scrubbing), not inherit raw uvicorn
logging — it's the most network-exposed process."""
from __future__ import annotations

import logging
import sys

from fastapi.testclient import TestClient


def test_lifespan_configures_logging(monkeypatch):
    import maverick.logging_config as lc
    from maverick_dashboard.app import app

    saved_handlers = logging.getLogger().handlers[:]
    saved_configured = lc._configured
    lc._configured = False
    try:
        with TestClient(app):  # entering the context runs lifespan startup
            assert lc._configured is True  # configure_logging() ran
    finally:
        lc._configured = saved_configured
        logging.getLogger().handlers[:] = saved_handlers


def test_shared_logging_targets_stderr_not_stdout(monkeypatch):
    # MCP runs over stdio: a log handler on stdout would corrupt the protocol.
    import maverick.logging_config as lc

    saved_handlers = logging.getLogger().handlers[:]
    saved_configured = lc._configured
    lc._configured = False
    try:
        lc.configure_logging()
        streams = [getattr(h, "stream", None) for h in logging.getLogger().handlers]
        assert sys.stdout not in streams
        assert sys.stderr in streams
    finally:
        lc._configured = saved_configured
        logging.getLogger().handlers[:] = saved_handlers
