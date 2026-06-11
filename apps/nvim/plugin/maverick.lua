-- Command registration for maverick.nvim (loaded automatically by Neovim).
if vim.g.loaded_maverick_nvim then
  return
end
vim.g.loaded_maverick_nvim = true

local function mv()
  return require("maverick")
end

vim.api.nvim_create_user_command("MaverickStart", function(opts)
  mv().start(opts.args)
end, { nargs = "?", desc = "Start a Maverick goal" })

vim.api.nvim_create_user_command("MaverickStatus", function()
  mv().status()
end, { desc = "Maverick runtime status + cost" })

vim.api.nvim_create_user_command("MaverickMonitor", function()
  mv().monitor()
end, { desc = "Live Maverick plan-tree monitor" })

vim.api.nvim_create_user_command("MaverickLogs", function()
  mv().logs()
end, { desc = "Recent Maverick run logs" })

vim.api.nvim_create_user_command("MaverickHalt", function()
  mv().halt()
end, { desc = "Arm the Maverick killswitch" })

vim.api.nvim_create_user_command("MaverickUnhalt", function()
  mv().unhalt()
end, { desc = "Clear the Maverick killswitch" })
