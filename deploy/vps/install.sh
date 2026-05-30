#!/usr/bin/env bash
# Maverick VPS bootstrap script.
#
# Usage:
#   curl -sSL https://raw.githubusercontent.com/cdayAI/Maverick/main/deploy/vps/install.sh | sudo bash
#
# Or pin to a specific tag:
#   curl -sSL ...install.sh | sudo MAVERICK_VERSION=v0.1.0 bash
#
# What it does:
#   1. Installs Python 3.12, pipx, git
#   2. Installs maverick (core + shield + channels + dashboard + mcp + installer)
#      into one pipx venv
#   3. Runs `maverick init` interactively
#   4. Drops a systemd unit so maverick serve runs at boot
#   5. Optionally configures Caddy for HTTPS (see Caddyfile next to this script)

set -euo pipefail

MAVERICK_VERSION="${MAVERICK_VERSION:-main}"

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
  log "Installing maverick @ ${MAVERICK_VERSION}..."
  if [[ ! -d /opt/maverick ]]; then
    git clone --branch "${MAVERICK_VERSION}" --depth 1 \
        https://github.com/cdayAI/Maverick /opt/maverick \
      || git clone https://github.com/cdayAI/Maverick /opt/maverick
  else
    git -C /opt/maverick fetch --depth 1 origin "${MAVERICK_VERSION}" 2>/dev/null || true
    git -C /opt/maverick checkout "${MAVERICK_VERSION}" 2>/dev/null \
      || git -C /opt/maverick pull --ff-only
  fi
  # pipx names the venv after the distribution Name, which is
  # `maverick-agent` (packages/maverick-core/pyproject.toml), NOT the
  # `maverick` console-script. Every inject must target `maverick-agent`
  # or pipx errors with "Package maverick is not installed". (The desktop
  # install scripts already use the correct name.)
  pipx install /opt/maverick/packages/maverick-core --force
  pipx inject maverick-agent /opt/maverick/packages/maverick-shield
  pipx inject maverick-agent /opt/maverick/packages/maverick-channels
  pipx inject maverick-agent /opt/maverick/packages/maverick-dashboard
  pipx inject maverick-agent /opt/maverick/packages/maverick-mcp
  pipx inject maverick-agent /opt/maverick/apps/installer-cli
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
