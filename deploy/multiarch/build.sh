#!/usr/bin/env bash
# Multi-architecture image build for Maverick (deploy/multiarch).
#
# Run from the REPO ROOT:
#   deploy/multiarch/build.sh                       # amd64 + arm64
#   PLATFORMS=linux/amd64,linux/arm64,linux/riscv64 deploy/multiarch/build.sh
#   PUSH=1 TAG=registry.example.com/maverick:0.1.6 deploy/multiarch/build.sh
#
# Cross-building needs QEMU binfmt handlers registered once per host:
#   docker run --privileged --rm tonistiigi/binfmt --install all
# (CI: run that exact command, or use docker/setup-qemu-action, before this
# script.)
#
# riscv64 is NOT in the default platform list: verify the base image first
# (see Dockerfile.multiarch header) and pass BASE_IMAGE=debian:sid-slim if
# the python:3.12-slim manifest lacks riscv64.
set -euo pipefail

PLATFORMS="${PLATFORMS:-linux/amd64,linux/arm64}"
TAG="${TAG:-maverick:multiarch}"
BASE_IMAGE="${BASE_IMAGE:-python:3.12-slim}"
INSTALL_DASHBOARD="${INSTALL_DASHBOARD:-0}"

if [ ! -f deploy/multiarch/Dockerfile.multiarch ]; then
    echo "error: run from the repo root (deploy/multiarch/build.sh)" >&2
    exit 1
fi

# A docker-container builder is required for multi-platform output.
BUILDER=maverick-multiarch
docker buildx inspect "$BUILDER" >/dev/null 2>&1 \
    || docker buildx create --name "$BUILDER" --driver docker-container

args=(
    --builder "$BUILDER"
    --platform "$PLATFORMS"
    --build-arg "BASE_IMAGE=$BASE_IMAGE"
    --build-arg "INSTALL_DASHBOARD=$INSTALL_DASHBOARD"
    -f deploy/multiarch/Dockerfile.multiarch
    -t "$TAG"
)

if [ "${PUSH:-0}" = "1" ]; then
    args+=(--push)
else
    # Multi-platform images cannot be --load'ed into the local daemon; keep
    # the result in the build cache and just validate the build.
    echo "note: PUSH=1 not set -> building without exporting (validation run)"
fi

docker buildx build "${args[@]}" .
