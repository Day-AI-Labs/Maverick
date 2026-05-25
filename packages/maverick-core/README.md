# maverick-core

The Maverick agent kernel. A recursive multi-agent swarm with persistent
world model, shared blackboard, hard budget caps, and closed-loop skill
learning.

See the [top-level README](../../README.md) and
[`ARCHITECTURE.md`](../../ARCHITECTURE.md) for the full picture.

This package is installable on its own:

```bash
pip install maverick
export ANTHROPIC_API_KEY=sk-ant-...
maverick start "your goal"
```

But you probably want `pipx install maverick` + `maverick init` instead,
which also pulls in the safety layer and configures per-role model choice.
