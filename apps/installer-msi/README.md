# maverick-installer-msi

WiX Toolset v4 authoring for a Windows MSI that installs the **maverick CLI**
per user: a `maverick.cmd` launcher on the user PATH plus the
`maverick-agent` wheel, bootstrapped into the per-user site-packages on
first run.

## What's in the package

| Piece | What it does |
|---|---|
| `Package.wxs` | WiX v4 product/package definition: per-user scope, stable `UpgradeCode`, `MajorUpgrade` rule, PATH environment component |
| `maverick.cmd` | Launcher installed to `%LOCALAPPDATA%\Programs\Maverick\bin`. Resolves the pip console script; on first run pip-installs the bundled wheel (`--user`) |
| `build.ps1` | `wix build` invocation; takes the wheel path and version |
| `test_wxs.py` | Static contract test (XML well-formed, UpgradeCode pinned, perUser scope, no hardcoded user paths) |

Design notes:

- **Per-user by default** (`Scope="perUser"`): no UAC, installs under
  `%LOCALAPPDATA%\Programs\Maverick`, and the PATH component edits the *user*
  PATH only (`System="no"`).
- **`UpgradeCode` is a constant** (`9E2B7C41-6A8D-4F3B-8E5A-2C90D17B4F6E`).
  Never change it: `MajorUpgrade` uses it to find and replace older versions.
  `test_wxs.py` pins the exact value so a drive-by edit fails CI.
- **The launcher uses the console-script entry point.** `py -m maverick`
  does not work — `packages/maverick-core/maverick/` has no `__main__.py` —
  so `maverick.cmd` runs `python -c "from maverick.cli import main; main()"`
  (the same target as the `maverick` console script in
  `packages/maverick-core/pyproject.toml`).
- **Python is a prerequisite, not bundled.** The MSI is ~a few hundred KB +
  the wheel; it does not embed a Python runtime. `maverick.cmd` prints an
  actionable error if Python 3.10+ is missing. Users who want a
  zero-prerequisite installer should use the Tauri GUI installer
  (`apps/installer-desktop`), whose bootstrap installs Python itself.

## Building

Requires a **Windows host**, the **WiX v4 CLI**, and a **built wheel**:

```powershell
dotnet tool install --global wix
python -m pip install build
python -m build --wheel packages/maverick-core
cd apps\installer-msi
.\build.ps1 -Wheel ..\..\packages\maverick-core\dist\maverick_agent-0.1.6-py3-none-any.whl
```

There is also a manual-dispatch CI workflow
(`.github/workflows/build-msi.yml`) that builds the wheel and the MSI on
`windows-latest` and uploads the artifact.

## Status — honest

- The `.wxs`, launcher, and build script were authored and statically
  validated (`test_wxs.py`) in a Linux environment. **No MSI was built or
  installed here** — that requires WiX v4 on a Windows host. Treat the first
  `build.ps1` run as a release candidate to smoke-test.
- The produced MSI ships **UNSIGNED** — exactly the same posture as the
  Tauri desktop installer (`apps/installer-desktop`): SmartScreen shows an
  "unknown publisher" warning users must click through until a Windows
  code-signing certificate exists.

## Testing

```bash
python -m pytest apps/installer-msi/test_wxs.py -q
```
