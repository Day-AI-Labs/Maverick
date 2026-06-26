#!/usr/bin/env bash
# Maverick VPS bootstrap script.
#
# Usage (defaults to the latest published release for a reproducible install):
#   curl -sSL https://raw.githubusercontent.com/Day-AI-Labs/Maverick/main/deploy/vps/install.sh | sudo bash
#
# Or pin to a specific tag / full commit SHA:
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

# Default to the latest *published release* for a reproducible, reviewed install
# rather than the mutable `main` branch (supply-chain hardening). An explicit
# MAVERICK_VERSION (tag or full SHA) always wins; if no release can be resolved
# (offline, or none published yet) we fall back to `main` with a loud warning.
resolve_default_version() {
  local tag
  tag="$(curl -fsSL https://api.github.com/repos/Day-AI-Labs/Maverick/releases/latest 2>/dev/null \
         | grep -m1 '"tag_name"' \
         | sed -E 's/.*"tag_name"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/' || true)"
  if [[ -n "${tag}" ]]; then printf '%s' "${tag}"; else printf 'main'; fi
}
MAVERICK_VERSION="${MAVERICK_VERSION:-$(resolve_default_version)}"

# Everything user-facing (the pipx venv, the wizard, the systemd service)
# runs as one non-root account with one consistent HOME, so the `maverick`
# binary always lives at a single known path. For sudo installs we use the
# invoking human; for direct-root installs we create/use a dedicated service
# account instead of running the remotely driven agent as root.
SERVICE_ACCOUNT="${MAVERICK_SERVICE_USER:-maverick}"
if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
  TARGET_USER="$SUDO_USER"
else
  TARGET_USER="$SERVICE_ACCOUNT"
fi
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6 || true)"
TARGET_HOME="${TARGET_HOME:-/var/lib/${TARGET_USER}}"

log() { echo "==> $*" >&2; }

run_as_user() {
  # Run a command as TARGET_USER with their HOME set.
  sudo -u "$TARGET_USER" -H "$@"
}

require_root() {
  if [[ $EUID -ne 0 ]]; then
    echo "This script must be run as root (try: sudo bash install.sh)" >&2
    exit 1
  fi
}

ensure_target_user() {
  if [[ "$TARGET_USER" == "root" ]]; then
    echo "Refusing to install Maverick as root; choose a non-root sudo user or set MAVERICK_SERVICE_USER." >&2
    exit 1
  fi

  if ! id -u "$TARGET_USER" >/dev/null 2>&1; then
    log "Creating dedicated Maverick service user ${TARGET_USER} (${TARGET_HOME})..."
    useradd --system --create-home --home-dir "$TARGET_HOME" --shell /usr/sbin/nologin "$TARGET_USER"
  else
    log "Using existing Maverick install user ${TARGET_USER} (${TARGET_HOME})..."
    if [[ ! -d "$TARGET_HOME" ]]; then
      primary_group="$(id -gn "$TARGET_USER")"
      install -d -o "$TARGET_USER" -g "$primary_group" "$TARGET_HOME"
    fi
  fi
}

install_system_deps() {
  log "Installing system packages..."
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv pipx \
    git curl ca-certificates sqlite3 sudo
  pipx ensurepath || true
}

install_maverick() {
  # Supply-chain warning: installing from the mutable `main` branch (the default
  # when MAVERICK_VERSION is unset) means a `curl | sudo bash` bootstrap runs
  # whatever main points at right now -- not a reviewed, immutable revision. For
  # a production VPS, pin a released tag or a full commit SHA:
  #   curl -sSL ...install.sh | sudo MAVERICK_VERSION=v0.1.6 bash
  if [[ "${MAVERICK_VERSION}" == "main" ]]; then
    log "WARNING: installing from the mutable 'main' branch. For a reproducible,"
    log "         reviewable install, set MAVERICK_VERSION to a release tag or a"
    log "         full commit SHA (see the usage header)."
  fi
  log "Installing maverick @ ${MAVERICK_VERSION} for user ${TARGET_USER}..."
  if [[ ! -d /opt/maverick ]]; then
    git clone --branch "${MAVERICK_VERSION}" --depth 1 \
        https://github.com/Day-AI-Labs/Maverick /opt/maverick \
      || git clone https://github.com/Day-AI-Labs/Maverick /opt/maverick
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
  ensure_target_user
  install_system_deps
  install_maverick
  run_wizard
  install_service
  log "Done. Tail logs with:  journalctl -u maverick -f"
}

main "$@"
