"""Release artifacts are Sigstore-signed (keyless) and verifiable.

Locks the supply-chain wiring: the release workflow signs every binary + the
SBOM with cosign keyless (needs `id-token: write`), and a verify script ships
for downstream users. Parsing the workflow keeps the wiring from silently
regressing (a dropped permission breaks keyless signing at release time, which
is hard to catch otherwise).
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
_RELEASE = _REPO / ".github" / "workflows" / "release.yml"
_VERIFY = _REPO / "deploy" / "verify-release.sh"


@pytest.fixture(scope="module")
def release_yaml():
    import yaml
    return yaml.safe_load(_RELEASE.read_text())


def _release_job(doc) -> dict:
    return doc["jobs"]["release"]


def test_release_job_has_id_token_permission(release_yaml):
    # Keyless cosign signing fails without OIDC token issuance.
    perms = _release_job(release_yaml)["permissions"]
    assert perms.get("id-token") == "write"


def test_release_signs_artifacts(release_yaml):
    steps = _release_job(release_yaml)["steps"]
    names = [s.get("name", "") for s in steps]
    assert any("cosign" in n.lower() for n in names), names
    sign_step = next(s for s in steps if "Sign release artifacts" in s.get("name", ""))
    run = sign_step["run"]
    assert "cosign sign-blob" in run
    assert "--output-signature" in run and "--output-certificate" in run


def test_cosign_installer_pinned(release_yaml):
    steps = _release_job(release_yaml)["steps"]
    uses = [s.get("uses", "") for s in steps]
    installer = [u for u in uses if u.startswith("sigstore/cosign-installer@")]
    assert installer, "cosign-installer action missing"
    # Pinned to a commit SHA, not a floating tag.
    assert "@" in installer[0] and len(installer[0].split("@", 1)[1].split(" ")[0]) == 40


def test_verify_script_present_and_executable():
    assert _VERIFY.is_file()
    assert os.access(_VERIFY, os.X_OK)
    body = _VERIFY.read_text()
    assert "cosign verify-blob" in body
    assert "--certificate-identity-regexp" in body
    assert "--certificate-oidc-issuer" in body
