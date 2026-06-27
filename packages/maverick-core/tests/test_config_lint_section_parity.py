"""config-lint and migrate must agree on which sections the runtime reads.

Client-journey finding (round 6): a client configured the documented
provider-failover resilience feature --

    [provider_failover.chains]
    "gpt-5.4" = ["vllm:stub-1"]

-- and `maverick config-lint` flagged [provider_failover] as an unknown
section ("did you mean providers?"), the same stale-registry bug as the
round-5 [audit]/[capabilities] fix. migrate.py's KNOWN_SECTIONS (curated from
the real load_config() call sites) listed it; config_lint's KNOWN_SCHEMA did
not -- the two registries had drifted by ~59 sections ([enterprise], [egress],
[governance], [finance], [encryption], [telemetry], ...). config_lint now
sources migrate's set so they can't drift again.
"""
from __future__ import annotations

from maverick.config_lint import KNOWN_SCHEMA, lint_config
from maverick.migrate import KNOWN_SECTIONS


def test_every_runtime_section_is_known_to_config_lint():
    missing = sorted(set(KNOWN_SECTIONS) - set(KNOWN_SCHEMA))
    assert not missing, f"config-lint would false-flag real sections: {missing}"


def test_registries_are_bidirectionally_consistent():
    # Neither tool may flag a section the other recognizes as real -- a2a
    # (read by a2a.py) and deployment (wizard-written) were known to
    # config-lint but flagged by migrate (round-6 finding).
    lint_only = sorted(set(KNOWN_SCHEMA) - set(KNOWN_SECTIONS))
    assert not lint_only, f"migrate would false-flag real sections: {lint_only}"


def test_provider_failover_lints_clean():
    cfg = {"provider_failover": {"chains": {"gpt-5.4": ["vllm:stub-1"]}}}
    unknown = [f for f in lint_config(cfg) if "unknown" in f.message.lower()]
    assert not unknown, [f.message for f in unknown]


def test_sampling_of_governance_sections_lint_clean():
    cfg = {
        "enterprise": {"mode": "on"},
        "egress": {"deny": ["*"]},
        "governance": {"policy": "strict"},
        "encryption": {"at_rest": True},
        "telemetry": {"failure_modes": True},
    }
    unknown = [f for f in lint_config(cfg) if "unknown" in f.message.lower()]
    assert not unknown, [f.message for f in unknown]


def test_self_learning_lifecycle_sections_lint_clean():
    # The learning lifecycle the wizard offers -- all read by real load_config()
    # call sites -- must not be flagged "unknown". These shipped as unknown:
    # config-lint even suggested "self_harness -> did you mean self_learning?",
    # a *different* feature, which would silently disable self-harness.
    cfg = {s: {"enable": True} for s in (
        "self_harness", "self_improvement", "dreaming",
        "fleet_memory", "rehearsal", "memory_guard")}
    unknown = [f for f in lint_config(cfg) if "unknown" in f.message.lower()]
    assert not unknown, [f.message for f in unknown]


def test_genuinely_unknown_section_still_flagged():
    findings = lint_config({"totally_made_up_section": {"x": 1}})
    assert any("unknown" in f.message.lower() for f in findings)
