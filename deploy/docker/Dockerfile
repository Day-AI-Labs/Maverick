# Maverick — single-container image.
#
# Build:   docker build -f deploy/docker/Dockerfile -t maverick:latest .
# Run:     docker run -it --rm \
#            -v $HOME/.maverick:/home/maverick/.maverick \
#            -v $HOME/maverick-workspace:/workspace \
#            -e ANTHROPIC_API_KEY \
#            maverick:latest start "..."
#
# Runs as the unprivileged "maverick" user (uid/gid 1000), not root.
#
# First run drops you into `maverick init` so the wizard can set up the
# config inside the mounted ~/.maverick directory.

# Pin the base by digest for a reproducible build: override on the build command
# with --build-arg PYTHON_DIGEST=@sha256:<digest> (resolve it for your target
# arch via `docker buildx imagetools inspect python:3.12-slim`). Left as the
# floating tag by default so the public quickstart still builds unchanged.
ARG PYTHON_DIGEST=
FROM python:3.12-slim${PYTHON_DIGEST} AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# System deps for sqlite + git (skills, world model).
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy package manifests first for layer caching.
COPY pyproject.toml ./
COPY packages/maverick-core/pyproject.toml ./packages/maverick-core/
COPY packages/maverick-shield/pyproject.toml ./packages/maverick-shield/
COPY packages/maverick-channels/pyproject.toml ./packages/maverick-channels/
COPY packages/maverick-dashboard/pyproject.toml ./packages/maverick-dashboard/
COPY packages/maverick-mcp/pyproject.toml ./packages/maverick-mcp/
COPY apps/installer-cli/pyproject.toml ./apps/installer-cli/

# Copy package sources.
COPY packages/maverick-core ./packages/maverick-core
COPY packages/maverick-shield ./packages/maverick-shield
COPY packages/maverick-channels ./packages/maverick-channels
COPY packages/maverick-dashboard ./packages/maverick-dashboard
COPY packages/maverick-mcp ./packages/maverick-mcp
COPY apps/installer-cli ./apps/installer-cli

# Install everything. dashboard + mcp are needed so `maverick dashboard`
# and `maverick mcp` work in the image instead of exiting 2.
RUN pip install ./packages/maverick-core \
    && pip install ./packages/maverick-shield \
    && pip install ./packages/maverick-channels \
    && pip install ./packages/maverick-dashboard \
    && pip install ./packages/maverick-mcp \
    && pip install ./apps/installer-cli

# Run as an unprivileged user. Enterprise container policies (and most
# Kubernetes Pod Security Standards) reject containers running as root.
# uid/gid 1000 is conventional and stable so volume ownership is predictable.
# The state dir (~/.maverick -> /home/maverick/.maverick) and /workspace are
# owned by this user; mount host volumes with matching ownership.
RUN groupadd --gid 1000 maverick \
    && useradd --uid 1000 --gid 1000 --create-home --shell /usr/sbin/nologin maverick \
    && mkdir -p /workspace /home/maverick/.maverick \
    && chown -R maverick:maverick /workspace /home/maverick

ENV HOME=/home/maverick
USER maverick
WORKDIR /workspace

# Container-native liveness: probe the dashboard's auth-exempt /livez when the
# image is run as the dashboard. Harmless for the CLI/`start` use (the probe
# just reports unhealthy with no server listening); orchestrators that run the
# dashboard get a real health signal without a separate sidecar. Uses stdlib
# only (no curl in the slim base).
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8765/livez', timeout=3).status==200 else 1)" || exit 1

# Default entrypoint is the maverick CLI. First run — if config is missing —
# helpfully points the user at `maverick init`.
ENTRYPOINT ["maverick"]
CMD ["--help"]
