"""Contract tests for the Windows MSI authoring (apps/installer-msi).

Static validation only — building/installing the MSI needs WiX v4 on a
Windows host. These tests pin the invariants that must survive edits: the
.wxs is well-formed XML, the UpgradeCode is present and stable (product
family identity for MajorUpgrade), the install is per-user, and nothing
hardcodes a developer's local paths.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_WXS = _HERE / "Package.wxs"
_NS = "{http://wixtoolset.org/schemas/v4/wxs}"

# The product family identity. NEVER change this value: MajorUpgrade matches
# installed versions by UpgradeCode, so a new GUID breaks upgrades into
# side-by-side installs. (Mirrored in Package.wxs.)
_UPGRADE_CODE = "9E2B7C41-6A8D-4F3B-8E5A-2C90D17B4F6E"


def _package() -> ET.Element:
    root = ET.parse(_WXS).getroot()
    assert root.tag == f"{_NS}Wix"
    pkg = root.find(f"{_NS}Package")
    assert pkg is not None, "Package element missing"
    return pkg


def test_wxs_is_wellformed_wix4_xml():
    _package()  # ET.parse raises on malformed XML; tag asserts pin the v4 namespace


def test_upgrade_code_present_and_stable():
    assert _package().get("UpgradeCode") == _UPGRADE_CODE


def test_major_upgrade_rule_declared():
    pkg = _package()
    up = pkg.find(f"{_NS}MajorUpgrade")
    assert up is not None, "MajorUpgrade element missing"
    assert up.get("DowngradeErrorMessage")


def test_per_user_install_default():
    assert _package().get("Scope") == "perUser"


def test_path_component_edits_user_path_only():
    pkg = _package()
    envs = pkg.findall(f".//{_NS}Environment")
    path_envs = [e for e in envs if e.get("Name") == "PATH"]
    assert len(path_envs) == 1, "expected exactly one PATH Environment component"
    env = path_envs[0]
    assert env.get("System") == "no"        # never the machine PATH on perUser
    assert env.get("Part") == "last"        # append, don't clobber
    assert env.get("Permanent") == "no"     # removed on uninstall
    assert env.get("Value") == "[BINFOLDER]"


def test_no_hardcoded_user_paths():
    # Sources must be relative or come from -d preprocessor vars, never a
    # developer's machine layout.
    for name in ("Package.wxs", "maverick.cmd", "build.ps1"):
        text = (_HERE / name).read_text()
        assert not re.search(r"[A-Za-z]:\\Users\\|/home/|/Users/", text), name


def test_launcher_uses_console_script_entry_point():
    # There is no maverick/__main__.py, so `py -m maverick` cannot work; the
    # launcher must go through maverick.cli:main and locate the bundled wheel
    # relative to itself.
    cmd = (_HERE / "maverick.cmd").read_text()
    assert "from maverick.cli import main" in cmd
    assert "%~dp0" in cmd
    assert re.search(r"py -3? -m maverick\b", cmd) is None


def test_build_script_invokes_wix_v4():
    ps1 = (_HERE / "build.ps1").read_text()
    assert "wix build" in ps1
    assert "WheelPath" in ps1 and "ProductVersion" in ps1
