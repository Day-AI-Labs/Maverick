#!/usr/bin/env bash
# Devcontainer / Codespaces bootstrap: editable-install the workspace packages
# the same way CI does, so tests and the CLI work out of the box.
set -euo pipefail

pip install -e ./packages/maverick-core
pip install --no-deps -e ./packages/maverick-shield
pip install --no-deps -e ./packages/maverick-channels
pip install --no-deps -e ./packages/maverick-evolve
pip install --no-deps -e ./packages/maverick-dashboard
pip install --no-deps -e ./packages/maverick-mcp
pip install --no-deps -e ./packages/maverick-knowledge
pip install --no-deps -e ./apps/installer-cli

# Runtime deps the --no-deps installs dropped, plus the dev tooling.
pip install 'questionary>=2.0' 'rich>=13.7' \
            'fastapi>=0.110' 'uvicorn>=0.27' 'jinja2>=3.1' \
            'httpx>=0.27' 'python-multipart>=0.0.9'
# pyjwt[crypto] mirrors the CI test job (test_oidc.py self-skips without it).
# cffi: distro-owned cryptography builds (e.g. Debian's 41.x) lack
# _cffi_backend for this interpreter and crash pytest collection with a
# pyo3 PanicException; pip can't replace the distro package, but installing
# cffi fixes the import. build: so `python3 -m build --wheel` works per-package.
pip install pytest pytest-asyncio 'ruff>=0.5' 'vulture>=2.11' \
            'pyjwt[crypto]' cffi build
# openai: every OpenAI-compatible provider (openai/ollama/vllm/tgi/azure/...)
# imports it; without it a vllm:/ollama:-routed run dies at the provider.
pip install 'openai>=1.30'

echo
echo "Maverick devcontainer ready."
echo "  try:  maverick --help"
echo "  test: python3 -m pytest packages/maverick-core/tests -q"
