#!/usr/bin/env bash
# Maverick desktop bootstrap (macOS / Linux).
#
# Zero prerequisites. It installs Python 3 if missing, installs the
# published Maverick package from PyPI into an isolated pipx environment,
# and launches the wizard (`maverick init`).
#
# Advanced source installs must pin MAVERICK_REF to a full 40-character
# commit SHA. Mutable branches/tags are rejected unless
# MAVERICK_ALLOW_UNPINNED=1 is set explicitly.

set -euo pipefail

REPO="${MAVERICK_REPO:-Day-AI-Labs/Maverick}"
REF="${MAVERICK_REF:-}"
SRC_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/maverick/src"
ALLOW_UNPINNED="${MAVERICK_ALLOW_UNPINNED:-}"

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

validate_source_pin() {
  [ -n "$REF" ] || return 0
  case "$REF" in
    [0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F]) return 0 ;;
  esac
  [ "$ALLOW_UNPINNED" = "1" ] && { warn "Installing from unpinned ref '$REF' because MAVERICK_ALLOW_UNPINNED=1."; return 0; }
  die "MAVERICK_REF must be a full 40-character commit SHA. Ref '$REF' is mutable; set MAVERICK_ALLOW_UNPINNED=1 only for trusted local testing."
}

validate_repo() {
  # MAVERICK_REPO is interpolated into https://github.com/$REPO for the git
  # clone/fetch below. Constrain it to a GitHub "owner/repo" slug so a hostile
  # or typo'd value can't point the install at a different repo or smuggle
  # shell/URL metacharacters into the git command. (Only the source path uses
  # REPO; the default PyPI install never touches it.)
  if [[ ! "$REPO" =~ ^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$ ]]; then
    die "MAVERICK_REPO must be a GitHub 'owner/repo' slug (letters, digits, '.', '_', '-'); got '$REPO'."
  fi
}

fetch_source() {
  validate_repo
  validate_source_pin
  if [ -d "$SRC_DIR/.git" ]; then
    log "Updating Maverick source ($REPO@$REF) ..."
    git -C "$SRC_DIR" remote set-url origin "https://github.com/$REPO"
    git -C "$SRC_DIR" fetch --depth 1 origin "$REF"
    git -C "$SRC_DIR" checkout --detach FETCH_HEAD >/dev/null 2>&1
  else
    log "Downloading Maverick ($REPO@$REF) ..."
    rm -rf "$SRC_DIR"
    mkdir -p "$(dirname "$SRC_DIR")"
    git clone --no-checkout --depth 1 "https://github.com/$REPO" "$SRC_DIR"
    git -C "$SRC_DIR" fetch --depth 1 origin "$REF"
    git -C "$SRC_DIR" checkout --detach FETCH_HEAD >/dev/null 2>&1
  fi
}

install_maverick() {
  log "Installing the agent + setup wizard (this can take a minute) ..."
  if [ -n "$REF" ]; then
    fetch_source
    pipx_cmd install --force "$SRC_DIR/packages/maverick-core"
    # The wizard ships in apps/installer-cli; install it into the same venv.
    pipx_cmd inject --force maverick-agent "$SRC_DIR/apps/installer-cli"
  else
    pipx_cmd install --force 'maverick-agent[installer]'
  fi
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
  validate_source_pin
  ensure_python
  ensure_pipx
  [ -z "$REF" ] || ensure_git
  install_maverick
  # The desktop GUI installer sets MAVERICK_NO_WIZARD: do the install but
  # skip the interactive wizard (the app then points the user at
  # `maverick init`, which a GUI can't drive over a pipe).
  if [ -n "${MAVERICK_NO_WIZARD:-}" ]; then
    printf '\nMaverick installed. Run `maverick init` to configure it.\n'
  else
    run_wizard
  fi
}

main "$@"
