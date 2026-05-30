<#
  Maverick desktop bootstrap (Windows).

  One-line install (PowerShell):
    irm https://raw.githubusercontent.com/cdayAI/Maverick/main/deploy/desktop/install.ps1 | iex

  Zero prerequisites. It installs Python 3.12 and Git if they are
  missing (via winget), pulls Maverick, installs the agent + setup
  wizard into an isolated pipx environment, and launches the wizard
  (`maverick init`).

  Pin or override the source first:
    $env:MAVERICK_REPO = "owner/maverick"; $env:MAVERICK_REF = "main"
    irm https://raw.githubusercontent.com/.../install.ps1 | iex

  If Python is already installed but not detected, point straight at it:
    $env:MAVERICK_PYTHON = "C:\path\to\python.exe"
#>

$ErrorActionPreference = 'Stop'

$Repo   = if ($env:MAVERICK_REPO) { $env:MAVERICK_REPO } else { 'cdayAI/Maverick' }
$Ref    = if ($env:MAVERICK_REF)  { $env:MAVERICK_REF }  else { 'main' }
$SrcDir = Join-Path $env:LOCALAPPDATA 'Maverick\src'

# How to call the resolved Python: $PyExe + $PyPre (e.g. 'py' + '-3').
$script:PyExe = $null
$script:PyPre = @()

