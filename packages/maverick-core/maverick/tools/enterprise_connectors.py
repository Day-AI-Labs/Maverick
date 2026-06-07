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

    # --- Cloud / infra ---
    dict(name="fastly", base_url_env="FASTLY_BASE_URL", token_env="FASTLY_TOKEN",
         token_header="Fastly-Key", scheme="", description="Fastly REST. ops "
         "get/post/put/delete (writes need confirm). Auth: FASTLY_BASE_URL + "
         "FASTLY_TOKEN (Fastly-Key)."),
    dict(name="akamai", base_url_env="AKAMAI_BASE_URL", token_env="AKAMAI_TOKEN",
         description="Akamai REST. ops get/post/put/delete (writes need confirm). "
         "Auth: AKAMAI_BASE_URL + AKAMAI_TOKEN."),
    dict(name="digitalocean", base_url_env="DIGITALOCEAN_BASE_URL",
         token_env="DIGITALOCEAN_TOKEN", description="DigitalOcean REST. ops "
         "get/post/put/delete (writes need confirm). e.g. /v2/droplets. Auth: "
         "DIGITALOCEAN_BASE_URL (https://api.digitalocean.com) + DIGITALOCEAN_TOKEN."),
    dict(name="terraform", base_url_env="TERRAFORM_BASE_URL", token_env="TERRAFORM_TOKEN",
         description="Terraform Cloud/Enterprise REST. ops get/post/patch/delete "
         "(writes need confirm). e.g. /api/v2/organizations/{org}/workspaces. Auth: "
         "TERRAFORM_BASE_URL + TERRAFORM_TOKEN."),
    dict(name="vault", base_url_env="VAULT_BASE_URL", token_env="VAULT_TOKEN",
         token_header="X-Vault-Token", scheme="", description="HashiCorp Vault REST. "
         "ops get/post/delete (writes need confirm). e.g. /v1/secret/data/{path}. "
         "Auth: VAULT_BASE_URL + VAULT_TOKEN (X-Vault-Token)."),

    # --- Identity / IAM ---
    dict(name="pingone", base_url_env="PINGONE_BASE_URL", token_env="PINGONE_TOKEN",
         description="Ping Identity (PingOne) REST. ops get/post/put/delete (writes "
         "need confirm). Auth: PINGONE_BASE_URL + PINGONE_TOKEN."),
    dict(name="cyberark", base_url_env="CYBERARK_BASE_URL", token_env="CYBERARK_TOKEN",
         description="CyberArk REST. ops get/post/put/delete (writes need confirm). "
         "Auth: CYBERARK_BASE_URL + CYBERARK_TOKEN."),
    dict(name="sailpoint", base_url_env="SAILPOINT_BASE_URL", token_env="SAILPOINT_TOKEN",
         description="SailPoint IdentityNow REST. ops get/post/patch/delete (writes "
         "need confirm). e.g. /v3/accounts. Auth: SAILPOINT_BASE_URL + SAILPOINT_TOKEN."),
    dict(name="onelogin", base_url_env="ONELOGIN_BASE_URL", token_env="ONELOGIN_TOKEN",
         description="OneLogin REST. ops get/post/put/delete (writes need confirm). "
         "e.g. /api/2/users. Auth: ONELOGIN_BASE_URL + ONELOGIN_TOKEN."),
    dict(name="auth0", base_url_env="AUTH0_BASE_URL", token_env="AUTH0_TOKEN",
         description="Auth0 Management REST. ops get/post/patch/delete (writes need "
         "confirm). e.g. /api/v2/users. Auth: AUTH0_BASE_URL + AUTH0_TOKEN."),
    dict(name="duo", base_url_env="DUO_BASE_URL", token_env="DUO_TOKEN", basic=True,
         description="Cisco Duo Admin REST. ops get/post (writes need confirm). "
         "Auth: DUO_BASE_URL + DUO_TOKEN (ikey:skey, basic)."),

    # --- Security / SIEM / endpoint ---
    dict(name="crowdstrike", base_url_env="CROWDSTRIKE_BASE_URL",
         token_env="CROWDSTRIKE_TOKEN", description="CrowdStrike Falcon REST. ops "
         "get/post/patch/delete (writes need confirm). e.g. /detects/queries/detects/v1. "
         "Auth: CROWDSTRIKE_BASE_URL + CROWDSTRIKE_TOKEN."),
    dict(name="splunk", base_url_env="SPLUNK_BASE_URL", token_env="SPLUNK_TOKEN",
         description="Splunk REST. ops get/post/delete (writes need confirm). e.g. "
         "/services/search/jobs. Auth: SPLUNK_BASE_URL + SPLUNK_TOKEN."),
    dict(name="zscaler", base_url_env="ZSCALER_BASE_URL", token_env="ZSCALER_TOKEN",
         description="Zscaler REST. ops get/post/put/delete (writes need confirm). "
         "Auth: ZSCALER_BASE_URL + ZSCALER_TOKEN."),
    dict(name="tenable", base_url_env="TENABLE_BASE_URL", token_env="TENABLE_TOKEN",
         token_header="X-ApiKeys", scheme="", description="Tenable.io REST. ops "
         "get/post/put/delete (writes need confirm). Auth: TENABLE_BASE_URL + "
         "TENABLE_TOKEN ('accessKey=...;secretKey=...')."),
    dict(name="qualys", base_url_env="QUALYS_BASE_URL", token_env="QUALYS_TOKEN",
         basic=True, description="Qualys REST. ops get/post (writes need confirm). "
         "Auth: QUALYS_BASE_URL + QUALYS_TOKEN (user:pass, basic)."),
    dict(name="rapid7", base_url_env="RAPID7_BASE_URL", token_env="RAPID7_TOKEN",
         token_header="X-Api-Key", scheme="", description="Rapid7 InsightVM/IDR REST. "
         "ops get/post/put/delete (writes need confirm). Auth: RAPID7_BASE_URL + "
         "RAPID7_TOKEN (X-Api-Key)."),
    dict(name="sentinelone", base_url_env="SENTINELONE_BASE_URL",
         token_env="SENTINELONE_TOKEN", scheme="ApiToken", description="SentinelOne "
         "REST. ops get/post/delete (writes need confirm). e.g. /web/api/v2.1/agents. "
         "Auth: SENTINELONE_BASE_URL + SENTINELONE_TOKEN (ApiToken)."),
    dict(name="proofpoint", base_url_env="PROOFPOINT_BASE_URL",
         token_env="PROOFPOINT_TOKEN", basic=True, description="Proofpoint REST. ops "
         "get/post (writes need confirm). Auth: PROOFPOINT_BASE_URL + PROOFPOINT_TOKEN "
         "(principal:secret, basic)."),
    dict(name="snyk", base_url_env="SNYK_BASE_URL", token_env="SNYK_TOKEN",
         scheme="token", description="Snyk REST. ops get/post/delete (writes need "
         "confirm). e.g. /rest/orgs. Auth: SNYK_BASE_URL + SNYK_TOKEN (token <key>)."),
    dict(name="fortinet", base_url_env="FORTINET_BASE_URL", token_env="FORTINET_TOKEN",
         description="Fortinet FortiGate/FortiManager REST. ops get/post/put/delete "
         "(writes need confirm). Auth: FORTINET_BASE_URL + FORTINET_TOKEN."),

    # --- BI / analytics ---
    dict(name="qlik", base_url_env="QLIK_BASE_URL", token_env="QLIK_TOKEN",
         description="Qlik Cloud REST. ops get/post/put/delete (writes need confirm). "
         "e.g. /api/v1/apps. Auth: QLIK_BASE_URL + QLIK_TOKEN."),
    dict(name="thoughtspot", base_url_env="THOUGHTSPOT_BASE_URL",
         token_env="THOUGHTSPOT_TOKEN", description="ThoughtSpot REST. ops get/post "
         "(writes need confirm). e.g. /api/rest/2.0/metadata/search. Auth: "
         "THOUGHTSPOT_BASE_URL + THOUGHTSPOT_TOKEN."),
    dict(name="sisense", base_url_env="SISENSE_BASE_URL", token_env="SISENSE_TOKEN",
         description="Sisense REST. ops get/post/put/delete (writes need confirm). "
         "Auth: SISENSE_BASE_URL + SISENSE_TOKEN."),
    dict(name="domo", base_url_env="DOMO_BASE_URL", token_env="DOMO_TOKEN",
         description="Domo REST. ops get/post/put/delete (writes need confirm). "
         "e.g. /v1/datasets. Auth: DOMO_BASE_URL + DOMO_TOKEN."),
    dict(name="mode", base_url_env="MODE_BASE_URL", token_env="MODE_TOKEN", basic=True,
         description="Mode Analytics REST. ops get/post (writes need confirm). Auth: "
         "MODE_BASE_URL + MODE_TOKEN (token:secret, basic)."),
    dict(name="metabase", base_url_env="METABASE_BASE_URL", token_env="METABASE_TOKEN",
         token_header="X-API-Key", scheme="", description="Metabase REST. ops "
         "get/post/put/delete (writes need confirm). e.g. /api/card. Auth: "
         "METABASE_BASE_URL + METABASE_TOKEN (X-API-Key)."),

    # --- DevOps / CI ---
    dict(name="jenkins", base_url_env="JENKINS_BASE_URL", token_env="JENKINS_TOKEN",
         basic=True, description="Jenkins REST. ops get/post (writes need confirm). "
         "e.g. /api/json, /job/{name}/build. Auth: JENKINS_BASE_URL + JENKINS_TOKEN "
         "(user:apitoken, basic)."),
    dict(name="circleci", base_url_env="CIRCLECI_BASE_URL", token_env="CIRCLECI_TOKEN",
         token_header="Circle-Token", scheme="", description="CircleCI REST. ops "
         "get/post (writes need confirm). e.g. /api/v2/project/{slug}/pipeline. Auth: "
         "CIRCLECI_BASE_URL + CIRCLECI_TOKEN (Circle-Token)."),
    dict(name="jfrog", base_url_env="JFROG_BASE_URL", token_env="JFROG_TOKEN",
         description="JFrog Artifactory REST. ops get/post/put/delete (writes need "
         "confirm). e.g. /artifactory/api/repositories. Auth: JFROG_BASE_URL + JFROG_TOKEN."),
    dict(name="sonarqube", base_url_env="SONARQUBE_BASE_URL", token_env="SONARQUBE_TOKEN",
         basic=True, description="SonarQube REST. ops get/post (writes need confirm). "
         "e.g. /api/issues/search, /api/projects/search. Auth: SONARQUBE_BASE_URL + "
         "SONARQUBE_TOKEN (token:, basic)."),
    dict(name="azure_devops", base_url_env="AZURE_DEVOPS_BASE_URL",
         token_env="AZURE_DEVOPS_TOKEN", basic=True, description="Azure DevOps REST. "
         "ops get/post/patch/put (writes need confirm). e.g. /{org}/{proj}/_apis/wit/"
         "workitems. Auth: AZURE_DEVOPS_BASE_URL + AZURE_DEVOPS_TOKEN (:PAT, basic)."),

    # --- Marketing / commerce ---
    dict(name="mailchimp", base_url_env="MAILCHIMP_BASE_URL", token_env="MAILCHIMP_TOKEN",
         basic=True, description="Mailchimp Marketing REST. ops get/post/put/patch/"
         "delete (writes need confirm). e.g. /3.0/lists. Auth: MAILCHIMP_BASE_URL + "
         "MAILCHIMP_TOKEN (anystring:apikey, basic)."),
    dict(name="klaviyo", base_url_env="KLAVIYO_BASE_URL", token_env="KLAVIYO_TOKEN",
         scheme="Klaviyo-API-Key", description="Klaviyo REST. ops get/post/patch/delete "
         "(writes need confirm). Auth: KLAVIYO_BASE_URL + KLAVIYO_TOKEN (Klaviyo-API-Key)."),
    dict(name="braze", base_url_env="BRAZE_BASE_URL", token_env="BRAZE_TOKEN",
         description="Braze REST. ops get/post (writes need confirm). e.g. "
         "/users/export/ids, /messages/send. Auth: BRAZE_BASE_URL + BRAZE_TOKEN."),
    dict(name="marketo", base_url_env="MARKETO_BASE_URL", token_env="MARKETO_TOKEN",
         description="Adobe Marketo Engage REST. ops get/post (writes need confirm). "
         "e.g. /rest/v1/leads.json. Auth: MARKETO_BASE_URL + MARKETO_TOKEN."),
    dict(name="sfmc", base_url_env="SFMC_BASE_URL", token_env="SFMC_TOKEN",
         description="Salesforce Marketing Cloud REST. ops get/post/put/delete (writes "
         "need confirm). Auth: SFMC_BASE_URL + SFMC_TOKEN."),
    dict(name="segment", base_url_env="SEGMENT_BASE_URL", token_env="SEGMENT_TOKEN",
         description="Twilio Segment Public API. ops get/post/patch/delete (writes "
         "need confirm). e.g. /workspaces, /sources. Auth: SEGMENT_BASE_URL + SEGMENT_TOKEN."),
    dict(name="adobe_analytics", base_url_env="ADOBE_ANALYTICS_BASE_URL",
         token_env="ADOBE_ANALYTICS_TOKEN", description="Adobe Analytics 2.0 REST. ops "
         "get/post (writes need confirm). e.g. /reports. Auth: ADOBE_ANALYTICS_BASE_URL "
         "+ ADOBE_ANALYTICS_TOKEN."),
    dict(name="aem", base_url_env="AEM_BASE_URL", token_env="AEM_TOKEN", basic=True,
         description="Adobe Experience Manager REST. ops get/post/put/delete (writes "
         "need confirm). Auth: AEM_BASE_URL + AEM_TOKEN (user:pass, basic)."),
    dict(name="bigcommerce", base_url_env="BIGCOMMERCE_BASE_URL",
         token_env="BIGCOMMERCE_TOKEN", token_header="X-Auth-Token", scheme="",
         description="BigCommerce REST. ops get/post/put/delete (writes need confirm). "
         "e.g. /v3/catalog/products. Auth: BIGCOMMERCE_BASE_URL + BIGCOMMERCE_TOKEN "
         "(X-Auth-Token)."),
    dict(name="sendgrid", base_url_env="SENDGRID_BASE_URL", token_env="SENDGRID_TOKEN",
         description="Twilio SendGrid REST. ops get/post/put/patch/delete (writes need "
         "confirm). e.g. /v3/mail/send, /v3/marketing/contacts. Auth: SENDGRID_BASE_URL "
         "(https://api.sendgrid.com) + SENDGRID_TOKEN."),

    # --- Data / ETL / streaming ---
    dict(name="fivetran", base_url_env="FIVETRAN_BASE_URL", token_env="FIVETRAN_TOKEN",
         basic=True, description="Fivetran REST. ops get/post/patch/delete (writes need "
         "confirm). e.g. /v1/connectors. Auth: FIVETRAN_BASE_URL + FIVETRAN_TOKEN "
         "(apikey:apisecret, basic)."),
    dict(name="dbt", base_url_env="DBT_BASE_URL", token_env="DBT_TOKEN", scheme="Token",
         description="dbt Cloud REST. ops get/post (writes need confirm). e.g. "
         "/api/v2/accounts/{id}/jobs. Auth: DBT_BASE_URL + DBT_TOKEN (Token <key>)."),
    dict(name="airflow", base_url_env="AIRFLOW_BASE_URL", token_env="AIRFLOW_TOKEN",
         basic=True, description="Apache Airflow REST. ops get/post/patch/delete "
         "(writes need confirm). e.g. /api/v1/dags. Auth: AIRFLOW_BASE_URL + "
         "AIRFLOW_TOKEN (user:pass, basic)."),
    dict(name="confluent", base_url_env="CONFLUENT_BASE_URL", token_env="CONFLUENT_TOKEN",
         basic=True, description="Confluent Cloud REST. ops get/post/patch/delete "
         "(writes need confirm). e.g. /kafka/v3/clusters. Auth: CONFLUENT_BASE_URL + "
         "CONFLUENT_TOKEN (key:secret, basic)."),
    dict(name="informatica", base_url_env="INFORMATICA_BASE_URL",
         token_env="INFORMATICA_TOKEN", description="Informatica IICS REST. ops "
         "get/post (writes need confirm). Auth: INFORMATICA_BASE_URL + INFORMATICA_TOKEN."),
    dict(name="talend", base_url_env="TALEND_BASE_URL", token_env="TALEND_TOKEN",
         description="Talend Cloud REST. ops get/post/put/delete (writes need confirm). "
         "Auth: TALEND_BASE_URL + TALEND_TOKEN."),
    dict(name="matillion", base_url_env="MATILLION_BASE_URL", token_env="MATILLION_TOKEN",
         basic=True, description="Matillion REST. ops get/post (writes need confirm). "
         "Auth: MATILLION_BASE_URL + MATILLION_TOKEN (user:pass, basic)."),
    dict(name="cloudera", base_url_env="CLOUDERA_BASE_URL", token_env="CLOUDERA_TOKEN",
         basic=True, description="Cloudera Manager REST. ops get/post/put/delete "
         "(writes need confirm). Auth: CLOUDERA_BASE_URL + CLOUDERA_TOKEN (user:pass, basic)."),

    # --- Collaboration / PM ---
    dict(name="miro", base_url_env="MIRO_BASE_URL", token_env="MIRO_TOKEN",
         description="Miro REST. ops get/post/patch/delete (writes need confirm). "
         "e.g. /v2/boards. Auth: MIRO_BASE_URL (https://api.miro.com) + MIRO_TOKEN."),
    dict(name="coda", base_url_env="CODA_BASE_URL", token_env="CODA_TOKEN",
         description="Coda REST. ops get/post/put/delete (writes need confirm). e.g. "
         "/v1/docs. Auth: CODA_BASE_URL (https://coda.io/apis/v1) + CODA_TOKEN."),
    dict(name="basecamp", base_url_env="BASECAMP_BASE_URL", token_env="BASECAMP_TOKEN",
         description="Basecamp REST. ops get/post/put (writes need confirm). Auth: "
         "BASECAMP_BASE_URL + BASECAMP_TOKEN."),
    dict(name="planview", base_url_env="PLANVIEW_BASE_URL", token_env="PLANVIEW_TOKEN",
         description="Planview REST. ops get/post/put/delete (writes need confirm). "
         "Auth: PLANVIEW_BASE_URL + PLANVIEW_TOKEN."),

    # --- ERP / HR (additional) ---
    dict(name="infor", base_url_env="INFOR_BASE_URL", token_env="INFOR_TOKEN",
         description="Infor CloudSuite (ION) REST. ops get/post/put/delete (writes "
         "need confirm). Auth: INFOR_BASE_URL + INFOR_TOKEN."),
    dict(name="netsuite", base_url_env="NETSUITE_BASE_URL", token_env="NETSUITE_TOKEN",
         description="Oracle NetSuite SuiteTalk REST. ops get/post/patch/delete (writes "
         "need confirm). e.g. /services/rest/record/v1/salesOrder. Auth: "
         "NETSUITE_BASE_URL + NETSUITE_TOKEN."),
    dict(name="adp", base_url_env="ADP_BASE_URL", token_env="ADP_TOKEN",
         description="ADP Workforce Now REST. ops get/post (writes need confirm). e.g. "
         "/hr/v2/workers. Auth: ADP_BASE_URL + ADP_TOKEN."),
    dict(name="ukg", base_url_env="UKG_BASE_URL", token_env="UKG_TOKEN",
         description="UKG (Ultimate Kronos) REST. ops get/post/put/delete (writes need "
         "confirm). Auth: UKG_BASE_URL + UKG_TOKEN."),

    # --- iPaaS / integration ---
    dict(name="mulesoft", base_url_env="MULESOFT_BASE_URL", token_env="MULESOFT_TOKEN",
         description="MuleSoft Anypoint REST. ops get/post/put/delete (writes need "
         "confirm). Auth: MULESOFT_BASE_URL + MULESOFT_TOKEN."),
    dict(name="boomi", base_url_env="BOOMI_BASE_URL", token_env="BOOMI_TOKEN", basic=True,
         description="Boomi AtomSphere REST. ops get/post (writes need confirm). Auth: "
         "BOOMI_BASE_URL + BOOMI_TOKEN (user:token, basic)."),
    dict(name="workato", base_url_env="WORKATO_BASE_URL", token_env="WORKATO_TOKEN",
         description="Workato REST. ops get/post/put/delete (writes need confirm). "
         "Auth: WORKATO_BASE_URL + WORKATO_TOKEN."),
    dict(name="zapier", base_url_env="ZAPIER_BASE_URL", token_env="ZAPIER_TOKEN",
         description="Zapier NLA / REST. ops get/post (writes need confirm). Auth: "
         "ZAPIER_BASE_URL + ZAPIER_TOKEN."),
]

ENTERPRISE_CONNECTOR_NAMES: list[str] = [s["name"] for s in _SPECS]


def enterprise_connectors() -> list[Tool]:
    """Instantiate every spec'd connector (registered in base_registry)."""
    return [make_rest_tool(**spec) for spec in _SPECS]
