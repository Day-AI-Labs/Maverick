"""gRPC binding for :class:`~maverick.grpc_api.service.GoalService`.

A thin protobuf shim: it maps the generated request/response messages onto the
transport-agnostic service and back. Everything here is behind the ``[grpc]``
extra (``grpcio`` + ``grpcio-tools``) and lazy — importing this module never
requires grpc; only :func:`serve` and :func:`_servicer` do.

Stubs are generated on demand from the bundled ``maverick.proto`` into this
package (``maverick_pb2`` / ``maverick_pb2_grpc``) so no generated code is
checked in. With the ``[grpc]`` extra installed, ``serve()`` just works.
"""
from __future__ import annotations

import logging
from concurrent import futures
from pathlib import Path

log = logging.getLogger(__name__)

_PROTO = Path(__file__).with_name("maverick.proto")
_DEFAULT_ADDR = "127.0.0.1:50051"


def _require_grpc():
    try:
        import grpc  # noqa: F401
    except ImportError as e:
        raise ImportError(
            "grpc not installed. Run: pip install 'maverick-agent[grpc]'"
        ) from e
    return __import__("grpc")


def _load_stubs():
    """Import the generated pb2 modules, generating them first if absent."""
    try:
        from . import maverick_pb2, maverick_pb2_grpc  # type: ignore
        return maverick_pb2, maverick_pb2_grpc
    except ImportError:
        _generate_stubs()
        from . import maverick_pb2, maverick_pb2_grpc  # type: ignore
        return maverick_pb2, maverick_pb2_grpc


def _generate_stubs() -> None:
    """Compile maverick.proto into this package using grpc_tools.protoc."""
    try:
        from grpc_tools import protoc
    except ImportError as e:
        raise ImportError(
            "grpcio-tools not installed (needed to generate stubs). "
            "Run: pip install 'maverick-agent[grpc]'"
        ) from e
    out = str(_PROTO.parent)
    rc = protoc.main([
        "protoc",
        f"-I{out}",
        f"--python_out={out}",
        f"--grpc_python_out={out}",
        str(_PROTO),
    ])
    if rc != 0:  # pragma: no cover -- only on a broken protoc toolchain
        raise RuntimeError(f"protoc failed to generate gRPC stubs (rc={rc})")


def _servicer(service, pb2, pb2_grpc):
    """Build a MaverickServicer bound to ``service`` (a GoalService)."""

    class MaverickServicer(pb2_grpc.MaverickServicer):
        def StartGoal(self, request, context):
            try:
                goal_id = service.start_goal(
                    request.title,
                    request.description,
                    max_dollars=request.max_dollars or None,
                    max_wall_seconds=request.max_wall_seconds or None,
                    channel=request.channel or None,
                    user_id=request.user_id or None,
                )
            except ValueError as e:
                context.abort(_grpc_code().INVALID_ARGUMENT, str(e))
            return pb2.StartGoalResponse(goal_id=goal_id)

        def StreamEpisode(self, request, context):
            for ev in service.stream_episode(
                request.goal_id,
                since_id=request.since_id,
                max_seconds=request.max_seconds or None,
            ):
                if not context.is_active():  # client hung up
                    return
                yield pb2.Event(
                    id=ev.id, goal_id=ev.goal_id, agent=ev.agent,
                    kind=ev.kind, content=ev.content, ts=ev.ts,
                )

        def Cancel(self, request, context):
            return pb2.CancelResponse(cancelled=service.cancel(request.goal_id))

        def GetStatus(self, request, context):
            st = service.status(request.goal_id)
            if st is None:
                return pb2.GoalStatus(goal_id=request.goal_id, found=False)
            return pb2.GoalStatus(
                goal_id=st.goal_id, status=st.status,
                result=st.result or "", found=True,
            )

    return MaverickServicer()


def _grpc_code():
    import grpc
    return grpc.StatusCode


def serve(address: str = _DEFAULT_ADDR, *, service=None, max_workers: int = 8):
    """Start a blocking gRPC server on ``address``. Returns the server handle.

    With ``block=False`` semantics omitted for simplicity: callers that want
    non-blocking use the returned server's ``stop()``. The default service runs
    real goals; tests pass a service wired to fakes.
    """
    grpc = _require_grpc()
    pb2, pb2_grpc = _load_stubs()
    if service is None:
        from .service import GoalService
        service = GoalService()
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=max_workers))
    pb2_grpc.add_MaverickServicer_to_server(_servicer(service, pb2, pb2_grpc), server)
    server.add_insecure_port(address)
    server.start()
    log.info("Maverick gRPC API listening on %s", address)
    return server


def main(argv: list[str] | None = None) -> int:  # pragma: no cover -- entrypoint
    import argparse

    ap = argparse.ArgumentParser("maverick-grpc", description="Maverick gRPC API server")
    ap.add_argument("--address", default=_DEFAULT_ADDR, help="host:port to bind")
    ap.add_argument("--max-workers", type=int, default=8)
    args = ap.parse_args(argv)
    server = serve(args.address, max_workers=args.max_workers)
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        server.stop(grace=2.0)
    return 0


__all__ = ["serve", "main"]
