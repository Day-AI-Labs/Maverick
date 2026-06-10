@echo off
rem Maverick CLI launcher, installed by the Maverick MSI (apps/installer-msi).
rem
rem Why this exists: the MSI cannot pip-install at install time without
rem custom actions, so it ships the wheel next to this script and bootstraps
rem lazily on first run. There is no maverick/__main__.py, so `py -m maverick`
rem does not work; the real entry point is the console script maverick.cli:main
rem (see packages/maverick-core/pyproject.toml [project.scripts]).
setlocal

rem Fast path: pip already put the console script on PATH (e.g. pipx or a
rem previous bootstrap whose Scripts dir is on PATH).
where maverick.exe >nul 2>nul && ( maverick.exe %* & exit /b %ERRORLEVEL% )

rem Resolve a Python 3 interpreter: the py launcher first, plain python second.
set "PYCMD=py -3"
%PYCMD% -c "import sys" >nul 2>nul || set "PYCMD=python"
%PYCMD% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul || (
  echo maverick: Python 3.10+ was not found. Install it from https://python.org
  echo           ^(check "Add python.exe to PATH"^) and run `maverick` again.
  exit /b 1
)

rem First run: install the wheel bundled by the MSI into the per-user site.
%PYCMD% -c "import maverick" >nul 2>nul || (
  echo maverick: first run - installing the bundled wheel into the user site...
  %PYCMD% -m pip install --user --quiet "%~dp0..\wheels\maverick_agent.whl" || (
    echo maverick: pip install of the bundled wheel failed.
    exit /b 1
  )
)

rem Invoke the click entry point directly; argv[1:] is forwarded unchanged.
%PYCMD% -c "from maverick.cli import main; main()" %*
exit /b %ERRORLEVEL%
