"""Release artifacts are Sigstore-signed (keyless) and verifiable.

Locks the supply-chain wiring: the release workflow signs every binary + the
SBOM with cosign keyless (needs `id-token: write`), and a verify script ships
for downstream users. Asserted as text (no yaml dep -- the kernel test env
doesn't install pyyaml) so a dropped permission/step is caught at PR time.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_RELEASE_TEXT = (_REPO / ".github" / "workflows" / "release.yml").read_text()
_VERIFY = _REPO / "deploy" / "verify-release.sh"


def test_release_job_has_id_token_permission():
    # Keyless cosign signing fails without OIDC token issuance. The permission
    # appears only in the release job (the binaries job doesn't grant it).
    assert "id-token: write" in _RELEASE_TEXT


def test_release_signs_artifacts():
    assert "cosign sign-blob" in _RELEASE_TEXT
    assert "--output-signature" in _RELEASE_TEXT
    assert "--output-certificate" in _RELEASE_TEXT


def test_cosign_installer_pinned_to_sha():
    m = re.search(r"sigstore/cosign-installer@([0-9a-f]+)", _RELEASE_TEXT)
    assert m, "cosign-installer action missing"
    assert len(m.group(1)) == 40, "cosign-installer must be pinned to a commit SHA"


def test_verify_script_present_and_executable():
    assert _VERIFY.is_file()
    assert os.access(_VERIFY, os.X_OK)
    body = _VERIFY.read_text()
    assert "cosign verify-blob" in body
    assert "--certificate-identity-regexp" in body
    assert "--certificate-oidc-issuer" in body


def test_verify_script_requires_exact_release_tag():
    body = _VERIFY.read_text()
    assert "usage: verify-release.sh <artifact> <release-tag> [sig] [cert]" in body
    assert 'TAG="$2"' in body
    assert "@refs/tags/${ESCAPED_TAG}$" in body
    assert "refs/tags/v.*" not in body
    assert 'IDENTITY_REGEXP="${IDENTITY_REGEXP:-' not in body
