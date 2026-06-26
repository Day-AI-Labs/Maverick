#!/usr/bin/env bash
# Fetch a Firecracker-compatible uncompressed Linux kernel (vmlinux) and place
# it where the firecracker sandbox backend looks: ~/.maverick/firecracker/kernel.img
#
# Firecracker boots an UNcompressed kernel (a raw vmlinux, not a bzImage). The
# Firecracker project publishes CI kernels in its S3 bucket; pin KERNEL_URL to a
# specific build for reproducibility. Override KERNEL_URL / DEST as needed.
set -euo pipefail

DEST="${DEST:-$HOME/.maverick/firecracker/kernel.img}"
ARCH="$(uname -m)"

# A Firecracker CI kernel for the host architecture. PIN this to a known-good
# build in your deployment; the 'latest' pointers below are a convenience.
case "$ARCH" in
  x86_64)  KERNEL_URL="${KERNEL_URL:-https://s3.amazonaws.com/spec.ccfc.min/firecracker-ci/v1.10/x86_64/vmlinux-5.10.bin}" ;;
  aarch64) KERNEL_URL="${KERNEL_URL:-https://s3.amazonaws.com/spec.ccfc.min/firecracker-ci/v1.10/aarch64/vmlinux-5.10.bin}" ;;
  *) echo "unsupported arch: $ARCH (set KERNEL_URL explicitly)" >&2; exit 2 ;;
esac

mkdir -p "$(dirname "$DEST")"

echo "Fetching kernel for $ARCH:"
echo "  $KERNEL_URL"
echo "  -> $DEST"

if command -v curl >/dev/null 2>&1; then
  curl -fSL --retry 3 -o "$DEST.tmp" "$KERNEL_URL"
elif command -v wget >/dev/null 2>&1; then
  wget -O "$DEST.tmp" "$KERNEL_URL"
else
  echo "need curl or wget" >&2; exit 1
fi

mv "$DEST.tmp" "$DEST"
chmod 0644 "$DEST"
echo "Kernel installed: $DEST"
