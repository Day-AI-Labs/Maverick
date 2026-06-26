"""Out-of-process dispatcher install at dashboard startup.

The queue (arq) dispatcher was installed at startup but the gRPC dispatcher --
which has a complete install_from_config() -- was never called, so
[grpc_dispatch] target was silently ignored. _install_queue_dispatcher now falls
back to gRPC when the queue backend isn't selected."""
from __future__ import annotations

import pytest
from maverick_dashboard import app as dash_app


@pytest.mark.asyncio
async def test_grpc_attempted_when_queue_not_installed(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "maverick.queue_dispatcher.install_from_config",
        lambda: calls.append("queue") or False,
    )
    monkeypatch.setattr(
        "maverick.grpc_dispatcher.install_from_config",
        lambda: calls.append("grpc") or True,
    )
    await dash_app._install_queue_dispatcher()
    assert calls == ["queue", "grpc"]   # queue tried first, then gRPC fallback


@pytest.mark.asyncio
async def test_grpc_skipped_when_queue_installs(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "maverick.queue_dispatcher.install_from_config",
        lambda: calls.append("queue") or True,
    )
    monkeypatch.setattr(
        "maverick.grpc_dispatcher.install_from_config",
        lambda: calls.append("grpc") or True,
    )
    await dash_app._install_queue_dispatcher()
    assert calls == ["queue"]           # queue took the slot; gRPC not attempted


@pytest.mark.asyncio
async def test_both_off_is_noop(monkeypatch):
    monkeypatch.setattr(
        "maverick.queue_dispatcher.install_from_config", lambda: False)
    monkeypatch.setattr(
        "maverick.grpc_dispatcher.install_from_config", lambda: False)
    # No raise, no dispatcher change -> default in-process install.
    await dash_app._install_queue_dispatcher()
