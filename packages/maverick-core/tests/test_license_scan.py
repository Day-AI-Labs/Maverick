"""License compliance scanner (ROADMAP 2028 H1)."""
from __future__ import annotations

from maverick.license_scan import (
    classify_license,
    policy_check,
    scan_distributions,
)


def test_classify_permissive():
    assert classify_license("MIT License") == "permissive"
    assert classify_license("Apache Software License 2.0") == "permissive"
    assert classify_license("BSD-3-Clause") == "permissive"
    assert classify_license("ISC") == "permissive"


def test_classify_copyleft_ordering():
    # AGPL/LGPL must win over the bare 'GPL' substring.
    assert classify_license("GNU Affero General Public License v3") == "strong-copyleft"
    assert classify_license("GNU Lesser General Public License v2.1") == "weak-copyleft"
    assert classify_license("GPLv3") == "strong-copyleft"
    assert classify_license("Mozilla Public License 2.0") == "weak-copyleft"
    # SSPL (MongoDB) is strong-copyleft and toxic to enterprise procurement.
    assert classify_license("Server Side Public License v1") == "strong-copyleft"
    assert classify_license("SSPL") == "strong-copyleft"


def test_classify_public_domain_and_unknown():
    assert classify_license("The Unlicense") == "public-domain"
    assert classify_license("CC0 1.0") == "public-domain"
    assert classify_license("") == "unknown"
    assert classify_license("Some Custom Thing") == "unknown"
    assert classify_license("Other/Proprietary License") == "proprietary"


class _Meta(dict):
    def __init__(self, d, classifiers=None):
        super().__init__(d)
        self._classifiers = classifiers or []

    def get_all(self, key):
        return self._classifiers if key == "Classifier" else []


class _Dist:
    def __init__(self, meta):
        self.metadata = meta
        self.name = meta.get("Name")


def test_scan_reads_license_field_and_classifiers():
    dists = [
        _Dist(_Meta({"Name": "permissive-pkg", "Version": "1.0",
                     "License": "MIT License"})),
        _Dist(_Meta({"Name": "trove-pkg", "Version": "2.0", "License": "UNKNOWN"},
                    classifiers=["License :: OSI Approved :: "
                                 "GNU General Public License v3 (GPLv3)"])),
    ]
    scanned = scan_distributions(dists)
    by_name = {r["name"]: r for r in scanned}
    assert by_name["permissive-pkg"]["category"] == "permissive"
    assert by_name["trove-pkg"]["category"] == "strong-copyleft"


def test_policy_check_flags_strong_copyleft_by_default():
    scanned = [
        {"name": "ok", "version": "1", "license": "MIT", "category": "permissive"},
        {"name": "bad", "version": "1", "license": "GPLv3",
         "category": "strong-copyleft"},
    ]
    violations = policy_check(scanned)
    assert [v["name"] for v in violations] == ["bad"]


def test_policy_check_custom_denylist():
    scanned = [
        {"name": "lgpl", "version": "1", "license": "LGPL", "category": "weak-copyleft"},
    ]
    assert policy_check(scanned, {"weak-copyleft"})
    assert not policy_check(scanned, {"strong-copyleft"})


def test_scan_dedups_by_name():
    dists = [
        _Dist(_Meta({"Name": "dup", "Version": "1.0", "License": "MIT"})),
        _Dist(_Meta({"Name": "dup", "Version": "2.0", "License": "MIT"})),
    ]
    assert len(scan_distributions(dists)) == 1
