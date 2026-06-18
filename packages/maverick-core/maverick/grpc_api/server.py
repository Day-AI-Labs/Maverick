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
    _authorize_caller(context, bearer_token)


def _authorize_caller(context, bearer_token: str):
    """Authorize a caller and return its identity.

    Accepts EITHER the configured shared operator bearer (returns ``None`` — the
    shared principal) OR a per-caller ``[agent_trust] grpc_token`` (returns the
    resolved :class:`TrustedAgent`). Aborts UNAUTHENTICATED when neither matches,
    so per-caller tokens are first-class without weakening the shared-bearer path.
    """
    supplied = _metadata_bearer_token(context)
    if supplied and bearer_token and hmac.compare_digest(
        supplied.encode(), bearer_token.encode()
    ):
        return None
    if supplied:
        try:
            from ..agent_trust import agent_for_token
            agent = agent_for_token(supplied, "grpc")
        except Exception:  # pragma: no cover - never break auth on a read error
            agent = None
        if agent is not None:
            return agent
    _abort(context, _grpc_code().UNAUTHENTICATED, "missing or invalid bearer token")


def _trust_capability(context, agent):
    """Agent Trust Plane gate for a goal-CREATING RPC. Returns the capability
    ceiling to intersect into the run (``None`` when disengaged). Aborts
    PERMISSION_DENIED when the caller isn't a permitted inbound agent.

    A per-caller token gates on that agent's entry; a shared-operator-bearer
    caller gates on the surface-wide ``"grpc"`` entry — so engaging the plane
    default-denies the gRPC goal API instead of leaving it open on the bearer."""
    try:
        from .. import agent_trust
        enforced, registry = agent_trust.load_trust_state()
    except Exception:  # pragma: no cover - config read never breaks the path
        return None
    if not enforced:
        return None
    agent_id = agent.id if agent is not None else "grpc"
    decision = agent_trust.decide_inbound(agent_id, registry=registry, enforced=True)
    if decision.denied:
        agent_trust.record_denied(agent_id, decision, direction="inbound")
        _abort(context, _grpc_code().PERMISSION_DENIED, decision.reason)
    return decision.capability


def _capability_from_json(raw: str):
    if not raw:
        return None
    from ..queue_dispatcher import _deserialize_capability

    return _deserialize_capability(json.loads(raw))


def _rpc_capability(capability, *, channel: str | None = None, user_id: str | None = None):
    """Attenuate an RPC-supplied grant by the worker's local policy.

    The bearer token authenticates access to the gRPC API; it is not proof that
    ``capability_json`` is a trusted, least-privilege grant.  When capability
    enforcement is enabled, intersect the received grant with the same local
    policy a root worker agent would derive if no explicit grant were supplied.
    This preserves legitimate delegated restrictions while ensuring external
    callers can only narrow, never broaden, the worker's configured policy.
    """
    if capability is None:
        return None

    from ..capability import capability_enforced, capability_from_config

    if not capability_enforced():
        return capability

    local = capability_from_config(
        principal=f"user:{user_id or 'local'}",
        channel=channel,
        user_id=user_id,
    )
    return local.intersect(capability, principal=local.principal)


def _servicer(service, pb2, pb2_grpc, *, bearer_token: str | None = None):
    """Build a MaverickServicer bound to ``service`` (a GoalService)."""
    bearer_token = _resolve_bearer_token(bearer_token)

    class MaverickServicer(pb2_grpc.MaverickServicer):
        def StartGoal(self, request, context):
            agent = _authorize_caller(context, bearer_token)
            capability = _trust_capability(context, agent)
            try:
                goal_id = service.start_goal(
                    request.title,
                    request.description,
                    max_dollars=request.max_dollars or None,
                    max_wall_seconds=request.max_wall_seconds or None,
                    channel=request.channel or None,
                    user_id=request.user_id or None,
                    capability=capability,
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
            agent = _authorize_caller(context, bearer_token)
            trust_cap = _trust_capability(context, agent)
            channel = request.channel or None
            user_id = request.user_id or None
            try:
                capability = _rpc_capability(
                    _capability_from_json(request.capability_json),
                    channel=channel,
                    user_id=user_id,
                )
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
                context.abort(_grpc_code().INVALID_ARGUMENT, str(e))
                raise
            # Intersect the caller's trust-plane ceiling (narrow-only) on top of
            # any RPC-supplied / locally-derived grant.
            if trust_cap is not None:
                capability = (trust_cap if capability is None
                              else capability.intersect(trust_cap, principal="grpc"))
            st = service.run_goal(
                request.goal_id,
                max_dollars=request.max_dollars or None,
                max_wall_seconds=request.max_wall_seconds or None,
                channel=channel,
                user_id=user_id,
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
    # Fail closed: a client-bound deployment must not serve unbound.
    from ..client import require_client_binding
    require_client_binding()
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
    # TLS when configured; fail closed if required (client-bound/enterprise).
    from ..grpc_tls import bind_port
    secure = bind_port(server, address, "grpc")
    server.start()
    log.info("Maverick gRPC API listening on %s (%s)", address,
             "TLS" if secure else "plaintext")
    return server


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    ap = argparse.ArgumentParser("maverick-grpc", description="Maverick gRPC API server")
    ap.add_argument("--address", default=_DEFAULT_ADDR, help="host:port to bind")
    ap.add_argument("--max-workers", type=int, default=8)
    ap.add_argument(
        "--bearer-token",
        default=None,
        help=f"bearer token required from clients (or set {_TOKEN_ENV})",
    )
    args = ap.parse_args(argv)
    # The two expected startup errors are operator-config, not crashes: a
    # missing bearer token (fail-closed auth default) and a missing grpcio
    # extra. Both already carry a one-line, actionable message -- print it and
    # exit non-zero instead of dumping a traceback (round-4 finding).
    try:
        server = serve(
            args.address, max_workers=args.max_workers,
            bearer_token=args.bearer_token,
        )
    except (ValueError, ImportError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        server.stop(grace=2.0)
    return 0


__all__ = ["serve", "main"]
