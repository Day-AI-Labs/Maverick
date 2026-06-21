# Firecracker microVM sandbox — kernel + rootfs

The `firecracker` sandbox backend
(`maverick/sandbox/firecracker.py`, `provider="local"`) boots a one-shot
[Firecracker](https://github.com/firecracker-microvm/firecracker) microVM per
command via `firectl`, giving kernel-level isolation that a Docker namespace
boundary can't. It expects two artifacts, by convention, under
`~/.maverick/firecracker/`:

| File | What it is |
|------|------------|
| `kernel.img` | An uncompressed Linux kernel (`vmlinux`) Firecracker can boot. |
| `rootfs.img` | An `ext4` root filesystem image with a shell + your toolchain. |

These are host- and distro-specific, so they are **not** shipped in the wheel —
build them once with the scripts here. Until both exist, the backend returns a
clear `exit_code=127` pointing back at this README rather than silently
downgrading isolation.

## Prerequisites

- A Linux host with KVM (`/dev/kvm` present and accessible).
- `firecracker` and `firectl` on `PATH`
  ([getting-started](https://github.com/firecracker-microvm/firecracker/blob/main/docs/getting-started.md)).
- `docker` (used by `build-rootfs.sh` to export a filesystem) and `e2fsprogs`
  (`mkfs.ext4`). Root (or `sudo`) is needed to populate the ext4 image.

## Build

```bash
# 1. Fetch a Firecracker-compatible uncompressed kernel -> ~/.maverick/firecracker/kernel.img
deploy/firecracker/fetch-kernel.sh

# 2. Build an ext4 rootfs from a container image -> ~/.maverick/firecracker/rootfs.img
#    Defaults to the maverick sandbox image; override with IMAGE=...
sudo deploy/firecracker/build-rootfs.sh
```

Then point the agent at it:

```toml
# ~/.maverick/config.toml
[sandbox]
backend  = "firecracker"
provider = "local"        # or "e2b" for E2B's hosted Firecracker (needs E2B_API_KEY)
network  = "egress-deny"  # egress-deny | egress-allow | bridge=<tap-name>
```

## Notes

- **Network.** `egress-deny` boots with `--no-network` (no NIC in the guest).
  `bridge=<name>` attaches a pre-created host TAP device; you own its firewall
  rules. `egress-allow` assumes the host default route is reachable.
- **Sizing.** The backend boots the VM with 1 vCPU / 512 MiB by default
  (`_firectl`). Adjust the rootfs size in `build-rootfs.sh` (`ROOTFS_MB`).
- **Hosted alternative.** If you don't want to operate Firecracker yourself,
  set `provider = "e2b"` and `E2B_API_KEY` — same `.exec()` interface, no
  kernel/rootfs to build.
- **Reproducibility.** Pin `KERNEL_URL` (in `fetch-kernel.sh`) and the source
  `IMAGE` digest so every host builds the same guest.
