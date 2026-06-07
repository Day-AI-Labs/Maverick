<#
  Maverick desktop bootstrap (Windows).

  Zero prerequisites. It installs Python 3.12 if missing, installs the
  published Maverick package from PyPI into an isolated pipx environment,
  and launches the wizard (`maverick init`).

  Advanced source installs must pin $env:MAVERICK_REF to a full
  40-character commit SHA. Mutable branches/tags are rejected unless
  $env:MAVERICK_ALLOW_UNPINNED = "1" is set explicitly.

  If Python is already installed but not detected, point straight at it:
    $env:MAVERICK_PYTHON = "C:\path\to\python.exe"
#>

$ErrorActionPreference = 'Stop'

$Repo   = if ($env:MAVERICK_REPO) { $env:MAVERICK_REPO } else { 'Day-AI-Labs/Maverick' }
$Ref    = if ($env:MAVERICK_REF)  { $env:MAVERICK_REF }  else { '' }
$SrcDir = Join-Path $env:LOCALAPPDATA 'Maverick\src'
$AllowUnpinned = if ($env:MAVERICK_ALLOW_UNPINNED) { $env:MAVERICK_ALLOW_UNPINNED } else { '' }

# How to call the resolved Python: $PyExe + $PyPre (e.g. 'py' + '-3').
$script:PyExe = $null
$script:PyPre = @()

function Write-Step($m) { Write-Host "==> $m" -ForegroundColor Cyan }
function Write-Warn($m) { Write-Host "!!  $m" -ForegroundColor Yellow }
function Die($m) { throw "Maverick install failed: $m" }
function Have($cmd) { [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }
function Py { & $script:PyExe @($script:PyPre + $args) }

function Test-PinnedRef($ref) {
  return ($ref -match '^[0-9a-fA-F]{40}$')
}

function Ensure-SourcePin {
  if (-not $Ref) { return }
  if (Test-PinnedRef $Ref) { return }
  if ($AllowUnpinned -eq '1') {
    Write-Warn "Installing from unpinned ref '$Ref' because MAVERICK_ALLOW_UNPINNED=1."
    return
  }
  Die "MAVERICK_REF must be a full 40-character commit SHA. Ref '$Ref' is mutable; set MAVERICK_ALLOW_UNPINNED=1 only for trusted local testing."
}

function Ensure-RepoSlug {
  # $Repo is interpolated into https://github.com/$Repo for the git clone/fetch
  # below. Constrain it to a GitHub "owner/repo" slug so a hostile or typo'd
  # value can't point the install at a different repo or smuggle URL/shell
  # metacharacters into the git command. Mirrors validate_repo in install.sh.
  # (Only the source path uses $Repo; the default PyPI install never touches it.)
  if ($Repo -notmatch '^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$') {
    Die "MAVERICK_REPO must be a GitHub 'owner/repo' slug (letters, digits, '.', '_', '-'); got '$Repo'."
  }
}


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
Ensure-SourcePin

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

# 2. pipx
Write-Step "Ensuring pipx ..."
Py -m pip install --user --upgrade pip pipx | Out-Null
Py -m pipx ensurepath | Out-Null

function Ensure-GitForSource {
  if (-not $Ref) { return }
  if (-not (Have git)) { Ensure-Winget; Winget-Install 'Git.Git' }
  if (-not (Have git)) { Die "Git installed, but it isn't on PATH. Open a NEW PowerShell window and re-run." }
}

function Fetch-Source {
  Ensure-SourcePin
  Ensure-RepoSlug
  Ensure-GitForSource
  if (Test-Path (Join-Path $SrcDir '.git')) {
    Write-Step "Updating Maverick source ($Repo@$Ref) ..."
    git -C $SrcDir remote set-url origin "https://github.com/$Repo"
    git -C $SrcDir fetch --depth 1 origin $Ref
    git -C $SrcDir checkout --detach FETCH_HEAD | Out-Null
  } else {
    Write-Step "Downloading Maverick ($Repo@$Ref) ..."
    Remove-Item -Recurse -Force $SrcDir -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path (Split-Path $SrcDir) | Out-Null
    git clone --no-checkout --depth 1 "https://github.com/$Repo" $SrcDir
    git -C $SrcDir fetch --depth 1 origin $Ref
    git -C $SrcDir checkout --detach FETCH_HEAD | Out-Null
  }
}

# 3. Install agent + wizard into one pipx venv.
Write-Step "Installing the agent + setup wizard (this can take a minute) ..."
if ($Ref) {
  Fetch-Source
  Py -m pipx install --force (Join-Path $SrcDir 'packages\maverick-core')
  Py -m pipx inject --force maverick-agent (Join-Path $SrcDir 'apps\installer-cli')
} else {
  Py -m pipx install --force 'maverick-agent[installer]'
}

# 4. Locate the maverick shim and launch the wizard.
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
