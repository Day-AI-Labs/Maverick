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

    # --- CRM / sales engagement ---
    dict(name="zoho", base_url_env="ZOHO_BASE_URL", token_env="ZOHO_TOKEN",
         scheme="Zoho-oauthtoken", description="Zoho CRM REST. ops "
         "get/post/put/patch/delete (writes need confirm). e.g. /crm/v5/Leads. "
         "Auth: ZOHO_BASE_URL + ZOHO_TOKEN (Zoho-oauthtoken)."),
    dict(name="pipedrive", base_url_env="PIPEDRIVE_BASE_URL", token_env="PIPEDRIVE_TOKEN",
         description="Pipedrive REST. ops get/post/put/delete (writes need confirm). "
         "e.g. /v1/deals, /v1/persons. Auth: PIPEDRIVE_BASE_URL + PIPEDRIVE_TOKEN."),
    dict(name="salesloft", base_url_env="SALESLOFT_BASE_URL", token_env="SALESLOFT_TOKEN",
         description="Salesloft REST. ops get/post/put/delete (writes need confirm). "
         "e.g. /v2/people, /v2/cadences. Auth: SALESLOFT_BASE_URL + SALESLOFT_TOKEN."),
    dict(name="outreach", base_url_env="OUTREACH_BASE_URL", token_env="OUTREACH_TOKEN",
         description="Outreach REST. ops get/post/patch/delete (writes need confirm). "
         "e.g. /api/v2/prospects, /api/v2/sequences. Auth: OUTREACH_BASE_URL + OUTREACH_TOKEN."),
    dict(name="gong", base_url_env="GONG_BASE_URL", token_env="GONG_TOKEN", basic=True,
         description="Gong revenue-intelligence REST. ops get/post (writes need "
         "confirm). e.g. /v2/calls, /v2/users. Auth: GONG_BASE_URL + GONG_TOKEN "
         "(accessKey:secret, basic)."),
    dict(name="clari", base_url_env="CLARI_BASE_URL", token_env="CLARI_TOKEN",
         token_header="apikey", scheme="", description="Clari REST. ops get/post "
         "(writes need confirm). Auth: CLARI_BASE_URL + CLARI_TOKEN (apikey header)."),
    dict(name="creatio", base_url_env="CREATIO_BASE_URL", token_env="CREATIO_TOKEN",
         description="Creatio (bpm'online) OData REST. ops get/post/patch/delete "
         "(writes need confirm). Auth: CREATIO_BASE_URL + CREATIO_TOKEN."),
    dict(name="pega", base_url_env="PEGA_BASE_URL", token_env="PEGA_TOKEN",
         description="Pega REST. ops get/post/put/delete (writes need confirm). "
         "e.g. /prweb/api/v1/cases. Auth: PEGA_BASE_URL + PEGA_TOKEN."),

    # --- ERP / finance ---
    dict(name="sage_intacct", base_url_env="SAGE_INTACCT_BASE_URL",
         token_env="SAGE_INTACCT_TOKEN", description="Sage Intacct REST. ops "
         "get/post/put/delete (writes need confirm). Auth: SAGE_INTACCT_BASE_URL + "
         "SAGE_INTACCT_TOKEN."),
    dict(name="epicor", base_url_env="EPICOR_BASE_URL", token_env="EPICOR_TOKEN",
         basic=True, description="Epicor ERP REST. ops get/post/patch/delete (writes "
         "need confirm). Auth: EPICOR_BASE_URL + EPICOR_TOKEN (user:pass, basic)."),
    dict(name="ifs", base_url_env="IFS_BASE_URL", token_env="IFS_TOKEN",
         description="IFS Cloud OData REST. ops get/post/patch/delete (writes need "
         "confirm). Auth: IFS_BASE_URL + IFS_TOKEN."),
    dict(name="unit4", base_url_env="UNIT4_BASE_URL", token_env="UNIT4_TOKEN",
         description="Unit4 ERP REST. ops get/post/put/delete (writes need confirm). "
         "Auth: UNIT4_BASE_URL + UNIT4_TOKEN."),
    dict(name="acumatica", base_url_env="ACUMATICA_BASE_URL", token_env="ACUMATICA_TOKEN",
         description="Acumatica REST. ops get/put/delete (writes need confirm). "
         "e.g. /entity/Default/.../SalesOrder. Auth: ACUMATICA_BASE_URL + ACUMATICA_TOKEN."),
    dict(name="quickbooks", base_url_env="QUICKBOOKS_BASE_URL", token_env="QUICKBOOKS_TOKEN",
         description="QuickBooks Online REST. ops get/post (writes need confirm). "
         "e.g. /v3/company/{id}/query. Auth: QUICKBOOKS_BASE_URL + QUICKBOOKS_TOKEN."),
    dict(name="xero", base_url_env="XERO_BASE_URL", token_env="XERO_TOKEN",
         description="Xero accounting REST. ops get/post/put (writes need confirm). "
         "e.g. /api.xro/2.0/Invoices. Auth: XERO_BASE_URL + XERO_TOKEN."),
    dict(name="billdotcom", base_url_env="BILLDOTCOM_BASE_URL", token_env="BILLDOTCOM_TOKEN",
         description="Bill.com REST. ops get/post (writes need confirm). Auth: "
         "BILLDOTCOM_BASE_URL + BILLDOTCOM_TOKEN."),

    # --- Support / CX / contact center ---
    dict(name="genesys", base_url_env="GENESYS_BASE_URL", token_env="GENESYS_TOKEN",
         description="Genesys Cloud REST. ops get/post/put/patch/delete (writes need "
         "confirm). e.g. /api/v2/conversations. Auth: GENESYS_BASE_URL + GENESYS_TOKEN."),
    dict(name="nice_cxone", base_url_env="NICE_CXONE_BASE_URL", token_env="NICE_CXONE_TOKEN",
         description="NICE CXone REST. ops get/post/put/delete (writes need confirm). "
         "Auth: NICE_CXONE_BASE_URL + NICE_CXONE_TOKEN."),
    dict(name="five9", base_url_env="FIVE9_BASE_URL", token_env="FIVE9_TOKEN", basic=True,
         description="Five9 REST. ops get/post/put/delete (writes need confirm). "
         "Auth: FIVE9_BASE_URL + FIVE9_TOKEN (user:pass, basic)."),
    dict(name="talkdesk", base_url_env="TALKDESK_BASE_URL", token_env="TALKDESK_TOKEN",
         description="Talkdesk REST. ops get/post/put/delete (writes need confirm). "
         "Auth: TALKDESK_BASE_URL + TALKDESK_TOKEN."),
    dict(name="helpscout", base_url_env="HELPSCOUT_BASE_URL", token_env="HELPSCOUT_TOKEN",
         description="Help Scout REST. ops get/post/put/patch/delete (writes need "
         "confirm). e.g. /v2/conversations. Auth: HELPSCOUT_BASE_URL + HELPSCOUT_TOKEN."),
    dict(name="kustomer", base_url_env="KUSTOMER_BASE_URL", token_env="KUSTOMER_TOKEN",
         description="Kustomer REST. ops get/post/put/delete (writes need confirm). "
         "Auth: KUSTOMER_BASE_URL + KUSTOMER_TOKEN."),
    dict(name="sprinklr", base_url_env="SPRINKLR_BASE_URL", token_env="SPRINKLR_TOKEN",
         description="Sprinklr REST. ops get/post/put/delete (writes need confirm). "
         "Auth: SPRINKLR_BASE_URL + SPRINKLR_TOKEN."),

    # --- ITSM / alerting ---
    dict(name="bmc_helix", base_url_env="BMC_HELIX_BASE_URL", token_env="BMC_HELIX_TOKEN",
         scheme="AR-JWT", description="BMC Helix / Remedy REST. ops get/post/put/delete "
         "(writes need confirm). Auth: BMC_HELIX_BASE_URL + BMC_HELIX_TOKEN (AR-JWT)."),
    dict(name="ivanti", base_url_env="IVANTI_BASE_URL", token_env="IVANTI_TOKEN",
         description="Ivanti Neurons / ITSM REST. ops get/post/put/delete (writes need "
         "confirm). Auth: IVANTI_BASE_URL + IVANTI_TOKEN."),
    dict(name="solarwinds", base_url_env="SOLARWINDS_BASE_URL", token_env="SOLARWINDS_TOKEN",
         description="SolarWinds Service Desk REST. ops get/post/put/delete (writes "
         "need confirm). Auth: SOLARWINDS_BASE_URL + SOLARWINDS_TOKEN."),
    dict(name="manageengine", base_url_env="MANAGEENGINE_BASE_URL",
         token_env="MANAGEENGINE_TOKEN", scheme="Zoho-oauthtoken",
         description="ManageEngine ServiceDesk Plus REST. ops get/post/put/delete "
         "(writes need confirm). Auth: MANAGEENGINE_BASE_URL + MANAGEENGINE_TOKEN."),
    dict(name="xmatters", base_url_env="XMATTERS_BASE_URL", token_env="XMATTERS_TOKEN",
         description="xMatters REST. ops get/post/delete (writes need confirm). "
         "e.g. /api/xm/1/events. Auth: XMATTERS_BASE_URL + XMATTERS_TOKEN."),

    # --- HR ---
    dict(name="rippling", base_url_env="RIPPLING_BASE_URL", token_env="RIPPLING_TOKEN",
         description="Rippling REST. ops get/post (writes need confirm). e.g. "
         "/platform/api/employees. Auth: RIPPLING_BASE_URL + RIPPLING_TOKEN."),
    dict(name="gusto", base_url_env="GUSTO_BASE_URL", token_env="GUSTO_TOKEN",
         description="Gusto REST. ops get/post/put (writes need confirm). e.g. "
         "/v1/companies/{id}/employees. Auth: GUSTO_BASE_URL + GUSTO_TOKEN."),
]

ENTERPRISE_CONNECTOR_NAMES: list[str] = [s["name"] for s in _SPECS]


def enterprise_connectors() -> list[Tool]:
    """Instantiate every spec'd connector (registered in base_registry)."""
    return [make_rest_tool(**spec) for spec in _SPECS]
