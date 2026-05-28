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
  $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
  $user    = [Environment]::GetEnvironmentVariable('Path', 'User')
  $env:Path = (@($machine, $user) | Where-Object { $_ }) -join ';'
}

function Ensure-Winget {
  if (Have winget) { return }
  Die @"
winget is not available (older Windows 10). Install these by hand, then re-run:
  Python 3.12 : https://www.python.org/downloads/  (tick 'Add python.exe to PATH')
  Git         : https://git-scm.com/download/win
"@
}

function Winget-Install($id) {
  Write-Step "Installing $id ..."
  winget install -e --id $id --accept-source-agreements --accept-package-agreements --silent
  Refresh-Path
}

# Find a Python >= 3.10. Returns 'py', 'python', or $null.
function Resolve-Python {
  foreach ($cand in @('py', 'python')) {
    if (-not (Have $cand)) { continue }
    $pre = if ($cand -eq 'py') { @('-3') } else { @() }
    try {
      $v = & $cand @($pre + @('-c', 'import sys;print("%d.%d"%sys.version_info[:2])')) 2>$null
      if ($v -match '^(\d+)\.(\d+)$') {
        $maj = [int]$Matches[1]; $min = [int]$Matches[2]
        if ($maj -gt 3 -or ($maj -eq 3 -and $min -ge 10)) {
          $script:PyExe = $cand; $script:PyPre = $pre
          return $cand
        }
      }
    } catch { }
  }
  return $null
}

Write-Host ""
Write-Host "Maverick desktop installer (Windows)" -ForegroundColor Green
Write-Host ""

# 1. Python 3.10+
if (-not (Resolve-Python)) {
  Ensure-Winget
  Winget-Install 'Python.Python.3.12'
  if (-not (Resolve-Python)) {
    Die "Python installed, but I still can't find it. Open a NEW PowerShell window and re-run the command."
  }
}
Write-Step ("Using Python " + (Py -c 'import sys;print(sys.version.split()[0])'))

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

# 5. Install agent + wizard into one pipx venv. We inject the wizard
#    from source (apps/installer-cli) rather than the [installer] extra
#    because maverick-installer is not published to PyPI.
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
Write-Host "Maverick installed." -ForegroundColor Green
Write-Host "Launching the setup wizard..." -ForegroundColor Green
Write-Host ""
if (Have maverick) {
  maverick init
} else {
  Write-Warn "Installed, but 'maverick' isn't on this window's PATH yet."
  Write-Host "Open a NEW PowerShell window and run:  maverick init"
}
