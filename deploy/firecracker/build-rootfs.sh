#!/usr/bin/env bash
# Build an ext4 root filesystem for the Firecracker sandbox by exporting a
# container image's filesystem into a fresh ext4 image, then place it where the
# backend looks: ~/.maverick/firecracker/rootfs.img
#
# Run as root (or via sudo): populating the ext4 image needs a loopback mount.
#
#   sudo deploy/firecracker/build-rootfs.sh
#   IMAGE=python:3.12-slim ROOTFS_MB=2048 sudo -E deploy/firecracker/build-rootfs.sh
set -euo pipefail

IMAGE="${IMAGE:-ubuntu:24.04}"
ROOTFS_MB="${ROOTFS_MB:-1024}"
# Resolve the invoking user's home even under sudo so the artifact lands in the
# operator's ~/.maverick, not root's.
USER_HOME="${USER_HOME:-$(eval echo "~${SUDO_USER:-$USER}")}"
DEST="${DEST:-$USER_HOME/.maverick/firecracker/rootfs.img}"

for bin in docker mkfs.ext4; do
  command -v "$bin" >/dev/null 2>&1 || { echo "need $bin on PATH" >&2; exit 1; }
done
if [ "$(id -u)" -ne 0 ]; then
  echo "must run as root (loopback mount needed): re-run with sudo" >&2
  exit 1
fi

WORK="$(mktemp -d)"
MNT="$WORK/mnt"
cleanup() {
  mountpoint -q "$MNT" 2>/dev/null && umount "$MNT" || true
  rm -rf "$WORK"
}
trap cleanup EXIT
mkdir -p "$MNT" "$(dirname "$DEST")"

echo "[1/4] Exporting $IMAGE filesystem ..."
CID="$(docker create "$IMAGE" /bin/true)"
docker export "$CID" >"$WORK/rootfs.tar"
docker rm "$CID" >/dev/null

echo "[2/4] Creating ${ROOTFS_MB}MiB ext4 image ..."
dd if=/dev/zero of="$WORK/rootfs.img" bs=1M count="$ROOTFS_MB" status=none
mkfs.ext4 -q "$WORK/rootfs.img"

echo "[3/4] Populating rootfs ..."
mount -o loop "$WORK/rootfs.img" "$MNT"
tar -xf "$WORK/rootfs.tar" -C "$MNT"
# Firecracker runs the guest's /sbin/init; a minimal one that runs the command
# passed on the kernel cmdline is enough for the one-shot exec model. Most base
# images already ship an init; ensure /dev and a resolv.conf exist for tooling.
mkdir -p "$MNT/dev" "$MNT/proc" "$MNT/sys" "$MNT/work"
[ -e "$MNT/etc/resolv.conf" ] || echo "nameserver 1.1.1.1" >"$MNT/etc/resolv.conf"
sync
umount "$MNT"

echo "[4/4] Installing -> $DEST"
mv "$WORK/rootfs.img" "$DEST"
chown "${SUDO_USER:-$USER}" "$DEST" 2>/dev/null || true
chmod 0644 "$DEST"
echo "Rootfs installed: $DEST  (image=$IMAGE, ${ROOTFS_MB}MiB)"
