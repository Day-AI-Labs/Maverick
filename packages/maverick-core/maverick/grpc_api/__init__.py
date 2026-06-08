"""Maverick gRPC API — StartGoal / StreamEpisode / Cancel / GetStatus.

The contract lives in ``maverick.proto``; the behaviour lives in
:class:`~maverick.grpc_api.service.GoalService` (transport-agnostic, no grpc
needed). ``server.serve`` binds the two behind the ``[grpc]`` extra.

Run the server with: ``python -m maverick.grpc_api`` (after
``pip install 'maverick-agent[grpc]'``).
"""
from __future__ import annotations

from .service import EventDTO, GoalService, GoalStatusDTO

__all__ = ["EventDTO", "GoalService", "GoalStatusDTO"]