function Write-Step($m) { Write-Host "==> $m" -ForegroundColor Cyan }
function Write-Warn($m) { Write-Host "!!  $m" -ForegroundColor Yellow }
function Die($m) { throw "Maverick install failed: $m" }
function Have($cmd) { [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }
function Py { & $script:PyExe @($script:PyPre + $args) }

function Refresh-Path {
  # Merge the live machine + user PATH from the registry into this
  # session WITHOUT dropping entries already added here (a freshly
  # installed Python dir, or pipx's bin dir below). The old version
  # overwrote $env:Path, which silently undid those additions -- which is
  # why `maverick init` often failed to launch in the same window.
  $parts = @(
    [Environment]::GetEnvironmentVariable('Path', 'Machine'),
    [Environment]::GetEnvironmentVariable('Path', 'User'),
    $env:Path
  ) | Where-Object { $_ } | ForEach-Object { $_ -split ';' } | Where-Object { $_ }
  $seen = New-Object System.Collections.Generic.HashSet[string]
  $env:Path = (@($parts | Where-Object { $seen.Add($_) }) -join ';')
}

function Ensure-Winget {
  if (Have winget) { return }
  Die @"
winget is not available (older Windows 10). Install these by hand, then re-run:
  Python 3.12 : https://www.python.org/downloads/  (tick 'Add python.exe to PATH')
  Git         : https://git-scm.com/download/win
"@
}

function Winget-Install($id, $override) {
  Write-Step "Installing $id ..."
  # An $override replaces winget's default installer args entirely, so it
  # must carry its own quiet flag. Used to force Python onto PATH.
  if ($override) {
    winget install -e --id $id --accept-source-agreements --accept-package-agreements --override $override
  } else {
    winget install -e --id $id --accept-source-agreements --accept-package-agreements --silent
  }
  Refresh-Path
}

# Validate one interpreter: run it and confirm it reports >= 3.10. On
# success, record how to invoke it ($script:PyExe / $script:PyPre).
#
# Probe with `--version`, NOT `-c "..."`. Windows PowerShell 5.1 mangles
# embedded double quotes when passing args to a native exe, so a quoted
# -c snippet fails even when the interpreter is perfectly fine -- which
# made every detection path (PATH, registry, disk) report "not found".
function Test-PyCandidate($exe, $pre) {
  try {
    $out = (& $exe @($pre + @('--version')) 2>&1) | Out-String
    if ($out -match 'Python\s+(\d+)\.(\d+)' -and
        ([int]$Matches[1] -gt 3 -or ([int]$Matches[1] -eq 3 -and [int]$Matches[2] -ge 10))) {
      $script:PyExe = $exe; $script:PyPre = $pre
      return $true
    }
  } catch { }
  return $false
}

# Full paths to every Python registered under PEP 514. The python.org
# installer (what winget runs) always writes these keys with the exact
# install location, regardless of PATH or install dir -- so this finds
# Python even when winget never put it on PATH.
function Get-RegistryPythons {
  $found = @()
  $roots = @(
    'HKCU:\SOFTWARE\Python\PythonCore',
    'HKLM:\SOFTWARE\Python\PythonCore',
    'HKLM:\SOFTWARE\WOW6432Node\Python\PythonCore'
  )
  foreach ($root in $roots) {
    if (-not (Test-Path $root)) { continue }
    foreach ($ver in (Get-ChildItem $root -ErrorAction SilentlyContinue)) {
      try {
        $ip  = Get-ItemProperty -Path (Join-Path $ver.PSPath 'InstallPath') -ErrorAction Stop
        $exe = $ip.ExecutablePath
        if (-not $exe -and $ip.'(default)') { $exe = Join-Path $ip.'(default)' 'python.exe' }
        if ($exe -and (Test-Path $exe)) { $found += $exe }
      } catch { }
    }
  }
  return $found
}

# Find a usable Python >= 3.10. PATH first, then the registry (winget
# runs the python.org installer, which does NOT add Python to PATH
# unless PrependPath is set), then a scan of well-known install dirs.
function Resolve-Python {
  # An explicit override wins -- the escape hatch when detection fails.
  if ($env:MAVERICK_PYTHON -and (Test-PyCandidate $env:MAVERICK_PYTHON @())) { return $true }

  if ((Have py)     -and (Test-PyCandidate 'py'     @('-3'))) { return $true }
  if ((Have python) -and (Test-PyCandidate 'python' @()))     { return $true }

  foreach ($exe in (Get-RegistryPythons | Sort-Object -Descending -Unique)) {
    if (Test-PyCandidate $exe @()) { return $true }
  }

  $parents = @(
    (Join-Path $env:LOCALAPPDATA 'Programs\Python'),
    $env:ProgramFiles,
    (Join-Path $env:ProgramFiles 'Python'),
    'C:\'
  )
  if (${env:ProgramFiles(x86)}) { $parents += ${env:ProgramFiles(x86)} }
  foreach ($p in $parents) {
    if (-not $p -or -not (Test-Path $p)) { continue }
    foreach ($d in (Get-ChildItem -LiteralPath $p -Directory -Filter 'Python3*' -ErrorAction SilentlyContinue)) {
      $exe = Join-Path $d.FullName 'python.exe'
      if ((Test-Path $exe) -and (Test-PyCandidate $exe @())) { return $true }
    }
  }
  return $false
}

Write-Host ""
Write-Host "Maverick desktop installer (Windows)" -ForegroundColor Green
Write-Host ""

# 1. Python 3.10+
if (-not (Resolve-Python)) {
  Ensure-Winget
  # PrependPath puts python.org's install on PATH for future sessions;
  # Resolve-Python also locates it on disk for the current one.
  Winget-Install 'Python.Python.3.12' '/quiet PrependPath=1 InstallLauncherAllUsers=0'
  if (-not (Resolve-Python)) {
    Die @"
Python was installed but couldn't be located (PATH + registry + disk all came up empty).
Reinstall from https://www.python.org/downloads/ with 'Add python.exe to PATH' ticked, then re-run this command.
"@
  }
}
Write-Step ("Using " + ((Py --version | Out-String).Trim()))

# 2. Git
if (-not (Have git)) { Ensure-Winget; Winget-Install 'Git.Git' }
if (-not (Have git)) { Die "Git installed, but it isn't on PATH. Open a NEW PowerShell window and re-run." }

# 3. pipx
Write-Step "Ensuring pipx ..."
Py -m pip install --user --upgrade pip pipx | Out-Null
Py -m pipx ensurepath | Out-Null

# 4. Source
if (Test-Path (Join-Path $SrcDir '.git')) {
  Write-Step "Updating Maverick source ($Ref) ..."
  git -C $SrcDir remote set-url origin "https://github.com/$Repo"
  git -C $SrcDir fetch --depth 1 origin $Ref
  git -C $SrcDir checkout -B $Ref FETCH_HEAD | Out-Null
} else {
  Write-Step "Downloading Maverick ($Repo@$Ref) ..."
  New-Item -ItemType Directory -Force -Path (Split-Path $SrcDir) | Out-Null
  git clone --depth 1 --branch $Ref "https://github.com/$Repo" $SrcDir
}

# 5. Install agent + wizard into one pipx venv. maverick-installer is
#    published to PyPI as of v0.1.3, so the [installer] extra resolves
#    from PyPI; we inject the wizard from source (apps/installer-cli) as a
#    pre-publish fallback and to pin it to this checkout.
Write-Step "Installing the agent + setup wizard (this can take a minute) ..."
Py -m pipx install --force (Join-Path $SrcDir 'packages\maverick-core')
Py -m pipx inject --force maverick-agent (Join-Path $SrcDir 'apps\installer-cli')

# 6. Locate the maverick shim and launch the wizard.
$binDir = $null
try { $binDir = (Py -m pipx environment --value PIPX_BIN_DIR).Trim() } catch { }
if (-not $binDir) { $binDir = Join-Path $env:USERPROFILE '.local\bin' }
$env:Path = "$binDir;$env:Path"
Refresh-Path

Write-Host ""
# The desktop GUI installer sets MAVERICK_NO_WIZARD: install but skip the
# interactive wizard (the app then points the user at `maverick init`).
if ($env:MAVERICK_NO_WIZARD) {
  Write-Host "Maverick installed. Run 'maverick init' to configure it." -ForegroundColor Green
} else {
  Write-Host "Maverick installed." -ForegroundColor Green
  Write-Host "Launching the setup wizard..." -ForegroundColor Green
  Write-Host ""
  if (Have maverick) {
    maverick init
  } else {
    Write-Warn "Installed, but 'maverick' isn't on this window's PATH yet."
    Write-Host "Open a NEW PowerShell window and run:  maverick init"
  }
}
