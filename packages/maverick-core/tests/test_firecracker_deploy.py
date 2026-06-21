"""Firecracker backend: the kernel/rootfs guidance points at real build scripts.

The backend tells operators to build the microVM kernel + rootfs with the
scripts under ``deploy/firecracker/``. Those scripts used to be referenced but
absent (a dangling pointer); these tests lock that they exist and that the
backend's missing-artifact error sends operators to them.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
_DEPLOY = _REPO / "deploy" / "firecracker"


class TestDeployArtifactsExist:
    @pytest.mark.parametrize("name", ["README.md", "fetch-kernel.sh", "build-rootfs.sh"])
    def test_artifact_present(self, name):
        assert (_DEPLOY / name).is_file(), f"missing deploy/firecracker/{name}"

    def test_scripts_are_executable(self):
        for s in ("fetch-kernel.sh", "build-rootfs.sh"):
            assert os.access(_DEPLOY / s, os.X_OK), f"{s} is not executable"

    def test_scripts_target_the_convention_path(self):
        # The backend reads ~/.maverick/firecracker/{kernel,rootfs}.img; the
        # build scripts must write there so the two halves line up.
        assert "firecracker/kernel.img" in (_DEPLOY / "fetch-kernel.sh").read_text()
        assert "firecracker/rootfs.img" in (_DEPLOY / "build-rootfs.sh").read_text()


class TestMissingKernelGuidance:
    def test_error_points_to_build_scripts(self, tmp_path, monkeypatch):
        # Pretend firecracker + firectl are installed so we reach _firectl, but
        # provide no kernel/rootfs -> the helpful build guidance must fire.
        import maverick.sandbox.firecracker as fc
        monkeypatch.setattr(fc.shutil, "which", lambda name: f"/usr/bin/{name}")
        monkeypatch.setattr(fc, "data_dir",
                            lambda *p: tmp_path.joinpath(*p))
        be = fc.FirecrackerBackend(workdir=tmp_path, provider="local")
        res = be.exec("echo hi")
        assert res.exit_code == 127
        assert "fetch-kernel.sh" in res.stderr
        assert "build-rootfs.sh" in res.stderr
