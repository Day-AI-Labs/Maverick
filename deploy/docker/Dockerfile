# Maverick — single-container image.
#
# Build:   docker build -f deploy/docker/Dockerfile -t maverick:latest .
# Run:     docker run -it --rm \
#            -v $HOME/.maverick:/root/.maverick \
#            -v $HOME/maverick-workspace:/workspace \
#            -e ANTHROPIC_API_KEY \
#            maverick:latest start "..."
#
# First run drops you into `maverick init` so the wizard can set up the
# config inside the mounted ~/.maverick directory.

FROM python:3.12-slim AS base

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

WORKDIR /workspace

# Default entrypoint is the maverick CLI. First run — if config is missing —
# helpfully points the user at `maverick init`.
ENTRYPOINT ["maverick"]
CMD ["--help"]
