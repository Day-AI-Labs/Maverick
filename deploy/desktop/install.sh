#!/usr/bin/env bash
# Maverick desktop bootstrap (macOS / Linux).
#
# One-line install:
#   curl -fsSL https://raw.githubusercontent.com/cdayAI/Maverick/main/deploy/desktop/install.sh | bash
#
# Zero prerequisites. It installs Python 3 and git if they are missing
# (via brew / apt / dnf / pacman), pulls Maverick, installs the agent +
# setup wizard into an isolated pipx environment, and launches the
# wizard (`maverick init`).
#
# Pin or override the source before running:
#   MAVERICK_REPO=owner/maverick MAVERICK_REF=main \
#     curl -fsSL https://raw.githubusercontent.com/.../install.sh | bash

set -euo pipefail

REPO="${MAVERICK_REPO:-cdayAI/Maverick}"
REF="${MAVERICK_REF:-main}"
SRC_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/maverick/src"

log()  { printf '==> %s\n' "$*" >&2; }
warn() { printf '!!  %s\n' "$*" >&2; }
die()  { printf 'Maverick install failed: %s\n' "$*" >&2; exit 1; }

have() { command -v "$1" >/dev/null 2>&1; }

# pipx may be a standalone CLI (installed by a package manager) or a
# module under the system Python. Call whichever exists.
pipx_cmd() { if have pipx; then pipx "$@"; else python3 -m pipx "$@"; fi; }

ensure_git() {
  have git && return
  log "Installing git ..."
  if   have brew;    then brew install git
  elif have apt-get; then sudo apt-get update && sudo apt-get install -y git
  elif have dnf;     then sudo dnf install -y git
  elif have pacman;  then sudo pacman -Sy --noconfirm git
  else die "No supported package manager (brew/apt/dnf/pacman). Install git, then re-run."
  fi
}

ensure_python() {
  if have python3 && \
     [ "$(python3 -c 'import sys;print("%d%02d"%sys.version_info[:2])')" -ge 310 ]; then
    return
  fi
  log "Installing Python 3 ..."
  case "$(uname -s)" in
    Darwin) have brew || die "Install Homebrew (https://brew.sh) or Python 3.10+, then re-run."
            brew install python ;;
    *)      if   have apt-get; then sudo apt-get update && sudo apt-get install -y python3 python3-venv python3-pip
            elif have dnf;     then sudo dnf install -y python3 python3-pip
            elif have pacman;  then sudo pacman -Sy --noconfirm python python-pip
            else die "No supported package manager. Install Python 3.10+, then re-run."
            fi ;;
  esac
  have python3 || die "Python install finished but 'python3' is not on PATH. Open a new terminal and re-run."
}

ensure_pipx() {
  pipx_cmd --version >/dev/null 2>&1 && { pipx_cmd ensurepath >/dev/null 2>&1 || true; return; }
  log "Installing pipx ..."
  if   have brew;    then brew install pipx
  elif have apt-get; then sudo apt-get update && sudo apt-get install -y pipx
  elif have dnf;     then sudo dnf install -y pipx
  elif have pacman;  then sudo pacman -Sy --noconfirm python-pipx
  else
    python3 -m ensurepip --upgrade >/dev/null 2>&1 || true
    # PEP 668 ("externally managed") needs --break-system-packages; older
    # pip does not know the flag, so fall back to a plain --user install.
    python3 -m pip install --user --upgrade pipx \
      || python3 -m pip install --user --break-system-packages --upgrade pipx
  fi
  pipx_cmd ensurepath >/dev/null 2>&1 || true
}

fetch_source() {
  if [ -d "$SRC_DIR/.git" ]; then
    log "Updating Maverick source ($REF) ..."
    git -C "$SRC_DIR" remote set-url origin "https://github.com/$REPO"
    git -C "$SRC_DIR" fetch --depth 1 origin "$REF"
    git -C "$SRC_DIR" checkout -B "$REF" FETCH_HEAD >/dev/null 2>&1
  else
    log "Downloading Maverick ($REPO@$REF) ..."
    mkdir -p "$(dirname "$SRC_DIR")"
    git clone --depth 1 --branch "$REF" "https://github.com/$REPO" "$SRC_DIR"
  fi
}

install_maverick() {
  log "Installing the agent + setup wizard (this can take a minute) ..."
  pipx_cmd install --force "$SRC_DIR/packages/maverick-core"
  # The wizard ships in apps/installer-cli; install it into the same venv.
  # We inject from source rather than the [installer] extra because
  # maverick-installer is not published to PyPI.
  pipx_cmd inject --force maverick-agent "$SRC_DIR/apps/installer-cli"
}

run_wizard() {
  local bin
  bin="$(pipx_cmd environment --value PIPX_BIN_DIR 2>/dev/null || true)"
  [ -n "$bin" ] || bin="$HOME/.local/bin"
  export PATH="$bin:$PATH"

  printf '\nMaverick installed.\nLaunching the setup wizard...\n\n'
  if ! have maverick; then
    warn "Installed, but 'maverick' is not on this shell's PATH yet."
    printf "Open a new terminal and run:  maverick init\n"
    return
  fi
  # This script is usually run via `curl | bash`, so stdin is the pipe,
  # not the keyboard. Re-attach the wizard to the terminal so its
  # interactive prompts can read input.
  if [ -e /dev/tty ]; then maverick init </dev/tty; else maverick init; fi
}

main() {
  printf '\nMaverick desktop installer\n\n'
  ensure_git
  ensure_python
  ensure_pipx
  fetch_source
  install_maverick
  run_wizard
}

main "$@"
