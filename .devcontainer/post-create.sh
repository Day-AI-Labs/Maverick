#!/usr/bin/env bash
# Devcontainer / Codespaces post-create: install Maverick (editable) so the
# `maverick` CLI, tests, and dashboard all work in the dev environment.
set -euxo pipefail

python -m pip install --upgrade pip

# maverick-core first; downstream packages use --no-deps (mirrors CI).
pip install -e ./packages/maverick-core
pip install --no-deps -e ./packages/maverick-shield
pip install --no-deps -e ./packages/maverick-channels
pip install --no-deps -e ./packages/maverick-evolve
pip install --no-deps -e ./packages/maverick-dashboard
pip install --no-deps -e ./packages/maverick-mcp
pip install --no-deps -e ./packages/maverick-knowledge
pip install --no-deps -e ./apps/installer-cli

# Runtime deps the --no-deps installs dropped + the test toolchain.
pip install 'questionary>=2.0' 'rich>=13.7' \
            'fastapi>=0.110' 'uvicorn>=0.27' 'jinja2>=3.1' \
            'httpx>=0.27' 'python-multipart>=0.0.9' \
            pytest pytest-asyncio ruff

echo "Maverick dev environment ready. Try: maverick init --fast && maverick start \"hello\""
