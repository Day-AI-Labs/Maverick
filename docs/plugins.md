# Plugin SDK

External Python packages can extend Lightwork by declaring entry points
in their `pyproject.toml`. Plugins are discovered at run-time and a
broken plugin can never take the swarm down — each load is wrapped in a
forgiving handler that logs and continues.

## What can be extended

| Slot | Entry-point group | What it does |
|---|---|---|
| Tools | `maverick.tools` | A callable that returns a `maverick.tools.Tool`. Registered in every agent's base registry. |
| Channels | `maverick.channels` | A `maverick_channels.Channel` subclass. Wired by `maverick serve` when enabled in config. |
| Skills | `maverick.skills` | A `maverick.skills.Skill` instance. Auto-included in skill retrieval. |
| Personas | `maverick.personas` | A renderer callable returning a system-prompt suffix. Referenced from `[persona] name = "..."`. |

## Tool plugin example

`my_plugin/pyproject.toml`:

```toml
[project]
name = "maverick-weather-plugin"
version = "0.1.0"
dependencies = ["maverick-agent>=0.1"]

[project.entry-points."maverick.tools"]
weather = "my_plugin:weather_tool"
```

`my_plugin/__init__.py`:

```python
from maverick.tools import Tool

def weather_tool():
    def fn(args):
        # ...call weather API with args["city"]...
        return "72°F, sunny"
    return Tool(
        name="weather",
        description="Look up current weather for a city.",
        input_schema={
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
        fn=fn,
    )
```

Install it: `pip install maverick-weather-plugin` — and on the next swarm
run, every agent gets a `weather` tool in its catalog. The tool passes
through `Shield.scan_tool_call` just like a built-in.

## Channel plugin example

```toml
[project.entry-points."maverick.channels"]
mattermost = "mattermost_channel:MattermostChannel"
```

```python
from maverick_channels import Channel

class MattermostChannel(Channel):
    name = "mattermost"
    async def start(self): ...
    async def send(self, user_id, text): ...
    async def stop(self): ...
```

Enable it in `~/.maverick/config.toml`:

```toml
[channels.mattermost]
enabled = true
url     = "https://chat.example.com"
```

(Plugin channels are not yet auto-wired into `maverick serve` — they are
discoverable via `maverick.plugins.discover_channels()`. Roadmap: a
channel plugin can register its own `_wire` callback so config-driven
startup works without core changes.)

## Skill plugin example

```toml
[project.entry-points."maverick.skills"]
postgres_migration = "myplugin:POSTGRES_MIGRATION_SKILL"
```

```python
from maverick.skills import Skill

POSTGRES_MIGRATION_SKILL = Skill(
    name="postgres_migration",
    triggers=["alter table", "add column", "drop index"],
    tools_needed=["shell", "read_file"],
    body="When migrating a Postgres column, ...",
)
```

## Persona plugin example

```toml
[project.entry-points."maverick.personas"]
pirate = "myplugin:render_pirate"
```

```python
def render_pirate() -> str:
    return "\nSpeak like a friendly pirate, but stay accurate."
```

`~/.maverick/config.toml`:

```toml
[persona]
name = "pirate"
```

## Discovery API

```python
from maverick import plugins

plugins.discover_tools()      # -> list[(name, factory)]
plugins.discover_channels()   # -> list[(name, Channel subclass)]
plugins.discover_skills()     # -> list[Skill]
plugins.discover_personas()   # -> dict[name, renderer]
plugins.installed_plugins()   # -> {"tools": [...], "channels": [...], ...}
```

## Safety + fault isolation

- Each plugin loads in isolation; an exception during `entry_point.load()`
  is logged and that single plugin is skipped. Other plugins and the
  core keep working.
- Tool factories execute per-agent build; a factory that raises is
  logged and dropped. The agent runs without that tool.
- Plugin tools go through `Shield.scan_tool_call` like every other
  tool. There is no "trusted plugin" bypass.
