# maverick-shield

Agent Shield integration for Lightwork. Provides three safety chokepoints
the agent loop wraps around:

- `Shield.scan_input(text)` — before user input enters the orchestrator
- `Shield.scan_tool_call(name, args)` — before any tool executes
- `Shield.scan_output(text)` — before the final answer reaches the user

See [`../../docs/safety.md`](../../docs/safety.md) for profiles and
threat coverage.
