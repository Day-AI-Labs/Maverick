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

import hmac
import json
import logging
import os
from concurrent import futures
from pathlib import Path

log = logging.getLogger(__name__)

_PROTO = Path(__file__).with_name("maverick.proto")
_DEFAULT_ADDR = "127.0.0.1:50051"
_TOKEN_ENV = "MAVERICK_GRPC_BEARER_TOKEN"
_AUTH_HEADER = "authorization"
_BEARER_PREFIX = "bearer "


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


def _resolve_bearer_token(bearer_token: str | None = None) -> str:
    token = (bearer_token if bearer_token is not None else os.getenv(_TOKEN_ENV, "")).strip()
    if not token:
        raise ValueError(
            "Maverick gRPC requires a bearer token. Set "
            f"{_TOKEN_ENV} or pass --bearer-token, and send it as "
            "metadata: authorization: Bearer <token>."
        )
    return token


def _metadata_bearer_token(context) -> str | None:
    metadata = context.invocation_metadata() or ()
    for key, value in metadata:
        if key.lower() != _AUTH_HEADER:
            continue
        value = str(value).strip()
        if value.lower().startswith(_BEARER_PREFIX):
            return value[len(_BEARER_PREFIX):].strip()
    return None


def _abort(context, code, details: str):
    context.abort(code, details)
    raise PermissionError(details)


def _require_authorized(context, bearer_token: str) -> None:
    supplied = _metadata_bearer_token(context)
    if supplied and hmac.compare_digest(supplied, bearer_token):
        return
    _abort(context, _grpc_code().UNAUTHENTICATED, "missing or invalid bearer token")


def _capability_from_json(raw: str):
    if not raw:
        return None
    from ..queue_dispatcher import _deserialize_capability

    return _deserialize_capability(json.loads(raw))


def _servicer(service, pb2, pb2_grpc, *, bearer_token: str | None = None):
    """Build a MaverickServicer bound to ``service`` (a GoalService)."""
    bearer_token = _resolve_bearer_token(bearer_token)

    class MaverickServicer(pb2_grpc.MaverickServicer):
        def StartGoal(self, request, context):
            _require_authorized(context, bearer_token)
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
            _require_authorized(context, bearer_token)
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
            _require_authorized(context, bearer_token)
            return pb2.CancelResponse(cancelled=service.cancel(request.goal_id))

        def GetStatus(self, request, context):
            _require_authorized(context, bearer_token)
            st = service.status(request.goal_id)
            if st is None:
                return pb2.GoalStatus(goal_id=request.goal_id, found=False)
            return pb2.GoalStatus(
                goal_id=st.goal_id, status=st.status,
                result=st.result or "", found=True,
            )

        def RunGoal(self, request, context):
            _require_authorized(context, bearer_token)
            try:
                capability = _capability_from_json(request.capability_json)
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
                context.abort(_grpc_code().INVALID_ARGUMENT, str(e))
                raise
            st = service.run_goal(
                request.goal_id,
                max_dollars=request.max_dollars or None,
                max_wall_seconds=request.max_wall_seconds or None,
                channel=request.channel or None,
                user_id=request.user_id or None,
                max_depth=request.max_depth or None,
                capability=capability,
            )
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


def serve(
    address: str = _DEFAULT_ADDR,
    *,
    service=None,
    max_workers: int = 8,
    bearer_token: str | None = None,
):
    """Start a blocking gRPC server on ``address``. Returns the server handle.

    With ``block=False`` semantics omitted for simplicity: callers that want
    non-blocking use the returned server's ``stop()``. The default service runs
    real goals; tests pass a service wired to fakes.
    """
    bearer_token = _resolve_bearer_token(bearer_token)
    grpc = _require_grpc()
    pb2, pb2_grpc = _load_stubs()
    if service is None:
        from .service import GoalService
        service = GoalService()
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=max_workers))
    pb2_grpc.add_MaverickServicer_to_server(
        _servicer(service, pb2, pb2_grpc, bearer_token=bearer_token), server
    )
    server.add_insecure_port(address)
    server.start()
    log.info("Maverick gRPC API listening on %s", address)
    return server


def main(argv: list[str] | None = None) -> int:  # pragma: no cover -- entrypoint
    import argparse

    ap = argparse.ArgumentParser("maverick-grpc", description="Maverick gRPC API server")
    ap.add_argument("--address", default=_DEFAULT_ADDR, help="host:port to bind")
    ap.add_argument("--max-workers", type=int, default=8)
    ap.add_argument(
        "--bearer-token",
        default=None,
        help=f"bearer token required from clients (or set {_TOKEN_ENV})",
    )
    args = ap.parse_args(argv)
    server = serve(args.address, max_workers=args.max_workers, bearer_token=args.bearer_token)
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        server.stop(grace=2.0)
    return 0


__all__ = ["serve", "main"]
