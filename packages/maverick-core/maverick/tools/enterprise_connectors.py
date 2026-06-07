"""Enterprise connector specs (the long tail), built on ``make_rest_tool``.

Each entry is a thin authenticated-REST tool: explicit-env auth, the agent
supplies the path, writes are confirm-gated. Add a system by appending one
spec here — no new module per connector. Systems that need a bespoke shape
(specific ops, GraphQL, CSRF, SQL result parsing) keep their own module
(servicenow_tool, snowflake_tool, sap_tool, ...).
"""
from __future__ import annotations

from . import Tool
from ._rest_connector import make_rest_tool

# name, base_url_env, token_env, description, **auth-overrides
_SPECS: list[dict] = [
    # --- Support / CX ---
    dict(name="zendesk", base_url_env="ZENDESK_BASE_URL", token_env="ZENDESK_TOKEN",
         description="Zendesk Support REST. ops get/post/put/delete (writes need "
         "confirm). e.g. /api/v2/tickets.json, /api/v2/search.json?query=. "
         "Auth: ZENDESK_BASE_URL (https://{sub}.zendesk.com) + ZENDESK_TOKEN."),
    dict(name="freshdesk", base_url_env="FRESHDESK_BASE_URL", token_env="FRESHDESK_TOKEN",
         basic=True, description="Freshdesk REST. ops get/post/put/delete (writes "
         "need confirm). e.g. /api/v2/tickets. Auth: FRESHDESK_BASE_URL "
         "(https://{sub}.freshdesk.com) + FRESHDESK_TOKEN (API key)."),
    dict(name="freshservice", base_url_env="FRESHSERVICE_BASE_URL",
         token_env="FRESHSERVICE_TOKEN", basic=True,
         description="Freshservice ITSM REST. ops get/post/put/delete (writes need "
         "confirm). e.g. /api/v2/tickets. Auth: FRESHSERVICE_BASE_URL + "
         "FRESHSERVICE_TOKEN (API key)."),
    dict(name="intercom", base_url_env="INTERCOM_BASE_URL", token_env="INTERCOM_TOKEN",
         description="Intercom REST. ops get/post/put/delete (writes need confirm). "
         "e.g. /contacts, /conversations. Auth: INTERCOM_BASE_URL "
         "(https://api.intercom.io) + INTERCOM_TOKEN."),
    # --- Identity ---
    dict(name="okta", base_url_env="OKTA_BASE_URL", token_env="OKTA_TOKEN",
         scheme="SSWS", description="Okta management REST. ops get/post/put/delete "
         "(writes need confirm). e.g. /api/v1/users, /api/v1/groups. Auth: "
         "OKTA_BASE_URL (https://{org}.okta.com) + OKTA_TOKEN (SSWS API token)."),
    # --- Content / storage / e-sign ---
    dict(name="box", base_url_env="BOX_BASE_URL", token_env="BOX_TOKEN",
         description="Box content REST. ops get/post/put/delete (writes need "
         "confirm). e.g. /folders/0/items, /search?query=. Auth: BOX_BASE_URL "
         "(https://api.box.com/2.0) + BOX_TOKEN."),
    dict(name="docusign", base_url_env="DOCUSIGN_BASE_URL", token_env="DOCUSIGN_TOKEN",
         description="DocuSign eSignature REST. ops get/post/put/delete (writes need "
         "confirm). e.g. /restapi/v2.1/accounts/{acct}/envelopes. Auth: "
         "DOCUSIGN_BASE_URL + DOCUSIGN_TOKEN."),
    # --- Procurement / spend ---
    dict(name="coupa", base_url_env="COUPA_BASE_URL", token_env="COUPA_TOKEN",
         description="Coupa spend/procurement REST. ops get/post/put/delete (writes "
         "need confirm). e.g. /api/requisitions, /api/purchase_orders. Auth: "
         "COUPA_BASE_URL + COUPA_TOKEN."),
    dict(name="ariba", base_url_env="ARIBA_BASE_URL", token_env="ARIBA_TOKEN",
         description="SAP Ariba REST. ops get/post/put/delete (writes need confirm). "
         "Auth: ARIBA_BASE_URL + ARIBA_TOKEN."),
    # --- Work management ---
    dict(name="smartsheet", base_url_env="SMARTSHEET_BASE_URL", token_env="SMARTSHEET_TOKEN",
         description="Smartsheet REST. ops get/post/put/delete (writes need confirm). "
         "e.g. /sheets, /sheets/{id}/rows. Auth: SMARTSHEET_BASE_URL "
         "(https://api.smartsheet.com/2.0) + SMARTSHEET_TOKEN."),
    dict(name="wrike", base_url_env="WRIKE_BASE_URL", token_env="WRIKE_TOKEN",
         description="Wrike work-management REST. ops get/post/put/delete (writes "
         "need confirm). e.g. /tasks, /folders. Auth: WRIKE_BASE_URL "
         "(https://www.wrike.com/api/v4) + WRIKE_TOKEN."),
    # --- HR / recruiting ---
    dict(name="bamboohr", base_url_env="BAMBOOHR_BASE_URL", token_env="BAMBOOHR_TOKEN",
         basic=True, description="BambooHR REST. ops get/post/put/delete (writes need "
         "confirm). e.g. /v1/employees/directory. Auth: BAMBOOHR_BASE_URL "
         "(https://api.bamboohr.com/api/gateway.php/{company}) + BAMBOOHR_TOKEN (API key)."),
    dict(name="greenhouse", base_url_env="GREENHOUSE_BASE_URL", token_env="GREENHOUSE_TOKEN",
         basic=True, description="Greenhouse Harvest REST. ops get/post/put/delete "
         "(writes need confirm). e.g. /v1/candidates, /v1/jobs. Auth: "
         "GREENHOUSE_BASE_URL (https://harvest.greenhouse.io) + GREENHOUSE_TOKEN (API key)."),
    dict(name="lever", base_url_env="LEVER_BASE_URL", token_env="LEVER_TOKEN",
         basic=True, description="Lever recruiting REST. ops get/post/put/delete "
         "(writes need confirm). e.g. /v1/opportunities, /v1/postings. Auth: "
         "LEVER_BASE_URL (https://api.lever.co) + LEVER_TOKEN (API key)."),
    # --- BI / analytics ---
    dict(name="tableau", base_url_env="TABLEAU_BASE_URL", token_env="TABLEAU_TOKEN",
         token_header="X-Tableau-Auth", scheme="",
         description="Tableau Server/Cloud REST. ops get/post/put/delete (writes need "
         "confirm). e.g. /api/3.21/sites/{id}/workbooks. Auth: TABLEAU_BASE_URL + "
         "TABLEAU_TOKEN (signed-in X-Tableau-Auth token)."),
    dict(name="powerbi", base_url_env="POWERBI_BASE_URL", token_env="POWERBI_TOKEN",
         description="Microsoft Power BI REST. ops get/post/put/delete (writes need "
         "confirm). e.g. /groups, /datasets, /reports. Auth: POWERBI_BASE_URL "
         "(https://api.powerbi.com/v1.0/myorg) + POWERBI_TOKEN."),
    dict(name="looker", base_url_env="LOOKER_BASE_URL", token_env="LOOKER_TOKEN",
         scheme="token", description="Looker REST. ops get/post/put/delete (writes "
         "need confirm). e.g. /api/4.0/looks, /api/4.0/dashboards. Auth: "
         "LOOKER_BASE_URL + LOOKER_TOKEN (Authorization: token <access_token>)."),
    # --- Observability ---
    dict(name="newrelic", base_url_env="NEWRELIC_BASE_URL", token_env="NEWRELIC_TOKEN",
         token_header="Api-Key", scheme="",
         description="New Relic REST. ops get/post/put/delete (writes need confirm). "
         "e.g. /v2/applications.json. Auth: NEWRELIC_BASE_URL "
         "(https://api.newrelic.com) + NEWRELIC_TOKEN (Api-Key header)."),
    dict(name="dynatrace", base_url_env="DYNATRACE_BASE_URL", token_env="DYNATRACE_TOKEN",
         scheme="Api-Token", description="Dynatrace REST. ops get/post/put/delete "
         "(writes need confirm). e.g. /api/v2/problems, /api/v2/metrics/query. Auth: "
         "DYNATRACE_BASE_URL + DYNATRACE_TOKEN (Authorization: Api-Token <tok>)."),
    dict(name="grafana", base_url_env="GRAFANA_BASE_URL", token_env="GRAFANA_TOKEN",
         description="Grafana REST. ops get/post/put/delete (writes need confirm). "
         "e.g. /api/dashboards/uid/{uid}, /api/datasources. Auth: GRAFANA_BASE_URL "
         "+ GRAFANA_TOKEN (service-account token)."),
]

ENTERPRISE_CONNECTOR_NAMES: list[str] = [s["name"] for s in _SPECS]


def enterprise_connectors() -> list[Tool]:
    """Instantiate every spec'd connector (registered in base_registry)."""
    return [make_rest_tool(**spec) for spec in _SPECS]
