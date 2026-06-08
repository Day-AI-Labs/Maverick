# gRPC API

Maverick exposes a small gRPC surface for driving the agent runtime from any
language: start a goal, stream its episode events, cancel it, and read status.
It is the cross-language complement to the [MCP server](./api.md) — pick gRPC
when you want a typed, streaming RPC contract and your own client codegen.

## Install & run

The API is behind an optional extra:

```bash
pip install 'maverick-agent[grpc]'
python -m maverick.grpc_api --address 127.0.0.1:50051
```

The server compiles the bundled `maverick.proto` into Python stubs on first
start (no generated code is checked in). Point your own `protoc` at the same
proto to generate a client in Go, Rust, TypeScript, C#, Java, etc.

## Service

```proto
service Maverick {
  rpc StartGoal(StartGoalRequest) returns (StartGoalResponse);
  rpc StreamEpisode(StreamEpisodeRequest) returns (stream Event);
  rpc Cancel(CancelRequest) returns (CancelResponse);
  rpc GetStatus(GetStatusRequest) returns (GoalStatus);
}
```

- **StartGoal** creates a goal and dispatches it for background execution,
  returning the goal id immediately. Optional `max_dollars` / `max_wall_seconds`
  override the per-run budget; `0` uses the server/config default.
- **StreamEpisode** streams the goal's events in id order as they land, ending
  with a final `kind="status"` event carrying the terminal status. Resume after
  a disconnect with `since_id`.
- **Cancel** marks a goal cancelled; it is honoured at the next dispatch / turn
  boundary (in-flight cooperative cancellation rides the global killswitch the
  agent loop already checks).
- **GetStatus** returns the point-in-time status + result.

The full message definitions are in
[`maverick.proto`](https://github.com/Day-AI-Labs/maverick/blob/main/packages/maverick-core/maverick/grpc_api/maverick.proto).

## Notes

- The behaviour lives in a transport-agnostic `GoalService`
  (`maverick.grpc_api.service`); the gRPC layer is a thin protobuf shim, so the
  same logic could back a second transport.
- The server binds an **insecure** port by default — front it with TLS
  termination / mTLS at your proxy, and gate it with the same network controls
  you use for the dashboard. Do not expose it directly to untrusted networks.
