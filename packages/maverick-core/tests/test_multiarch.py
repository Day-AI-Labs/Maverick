"""Contract tests for the multi-arch build kit (deploy/multiarch).

hadolint is not available in the test environment, so this is the
documented fallback: basic invariant checks that the Dockerfile parses
structurally (ARG-before-FROM, known instructions only) and that the
arch-independence contract holds (no native-extra installs, gated riscv64
fallback, buildx + QEMU guidance present).
"""
from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_MA = _REPO_ROOT / "deploy" / "multiarch"
_DOCKERFILE = _MA / "Dockerfile.multiarch"

_KNOWN_INSTRUCTIONS = {
    "FROM", "ARG", "ENV", "RUN", "COPY", "WORKDIR", "ENTRYPOINT", "CMD",
}


def _instructions() -> list[str]:
    lines: list[str] = []
    continued = False
    for raw in _DOCKERFILE.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if continued:
            continued = line.endswith("\\")
            continue
        lines.append(line)
        continued = line.endswith("\\")
    return lines


def test_dockerfile_parses_with_known_instructions_only():
    instructions = _instructions()
    assert instructions, "empty Dockerfile"
    for line in instructions:
        word = line.split()[0]
        assert word in _KNOWN_INSTRUCTIONS, f"unknown instruction: {line!r}"


def test_base_image_is_arg_gated_with_slim_default():
    instructions = _instructions()
    # ARG BASE_IMAGE must precede FROM so --build-arg can swap in the
    # riscv64 fallback base (debian sid/trixie).
    arg_idx = next(i for i, line in enumerate(instructions)
                   if line.startswith("ARG BASE_IMAGE"))
    from_idx = next(i for i, line in enumerate(instructions)
                    if line.startswith("FROM"))
    assert arg_idx < from_idx
    assert "ARG BASE_IMAGE=python:3.12-slim" in instructions[arg_idx]
    assert instructions[from_idx].startswith("FROM ${BASE_IMAGE}")


def test_riscv64_fallback_is_gated_not_assumed():
    text = _DOCKERFILE.read_text()
    # Conditional CPython bootstrap for bare-Debian bases...
    assert "command -v python3" in text
    # ...and the README-documented verification step, stated in the header.
    assert "docker manifest inspect python:3.12-slim" in text
    assert "debian:sid-slim" in text


def test_image_stays_pure_python_by_default():
    text = _DOCKERFILE.read_text()
    assert "pip install ./packages/maverick-core" in text
    # Dashboard (pydantic-core, compiled Rust) is opt-in.
    assert "ARG INSTALL_DASHBOARD=0" in text
    # No native-wheel extras may sneak into the default install.
    run_lines = [line for line in _instructions() if line.startswith("RUN")]
    joined = " ".join(run_lines)
    for native in ("torch", "grpcio", "pyarrow", "playwright"):
        assert native not in joined, native
    assert not re.search(r"pip install \S*\[", joined), "no extras in the image"
    assert 'ENTRYPOINT ["maverick"]' in text


def test_build_script_targets_multiple_platforms_via_buildx():
    text = (_MA / "build.sh").read_text()
    assert "docker buildx build" in text
    assert "linux/amd64,linux/arm64" in text
    assert "linux/riscv64" in text          # documented, opt-in
    assert "tonistiigi/binfmt --install all" in text  # QEMU prerequisite
    assert "Dockerfile.multiarch" in text


def test_readme_is_honest_about_riscv64_and_extras():
    text = (_MA / "README.md").read_text()
    assert re.search(r"could not be\s+verified", text, re.I)
    # The known wheel gaps must be listed per extra.
    for native in ("grpcio", "torch", "pyarrow", "pydantic-core"):
        assert native in text, native
    assert "setup-qemu-action" in text
