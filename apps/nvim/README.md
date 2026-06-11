# maverick.nvim

Drive the [Maverick](https://github.com/Day-AI-Labs/maverick) agent runtime
from Neovim — a thin front end over the locally installed `maverick` CLI.

## Install

lazy.nvim:

```lua
{
  dir = "/path/to/Maverick/apps/nvim",  -- or your fork/checkout
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
| `:MaverickStart {goal}` | start a goal (prompts when no arg) |
| `:MaverickStatus` | runtime status + cost |
| `:MaverickMonitor` | live plan-tree TUI in a terminal split |
| `:MaverickLogs` | recent run logs |
| `:MaverickHalt` | arm the killswitch (confirms first) |
| `:MaverickUnhalt` | clear the killswitch |

Classic Vim (non-Neovim) users: the CLI works in any `:terminal` —
`maverick monitor` is the same TUI.
