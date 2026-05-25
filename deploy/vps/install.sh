#!/usr/bin/env bash
# Maverick VPS bootstrap script.
#
# Usage on a fresh Ubuntu / Debian VPS (run as root or via sudo):
#
#   curl -sSL https://raw.githubusercontent.com/texasreaper62/maverick/main/deploy/vps/install.sh | sudo bash
#
# What it does:
#   1. Installs Python 3.12, pipx, git
#   2. Installs the maverick CLI + installer + shield
#   3. Runs `maverick init` interactively (you pick everything)
#   4. Drops a systemd unit so maverick runs at boot
#   5. Optionally configures Caddy for HTTPS access (if you provide a domain)

set -euo pipefail

log() { echo "==> $*" >&2; }

require_root() {
  if [[ $EUID -ne 0 ]]; then
    echo "This script must be run as root (try: sudo bash install.sh)" >&2
    exit 1
  fi
}

install_system_deps() {
  log "Installing system packages..."
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv pipx \
    git curl ca-certificates sqlite3
  pipx ensurepath || true
}

install_maverick() {
  log "Installing maverick..."
  # Until packages are on PyPI, install from the repo.
  if [[ ! -d /opt/maverick ]]; then
    git clone https://github.com/texasreaper62/maverick /opt/maverick
  else
    git -C /opt/maverick pull --ff-only
  fi
  pipx install /opt/maverick/packages/maverick-core --force
  pipx inject maverick /opt/maverick/packages/maverick-shield
  pipx inject maverick /opt/maverick/apps/installer-cli
}

run_wizard() {
  log "Launching the setup wizard. Pick deployment=vps when asked."
  sudo -u "${SUDO_USER:-root}" -i maverick init
}

install_service() {
  log "Installing systemd unit..."
  cp /opt/maverick/deploy/vps/maverick.service /etc/systemd/system/maverick.service
  systemctl daemon-reload
  systemctl enable maverick.service
  log "Service installed. Start with:  systemctl start maverick"
}

main() {
  require_root
  install_system_deps
  install_maverick
  run_wizard
  install_service
  log "Done. Tail logs with:  journalctl -u maverick -f"
}

main "$@"
