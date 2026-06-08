"""Risk classification for mutating enterprise REST connectors."""

from __future__ import annotations

import pytest

ENTERPRISE_REST_CONNECTORS = (
    "kubernetes",
    "openshift",
    "vsphere",
    "azure",
    "gcp",
    "ibm_cloud",
    "alibaba_cloud",
    "sentinel",
    "defender",
    "qradar",
    "palo_alto",
    "jamf",
    "ringcentral",
    "vonage",
    "webex",
    "neo4j",
    "teradata",
    "microstrategy",
    "cognos",
    "concur",
    "anaplan",
    "smartrecruiters",
    "gainsight",
    "amplitude",
)


@pytest.mark.parametrize("name", ENTERPRISE_REST_CONNECTORS)
def test_mutating_enterprise_rest_connectors_are_high_risk(name: str):
    from maverick.safety.tool_risk import tool_risk

    assert tool_risk(name) == "high"


def test_medium_risk_ceiling_drops_mutating_enterprise_rest_connectors():
    from maverick.safety.tool_risk import tools_exceeding

    assert tools_exceeding(ENTERPRISE_REST_CONNECTORS, "medium") == set(
        ENTERPRISE_REST_CONNECTORS
    )
