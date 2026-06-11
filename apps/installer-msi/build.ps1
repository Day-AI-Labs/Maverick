# Build the Maverick CLI MSI with WiX Toolset v4.
#
# Requires (Windows host):
#   * .NET SDK + WiX v4 CLI:  dotnet tool install --global wix
#   * a built maverick-agent wheel:
#       python -m pip install build
#       python -m build --wheel packages/maverick-core   # writes packages/maverick-core/dist/
#
# Usage (from this directory):
#   .\build.ps1 -Wheel ..\..\packages\maverick-core\dist\maverick_agent-0.1.6-py3-none-any.whl
#
# The output MSI is UNSIGNED (same posture as apps/installer-desktop).
param(
    [Parameter(Mandatory = $true)][string]$Wheel,
    [string]$Version = "0.1.6",
    [string]$OutDir = "dist"
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command wix -ErrorAction SilentlyContinue)) {
    throw "WiX v4 CLI not found. Install it with: dotnet tool install --global wix"
}
if (-not (Test-Path $Wheel)) {
    throw "wheel not found: $Wheel (build it with `python -m build --wheel packages/maverick-core`)"
}

$wheelPath = (Resolve-Path $Wheel).Path
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$msi = Join-Path $OutDir "maverick-cli-$Version.msi"

wix build "$PSScriptRoot\Package.wxs" `
    -d ProductVersion=$Version `
    -d WheelPath=$wheelPath `
    -arch x64 `
    -o $msi
if ($LASTEXITCODE -ne 0) { throw "wix build failed ($LASTEXITCODE)" }

Write-Host "Wrote $msi"
Write-Host "NOTE: this MSI is UNSIGNED. SmartScreen will warn until a code-signing cert exists."
