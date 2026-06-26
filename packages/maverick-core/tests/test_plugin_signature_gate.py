"""The plugin load gate enforces the signing CA when configured (fail-closed).

Regression for the council finding that ``plugin_ca.verify_artifact`` existed
but was wired into no loader, so the CA gated nothing. ``_gate`` now refuses an
unsigned/invalid plugin when ``[plugins] ca_root_pubkey`` / ``require_signing``
(or enterprise mode) is on, and stays a no-op in the default config.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

cryptography = pytest.importorskip("cryptography")

from maverick import plugin_ca, plugins  # noqa: E402


class _FakeDist:
    def __init__(self, root: Path, files: list[str]):
        self._root = root
        self.files = [Path(f) for f in files]

    def locate_file(self, f):
        return self._root / f


class _FakeEP:
    def __init__(self, dist):
        self.name = "acme_tool"
        self.value = "myplugin.tools:reg"
        self.module = "myplugin.tools"
        self.dist = dist


def _signed_plugin(tmp_path: Path, *, extra_files: dict[str, str] | None = None):
    ca = plugin_ca.PluginCA(tmp_path / "ca")
    ca.init_root()
    priv, pub = plugin_ca.new_publisher_keypair()
    cert = ca.issue("acme", pub)
    mod = tmp_path / "myplugin" / "tools.py"
    mod.parent.mkdir(parents=True)
    mod.write_text("def reg():\n    return []\n", encoding="utf-8")
    files = ["myplugin/tools.py", "maverick_plugin.sig.json"]
    for rel, body in (extra_files or {}).items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        files.append(rel)
    ep = _FakeEP(_FakeDist(tmp_path, files))
    manifest = plugins._expected_plugin_signature_manifest(ep)
    assert manifest is not None
    bundle = plugin_ca.sign_digest(
        plugins._plugin_manifest_digest(manifest), publisher_priv_hex=priv, cert=cert
    )
    bundle["manifest"] = manifest
    (tmp_path / "maverick_plugin.sig.json").write_text(json.dumps(bundle))
    return ca, mod


def test_valid_signature_passes(tmp_path):
    ca, _ = _signed_plugin(tmp_path)
    ep = _FakeEP(_FakeDist(tmp_path, ["myplugin/tools.py", "maverick_plugin.sig.json"]))
    assert plugins._plugin_signature_ok(ep, ca.root_pub(), set()) is True


def test_unsigned_package_file_refused(tmp_path):
    ca, _ = _signed_plugin(tmp_path)
    init = tmp_path / "myplugin" / "__init__.py"
    init.write_text("raise RuntimeError('unsigned code executed')\n", encoding="utf-8")
    ep = _FakeEP(_FakeDist(
        tmp_path, ["myplugin/__init__.py", "myplugin/tools.py", "maverick_plugin.sig.json"]
    ))
    assert plugins._plugin_signature_ok(ep, ca.root_pub(), set()) is False


def test_signed_package_file_passes(tmp_path):
    ca, _ = _signed_plugin(tmp_path, extra_files={"myplugin/__init__.py": "SAFE = True\n"})
    ep = _FakeEP(_FakeDist(
        tmp_path, ["myplugin/__init__.py", "myplugin/tools.py", "maverick_plugin.sig.json"]
    ))
    assert plugins._plugin_signature_ok(ep, ca.root_pub(), set()) is True


def test_wrong_root_refused(tmp_path):
    _signed_plugin(tmp_path)
    ep = _FakeEP(_FakeDist(tmp_path, ["myplugin/tools.py", "maverick_plugin.sig.json"]))
    assert plugins._plugin_signature_ok(ep, "00" * 32, set()) is False


def test_require_without_anchor_fails_closed(tmp_path):
    ca, _ = _signed_plugin(tmp_path)
    ep = _FakeEP(_FakeDist(tmp_path, ["myplugin/tools.py", "maverick_plugin.sig.json"]))
    # require_signing on, but no root pubkey -> cannot be satisfied safely.
    assert plugins._plugin_signature_ok(ep, None, set()) is False


def test_missing_bundle_fails_closed(tmp_path):
    ca, _ = _signed_plugin(tmp_path)
    ep = _FakeEP(_FakeDist(tmp_path, ["myplugin/tools.py"]))  # no sig bundle shipped
    assert plugins._plugin_signature_ok(ep, ca.root_pub(), set()) is False


def test_tampered_module_refused(tmp_path):
    ca, mod = _signed_plugin(tmp_path)
    mod.write_text("def reg():\n    return ['EVIL']\n", encoding="utf-8")  # post-sign edit
    ep = _FakeEP(_FakeDist(tmp_path, ["myplugin/tools.py", "maverick_plugin.sig.json"]))
    assert plugins._plugin_signature_ok(ep, ca.root_pub(), set()) is False


def test_revoked_cert_refused(tmp_path):
    ca, _ = _signed_plugin(tmp_path)
    ep = _FakeEP(_FakeDist(tmp_path, ["myplugin/tools.py", "maverick_plugin.sig.json"]))
    bundle = json.loads((tmp_path / "maverick_plugin.sig.json").read_text())
    serial = bundle["cert"]["serial"]
    assert plugins._plugin_signature_ok(ep, ca.root_pub(), {serial}) is False


def test_default_config_is_noop():
    # With no ca_root_pubkey / require_signing / enterprise, signing is off.
    root, require, revoked = plugins._plugin_signing_policy()
    assert require is False and root is None and revoked == set()
