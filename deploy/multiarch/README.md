# multiarch — ARM and RISC-V image builds

Multi-architecture container builds for the Lightwork runtime:
`Dockerfile.multiarch` + `build.sh` (docker buildx) targeting
**linux/amd64**, **linux/arm64**, and — gated, see below — **linux/riscv64**.

```bash
# one-time per host: register QEMU binfmt handlers for cross-builds
docker run --privileged --rm tonistiigi/binfmt --install all

# amd64 + arm64 (default)
deploy/multiarch/build.sh

# push a tagged multi-arch manifest
PUSH=1 TAG=registry.example.com/maverick:0.1.6 deploy/multiarch/build.sh
```

## Why this mostly Just Works: the core is pure Python

`maverick-core`'s hard dependencies — `anthropic`, `click`, `httpx`,
`tomli` — are pure-Python wheels, i.e. **architecture-independent**. The
same is true of `maverick-shield` (the wrapper has zero hard deps). So the
base image's CPython is the only native code in the default build, and the
image works on any arch the base supports.

## riscv64 base image: checked honestly

- `python:3.12-slim` publishes **amd64 and arm64** (and more); whether the
  current tag also publishes **riscv64** depends on its Debian base —
  riscv64 became an official Debian arch with *trixie*. This **could not be
  verified from the authoring environment** (no Docker daemon, no registry
  access). Verify on your build host:

  ```bash
  docker manifest inspect python:3.12-slim | grep -i riscv64
  ```

- **Gated fallback** if the manifest lacks riscv64: build from a Debian
  base that ships riscv64 (sid/trixie) — the Dockerfile detects the missing
  CPython and installs it from apt:

  ```bash
  PLATFORMS=linux/riscv64 BASE_IMAGE=debian:sid-slim deploy/multiarch/build.sh
  ```

## Optional extras: native-wheel availability (per `packages/maverick-core/pyproject.toml`)

The default image installs **no extras**, exactly to stay arch-independent.
If you add extras, this is the honest wheel situation (PyPI wheel tags as
of authoring; re-check before relying on it):

| Extra(s) | Native dep | arm64 | riscv64 |
|---|---|---|---|
| `grpc`, `weaviate` | grpcio / grpcio-tools | wheels | **no wheels** — C++ source build (heavy); usually skip |
| `training` | torch | wheels (CPU) | **unsupported upstream** — skip |
| `pandas` | pandas, pyarrow | wheels | **no wheels** — pyarrow source build is a major undertaking; skip |
| `chroma`, `qdrant`, `embeddings` | onnxruntime (via chromadb/fastembed) | wheels | **no wheels** — skip |
| `voice` | ctranslate2 (via faster-whisper) | wheels | **no wheels** — skip |
| `capture`, `browser` | playwright (bundled browsers) | supported | **unsupported** — no riscv64 browser builds |
| `audit-signing`, `oidc` | cryptography | wheels | no wheels — source build needs Rust + OpenSSL headers (works, slow) |
| `zstd` | zstandard (cffi) | wheels | no wheels — C source build (apt `gcc` + `python3-dev`; fine) |
| `postgres` | psycopg[binary] | binary wheels | no binary wheel — use pure `psycopg` + system libpq instead |
| `calendar` | lxml (via caldav) | wheels | no wheels — source build needs libxml2/libxslt headers |
| `computer-use`, `pdf` | pillow | wheels | no wheels — source build needs libjpeg/zlib headers |
| `mongodb` | pymongo C extensions | wheels | sdist falls back to pure Python automatically (slower, works) |
| dashboard (`maverick-dashboard`) | pydantic-core (Rust, via fastapi) | wheels | no wheels — source build needs a Rust toolchain. This is why `INSTALL_DASHBOARD` defaults to 0 |
| everything else (`openai`/provider extras, `math`, `queue`, `redis`, `s3`, `websocket`, `observability`, session extras, ...) | — pure Python | works | works |

## CI guidance

Cross-builds emulate foreign arches with QEMU; register binfmt first.

```yaml
# GitHub Actions
- uses: docker/setup-qemu-action@v3        # registers binfmt handlers
- uses: docker/setup-buildx-action@v3
- run: PLATFORMS=linux/amd64,linux/arm64 deploy/multiarch/build.sh
```

Plain runner / other CI:

```bash
docker run --privileged --rm tonistiigi/binfmt --install all
deploy/multiarch/build.sh
```

Notes:
- QEMU-emulated riscv64 builds are *slow* (the apt fallback installs
  CPython under emulation); budget tens of minutes or use a native runner.
- Multi-platform results can't be `--load`ed into the local daemon;
  `build.sh` builds-to-cache for validation unless `PUSH=1`.

## What was and wasn't verified here

Authored + statically contract-tested
(`packages/maverick-core/tests/test_multiarch.py`); **no image was built in
this environment** (no Docker daemon, no hadolint), and the riscv64 base
availability is documented as a check-on-your-host step rather than
asserted. The first `build.sh` run on a Docker-capable host is the smoke
test.
