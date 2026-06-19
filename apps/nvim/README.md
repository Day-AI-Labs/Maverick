# maverick.nvim

Drive the [Lightwork](https://github.com/Day-AI-Labs/maverick) agent runtime
from Neovim — a thin front end over the locally installed `maverick` CLI.

## Install

lazy.nvim:

```lua
{
  dir = "/path/to/Lightwork/apps/nvim",  -- or your fork/checkout
  config = function()
    require("maverick").setup({
      cli = "maverick",   -- path to the CLI
      max_dollars = nil,  -- optional per-run spend cap
    })
  end,
}
```

## Commands

| Command | What it does |
|---|---|
| `:LightworkStart {goal}` | start a goal (prompts when no arg) |
| `:LightworkStatus` | runtime status + cost |
| `:LightworkMonitor` | live plan-tree TUI in a terminal split |
| `:LightworkLogs` | recent run logs |
| `:LightworkHalt` | arm the killswitch (confirms first) |
| `:LightworkUnhalt` | clear the killswitch |

Classic Vim (non-Neovim) users: the CLI works in any `:terminal` —
`maverick monitor` is the same TUI.
