"""Regression tests for devcontainer spec parsing security.

The `image` field is read from a repo-supplied devcontainer.json and placed
as the IMAGE positional in `docker run`. A leading-dash value is parsed by
docker's CLI as a flag (e.g. `--privileged`), which would negate the
--cap-drop ALL / no-new-privileges hardening. `_parse_devcontainer` must
reject option-like image values.
"""
from __future__ import annotations

import json

import pytest
from maverick.sandbox.devcontainer import _parse_devcontainer


def _write_devcontainer(tmp_path, image):
    p = tmp_path / "devcontainer.json"
    p.write_text(json.dumps({"image": image}), encoding="utf-8")
    return p


def test_parse_rejects_option_like_image(tmp_path):
    # `"image": "--privileged"` would inject a docker run flag that defeats the
    # sandbox's --cap-drop ALL / no-new-privileges hardening.
    p = _write_devcontainer(tmp_path, "--privileged")
    with pytest.raises(RuntimeError, match="option-like"):
        _parse_devcontainer(p)


@pytest.mark.parametrize(
    "bad",
    ["-v/etc:/host", "--mount=type=bind,src=/,dst=/host", "--network=host"],
)
def test_parse_rejects_other_flag_shapes(tmp_path, bad):
    p = _write_devcontainer(tmp_path, bad)
    with pytest.raises(RuntimeError, match="option-like"):
        _parse_devcontainer(p)


@pytest.mark.parametrize(
    "good",
    [
        "python:3.12-slim",
        "ubuntu:22.04",
        "ghcr.io/org/repo:tag",
        "registry.example.com:5000/team/img@sha256:" + "a" * 64,
    ],
)
def test_parse_accepts_normal_image(tmp_path, good):
    p = _write_devcontainer(tmp_path, good)
    spec = _parse_devcontainer(p)
    assert spec.image == good
