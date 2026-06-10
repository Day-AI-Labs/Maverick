"""gRPC dispatch (roadmap: 2027 H1 performance).

Move goal execution to a remote Maverick worker over gRPC: a
:class:`GrpcDispatcher` implements the :class:`maverick.runner.Dispatcher`
protocol by calling the worker's ``RunGoal`` RPC (added to
``grpc_api/maverick.proto``), which runs an **existing** goal row to
completion and returns its terminal status — the same contract as the local
thread dispatcher, so no caller changes.

Deployment contract (same as the arq QueueDispatcher): the API process and
the worker must **share the world DB** (the Postgres backend) — the RPC
carries only the goal id, not the goal. The worker is just
``python -m maverick.grpc_api`` on the other host.

Opt-in::

    [grpc_dispatch]
    target = "worker-host:50051"
    # token = "..."        # must match the worker's [grpc] token, if set
    # timeout_s = 0         # 0 = no client deadline (long-horizon runs)

Behind the same ``[grpc]`` extra as the server. Fail-honest: an unreachable
worker returns ``None`` ("could not start") rather than raising into the
caller, and logs why.
"""
from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger(__name__)

_DEFAULT_PORT = 50051


def _cfg() -> dict:
    try:
        from .config import load_config
        return (load_config() or {}).get("grpc_dispatch") or {}
    except Exception:  # pragma: no cover -- config never blocks dispatch
        return {}


def configured_target() -> str:
    """``host:port`` of the remote worker (empty = gRPC dispatch off)."""
    env = os.environ.get("MAVERICK_GRPC_DISPATCH_TARGET", "").strip()
    if env:
        return env
    return str(_cfg().get("target") or "").strip()


class GrpcDispatcher:
    """Dispatcher that executes goals on a remote worker via ``RunGoal``."""

    def __init__(
        self,
        target: str | None = None,
        *,
        token: str | None = None,
        timeout_s: float | None = None,
        stub_factory: Any | None = None,
    ):
        self.target = (target or configured_target()).strip()
        if not self.target:
            raise ValueError("gRPC dispatch needs a target (host:port)")
        if ":" not in self.target:
            self.target = f"{self.target}:{_DEFAULT_PORT}"
        cfg = _cfg()
        self.token = token if token is not None else str(cfg.get("token") or "") or None
        if timeout_s is None:
            try:
                timeout_s = float(cfg.get("timeout_s", 0) or 0)
            except (TypeError, ValueError):
                timeout_s = 0.0
        self.timeout_s = timeout_s if timeout_s and timeout_s > 0 else None
        # Test seam: stub_factory() -> (stub, pb2). Default builds a real
        # channel lazily so importing this module never requires grpcio.
        self._stub_factory = stub_factory

    def _build_stub(self):
        if self._stub_factory is not None:
            return self._stub_factory()
        import grpc

        from .grpc_api.server import _load_stubs  # compiled-on-demand stubs
        pb2, pb2_grpc = _load_stubs()
        channel = grpc.insecure_channel(self.target)
        return pb2_grpc.MaverickStub(channel), pb2

    def _metadata(self) -> list[tuple[str, str]]:
        if self.token:
            return [("authorization", f"Bearer {self.token}")]
        return []

    def submit(
        self,
        goal_id: int,
        *,
        max_dollars: float | None = None,
        max_wall_seconds: float | None = None,
        max_depth: int = 3,
        channel: str | None = None,
        user_id: str | None = None,
        capability: Any | None = None,
    ) -> str | None:
        # max_depth/capability are per-process concerns the worker derives
        # from its own config; the RPC carries the run-shaping knobs only.
        del max_depth, capability
        try:
            stub, pb2 = self._build_stub()
        except Exception as e:  # missing extra / bad target
            log.warning("gRPC dispatch unavailable (%s); goal %s not started", e, goal_id)
            return None
        request = pb2.RunGoalRequest(
            goal_id=int(goal_id),
            max_dollars=float(max_dollars or 0),
            max_wall_seconds=float(max_wall_seconds or 0),
            channel=channel or "",
            user_id=user_id or "",
        )
        try:
            status = stub.RunGoal(
                request, timeout=self.timeout_s, metadata=self._metadata(),
            )
        except Exception as e:  # worker down / deadline / auth
            log.warning("gRPC dispatch of goal %s failed: %s", goal_id, e)
            return None
        if not getattr(status, "found", False):
            log.warning(
                "gRPC worker has no goal %s — are the API and worker sharing "
                "the world DB ([world_model] backend = 'postgres')?", goal_id)
            return None
        return str(status.status or "") or None


def install_from_config() -> bool:
    """Install the GrpcDispatcher when ``[grpc_dispatch] target`` is set.

    Mirrors ``queue_dispatcher.install_from_config``: returns True when
    installed. Never raises — a bad config logs and leaves the local
    dispatcher in place.
    """
    target = configured_target()
    if not target:
        return False
    try:
        from .runner import set_dispatcher
        set_dispatcher(GrpcDispatcher(target))
        log.info("goal dispatch -> gRPC worker at %s", target)
        return True
    except Exception:  # pragma: no cover -- never break startup on config
        log.exception("gRPC dispatcher install failed (running in-process)")
        return False


__all__ = ["GrpcDispatcher", "configured_target", "install_from_config"]
