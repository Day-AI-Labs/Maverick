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

# Everything user-facing (the pipx venv, the wizard, the systemd service)
# runs as the human who invoked `sudo` -- or root for a direct-root install
# -- with one consistent HOME, so the `maverick` binary always lives at a
# single known path. Mixing a root install with a user-run service (and a
# %i that expands to empty) was why the service never started.
TARGET_USER="${SUDO_USER:-root}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
TARGET_HOME="${TARGET_HOME:-/root}"

log() { echo "==> $*" >&2; }

run_as_user() {
  # Run a command as TARGET_USER with their HOME set.
  if [[ "$TARGET_USER" == "root" ]]; then
    HOME="$TARGET_HOME" "$@"
  else
    sudo -u "$TARGET_USER" -H "$@"
  fi
}

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
  log "Installing maverick @ ${MAVERICK_VERSION} for user ${TARGET_USER}..."
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
  run_as_user pipx ensurepath || true
  run_as_user pipx install /opt/maverick/packages/maverick-core --force
  run_as_user pipx inject maverick-agent /opt/maverick/packages/maverick-shield
  run_as_user pipx inject maverick-agent /opt/maverick/packages/maverick-channels
  run_as_user pipx inject maverick-agent /opt/maverick/packages/maverick-dashboard
  run_as_user pipx inject maverick-agent /opt/maverick/packages/maverick-mcp
  run_as_user pipx inject maverick-agent /opt/maverick/apps/installer-cli
}

run_wizard() {
  log "Launching the setup wizard. Pick deployment=vps when asked."
  run_as_user "${TARGET_HOME}/.local/bin/maverick" init
}

install_service() {
  log "Installing systemd unit (User=${TARGET_USER}, home=${TARGET_HOME})..."
  # The unit ships with %i / /home/%i placeholders; render them to the
  # concrete install user + home so the service runs as the same user that
  # owns the pipx venv (and so /root vs /home/<user> is handled). Installing
  # the raw unit left %i empty -> User= empty + /home//... -> never started.
  sed -e "s#%i#${TARGET_USER}#g" -e "s#/home/${TARGET_USER}#${TARGET_HOME}#g" \
      /opt/maverick/deploy/vps/maverick.service \
    > /etc/systemd/system/maverick.service
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
