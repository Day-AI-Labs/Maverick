-- maverick.nvim — drive the Maverick agent runtime from Neovim.
--
-- A thin front end over the locally installed `maverick` CLI; nothing here
-- talks to a network itself.
--
--   :MaverickStart {goal}   start a goal (prompts when no arg)
--   :MaverickStatus         runtime status + cost (split)
--   :MaverickMonitor        live plan-tree TUI (terminal split)
--   :MaverickLogs           recent run logs
--   :MaverickHalt           arm the killswitch (confirms first)
--   :MaverickUnhalt         clear the killswitch
--
-- setup{} is optional:
--   require("maverick").setup({ cli = "/path/to/maverick", max_dollars = 5 })

local M = {}

M.config = {
  cli = "maverick",
  max_dollars = nil, -- when set, passed to `maverick start --max-dollars`
}

function M.setup(opts)
  M.config = vim.tbl_deep_extend("force", M.config, opts or {})
end

local function term_run(args)
  vim.cmd("botright split")
  vim.cmd("resize 15")
  vim.fn.termopen(vim.list_extend({ M.config.cli }, args))
  vim.cmd("startinsert")
end

function M.start(goal)
  if goal == nil or goal == "" then
    vim.ui.input({ prompt = "Goal for Maverick: " }, function(input)
      if input and input ~= "" then
        M.start(input)
      end
    end)
    return
  end
  local args = { "start", goal }
  if M.config.max_dollars then
    table.insert(args, "--max-dollars")
    table.insert(args, tostring(M.config.max_dollars))
  end
  term_run(args)
end

function M.status()
  term_run({ "status", "--cost" })
end

function M.monitor()
  term_run({ "monitor" })
end

function M.logs()
  term_run({ "logs" })
end

function M.halt()
  vim.ui.select({ "No", "Yes — abort ALL running goals" },
    { prompt = "Arm the Maverick killswitch?" },
    function(choice)
      if choice and choice:sub(1, 3) == "Yes" then
        vim.fn.system({ M.config.cli, "halt" })
        vim.notify("Maverick killswitch armed.", vim.log.levels.WARN)
      end
    end)
end

function M.unhalt()
  vim.fn.system({ M.config.cli, "unhalt" })
  vim.notify("Maverick killswitch cleared.", vim.log.levels.INFO)
end

return M
