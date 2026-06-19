# maverick.el

Drive the [Lightwork](https://github.com/Day-AI-Labs/maverick) agent runtime
from Emacs — a dependency-free front end over the locally installed
`maverick` CLI (Emacs 27.1+).

## Install

Add to `load-path` and require:

```elisp
(add-to-list 'load-path "/path/to/Lightwork/apps/emacs")
(require 'maverick)
(setq maverick-cli-path "maverick")           ; if not on PATH
(setq maverick-default-max-dollars nil)       ; optional per-run cap
```

## Commands

| Command | What it does |
|---|---|
| `M-x maverick-start` | prompt for a goal, run it (compilation buffer) |
| `M-x maverick-status` | runtime status + cost |
| `M-x maverick-monitor` | live plan-tree TUI (term buffer) |
| `M-x maverick-logs` | recent run logs |
| `M-x maverick-halt` | arm the killswitch (confirms first) |
| `M-x maverick-unhalt` | clear the killswitch |
