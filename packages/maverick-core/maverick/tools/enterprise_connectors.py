"""Enterprise connector specs (the long tail), built on ``make_rest_tool``.

Each entry is a thin authenticated-REST tool: explicit-env auth, the agent
supplies the path, writes are confirm-gated. Add a system by appending one
spec here — no new module per connector. Systems that need a bespoke shape
(specific ops, GraphQL, CSRF, SQL result parsing) keep their own module
(servicenow_tool, snowflake_tool, sap_tool, ...).
"""
from __future__ import annotations

from . import Tool
from ._rest_connector import make_graphql_tool, make_rest_tool


def _fill_env(spec: dict) -> dict:
    """Default a spec's env-var names from its ``name``.

    Almost every connector follows the ``<NAME>_BASE_URL`` / ``<NAME>_TOKEN``
    convention, so a spec only spells those out when it deviates (e.g.
    ``salesforce_commerce`` -> ``SFCC_*``). Filling them here keeps the spec
    list free of that mechanical, typo-prone repetition.
    """
    n = spec["name"].upper()
    spec.setdefault("base_url_env", f"{n}_BASE_URL")
    spec.setdefault("token_env", f"{n}_TOKEN")
    return spec


# name, description, **auth-overrides (base_url_env/token_env default to
# <NAME>_BASE_URL / <NAME>_TOKEN -- spell them out only when they differ).
_SPECS: list[dict] = [
    # --- Support / CX ---
    dict(name="zendesk",
         description="Zendesk Support REST. ops get/post/put/delete (writes need "
         "confirm). e.g. /api/v2/tickets.json, /api/v2/search.json?query=. "
         "Auth: ZENDESK_BASE_URL (https://{sub}.zendesk.com) + ZENDESK_TOKEN."),
    dict(name="freshdesk",
         basic=True, description="Freshdesk REST. ops get/post/put/delete (writes "
         "need confirm). e.g. /api/v2/tickets. Auth: FRESHDESK_BASE_URL "
         "(https://{sub}.freshdesk.com) + FRESHDESK_TOKEN (API key)."),
    dict(name="freshservice", basic=True,
         description="Freshservice ITSM REST. ops get/post/put/delete (writes need "
         "confirm). e.g. /api/v2/tickets. Auth: FRESHSERVICE_BASE_URL + "
         "FRESHSERVICE_TOKEN (API key)."),
    dict(name="intercom",
         description="Intercom REST. ops get/post/put/delete (writes need confirm). "
         "e.g. /contacts, /conversations. Auth: INTERCOM_BASE_URL "
         "(https://api.intercom.io) + INTERCOM_TOKEN."),
    # --- Identity ---
    dict(name="okta",
         scheme="SSWS", description="Okta management REST. ops get/post/put/delete "
         "(writes need confirm). e.g. /api/v1/users, /api/v1/groups. Auth: "
         "OKTA_BASE_URL (https://{org}.okta.com) + OKTA_TOKEN (SSWS API token)."),
    # --- Content / storage / e-sign ---
    dict(name="box",
         description="Box content REST. ops get/post/put/delete (writes need "
         "confirm). e.g. /folders/0/items, /search?query=. Auth: BOX_BASE_URL "
         "(https://api.box.com/2.0) + BOX_TOKEN."),
    dict(name="docusign",
         description="DocuSign eSignature REST. ops get/post/put/delete (writes need "
         "confirm). e.g. /restapi/v2.1/accounts/{acct}/envelopes. Auth: "
         "DOCUSIGN_BASE_URL + DOCUSIGN_TOKEN."),
    # --- Procurement / spend ---
    dict(name="coupa",
         description="Coupa spend/procurement REST. ops get/post/put/delete (writes "
         "need confirm). e.g. /api/requisitions, /api/purchase_orders. Auth: "
         "COUPA_BASE_URL + COUPA_TOKEN."),
    dict(name="ariba",
         description="SAP Ariba REST. ops get/post/put/delete (writes need confirm). "
         "Auth: ARIBA_BASE_URL + ARIBA_TOKEN."),
    # --- Work management ---
    dict(name="smartsheet",
         description="Smartsheet REST. ops get/post/put/delete (writes need confirm). "
         "e.g. /sheets, /sheets/{id}/rows. Auth: SMARTSHEET_BASE_URL "
         "(https://api.smartsheet.com/2.0) + SMARTSHEET_TOKEN."),
    dict(name="wrike",
         description="Wrike work-management REST. ops get/post/put/delete (writes "
         "need confirm). e.g. /tasks, /folders. Auth: WRIKE_BASE_URL "
         "(https://www.wrike.com/api/v4) + WRIKE_TOKEN."),
    # --- HR / recruiting ---
    dict(name="bamboohr",
         basic=True, description="BambooHR REST. ops get/post/put/delete (writes need "
         "confirm). e.g. /v1/employees/directory. Auth: BAMBOOHR_BASE_URL "
         "(https://api.bamboohr.com/api/gateway.php/{company}) + BAMBOOHR_TOKEN (API key)."),
    dict(name="greenhouse",
         basic=True, description="Greenhouse Harvest REST. ops get/post/put/delete "
         "(writes need confirm). e.g. /v1/candidates, /v1/jobs. Auth: "
         "GREENHOUSE_BASE_URL (https://harvest.greenhouse.io) + GREENHOUSE_TOKEN (API key)."),
    dict(name="lever",
         basic=True, description="Lever recruiting REST. ops get/post/put/delete "
         "(writes need confirm). e.g. /v1/opportunities, /v1/postings. Auth: "
         "LEVER_BASE_URL (https://api.lever.co) + LEVER_TOKEN (API key)."),
    # --- BI / analytics ---
    dict(name="tableau",
         token_header="X-Tableau-Auth", scheme="",
         description="Tableau Server/Cloud REST. ops get/post/put/delete (writes need "
         "confirm). e.g. /api/3.21/sites/{id}/workbooks. Auth: TABLEAU_BASE_URL + "
         "TABLEAU_TOKEN (signed-in X-Tableau-Auth token)."),
    dict(name="powerbi",
         description="Microsoft Power BI REST. ops get/post/put/delete (writes need "
         "confirm). e.g. /groups, /datasets, /reports. Auth: POWERBI_BASE_URL "
         "(https://api.powerbi.com/v1.0/myorg) + POWERBI_TOKEN."),
    dict(name="looker",
         scheme="token", description="Looker REST. ops get/post/put/delete (writes "
         "need confirm). e.g. /api/4.0/looks, /api/4.0/dashboards. Auth: "
         "LOOKER_BASE_URL + LOOKER_TOKEN (Authorization: token <access_token>)."),
    # --- Observability ---
    dict(name="newrelic",
         token_header="Api-Key", scheme="",
         description="New Relic REST. ops get/post/put/delete (writes need confirm). "
         "e.g. /v2/applications.json. Auth: NEWRELIC_BASE_URL "
         "(https://api.newrelic.com) + NEWRELIC_TOKEN (Api-Key header)."),
    dict(name="dynatrace",
         scheme="Api-Token", description="Dynatrace REST. ops get/post/put/delete "
         "(writes need confirm). e.g. /api/v2/problems, /api/v2/metrics/query. Auth: "
         "DYNATRACE_BASE_URL + DYNATRACE_TOKEN (Authorization: Api-Token <tok>)."),
    dict(name="grafana",
         description="Grafana REST. ops get/post/put/delete (writes need confirm). "
         "e.g. /api/dashboards/uid/{uid}, /api/datasources. Auth: GRAFANA_BASE_URL "
         "+ GRAFANA_TOKEN (service-account token)."),

    # --- CRM / sales engagement ---
    dict(name="zoho",
         scheme="Zoho-oauthtoken", description="Zoho CRM REST. ops "
         "get/post/put/patch/delete (writes need confirm). e.g. /crm/v5/Leads. "
         "Auth: ZOHO_BASE_URL + ZOHO_TOKEN (Zoho-oauthtoken)."),
    dict(name="pipedrive",
         description="Pipedrive REST. ops get/post/put/delete (writes need confirm). "
         "e.g. /v1/deals, /v1/persons. Auth: PIPEDRIVE_BASE_URL + PIPEDRIVE_TOKEN."),
    dict(name="salesloft",
         description="Salesloft REST. ops get/post/put/delete (writes need confirm). "
         "e.g. /v2/people, /v2/cadences. Auth: SALESLOFT_BASE_URL + SALESLOFT_TOKEN."),
    dict(name="outreach",
         description="Outreach REST. ops get/post/patch/delete (writes need confirm). "
         "e.g. /api/v2/prospects, /api/v2/sequences. Auth: OUTREACH_BASE_URL + OUTREACH_TOKEN."),
    dict(name="gong", basic=True,
         description="Gong revenue-intelligence REST. ops get/post (writes need "
         "confirm). e.g. /v2/calls, /v2/users. Auth: GONG_BASE_URL + GONG_TOKEN "
         "(accessKey:secret, basic)."),
    dict(name="clari",
         token_header="apikey", scheme="", description="Clari REST. ops get/post "
         "(writes need confirm). Auth: CLARI_BASE_URL + CLARI_TOKEN (apikey header)."),
    dict(name="creatio",
         description="Creatio (bpm'online) OData REST. ops get/post/patch/delete "
         "(writes need confirm). Auth: CREATIO_BASE_URL + CREATIO_TOKEN."),
    dict(name="pega",
         description="Pega REST. ops get/post/put/delete (writes need confirm). "
         "e.g. /prweb/api/v1/cases. Auth: PEGA_BASE_URL + PEGA_TOKEN."),

    # --- ERP / finance ---
    dict(name="sage_intacct", description="Sage Intacct REST. ops "
         "get/post/put/delete (writes need confirm). Auth: SAGE_INTACCT_BASE_URL + "
         "SAGE_INTACCT_TOKEN."),
    dict(name="epicor",
         basic=True, description="Epicor ERP REST. ops get/post/patch/delete (writes "
         "need confirm). Auth: EPICOR_BASE_URL + EPICOR_TOKEN (user:pass, basic)."),
    dict(name="ifs",
         description="IFS Cloud OData REST. ops get/post/patch/delete (writes need "
         "confirm). Auth: IFS_BASE_URL + IFS_TOKEN."),
    dict(name="unit4",
         description="Unit4 ERP REST. ops get/post/put/delete (writes need confirm). "
         "Auth: UNIT4_BASE_URL + UNIT4_TOKEN."),
    dict(name="acumatica",
         description="Acumatica REST. ops get/put/delete (writes need confirm). "
         "e.g. /entity/Default/.../SalesOrder. Auth: ACUMATICA_BASE_URL + ACUMATICA_TOKEN."),
    dict(name="quickbooks",
         description="QuickBooks Online REST. ops get/post (writes need confirm). "
         "e.g. /v3/company/{id}/query. Auth: QUICKBOOKS_BASE_URL + QUICKBOOKS_TOKEN."),
    dict(name="xero",
         description="Xero accounting REST. ops get/post/put (writes need confirm). "
         "e.g. /api.xro/2.0/Invoices. Auth: XERO_BASE_URL + XERO_TOKEN."),
    dict(name="billdotcom",
         description="Bill.com REST. ops get/post (writes need confirm). Auth: "
         "BILLDOTCOM_BASE_URL + BILLDOTCOM_TOKEN."),

    # --- Support / CX / contact center ---
    dict(name="genesys",
         description="Genesys Cloud REST. ops get/post/put/patch/delete (writes need "
         "confirm). e.g. /api/v2/conversations. Auth: GENESYS_BASE_URL + GENESYS_TOKEN."),
    dict(name="nice_cxone",
         description="NICE CXone REST. ops get/post/put/delete (writes need confirm). "
         "Auth: NICE_CXONE_BASE_URL + NICE_CXONE_TOKEN."),
    dict(name="five9", basic=True,
         description="Five9 REST. ops get/post/put/delete (writes need confirm). "
         "Auth: FIVE9_BASE_URL + FIVE9_TOKEN (user:pass, basic)."),
    dict(name="talkdesk",
         description="Talkdesk REST. ops get/post/put/delete (writes need confirm). "
         "Auth: TALKDESK_BASE_URL + TALKDESK_TOKEN."),
    dict(name="helpscout",
         description="Help Scout REST. ops get/post/put/patch/delete (writes need "
         "confirm). e.g. /v2/conversations. Auth: HELPSCOUT_BASE_URL + HELPSCOUT_TOKEN."),
    dict(name="kustomer",
         description="Kustomer REST. ops get/post/put/delete (writes need confirm). "
         "Auth: KUSTOMER_BASE_URL + KUSTOMER_TOKEN."),
    dict(name="sprinklr",
         description="Sprinklr REST. ops get/post/put/delete (writes need confirm). "
         "Auth: SPRINKLR_BASE_URL + SPRINKLR_TOKEN."),

    # --- ITSM / alerting ---
    dict(name="bmc_helix",
         scheme="AR-JWT", description="BMC Helix / Remedy REST. ops get/post/put/delete "
         "(writes need confirm). Auth: BMC_HELIX_BASE_URL + BMC_HELIX_TOKEN (AR-JWT)."),
    dict(name="ivanti",
         description="Ivanti Neurons / ITSM REST. ops get/post/put/delete (writes need "
         "confirm). Auth: IVANTI_BASE_URL + IVANTI_TOKEN."),
    dict(name="solarwinds",
         description="SolarWinds Service Desk REST. ops get/post/put/delete (writes "
         "need confirm). Auth: SOLARWINDS_BASE_URL + SOLARWINDS_TOKEN."),
    dict(name="manageengine", scheme="Zoho-oauthtoken",
         description="ManageEngine ServiceDesk Plus REST. ops get/post/put/delete "
         "(writes need confirm). Auth: MANAGEENGINE_BASE_URL + MANAGEENGINE_TOKEN."),
    dict(name="xmatters",
         description="xMatters REST. ops get/post/delete (writes need confirm). "
         "e.g. /api/xm/1/events. Auth: XMATTERS_BASE_URL + XMATTERS_TOKEN."),

    # --- HR ---
    dict(name="rippling",
         description="Rippling REST. ops get/post (writes need confirm). e.g. "
         "/platform/api/employees. Auth: RIPPLING_BASE_URL + RIPPLING_TOKEN."),
    dict(name="gusto",
         description="Gusto REST. ops get/post/put (writes need confirm). e.g. "
         "/v1/companies/{id}/employees. Auth: GUSTO_BASE_URL + GUSTO_TOKEN."),

    # --- Cloud / infra ---
    dict(name="fastly",
         token_header="Fastly-Key", scheme="", description="Fastly REST. ops "
         "get/post/put/delete (writes need confirm). Auth: FASTLY_BASE_URL + "
         "FASTLY_TOKEN (Fastly-Key)."),
    dict(name="akamai",
         description="Akamai REST. ops get/post/put/delete (writes need confirm). "
         "Auth: AKAMAI_BASE_URL + AKAMAI_TOKEN."),
    dict(name="digitalocean", description="DigitalOcean REST. ops "
         "get/post/put/delete (writes need confirm). e.g. /v2/droplets. Auth: "
         "DIGITALOCEAN_BASE_URL (https://api.digitalocean.com) + DIGITALOCEAN_TOKEN."),
    dict(name="terraform",
         description="Terraform Cloud/Enterprise REST. ops get/post/patch/delete "
         "(writes need confirm). e.g. /api/v2/organizations/{org}/workspaces. Auth: "
         "TERRAFORM_BASE_URL + TERRAFORM_TOKEN."),
    dict(name="vault",
         token_header="X-Vault-Token", scheme="", description="HashiCorp Vault REST. "
         "ops get/post/delete (writes need confirm). e.g. /v1/secret/data/{path}. "
         "Auth: VAULT_BASE_URL + VAULT_TOKEN (X-Vault-Token)."),

    # --- Identity / IAM ---
    dict(name="pingone",
         description="Ping Identity (PingOne) REST. ops get/post/put/delete (writes "
         "need confirm). Auth: PINGONE_BASE_URL + PINGONE_TOKEN."),
    dict(name="cyberark",
         description="CyberArk REST. ops get/post/put/delete (writes need confirm). "
         "Auth: CYBERARK_BASE_URL + CYBERARK_TOKEN."),
    dict(name="sailpoint",
         description="SailPoint IdentityNow REST. ops get/post/patch/delete (writes "
         "need confirm). e.g. /v3/accounts. Auth: SAILPOINT_BASE_URL + SAILPOINT_TOKEN."),
    dict(name="onelogin",
         description="OneLogin REST. ops get/post/put/delete (writes need confirm). "
         "e.g. /api/2/users. Auth: ONELOGIN_BASE_URL + ONELOGIN_TOKEN."),
    dict(name="auth0",
         description="Auth0 Management REST. ops get/post/patch/delete (writes need "
         "confirm). e.g. /api/v2/users. Auth: AUTH0_BASE_URL + AUTH0_TOKEN."),
    dict(name="duo", basic=True,
         description="Cisco Duo Admin REST. ops get/post (writes need confirm). "
         "Auth: DUO_BASE_URL + DUO_TOKEN (ikey:skey, basic)."),

    # --- Security / SIEM / endpoint ---
    dict(name="crowdstrike", description="CrowdStrike Falcon REST. ops "
         "get/post/patch/delete (writes need confirm). e.g. /detects/queries/detects/v1. "
         "Auth: CROWDSTRIKE_BASE_URL + CROWDSTRIKE_TOKEN."),
    dict(name="splunk",
         description="Splunk REST. ops get/post/delete (writes need confirm). e.g. "
         "/services/search/jobs. Auth: SPLUNK_BASE_URL + SPLUNK_TOKEN."),
    dict(name="zscaler",
         description="Zscaler REST. ops get/post/put/delete (writes need confirm). "
         "Auth: ZSCALER_BASE_URL + ZSCALER_TOKEN."),
    dict(name="tenable",
         token_header="X-ApiKeys", scheme="", description="Tenable.io REST. ops "
         "get/post/put/delete (writes need confirm). Auth: TENABLE_BASE_URL + "
         "TENABLE_TOKEN ('accessKey=...;secretKey=...')."),
    dict(name="qualys",
         basic=True, description="Qualys REST. ops get/post (writes need confirm). "
         "Auth: QUALYS_BASE_URL + QUALYS_TOKEN (user:pass, basic)."),
    dict(name="rapid7",
         token_header="X-Api-Key", scheme="", description="Rapid7 InsightVM/IDR REST. "
         "ops get/post/put/delete (writes need confirm). Auth: RAPID7_BASE_URL + "
         "RAPID7_TOKEN (X-Api-Key)."),
    dict(name="sentinelone", scheme="ApiToken", description="SentinelOne "
         "REST. ops get/post/delete (writes need confirm). e.g. /web/api/v2.1/agents. "
         "Auth: SENTINELONE_BASE_URL + SENTINELONE_TOKEN (ApiToken)."),
    dict(name="proofpoint", basic=True, description="Proofpoint REST. ops "
         "get/post (writes need confirm). Auth: PROOFPOINT_BASE_URL + PROOFPOINT_TOKEN "
         "(principal:secret, basic)."),
    dict(name="snyk",
         scheme="token", description="Snyk REST. ops get/post/delete (writes need "
         "confirm). e.g. /rest/orgs. Auth: SNYK_BASE_URL + SNYK_TOKEN (token <key>)."),
    dict(name="fortinet",
         description="Fortinet FortiGate/FortiManager REST. ops get/post/put/delete "
         "(writes need confirm). Auth: FORTINET_BASE_URL + FORTINET_TOKEN."),

    # --- BI / analytics ---
    dict(name="qlik",
         description="Qlik Cloud REST. ops get/post/put/delete (writes need confirm). "
         "e.g. /api/v1/apps. Auth: QLIK_BASE_URL + QLIK_TOKEN."),
    dict(name="thoughtspot", description="ThoughtSpot REST. ops get/post "
         "(writes need confirm). e.g. /api/rest/2.0/metadata/search. Auth: "
         "THOUGHTSPOT_BASE_URL + THOUGHTSPOT_TOKEN."),
    dict(name="sisense",
         description="Sisense REST. ops get/post/put/delete (writes need confirm). "
         "Auth: SISENSE_BASE_URL + SISENSE_TOKEN."),
    dict(name="domo",
         description="Domo REST. ops get/post/put/delete (writes need confirm). "
         "e.g. /v1/datasets. Auth: DOMO_BASE_URL + DOMO_TOKEN."),
    dict(name="mode", basic=True,
         description="Mode Analytics REST. ops get/post (writes need confirm). Auth: "
         "MODE_BASE_URL + MODE_TOKEN (token:secret, basic)."),
    dict(name="metabase",
         token_header="X-API-Key", scheme="", description="Metabase REST. ops "
         "get/post/put/delete (writes need confirm). e.g. /api/card. Auth: "
         "METABASE_BASE_URL + METABASE_TOKEN (X-API-Key)."),

    # --- DevOps / CI ---
    dict(name="jenkins",
         basic=True, description="Jenkins REST. ops get/post (writes need confirm). "
         "e.g. /api/json, /job/{name}/build. Auth: JENKINS_BASE_URL + JENKINS_TOKEN "
         "(user:apitoken, basic)."),
    dict(name="circleci",
         token_header="Circle-Token", scheme="", description="CircleCI REST. ops "
         "get/post (writes need confirm). e.g. /api/v2/project/{slug}/pipeline. Auth: "
         "CIRCLECI_BASE_URL + CIRCLECI_TOKEN (Circle-Token)."),
    dict(name="jfrog",
         description="JFrog Artifactory REST. ops get/post/put/delete (writes need "
         "confirm). e.g. /artifactory/api/repositories. Auth: JFROG_BASE_URL + JFROG_TOKEN."),
    dict(name="sonarqube",
         basic=True, description="SonarQube REST. ops get/post (writes need confirm). "
         "e.g. /api/issues/search, /api/projects/search. Auth: SONARQUBE_BASE_URL + "
         "SONARQUBE_TOKEN (token:, basic)."),
    dict(name="azure_devops", basic=True, description="Azure DevOps REST. "
         "ops get/post/patch/put (writes need confirm). e.g. /{org}/{proj}/_apis/wit/"
         "workitems. Auth: AZURE_DEVOPS_BASE_URL + AZURE_DEVOPS_TOKEN (:PAT, basic)."),

    # --- Marketing / commerce ---
    dict(name="mailchimp",
         basic=True, description="Mailchimp Marketing REST. ops get/post/put/patch/"
         "delete (writes need confirm). e.g. /3.0/lists. Auth: MAILCHIMP_BASE_URL + "
         "MAILCHIMP_TOKEN (anystring:apikey, basic)."),
    dict(name="klaviyo",
         scheme="Klaviyo-API-Key", description="Klaviyo REST. ops get/post/patch/delete "
         "(writes need confirm). Auth: KLAVIYO_BASE_URL + KLAVIYO_TOKEN (Klaviyo-API-Key)."),
    dict(name="braze",
         description="Braze REST. ops get/post (writes need confirm). e.g. "
         "/users/export/ids, /messages/send. Auth: BRAZE_BASE_URL + BRAZE_TOKEN."),
    dict(name="marketo",
         description="Adobe Marketo Engage REST. ops get/post (writes need confirm). "
         "e.g. /rest/v1/leads.json. Auth: MARKETO_BASE_URL + MARKETO_TOKEN."),
    dict(name="sfmc",
         description="Salesforce Marketing Cloud REST. ops get/post/put/delete (writes "
         "need confirm). Auth: SFMC_BASE_URL + SFMC_TOKEN."),
    dict(name="segment",
         description="Twilio Segment Public API. ops get/post/patch/delete (writes "
         "need confirm). e.g. /workspaces, /sources. Auth: SEGMENT_BASE_URL + SEGMENT_TOKEN."),
    dict(name="adobe_analytics", description="Adobe Analytics 2.0 REST. ops "
         "get/post (writes need confirm). e.g. /reports. Auth: ADOBE_ANALYTICS_BASE_URL "
         "+ ADOBE_ANALYTICS_TOKEN."),
    dict(name="aem", basic=True,
         description="Adobe Experience Manager REST. ops get/post/put/delete (writes "
         "need confirm). Auth: AEM_BASE_URL + AEM_TOKEN (user:pass, basic)."),
    dict(name="bigcommerce", token_header="X-Auth-Token", scheme="",
         description="BigCommerce REST. ops get/post/put/delete (writes need confirm). "
         "e.g. /v3/catalog/products. Auth: BIGCOMMERCE_BASE_URL + BIGCOMMERCE_TOKEN "
         "(X-Auth-Token)."),
    dict(name="sendgrid",
         description="Twilio SendGrid REST. ops get/post/put/patch/delete (writes need "
         "confirm). e.g. /v3/mail/send, /v3/marketing/contacts. Auth: SENDGRID_BASE_URL "
         "(https://api.sendgrid.com) + SENDGRID_TOKEN."),

    # --- Data / ETL / streaming ---
    dict(name="fivetran",
         basic=True, description="Fivetran REST. ops get/post/patch/delete (writes need "
         "confirm). e.g. /v1/connectors. Auth: FIVETRAN_BASE_URL + FIVETRAN_TOKEN "
         "(apikey:apisecret, basic)."),
    dict(name="dbt", scheme="Token",
         description="dbt Cloud REST. ops get/post (writes need confirm). e.g. "
         "/api/v2/accounts/{id}/jobs. Auth: DBT_BASE_URL + DBT_TOKEN (Token <key>)."),
    dict(name="airflow",
         basic=True, description="Apache Airflow REST. ops get/post/patch/delete "
         "(writes need confirm). e.g. /api/v1/dags. Auth: AIRFLOW_BASE_URL + "
         "AIRFLOW_TOKEN (user:pass, basic)."),
    dict(name="confluent",
         basic=True, description="Confluent Cloud REST. ops get/post/patch/delete "
         "(writes need confirm). e.g. /kafka/v3/clusters. Auth: CONFLUENT_BASE_URL + "
         "CONFLUENT_TOKEN (key:secret, basic)."),
    dict(name="informatica", description="Informatica IICS REST. ops "
         "get/post (writes need confirm). Auth: INFORMATICA_BASE_URL + INFORMATICA_TOKEN."),
    dict(name="talend",
         description="Talend Cloud REST. ops get/post/put/delete (writes need confirm). "
         "Auth: TALEND_BASE_URL + TALEND_TOKEN."),
    dict(name="matillion",
         basic=True, description="Matillion REST. ops get/post (writes need confirm). "
         "Auth: MATILLION_BASE_URL + MATILLION_TOKEN (user:pass, basic)."),
    dict(name="cloudera",
         basic=True, description="Cloudera Manager REST. ops get/post/put/delete "
         "(writes need confirm). Auth: CLOUDERA_BASE_URL + CLOUDERA_TOKEN (user:pass, basic)."),

    # --- Collaboration / PM ---
    dict(name="miro",
         description="Miro REST. ops get/post/patch/delete (writes need confirm). "
         "e.g. /v2/boards. Auth: MIRO_BASE_URL (https://api.miro.com) + MIRO_TOKEN."),
    dict(name="coda",
         description="Coda REST. ops get/post/put/delete (writes need confirm). e.g. "
         "/v1/docs. Auth: CODA_BASE_URL (https://coda.io/apis/v1) + CODA_TOKEN."),
    dict(name="basecamp",
         description="Basecamp REST. ops get/post/put (writes need confirm). Auth: "
         "BASECAMP_BASE_URL + BASECAMP_TOKEN."),
    dict(name="planview",
         description="Planview REST. ops get/post/put/delete (writes need confirm). "
         "Auth: PLANVIEW_BASE_URL + PLANVIEW_TOKEN."),

    # --- ERP / HR (additional) ---
    dict(name="infor",
         description="Infor CloudSuite (ION) REST. ops get/post/put/delete (writes "
         "need confirm). Auth: INFOR_BASE_URL + INFOR_TOKEN."),
    dict(name="netsuite",
         description="Oracle NetSuite SuiteTalk REST. ops get/post/patch/delete (writes "
         "need confirm). e.g. /services/rest/record/v1/salesOrder. Auth: "
         "NETSUITE_BASE_URL + NETSUITE_TOKEN."),
    dict(name="adp",
         description="ADP Workforce Now REST. ops get/post (writes need confirm). e.g. "
         "/hr/v2/workers. Auth: ADP_BASE_URL + ADP_TOKEN."),
    dict(name="ukg",
         description="UKG (Ultimate Kronos) REST. ops get/post/put/delete (writes need "
         "confirm). Auth: UKG_BASE_URL + UKG_TOKEN."),

    # --- iPaaS / integration ---
    dict(name="mulesoft",
         description="MuleSoft Anypoint REST. ops get/post/put/delete (writes need "
         "confirm). Auth: MULESOFT_BASE_URL + MULESOFT_TOKEN."),
    dict(name="boomi", basic=True,
         description="Boomi AtomSphere REST. ops get/post (writes need confirm). Auth: "
         "BOOMI_BASE_URL + BOOMI_TOKEN (user:token, basic)."),
    dict(name="workato",
         description="Workato REST. ops get/post/put/delete (writes need confirm). "
         "Auth: WORKATO_BASE_URL + WORKATO_TOKEN."),
    dict(name="zapier",
         description="Zapier NLA / REST. ops get/post (writes need confirm). Auth: "
         "ZAPIER_BASE_URL + ZAPIER_TOKEN."),

    # --- Cloud platforms / orchestration (control-plane REST) ---
    dict(name="kubernetes",
         description="Kubernetes API server REST. ops get/post/patch/delete (writes "
         "need confirm). e.g. /api/v1/namespaces/{ns}/pods. Auth: KUBERNETES_BASE_URL "
         "+ KUBERNETES_TOKEN (service-account bearer)."),
    dict(name="openshift",
         description="Red Hat OpenShift API REST. ops get/post/patch/delete (writes "
         "need confirm). Auth: OPENSHIFT_BASE_URL + OPENSHIFT_TOKEN (bearer)."),
    dict(name="vsphere",
         token_header="vmware-api-session-id", scheme="", description="VMware vSphere "
         "REST. ops get/post/patch/delete (writes need confirm). e.g. /api/vcenter/vm. "
         "Auth: VSPHERE_BASE_URL + VSPHERE_TOKEN (session id)."),
    dict(name="azure",
         description="Microsoft Azure Resource Manager REST. ops get/put/post/patch/"
         "delete (writes need confirm). e.g. /subscriptions/{id}/resourcegroups. Auth: "
         "AZURE_BASE_URL (https://management.azure.com) + AZURE_TOKEN."),
    dict(name="gcp",
         description="Google Cloud REST (Compute/Resource Manager/...). ops get/post/"
         "patch/delete (writes need confirm). Auth: GCP_BASE_URL + GCP_TOKEN (OAuth "
         "bearer, e.g. gcloud auth print-access-token)."),
    dict(name="ibm_cloud",
         description="IBM Cloud REST. ops get/post/put/delete (writes need confirm). "
         "Auth: IBM_CLOUD_BASE_URL + IBM_CLOUD_TOKEN (IAM bearer)."),
    dict(name="alibaba_cloud", description="Alibaba Cloud REST. ops get/post "
         "(writes need confirm). Auth: ALIBABA_CLOUD_BASE_URL + ALIBABA_CLOUD_TOKEN."),

    # --- Security (cloud-native / SIEM) ---
    dict(name="sentinel",
         description="Microsoft Sentinel REST (Azure). ops get/put/post/delete (writes "
         "need confirm). e.g. .../providers/Microsoft.SecurityInsights/incidents. Auth: "
         "SENTINEL_BASE_URL + SENTINEL_TOKEN."),
    dict(name="defender",
         description="Microsoft Defender REST. ops get/post (writes need confirm). e.g. "
         "/api/alerts, /api/machines. Auth: DEFENDER_BASE_URL + DEFENDER_TOKEN."),
    dict(name="qradar",
         token_header="SEC", scheme="", description="IBM QRadar REST. ops get/post "
         "(writes need confirm). e.g. /api/siem/offenses. Auth: QRADAR_BASE_URL + "
         "QRADAR_TOKEN (SEC header)."),
    dict(name="palo_alto",
         description="Palo Alto Networks (Cortex/Prisma) REST. ops get/post (writes "
         "need confirm). Auth: PALO_ALTO_BASE_URL + PALO_ALTO_TOKEN."),
    dict(name="jamf",
         description="Jamf Pro REST. ops get/post/put/delete (writes need confirm). "
         "e.g. /api/v1/computers-inventory. Auth: JAMF_BASE_URL + JAMF_TOKEN."),

    # --- Comms ---
    dict(name="ringcentral", description="RingCentral REST. ops get/post/"
         "put/delete (writes need confirm). e.g. /restapi/v1.0/account/~/extension. "
         "Auth: RINGCENTRAL_BASE_URL + RINGCENTRAL_TOKEN."),
    dict(name="vonage",
         description="Vonage REST. ops get/post (writes need confirm). Auth: "
         "VONAGE_BASE_URL + VONAGE_TOKEN."),
    dict(name="webex",
         description="Cisco Webex REST. ops get/post/put/delete (writes need confirm). "
         "e.g. /v1/messages, /v1/rooms. Auth: WEBEX_BASE_URL (https://webexapis.com) + "
         "WEBEX_TOKEN."),

    # --- Databases / BI over REST ---
    dict(name="neo4j", basic=True,
         description="Neo4j HTTP API (Cypher). op post (Cypher via /db/neo4j/tx/commit; "
         "needs confirm). Auth: NEO4J_BASE_URL + NEO4J_TOKEN (user:pass, basic)."),
    dict(name="teradata",
         basic=True, description="Teradata REST (Vantage). ops get/post (writes need "
         "confirm). Auth: TERADATA_BASE_URL + TERADATA_TOKEN (user:pass, basic)."),
    dict(name="microstrategy", token_header="X-MSTR-AuthToken", scheme="",
         description="MicroStrategy REST. ops get/post/put/delete (writes need confirm). "
         "Auth: MICROSTRATEGY_BASE_URL + MICROSTRATEGY_TOKEN (X-MSTR-AuthToken)."),
    dict(name="cognos",
         description="IBM Cognos Analytics REST. ops get/post (writes need confirm). "
         "Auth: COGNOS_BASE_URL + COGNOS_TOKEN."),

    # --- Finance / ERP / HR / CS (additional) ---
    dict(name="concur",
         description="SAP Concur REST. ops get/post/put/delete (writes need confirm). "
         "e.g. /expensereports/v4/reports. Auth: CONCUR_BASE_URL + CONCUR_TOKEN."),
    dict(name="anaplan",
         description="Anaplan REST. ops get/post/put (writes need confirm). Auth: "
         "ANAPLAN_BASE_URL + ANAPLAN_TOKEN."),
    dict(name="smartrecruiters", token_header="X-SmartToken", scheme="",
         description="SmartRecruiters REST. ops get/post/put/delete (writes need "
         "confirm). Auth: SMARTRECRUITERS_BASE_URL + SMARTRECRUITERS_TOKEN (X-SmartToken)."),
    dict(name="gainsight",
         token_header="accesskey", scheme="", description="Gainsight REST. ops get/post "
         "(writes need confirm). Auth: GAINSIGHT_BASE_URL + GAINSIGHT_TOKEN (accesskey)."),
    dict(name="amplitude",
         basic=True, description="Amplitude Analytics REST. ops get/post (writes need "
         "confirm). Auth: AMPLITUDE_BASE_URL + AMPLITUDE_TOKEN (apikey:secret, basic)."),

    # --- Payments / spend / financial close ---
    dict(name="square",
         description="Square REST. ops get/post/put/delete (writes need confirm). Auth: "
         "SQUARE_BASE_URL (https://connect.squareup.com) + SQUARE_TOKEN (bearer)."),
    dict(name="paypal",
         description="PayPal REST. ops get/post/put/delete (writes need confirm). Auth: "
         "PAYPAL_BASE_URL (https://api-m.paypal.com) + PAYPAL_TOKEN (OAuth bearer)."),
    dict(name="adyen",
         token_header="X-API-Key", scheme="", description="Adyen REST. ops get/post "
         "(writes need confirm). Auth: ADYEN_BASE_URL + ADYEN_TOKEN (X-API-Key)."),
    dict(name="ramp",
         description="Ramp REST (spend). ops get/post/put/delete (writes need confirm). "
         "Auth: RAMP_BASE_URL (https://api.ramp.com) + RAMP_TOKEN (bearer)."),
    dict(name="brex",
         description="Brex REST (spend). ops get/post/put/delete (writes need confirm). "
         "Auth: BREX_BASE_URL (https://platform.brexapis.com) + BREX_TOKEN (bearer)."),
    dict(name="blackline",
         description="BlackLine REST (financial close). ops get/post (writes need "
         "confirm). Auth: BLACKLINE_BASE_URL + BLACKLINE_TOKEN (bearer)."),
    dict(name="workiva",
         description="Workiva (Wdesk) REST. ops get/post/put/delete (writes need "
         "confirm). Auth: WORKIVA_BASE_URL + WORKIVA_TOKEN (bearer)."),

    # --- HR / HCM / payroll / recruiting (additional) ---
    dict(name="successfactors", basic=True, description="SAP SuccessFactors "
         "OData REST. ops get/post (writes need confirm). Auth: SUCCESSFACTORS_BASE_URL + "
         "SUCCESSFACTORS_TOKEN (user@company:pass, basic)."),
    dict(name="cornerstone", description="Cornerstone OnDemand REST. ops "
         "get/post (writes need confirm). Auth: CORNERSTONE_BASE_URL + CORNERSTONE_TOKEN (bearer)."),
    dict(name="icims", basic=True,
         description="iCIMS REST (recruiting). ops get/post (writes need confirm). Auth: "
         "ICIMS_BASE_URL + ICIMS_TOKEN (user:pass, basic)."),
    dict(name="paylocity",
         description="Paylocity REST. ops get/post/put (writes need confirm). Auth: "
         "PAYLOCITY_BASE_URL + PAYLOCITY_TOKEN (OAuth bearer)."),
    dict(name="workable",
         description="Workable REST (recruiting). ops get/post (writes need confirm). "
         "Auth: WORKABLE_BASE_URL + WORKABLE_TOKEN (bearer)."),
    dict(name="deel",
         description="Deel REST (global payroll/EOR). ops get/post/put/delete (writes "
         "need confirm). Auth: DEEL_BASE_URL + DEEL_TOKEN (bearer)."),

    # --- Commerce platforms ---
    dict(name="magento",
         description="Adobe Commerce (Magento) REST. ops get/post/put/delete (writes "
         "need confirm). e.g. /rest/V1/products. Auth: MAGENTO_BASE_URL + MAGENTO_TOKEN (bearer)."),
    dict(name="salesforce_commerce", base_url_env="SFCC_BASE_URL", token_env="SFCC_TOKEN",
         description="Salesforce Commerce Cloud (SCAPI/OCAPI) REST. ops get/post/put/"
         "delete (writes need confirm). Auth: SFCC_BASE_URL + SFCC_TOKEN (bearer)."),
    dict(name="sap_commerce", description="SAP Commerce Cloud (Hybris) OCC "
         "REST. ops get/post/put/delete (writes need confirm). Auth: SAP_COMMERCE_BASE_URL "
         "+ SAP_COMMERCE_TOKEN (OAuth bearer)."),

    # --- Observability / APM (additional) ---
    dict(name="appdynamics", description="AppDynamics REST. ops get/post "
         "(writes need confirm). Auth: APPDYNAMICS_BASE_URL + APPDYNAMICS_TOKEN (OAuth bearer)."),
    dict(name="sumologic",
         basic=True, description="Sumo Logic REST. ops get/post/put/delete (writes need "
         "confirm). Auth: SUMOLOGIC_BASE_URL + SUMOLOGIC_TOKEN (accessId:accessKey, basic)."),
    dict(name="logicmonitor", description="LogicMonitor REST. ops get/post "
         "(writes need confirm). Auth: LOGICMONITOR_BASE_URL + LOGICMONITOR_TOKEN (Bearer API token)."),

    # --- Security / GRC (additional) ---
    dict(name="netskope",
         token_header="Netskope-Api-Token", scheme="", description="Netskope REST. ops "
         "get/post (writes need confirm). Auth: NETSKOPE_BASE_URL + NETSKOPE_TOKEN (Netskope-Api-Token)."),
    dict(name="cisco_umbrella", base_url_env="UMBRELLA_BASE_URL", token_env="UMBRELLA_TOKEN",
         description="Cisco Umbrella REST. ops get/post/put/delete (writes need confirm). "
         "Auth: UMBRELLA_BASE_URL + UMBRELLA_TOKEN (OAuth bearer)."),
    dict(name="vanta",
         description="Vanta REST (GRC/compliance). ops get/post (writes need confirm). "
         "Auth: VANTA_BASE_URL + VANTA_TOKEN (OAuth bearer)."),
    dict(name="drata",
         description="Drata REST (GRC/compliance). ops get/post (writes need confirm). "
         "Auth: DRATA_BASE_URL + DRATA_TOKEN (bearer)."),
    dict(name="logicgate",
         description="LogicGate Risk Cloud REST. ops get/post/put/delete (writes need "
         "confirm). Auth: LOGICGATE_BASE_URL + LOGICGATE_TOKEN (bearer)."),

    # --- Sales intelligence ---
    dict(name="apollo",
         token_header="X-Api-Key", scheme="", description="Apollo.io REST. ops get/post "
         "(writes need confirm). Auth: APOLLO_BASE_URL + APOLLO_TOKEN (X-Api-Key)."),
    dict(name="zoominfo",
         description="ZoomInfo REST. ops get/post (writes need confirm). Auth: "
         "ZOOMINFO_BASE_URL + ZOOMINFO_TOKEN (JWT bearer)."),
    dict(name="clearbit",
         description="Clearbit REST. ops get/post (writes need confirm). Auth: "
         "CLEARBIT_BASE_URL + CLEARBIT_TOKEN (bearer)."),

    # --- DevOps / CD / registries (additional) ---
    dict(name="argocd",
         description="Argo CD REST. ops get/post/put/delete (writes need confirm). Auth: "
         "ARGOCD_BASE_URL + ARGOCD_TOKEN (bearer)."),
    dict(name="harness",
         token_header="x-api-key", scheme="", description="Harness REST. ops get/post/put/"
         "delete (writes need confirm). Auth: HARNESS_BASE_URL + HARNESS_TOKEN (x-api-key)."),
    dict(name="octopus_deploy", base_url_env="OCTOPUS_BASE_URL", token_env="OCTOPUS_TOKEN",
         token_header="X-Octopus-ApiKey", scheme="", description="Octopus Deploy REST. ops "
         "get/post/put/delete (writes need confirm). Auth: OCTOPUS_BASE_URL + OCTOPUS_TOKEN (X-Octopus-ApiKey)."),
    dict(name="dockerhub",
         description="Docker Hub REST. ops get/post/put/delete (writes need confirm). "
         "Auth: DOCKERHUB_BASE_URL (https://hub.docker.com) + DOCKERHUB_TOKEN (JWT bearer)."),

    # --- Marketing / product analytics (additional) ---
    dict(name="iterable",
         token_header="Api-Key", scheme="", description="Iterable REST. ops get/post "
         "(writes need confirm). Auth: ITERABLE_BASE_URL + ITERABLE_TOKEN (Api-Key)."),
    dict(name="pendo",
         token_header="x-pendo-integration-key", scheme="", description="Pendo REST. ops "
         "get/post (writes need confirm). Auth: PENDO_BASE_URL + PENDO_TOKEN (x-pendo-integration-key)."),

    # --- Contact center / CX (additional) ---
    dict(name="dialpad",
         description="Dialpad REST. ops get/post/put/delete (writes need confirm). Auth: "
         "DIALPAD_BASE_URL + DIALPAD_TOKEN (bearer)."),
    dict(name="aircall",
         basic=True, description="Aircall REST. ops get/post/put/delete (writes need "
         "confirm). Auth: AIRCALL_BASE_URL + AIRCALL_TOKEN (api_id:api_token, basic)."),
    dict(name="front",
         description="Front REST (shared inbox). ops get/post/put/delete (writes need "
         "confirm). Auth: FRONT_BASE_URL + FRONT_TOKEN (bearer)."),
    dict(name="gladly",
         basic=True, description="Gladly REST. ops get/post/put (writes need confirm). "
         "Auth: GLADLY_BASE_URL + GLADLY_TOKEN (email:apitoken, basic)."),

    # --- Design / diagramming / events ---
    dict(name="figma",
         token_header="X-Figma-Token", scheme="", description="Figma REST. ops get/post "
         "(writes need confirm). Auth: FIGMA_BASE_URL (https://api.figma.com) + FIGMA_TOKEN (X-Figma-Token)."),
    dict(name="lucid",
         description="Lucid (Lucidchart) REST. ops get/post/put/delete (writes need "
         "confirm). Auth: LUCID_BASE_URL + LUCID_TOKEN (bearer)."),
    dict(name="eventbrite",
         description="Eventbrite REST. ops get/post/put/delete (writes need confirm). "
         "Auth: EVENTBRITE_BASE_URL + EVENTBRITE_TOKEN (bearer)."),
    dict(name="cvent",
         description="Cvent REST (events). ops get/post/put/delete (writes need confirm). "
         "Auth: CVENT_BASE_URL + CVENT_TOKEN (OAuth bearer)."),

    # --- Final checklist closers (CRM / payroll / incident mgmt) ---
    dict(name="sugarcrm",
         description="SugarCRM REST (v11+). ops get/post/put/delete (writes need confirm). "
         "Auth: SUGARCRM_BASE_URL + SUGARCRM_TOKEN (OAuth bearer)."),
    dict(name="paychex",
         description="Paychex Flex REST. ops get/post (writes need confirm). Auth: "
         "PAYCHEX_BASE_URL + PAYCHEX_TOKEN (OAuth bearer)."),
    dict(name="opsgenie",
         scheme="GenieKey", description="Opsgenie REST (incident mgmt). ops get/post/put/"
         "delete (writes need confirm). Auth: OPSGENIE_BASE_URL + OPSGENIE_TOKEN (GenieKey)."),

    # --- Finance long-pole: banking / treasury / payments ---
    dict(name="modern_treasury", basic=True,
         description="Modern Treasury REST (payments/ledgers/reconciliation). ops get/post/"
         "put/delete (writes need confirm). e.g. /api/payment_orders, /api/counterparties, "
         "/api/internal_accounts. Auth: MODERN_TREASURY_BASE_URL "
         "(https://app.moderntreasury.com) + MODERN_TREASURY_TOKEN (Basic org_id:api_key)."),
    dict(name="mercury",
         description="Mercury banking REST (read balances/transactions; payments are "
         "confirm-gated). e.g. /accounts, /account/{id}/transactions. Auth: MERCURY_BASE_URL "
         "(https://api.mercury.com/api/v1) + MERCURY_TOKEN (bearer)."),
    dict(name="wise",
         description="Wise (TransferWise) REST (multi-currency balances/transfers; writes "
         "need confirm). e.g. /v1/profiles, /v1/borderless-accounts. Auth: WISE_BASE_URL "
         "(https://api.wise.com) + WISE_TOKEN (bearer)."),

    # --- Finance long-pole: AP / spend / travel & expense ---
    dict(name="airbase",
         description="Airbase spend/AP REST. ops get/post/put/delete (writes need confirm). "
         "Auth: AIRBASE_BASE_URL (https://api.airbase.io) + AIRBASE_TOKEN (bearer)."),
    dict(name="navan",
         description="Navan (TripActions) travel & expense REST. ops get/post (writes need "
         "confirm). Auth: NAVAN_BASE_URL (https://api.navan.com) + NAVAN_TOKEN (OAuth bearer)."),
    dict(name="pleo",
         description="Pleo spend-management REST. ops get/post (writes need confirm). Auth: "
         "PLEO_BASE_URL (https://external.pleo.io) + PLEO_TOKEN (bearer)."),

    # --- Finance long-pole: tax ---
    dict(name="avalara",
         basic=True, description="Avalara AvaTax REST (sales/use tax). ops get/post (writes "
         "need confirm). e.g. /api/v2/transactions/create, /api/v2/companies. Auth: "
         "AVALARA_BASE_URL (https://rest.avatax.com) + AVALARA_TOKEN (Basic account#:licensekey)."),
    dict(name="vertex_tax",
         description="Vertex O Series tax REST (calculation/returns; distinct from the "
         "Vertex AI tool). ops get/post (writes need confirm). Auth: VERTEX_TAX_BASE_URL "
         "(your Vertex endpoint) + VERTEX_TAX_TOKEN (OAuth bearer)."),
    dict(name="cch_axcess",
         extra_headers_env={"Ocp-Apim-Subscription-Key": "CCH_AXCESS_SUBSCRIPTION_KEY"},
         description="Wolters Kluwer CCH Axcess Open Integration Platform REST "
         "(Tax / Document / Workstream). ops get/post/put/delete (writes need "
         "confirm). e.g. /api/TaxService/v1.0/..., /api/DocumentService/v1.0/.... "
         "Auth: CCH_AXCESS_BASE_URL (https://api.cchaxcess.com) + CCH_AXCESS_TOKEN "
         "(OAuth bearer) + CCH_AXCESS_SUBSCRIPTION_KEY (Ocp-Apim-Subscription-Key)."),
    dict(name="gosystem_tax",
         description="Thomson Reuters GoSystem Tax RS REST (returns, e-file status, "
         "locators). ops get/post (writes need confirm). Auth: GOSYSTEM_TAX_BASE_URL "
         "(your GoSystem Tax API endpoint) + GOSYSTEM_TAX_TOKEN (OAuth bearer)."),

    # --- Finance long-pole: close / EPM-FP&A / equity ---
    dict(name="floqast",
         description="FloQast close & reconciliation REST. ops get/post (writes need "
         "confirm). Auth: FLOQAST_BASE_URL (https://api.floqast.com) + FLOQAST_TOKEN (bearer)."),
    dict(name="pigment",
         description="Pigment EPM / planning REST. ops get/post (writes need confirm). Auth: "
         "PIGMENT_BASE_URL (your Pigment API base) + PIGMENT_TOKEN (bearer)."),
    dict(name="planful",
         description="Planful EPM REST. ops get/post (writes need confirm). Auth: "
         "PLANFUL_BASE_URL (your Planful tenant) + PLANFUL_TOKEN (bearer)."),
    dict(name="carta",
         description="Carta cap-table / equity REST. ops get/post (writes need confirm). "
         "Auth: CARTA_BASE_URL (https://api.carta.com) + CARTA_TOKEN (OAuth bearer)."),

    # --- Legal: contract lifecycle / practice management ---
    dict(name="ironclad",
         description="Ironclad CLM REST. paths /public/api/v1/... (workflows, records). "
         "ops get/post/put/delete (writes need confirm). Auth: IRONCLAD_BASE_URL "
         "(https://ironcladapp.com) + IRONCLAD_TOKEN (bearer)."),
    dict(name="contractbook", description="Contractbook CLM REST. ops get/post/put/delete (writes need confirm). "
         "Auth: CONTRACTBOOK_BASE_URL (https://api.contractbook.com) + CONTRACTBOOK_TOKEN (bearer)."),
    dict(name="clio",
         description="Clio legal practice-management REST (v4). ops get/post/put/delete "
         "(writes need confirm). Auth: CLIO_BASE_URL (https://app.clio.com) + CLIO_TOKEN "
         "(OAuth bearer)."),

    # --- HR / People ---
    dict(name="hibob", basic=True,
         description="HiBob (bob) HRIS REST. ops get/post/put (writes need confirm). e.g. "
         "/v1/people, /v1/people/search. Auth: HIBOB_BASE_URL (https://api.hibob.com) + "
         "HIBOB_TOKEN (Basic service-user-id:token)."),
    dict(name="lattice",
         description="Lattice performance/engagement REST. ops get/post (writes need "
         "confirm). Auth: LATTICE_BASE_URL (https://api.latticehq.com) + LATTICE_TOKEN (bearer)."),

    # --- Product / Engineering: feature management ---
    dict(name="launchdarkly", scheme="",
         description="LaunchDarkly feature-flag REST (v2). ops get/post/patch/delete (writes "
         "need confirm). e.g. /api/v2/flags/{proj}. Auth: LAUNCHDARKLY_BASE_URL "
         "(https://app.launchdarkly.com) + LAUNCHDARKLY_TOKEN (raw Authorization)."),
    dict(name="split",
         description="Split feature-flag / experimentation REST. ops get/post/patch (writes "
         "need confirm). Auth: SPLIT_BASE_URL (https://api.split.io) + SPLIT_TOKEN (bearer)."),

    # --- Operations / supply chain / logistics ---
    dict(name="samsara",
         description="Samsara fleet / IoT REST. ops get/post (writes need confirm). e.g. "
         "/fleet/vehicles, /fleet/vehicles/locations. Auth: SAMSARA_BASE_URL "
         "(https://api.samsara.com) + SAMSARA_TOKEN (bearer)."),
    dict(name="easypost",
         basic=True, description="EasyPost shipping REST. ops get/post (writes need confirm). "
         "e.g. /v2/shipments, /v2/trackers. Auth: EASYPOST_BASE_URL (https://api.easypost.com) "
         "+ EASYPOST_TOKEN (Basic; API key as username)."),
    dict(name="flexport",
         description="Flexport freight / logistics REST. ops get/post (writes need confirm). "
         "Auth: FLEXPORT_BASE_URL (https://api.flexport.com) + FLEXPORT_TOKEN (bearer)."),
    dict(name="shippo",
         scheme="ShippoToken", description="Shippo multi-carrier shipping REST. ops get/post "
         "(writes need confirm). Auth: SHIPPO_BASE_URL (https://api.goshippo.com) + "
         "SHIPPO_TOKEN (ShippoToken scheme)."),

    # --- Strategy / market intelligence; IT-GRC ---
    dict(name="crunchbase",
         token_header="X-cb-user-key", scheme="",
         description="Crunchbase company / funding data REST (v4). op get (read-only). e.g. "
         "/api/v4/entities/organizations/{id}, /api/v4/searches/organizations. Auth: "
         "CRUNCHBASE_BASE_URL (https://api.crunchbase.com) + CRUNCHBASE_TOKEN (X-cb-user-key)."),
    dict(name="secureframe", description="Secureframe compliance-automation REST. ops get/post (writes need "
         "confirm). Auth: SECUREFRAME_BASE_URL (https://api.secureframe.com) + "
         "SECUREFRAME_TOKEN (bearer)."),

    # --- Finance long-pole: subscription billing / revenue ---
    dict(name="zuora",
         description="Zuora billing / revenue REST. ops get/post/put (writes need confirm). "
         "e.g. /v1/subscriptions, /v1/accounts, /v1/invoices. Auth: ZUORA_BASE_URL "
         "(https://rest.zuora.com) + ZUORA_TOKEN (OAuth bearer)."),
    dict(name="chargebee",
         basic=True, description="Chargebee subscription-billing REST (v2). ops get/post "
         "(writes need confirm). e.g. /api/v2/subscriptions, /api/v2/invoices. Auth: "
         "CHARGEBEE_BASE_URL (https://{site}.chargebee.com) + CHARGEBEE_TOKEN (Basic; API "
         "key as username)."),
    dict(name="recurly",
         basic=True, description="Recurly subscription-billing REST (v3). ops get/post/put "
         "(writes need confirm). e.g. /accounts, /subscriptions, /invoices. Auth: "
         "RECURLY_BASE_URL (https://v3.recurly.com) + RECURLY_TOKEN (Basic; API key as username)."),
    dict(name="gocardless",
         description="GoCardless bank-debit REST. ops get/post (writes need confirm; set "
         "GoCardless-Version via the path/headers per their docs). e.g. /payments, /mandates, "
         "/customers. Auth: GOCARDLESS_BASE_URL (https://api.gocardless.com) + GOCARDLESS_TOKEN "
         "(bearer)."),
    dict(name="freshbooks",
         description="FreshBooks accounting REST. ops get/post/put (writes need confirm). "
         "e.g. /accounting/account/{id}/invoices/invoices. Auth: FRESHBOOKS_BASE_URL "
         "(https://api.freshbooks.com) + FRESHBOOKS_TOKEN (OAuth bearer)."),
]

# GraphQL services (single POST endpoint; mutations confirm-gated).
_GRAPHQL_SPECS: list[dict] = [
    dict(name="monday",
         scheme="", description="monday.com GraphQL. op query (queries run; mutations "
         "need confirm). Auth: MONDAY_BASE_URL (https://api.monday.com/v2) + "
         "MONDAY_TOKEN (raw Authorization)."),
    dict(name="wiz",
         description="Wiz CNAPP GraphQL. op query (queries run; mutations need "
         "confirm). Auth: WIZ_BASE_URL (your Wiz API endpoint) + WIZ_TOKEN (bearer)."),
]

for _spec in (*_SPECS, *_GRAPHQL_SPECS):
    _fill_env(_spec)

# Read-only (GET-only) variants for finance vendors -- the bridge that
# lets a read-only pack (max_risk <= medium) pull narrowly-scoped data without
# handing it a write-capable seat. Same env/creds as the write connector; writes
# are structurally unreachable, and reads are constrained by explicit endpoint
# allowlists (allowed_read_paths). Risk is tracked explicitly in
# READ_CONNECTOR_RISKS so read-only seats for sensitive systems do not bypass
# low-risk ceilings.
_READ_SPECS: list[dict] = [
    dict(name="modern_treasury_read", base_url_env="MODERN_TREASURY_BASE_URL",
         token_env="MODERN_TREASURY_TOKEN", basic=True,
         allowed_read_paths=(
             "/api/internal_accounts",
             "/api/transactions",
             "/api/ledger_account_balances",
         ),
         description="Modern Treasury REST, READ-ONLY (GET) for cash-positioning paths "
         "only: /api/internal_accounts, /api/transactions, "
         "/api/ledger_account_balances. Auth: MODERN_TREASURY_BASE_URL "
         "(https://app.moderntreasury.com) + MODERN_TREASURY_TOKEN "
         "(Basic org_id:api_key)."),
]
_READ_CONNECTOR_RISKS: dict[str, str] = {"modern_treasury_read": "low"}


def _read_specs_for(vendors: list[str]) -> list[dict]:
    """Derive GET-only read specs from existing write connectors -- same base URL,
    token env, and auth mode (so creds + auth are correct by construction); only
    the name (``<vendor>_read``) and a read-only description differ. Unknown
    vendors are skipped rather than wedging import."""
    by_name = {s["name"]: s for s in _SPECS}
    out: list[dict] = []
    for v in vendors:
        src = by_name.get(v)
        if src is None:
            continue
        spec = {k: val for k, val in src.items() if k not in ("name", "description")}
        spec["name"] = f"{v}_read"
        spec["description"] = (
            f"{v} REST, READ-ONLY (GET) -- read records/balances; the agent supplies "
            f"the path. Reuses {src['base_url_env']} + {src['token_env']} (same creds "
            f"and auth as the '{v}' connector)."
        )
        out.append(spec)
    return out


# Finance vendors whose read-only/draft packs need to pull data: each gets a
# GET-only, LOW-risk variant (wired into the matching pack's allow_tools), so the
# whole CFO office can read its systems while money tools stay denied.
_FINANCE_READ_VENDORS: list[str] = [
    "billdotcom", "coupa", "ariba", "chargebee", "netsuite", "carta",
    "concur", "ramp", "adp", "gusto", "workiva", "avalara",
]
_FINANCE_READ_SPECS = _read_specs_for(_FINANCE_READ_VENDORS)
_READ_SPECS += _FINANCE_READ_SPECS
_READ_CONNECTOR_RISKS.update({s["name"]: "low" for s in _FINANCE_READ_SPECS})

# Tax-engine read seats: the tax_ suite's read-only packs may check narrow
# operational status/locator endpoints in the firm's professional tax engine
# (CCH Axcess / GoSystem). They must not inherit unrestricted GET access from
# the write connector because tax-engine APIs also expose taxpayer documents and
# full returns. Submitting or modifying a return stays on the write connector
# (high risk, confirm-gated, unreachable from the low-risk packs by construction).
_TAX_READ_ALLOWLISTS: dict[str, tuple[str, ...]] = {
    "cch_axcess_read": (
        "/api/TaxService/v1.0/eFileStatus",
        "/api/TaxService/v1.0/locators",
    ),
    "gosystem_tax_read": (
        "/e-file-status",
        "/efile-status",
        "/locators",
    ),
}
_TAX_READ_VENDORS: list[str] = ["cch_axcess", "gosystem_tax"]
_TAX_READ_SPECS = _read_specs_for(_TAX_READ_VENDORS)
for _spec in _TAX_READ_SPECS:
    _allowed = _TAX_READ_ALLOWLISTS.get(_spec["name"], ())
    _spec["allowed_read_paths"] = _allowed
    _spec["description"] += (
        " Low-risk seat is restricted to these status/locator prefixes: "
        + ", ".join(_allowed)
        + ". Use the high-risk write connector for broader tax-engine access."
    )
_READ_SPECS += _TAX_READ_SPECS
_READ_CONNECTOR_RISKS.update({s["name"]: "low" for s in _TAX_READ_SPECS})

# Read seats for the OTHER suites' systems, derived the same way (GET-only,
# reuse the write connector's creds). These systems often contain high-confidentiality
# identity, HR, security, CI/CD, legal, and customer data, so the read seats are
# fail-closed as high risk unless an operator deliberately overrides them.
# Bespoke-module vendors (Salesforce, HubSpot,
# Jira, GitHub, Datadog, ...) aren't in _SPECS, so they're skipped here -- this
# covers the spec'd long-tail systems each suite reads.
_SUITE_READ_VENDORS: list[str] = [
    # GTM / Sales -- sales engagement, marketing, enrichment, CS, analytics
    "salesloft", "outreach", "gong", "clari", "apollo", "zoominfo", "clearbit",
    "marketo", "klaviyo", "braze", "mailchimp", "sfmc", "iterable", "segment",
    "amplitude", "gainsight", "pendo", "pipedrive", "sugarcrm", "eventbrite",
    "cvent", "sprinklr",
    # Legal -- CLM, e-signature, practice management
    "ironclad", "contractbook", "clio", "docusign",
    # Operations / supply chain -- logistics, fleet, shipping (coupa/ariba reuse finance)
    "flexport", "samsara", "easypost", "shippo",
    # HR / People -- HRIS, recruiting, performance (gusto/adp reuse finance)
    "bamboohr", "greenhouse", "lever", "rippling", "smartrecruiters", "workable",
    "deel", "paylocity", "paychex", "lattice", "cornerstone", "icims", "hibob",
    "ukg", "successfactors",
    # IT / GRC / Security -- identity, EDR/SIEM, vuln, GRC automation
    "okta", "auth0", "onelogin", "pingone", "duo", "cyberark", "sailpoint",
    "crowdstrike", "splunk", "zscaler", "tenable", "qualys", "rapid7",
    "sentinelone", "proofpoint", "snyk", "fortinet", "vanta", "drata", "logicgate",
    "netskope", "cisco_umbrella", "defender", "qradar", "palo_alto", "jamf",
    "secureframe", "sumologic", "logicmonitor", "appdynamics",
    # Product / Engineering -- CI/CD, code quality, feature flags, observability
    "jenkins", "circleci", "jfrog", "sonarqube", "azure_devops", "launchdarkly",
    "split", "argocd", "harness", "octopus_deploy", "dockerhub", "newrelic",
    "dynatrace", "grafana", "opsgenie",
    # Strategy / CorpDev -- market intel, BI / analytics, EPM
    "crunchbase", "tableau", "powerbi", "looker", "qlik", "thoughtspot",
    "sisense", "domo", "mode", "metabase", "anaplan", "microstrategy", "cognos",
]
_SUITE_READ_SPECS = _read_specs_for(_SUITE_READ_VENDORS)
_READ_SPECS += _SUITE_READ_SPECS
_READ_CONNECTOR_RISKS.update({s["name"]: "high" for s in _SUITE_READ_SPECS})

# --- Primary-source / public-reference data connectors ----------------------
# Authoritative GOVERNMENT and public data APIs that ground the analyst-style
# packs (finance, banking, insurance, legal, GRC, gov-contracting, healthcare,
# utilities, ESG, strategy) in primary sources instead of model memory. All are
# GET-only and LOW risk: they read public reference data, mutate nothing, and
# carry no customer/tenant secrets. Most are keyless (a fixed public host, no
# credential); some take a free API key delivered either as a header or a query
# param (never from the prompt -- it comes from the connector's env var).
#
# ``_pub`` fills the standard env names so a spec is one line. A keyless spec
# ships a ``default_base_url`` so it works with zero config; a keyed spec needs
# only its ``*_API_KEY`` env var (the base URL still defaults).
def _pub(name: str, default_base_url: str, description: str, **kw) -> dict:
    return dict(
        name=name,
        base_url_env=f"{name.upper()}_BASE_URL",
        token_env=f"{name.upper()}_API_KEY",
        default_base_url=default_base_url,
        description=description,
        **kw,
    )


_PUBLIC_DATA_SPECS: list[dict] = [
    # --- Financial markets & macroeconomic data ---
    _pub("fred", "https://api.stlouisfed.org", query_auth="api_key",
         description="FRED (St. Louis Fed) economic data, READ-ONLY. e.g. "
         "/fred/series/observations?series_id=GDP&file_type=json. Key as query "
         "param. Auth: FRED_API_KEY (free)."),
    _pub("sec_edgar", "https://data.sec.gov", keyless=True,
         description="SEC EDGAR company filings & XBRL facts, READ-ONLY, keyless. "
         "e.g. /submissions/CIK0000320193.json, "
         "/api/xbrl/companyconcept/CIK0000320193/us-gaap/Revenues.json. "
         "Send a descriptive User-Agent via SEC_EDGAR_* if required."),
    _pub("treasury_fiscaldata", "https://api.fiscaldata.treasury.gov", keyless=True,
         description="U.S. Treasury Fiscal Data, READ-ONLY, keyless. e.g. "
         "/services/api/fiscal_service/v2/accounting/od/avg_interest_rates."),
    _pub("world_bank", "https://api.worldbank.org", keyless=True,
         description="World Bank Open Data, READ-ONLY, keyless. e.g. "
         "/v2/country/US/indicator/NY.GDP.MKTP.CD?format=json."),
    _pub("imf", "https://www.imf.org/external/datamapper/api", keyless=True,
         description="IMF DataMapper, READ-ONLY, keyless. e.g. /v1/NGDP_RPCH/USA."),
    _pub("fdic", "https://banks.data.fdic.gov", keyless=True,
         description="FDIC BankFind (institutions & financials), READ-ONLY, keyless. "
         "e.g. /api/financials?filters=STNAME:Texas&fields=REPDTE,ASSET."),
    _pub("bea", "https://apps.bea.gov", query_auth="UserID",
         description="Bureau of Economic Analysis, READ-ONLY. e.g. "
         "/api/data?method=GetData&datasetname=NIPA&... UserID as query param. "
         "Auth: BEA_API_KEY (free)."),
    _pub("census", "https://api.census.gov", query_auth="key",
         description="U.S. Census Bureau data, READ-ONLY. e.g. "
         "/data/2022/acs/acs5?get=NAME,B01001_001E&for=state:*. Key as query "
         "param. Auth: CENSUS_API_KEY (free)."),
    _pub("bls", "https://api.bls.gov", keyless=True,
         description="Bureau of Labor Statistics v1, READ-ONLY, keyless. e.g. "
         "/publicAPI/v1/timeseries/data/CUUR0000SA0 (CPI series)."),
    _pub("eia", "https://api.eia.gov", query_auth="api_key",
         description="EIA energy data, READ-ONLY. e.g. "
         "/v2/electricity/rto/region-data/data?... Key as query param. "
         "Auth: EIA_API_KEY (free)."),
    _pub("alphavantage", "https://www.alphavantage.co", query_auth="apikey",
         description="Alpha Vantage market data, READ-ONLY. e.g. "
         "/query?function=TIME_SERIES_DAILY&symbol=IBM. Key as query param. "
         "Auth: ALPHAVANTAGE_API_KEY (free)."),
    _pub("finnhub", "https://finnhub.io", token_header="X-Finnhub-Token", scheme="",
         description="Finnhub market data, READ-ONLY. e.g. /api/v1/quote?symbol=AAPL, "
         "/api/v1/stock/profile2?symbol=AAPL. Auth: FINNHUB_API_KEY (X-Finnhub-Token)."),
    _pub("polygon", "https://api.polygon.io",
         description="Polygon.io market data, READ-ONLY (Bearer). e.g. "
         "/v3/reference/tickers, /v2/aggs/ticker/AAPL/range/1/day/2024-01-01/2024-02-01. "
         "Auth: POLYGON_API_KEY (Bearer)."),
    _pub("openfigi", "https://api.openfigi.com", token_header="X-OPENFIGI-APIKEY", scheme="",
         description="OpenFIGI security-identifier mapping, READ-ONLY. POST-style "
         "mapping is read-shaped; e.g. GET /v3/search. Auth: OPENFIGI_API_KEY."),
    # --- Regulatory / legal / government ---
    _pub("federal_register", "https://www.federalregister.gov", keyless=True,
         description="U.S. Federal Register, READ-ONLY, keyless. e.g. "
         "/api/v1/documents.json?conditions[term]=privacy&per_page=20."),
    _pub("ecfr", "https://www.ecfr.gov", keyless=True,
         description="Electronic Code of Federal Regulations, READ-ONLY, keyless. "
         "e.g. /api/versioner/v1/titles.json, /api/search/v1/results?query=."),
    _pub("regulations_gov", "https://api.regulations.gov",
         token_header="X-Api-Key", scheme="",
         description="Regulations.gov dockets & comments, READ-ONLY. e.g. "
         "/v4/documents?filter[searchTerm]=. Auth: REGULATIONS_GOV_API_KEY "
         "(X-Api-Key; free via api.data.gov)."),
    _pub("courtlistener", "https://www.courtlistener.com", scheme="Token",
         description="CourtListener case law & dockets, READ-ONLY. e.g. "
         "/api/rest/v4/search/?q=, /api/rest/v4/opinions/. Auth: "
         "COURTLISTENER_API_KEY (Authorization: Token <key>)."),
    _pub("govinfo", "https://api.govinfo.gov", query_auth="api_key",
         description="GovInfo (bills, CFR, public laws), READ-ONLY. e.g. "
         "/collections, /packages/{id}/summary. Key as query param. "
         "Auth: GOVINFO_API_KEY (free via api.data.gov)."),
    _pub("usaspending", "https://api.usaspending.gov", keyless=True,
         description="USAspending federal awards/spending, READ-ONLY, keyless. e.g. "
         "/api/v2/search/spending_by_award/ (POST search is read-shaped)."),
    _pub("sam_gov", "https://api.sam.gov", query_auth="api_key",
         description="SAM.gov entity registration & exclusions, READ-ONLY. e.g. "
         "/entity-information/v3/entities?ueiSAM=. Key as query param. "
         "Auth: SAM_GOV_API_KEY (free via api.data.gov)."),
    _pub("openstates", "https://v3.openstates.org", token_header="X-API-KEY", scheme="",
         description="Open States (state legislatures), READ-ONLY. e.g. /bills?jurisdiction=, "
         "/people. Auth: OPENSTATES_API_KEY (X-API-KEY)."),
    _pub("patentsview", "https://search.patentsview.org", keyless=True,
         description="PatentsView (USPTO patent data), READ-ONLY, keyless. e.g. "
         "/api/v1/patent/?q={...}&f={...}."),
    # --- Company / legal-entity registries ---
    _pub("gleif", "https://api.gleif.org", keyless=True,
         description="GLEIF Legal Entity Identifier (LEI) registry, READ-ONLY, keyless. "
         "e.g. /api/v1/lei-records?filter[entity.legalName]=Apple."),
    _pub("opencorporates", "https://api.opencorporates.com", query_auth="api_token",
         description="OpenCorporates company registry, READ-ONLY. e.g. "
         "/v0.4/companies/search?q=. Token as query param. Auth: OPENCORPORATES_API_KEY."),
    _pub("companies_house", "https://api.company-information.service.gov.uk", basic=True,
         description="UK Companies House, READ-ONLY (basic: API key as username). e.g. "
         "/search/companies?q=, /company/{number}. Auth: COMPANIES_HOUSE_API_KEY."),
    # --- Health / life sciences ---
    _pub("openfda", "https://api.fda.gov", keyless=True,
         description="openFDA (drug/device/food adverse events, recalls, labels), "
         "READ-ONLY, keyless. e.g. /drug/event.json?search=&limit=5, "
         "/device/recall.json?search=."),
    _pub("nppes", "https://npiregistry.cms.hhs.gov", keyless=True,
         description="NPPES NPI Registry (US healthcare providers), READ-ONLY, keyless. "
         "e.g. /api/?version=2.1&number=&first_name=&state=."),
    _pub("clinicaltrials", "https://clinicaltrials.gov", keyless=True,
         description="ClinicalTrials.gov v2, READ-ONLY, keyless. e.g. "
         "/api/v2/studies?query.term=diabetes&pageSize=10."),
    _pub("rxnorm", "https://rxnav.nlm.nih.gov", keyless=True,
         description="RxNorm/RxNav drug normalization, READ-ONLY, keyless. e.g. "
         "/REST/rxcui.json?name=ibuprofen, /REST/interaction/interaction.json?rxcui=."),
    _pub("pubmed", "https://eutils.ncbi.nlm.nih.gov", keyless=True,
         description="PubMed/NCBI E-utilities, READ-ONLY, keyless. e.g. "
         "/entrez/eutils/esearch.fcgi?db=pubmed&term=&retmode=json."),
    # --- Geo / weather / energy / environment (ESG) ---
    _pub("nws_weather", "https://api.weather.gov", keyless=True,
         description="US National Weather Service, READ-ONLY, keyless. e.g. "
         "/points/{lat},{lon}, /gridpoints/{office}/{x},{y}/forecast, /alerts/active."),
    _pub("noaa_climate", "https://www.ncdc.noaa.gov", token_header="token", scheme="",
         description="NOAA Climate Data Online, READ-ONLY. e.g. "
         "/cdo-web/api/v2/data?datasetid=GHCND&... Auth: NOAA_CLIMATE_API_KEY (token header)."),
    _pub("openweather", "https://api.openweathermap.org", query_auth="appid",
         description="OpenWeather, READ-ONLY. e.g. /data/2.5/weather?q=London. "
         "Key as query param (appid). Auth: OPENWEATHER_API_KEY."),
    _pub("epa_envirofacts", "https://data.epa.gov", keyless=True,
         description="EPA Envirofacts environmental data, READ-ONLY, keyless. e.g. "
         "/efservice/{table}/{column}/{value}/JSON."),
    _pub("climatiq", "https://api.climatiq.io",
         description="Climatiq carbon-emission factors/estimates, READ-ONLY (Bearer). "
         "e.g. /data/v1/search?query=electricity. Auth: CLIMATIQ_API_KEY (Bearer)."),
    _pub("carbon_interface", "https://www.carboninterface.com",
         description="Carbon Interface emission estimates, READ-ONLY (Bearer). e.g. "
         "GET /api/v1/estimates/{id}. Auth: CARBON_INTERFACE_API_KEY (Bearer)."),
]
_READ_SPECS += _PUBLIC_DATA_SPECS
_READ_CONNECTOR_RISKS.update({s["name"]: "low" for s in _PUBLIC_DATA_SPECS})
# Names of just the primary-source data connectors, for docs/tests.
PUBLIC_DATA_CONNECTOR_NAMES: list[str] = [s["name"] for s in _PUBLIC_DATA_SPECS]

# The public host each data connector reaches (from its default base URL). Used
# when an operator wants to widen a host-restricted pack's egress to admit a
# granted data connector -- the grant itself (see domain.py) never loosens a
# pack's allow_hosts automatically.
from urllib.parse import urlsplit as _urlsplit  # noqa: E402

PUBLIC_DATA_CONNECTOR_HOSTS: dict[str, str] = {
    s["name"]: _urlsplit(s["default_base_url"]).netloc for s in _PUBLIC_DATA_SPECS
}


# --- Suite -> primary-source data connectors --------------------------------
# Which public-data connectors each business suite's packs get in their
# capability envelope, so an analyst pack reaches for FRED/SEC EDGAR/openFDA/etc.
# by default instead of guessing. All are GET-only and LOW risk, so they sit
# under a read-only pack's ceiling. Layered centrally in domain.domain_capability
# (additive to allow_tools; deferred, so no context cost until find_tools).
#
# Reusable bundles, composed per suite below. Keep a suite's set curated -- the
# few sources its work actually grounds in, not the whole catalogue.
_MARKETS_CORE = frozenset({
    "fred", "sec_edgar", "treasury_fiscaldata", "world_bank", "bls",
    "alphavantage", "finnhub", "polygon", "openfigi",
})
_ENTITY = frozenset({"gleif", "opencorporates", "companies_house"})
_REG_FED = frozenset({"federal_register", "ecfr", "regulations_gov", "govinfo"})
_GOV_SPEND = frozenset({"usaspending", "sam_gov"})
_HEALTH = frozenset({"openfda", "nppes", "clinicaltrials", "rxnorm", "pubmed"})
_CLIMATE = frozenset({
    "nws_weather", "noaa_climate", "openweather", "epa_envirofacts",
    "climatiq", "carbon_interface",
})
_STATS = frozenset({"census", "bls", "fred", "world_bank"})

SUITE_DATA_CONNECTORS: dict[str, frozenset[str]] = {
    # --- Finance / capital / deals / banking / insurance / tax ---
    "finance": _MARKETS_CORE | _ENTITY | frozenset({"bea"}),
    "capital_markets": _MARKETS_CORE | frozenset({"imf", "bea", "gleif", "openfigi"}),
    "private_equity_vc": _MARKETS_CORE | _ENTITY | frozenset({"sam_gov", "usaspending"}),
    "banking": frozenset({
        "fdic", "fred", "treasury_fiscaldata", "sec_edgar", "bls", "census",
    }) | _ENTITY,
    "insurance": frozenset({
        "nws_weather", "noaa_climate", "fred", "treasury_fiscaldata", "sec_edgar",
        "bls", "census", "fdic", "epa_envirofacts",
    }),
    "tax": _REG_FED | frozenset({"courtlistener", "sec_edgar", "bls", "census", "fred"}),
    # --- Legal / GRC / risk / trust&safety / IP ---
    "legal": frozenset({"courtlistener", "patentsview"}) | _REG_FED | _ENTITY
             | frozenset({"sec_edgar", "sam_gov"}),
    "it_grc": _REG_FED | frozenset({"sec_edgar"}),
    "security_ops": frozenset({"federal_register", "regulations_gov"}),
    "enterprise_risk": frozenset({
        "fred", "world_bank", "imf", "sec_edgar", "nws_weather", "noaa_climate",
    }) | _REG_FED | _ENTITY,
    "trust_safety": frozenset({"federal_register", "regulations_gov", "courtlistener"}),
    # --- Government / public sector / aero-defense / education ---
    "government_contracting": _GOV_SPEND | _REG_FED | frozenset({"sec_edgar"}),
    "public_sector": _GOV_SPEND | _REG_FED
                     | frozenset({"openstates", "census", "bls"}),
    "aerospace_defense": _GOV_SPEND | frozenset({
        "sec_edgar", "federal_register", "patentsview", "world_bank", "bls",
    }),
    "education_nonprofit": frozenset({
        "census", "bls", "fred", "federal_register", "world_bank",
    }) | _GOV_SPEND,
    # --- Health / life sciences / devices ---
    "healthcare": _HEALTH | frozenset({"federal_register", "regulations_gov"}),
    "medical_devices": frozenset({
        "openfda", "clinicaltrials", "pubmed", "patentsview",
        "federal_register", "regulations_gov",
    }),
    "pharma_lifesciences": frozenset({
        "openfda", "clinicaltrials", "pubmed", "rxnorm", "patentsview",
        "federal_register", "regulations_gov", "sec_edgar",
    }),
    # --- Energy / utilities / environment / ESG / ag ---
    "utilities": frozenset({
        "eia", "nws_weather", "noaa_climate", "epa_envirofacts",
        "federal_register", "fred",
    }),
    "water_utilities": frozenset({
        "epa_envirofacts", "nws_weather", "noaa_climate", "eia", "federal_register",
    }),
    "oil_gas": frozenset({
        "eia", "epa_envirofacts", "nws_weather", "noaa_climate",
        "federal_register", "sec_edgar", "world_bank",
    }),
    "renewables_cleantech": frozenset({
        "eia", "climatiq", "carbon_interface", "epa_envirofacts",
        "nws_weather", "noaa_climate", "fred",
    }),
    "esg_sustainability": _CLIMATE | frozenset({
        "eia", "sec_edgar", "federal_register", "world_bank",
    }),
    "agriculture": frozenset({
        "nws_weather", "noaa_climate", "epa_envirofacts", "eia",
        "world_bank", "census", "fred", "climatiq",
    }),
    "facilities_ehs": frozenset({
        "epa_envirofacts", "nws_weather", "noaa_climate", "eia",
        "federal_register", "regulations_gov",
    }),
    # --- Industrials / materials / mobility ---
    "manufacturing_vertical": frozenset({
        "bls", "fred", "census", "eia", "epa_envirofacts", "world_bank", "patentsview",
    }),
    "chemicals": frozenset({
        "epa_envirofacts", "federal_register", "regulations_gov", "eia",
        "patentsview", "nws_weather",
    }),
    "mining_metals": frozenset({
        "world_bank", "fred", "eia", "epa_envirofacts", "nws_weather", "sec_edgar",
    }),
    "automotive": frozenset({
        "bls", "fred", "census", "epa_envirofacts", "patentsview", "world_bank",
    }),
    "semiconductors": frozenset({
        "sec_edgar", "world_bank", "census", "bls", "patentsview", "fred", "finnhub",
    }),
    "construction": frozenset({
        "bls", "fred", "census", "nws_weather", "epa_envirofacts", "eia", "world_bank",
    }),
    # --- Logistics / maritime / travel ---
    "logistics": frozenset({
        "nws_weather", "noaa_climate", "eia", "census", "world_bank",
        "federal_register", "usaspending",
    }),
    "maritime": frozenset({
        "nws_weather", "noaa_climate", "world_bank", "eia", "federal_register",
    }),
    "travel_aviation": frozenset({
        "nws_weather", "noaa_climate", "bls", "fred", "world_bank",
        "eia", "federal_register",
    }),
    # --- Consumer / retail / media ---
    "retail": frozenset({
        "census", "bls", "fred", "world_bank", "openfda", "epa_envirofacts",
    }),
    "food_beverage_cpg": frozenset({
        "openfda", "epa_envirofacts", "census", "bls", "fred",
        "nws_weather", "federal_register", "regulations_gov",
    }),
    "hospitality": frozenset({"bls", "fred", "census", "nws_weather", "world_bank"}),
    "telecom_media": frozenset({
        "federal_register", "regulations_gov", "sec_edgar",
        "census", "bls", "fred", "patentsview",
    }),
    "crypto_digital_assets": frozenset({
        "sec_edgar", "federal_register", "regulations_gov", "courtlistener",
        "fred", "finnhub", "world_bank",
    }),
    "real_estate": frozenset({
        "fred", "census", "fdic", "treasury_fiscaldata", "nws_weather",
        "epa_envirofacts", "world_bank", "bls",
    }),
    # --- Cross-functional horizontals ---
    "strategy": _MARKETS_CORE | _ENTITY | frozenset({
        "imf", "census", "patentsview", "federal_register",
    }),
    "operations": frozenset({"bls", "fred", "census", "eia", "nws_weather", "world_bank"}),
    "procurement": _GOV_SPEND | _ENTITY | frozenset({"sec_edgar", "fred", "bls"}),
    "professional_services": frozenset({
        "sec_edgar", "courtlistener", "federal_register", "fred", "bls",
    }) | _ENTITY,
    "hr": frozenset({"bls", "census", "fred", "federal_register", "regulations_gov"}),
    "sales_gtm": frozenset({"sec_edgar", "fred", "bls"}) | _ENTITY,
    "marketing": frozenset({"census", "bls", "fred", "world_bank"}),
    "data_analytics": frozenset({"census", "bls", "fred", "world_bank", "eia", "sec_edgar"}),
    "executive_office": frozenset({"sec_edgar", "fred", "world_bank", "bls", "federal_register"}),
    "knowledge_management": frozenset({"pubmed", "patentsview", "federal_register", "sec_edgar"}),
    "product_engineering": frozenset({"patentsview", "federal_register", "sec_edgar"}),
}


def data_connectors_for_suite(suite: str | None) -> frozenset[str]:
    """The primary-source data connectors a suite's packs are granted (read-only,
    low-risk). Empty for an unmapped/None suite."""
    if not suite:
        return frozenset()
    return SUITE_DATA_CONNECTORS.get(suite, frozenset())

READ_CONNECTOR_NAMES: list[str] = [s["name"] for s in _READ_SPECS]
READ_CONNECTOR_RISKS: dict[str, str] = {
    name: _READ_CONNECTOR_RISKS.get(name, "high") for name in READ_CONNECTOR_NAMES
}

ENTERPRISE_CONNECTOR_NAMES: list[str] = (
    [s["name"] for s in _SPECS] + [s["name"] for s in _GRAPHQL_SPECS]
)


def enterprise_connectors() -> list[Tool]:
    """Instantiate every spec'd connector (registered in base_registry)."""
    return ([make_rest_tool(**spec) for spec in _SPECS]
            + [make_graphql_tool(**spec) for spec in _GRAPHQL_SPECS]
            + [make_rest_tool(read_only=True, **spec) for spec in _READ_SPECS])


# Bespoke (hand-written) strategic connectors live in their own modules, not in
# _SPECS, and some use a non-uniform env shape (account/project/location rather
# than base-URL + token). List their env vars here so the installer wizard can
# collect them too. Each env entry is (ENV_NAME, is_secret).
_BESPOKE_CATALOG: list[dict] = [
    {"name": "servicenow", "label": "ServiceNow",
     "env": [("SERVICENOW_INSTANCE_URL", False), ("SERVICENOW_TOKEN", True)]},
    {"name": "snowflake", "label": "Snowflake",
     "env": [("SNOWFLAKE_ACCOUNT", False), ("SNOWFLAKE_TOKEN", True)]},
    {"name": "databricks", "label": "Databricks",
     "env": [("DATABRICKS_HOST", False), ("DATABRICKS_TOKEN", True),
             ("DATABRICKS_WAREHOUSE_ID", False)]},
    {"name": "onetrust", "label": "OneTrust",
     "env": [("ONETRUST_HOSTNAME", False), ("ONETRUST_TOKEN", True)]},
    {"name": "vertex", "label": "Google Vertex AI",
     "env": [("VERTEX_PROJECT", False), ("VERTEX_LOCATION", False),
             ("VERTEX_ACCESS_TOKEN", True)]},
    {"name": "oracle", "label": "Oracle (ORDS)",
     "env": [("ORACLE_ORDS_URL", False), ("ORACLE_ORDS_TOKEN", True)]},
    {"name": "sap", "label": "SAP (OData)",
     "env": [("SAP_BASE_URL", False), ("SAP_TOKEN", True)]},
    {"name": "workday", "label": "Workday",
     "env": [("WORKDAY_BASE_URL", False), ("WORKDAY_TOKEN", True)]},
    {"name": "bigquery", "label": "Google BigQuery",
     "env": [("BIGQUERY_PROJECT", False), ("BIGQUERY_ACCESS_TOKEN", True)]},
    {"name": "dynamics", "label": "Microsoft Dynamics 365",
     "env": [("DYNAMICS_RESOURCE_URL", False), ("DYNAMICS_TOKEN", True),
             ("DYNAMICS_API_VERSION", False)]},
    {"name": "database", "label": "Relational database (SQLAlchemy URL)",
     "env": [("DATABASE_URL", True)]},
    # Other always-registered bespoke connectors (headline SaaS). (AWS s3/lambda/
    # dynamodb/ses/sns and airtable/asana/clickup/vercel/gdrive are gated behind
    # MAVERICK_ENABLE_CRED_TOOLS, so they're documented there, not offered here.)
    {"name": "salesforce", "label": "Salesforce",
     "env": [("SALESFORCE_INSTANCE_URL", False), ("SALESFORCE_ACCESS_TOKEN", True)]},
    {"name": "hubspot", "label": "HubSpot", "env": [("HUBSPOT_TOKEN", True)]},
    {"name": "stripe", "label": "Stripe", "env": [("STRIPE_SECRET_KEY", True)]},
    {"name": "shopify", "label": "Shopify",
     "env": [("SHOPIFY_STORE", False), ("SHOPIFY_ACCESS_TOKEN", True)]},
    {"name": "twilio", "label": "Twilio",
     "env": [("TWILIO_ACCOUNT_SID", False), ("TWILIO_AUTH_TOKEN", True),
             ("TWILIO_FROM_NUMBER", False)]},
    {"name": "sentry", "label": "Sentry",
     "env": [("SENTRY_HOST", False), ("SENTRY_AUTH_TOKEN", True)]},
    {"name": "datadog", "label": "Datadog",
     "env": [("DATADOG_API_KEY", True), ("DATADOG_APP_KEY", True)]},
    {"name": "pagerduty", "label": "PagerDuty",
     "env": [("PAGERDUTY_API_TOKEN", True), ("PAGERDUTY_EVENTS_KEY", True)]},
    {"name": "bitbucket", "label": "Bitbucket",
     "env": [("BITBUCKET_ACCESS_TOKEN", True)]},
    {"name": "cloudflare", "label": "Cloudflare",
     "env": [("CLOUDFLARE_API_TOKEN", True), ("CLOUDFLARE_ZONE_ID", False)]},
    {"name": "confluence", "label": "Confluence",
     "env": [("CONFLUENCE_URL", False), ("CONFLUENCE_USER", False),
             ("CONFLUENCE_API_TOKEN", True)]},
    {"name": "elasticsearch", "label": "Elasticsearch",
     "env": [("ES_URL", False), ("ES_API_KEY", True)]},
    {"name": "plaid", "label": "Plaid",
     "env": [("PLAID_CLIENT_ID", False), ("PLAID_SECRET", True)]},
    {"name": "calendly", "label": "Calendly", "env": [("CALENDLY_TOKEN", True)]},
    {"name": "trello", "label": "Trello",
     "env": [("TRELLO_KEY", True), ("TRELLO_TOKEN", True)]},
    {"name": "replicate", "label": "Replicate",
     "env": [("REPLICATE_API_TOKEN", True)]},
    {"name": "mixpanel", "label": "Mixpanel",
     "env": [("MIXPANEL_PROJECT_ID", False), ("MIXPANEL_PROJECT_TOKEN", True),
             ("MIXPANEL_SERVICE_SECRET", True)]},
    {"name": "posthog", "label": "PostHog",
     "env": [("POSTHOG_HOST", False), ("POSTHOG_PROJECT_ID", False),
             ("POSTHOG_API_KEY", True), ("POSTHOG_PERSONAL_API_KEY", True)]},
    {"name": "plausible", "label": "Plausible",
     "env": [("PLAUSIBLE_HOST", False), ("PLAUSIBLE_SITE_ID", False),
             ("PLAUSIBLE_API_KEY", True)]},
    {"name": "ga4", "label": "Google Analytics 4",
     "env": [("GA4_PROPERTY_ID", False), ("GA4_MEASUREMENT_ID", False),
             ("GA4_ACCESS_TOKEN", True), ("GA4_API_SECRET", True)]},
    {"name": "zoom", "label": "Zoom",
     "env": [("ZOOM_USER_ID", False), ("ZOOM_OAUTH_TOKEN", True)]},
    {"name": "teams", "label": "Microsoft Teams",
     "env": [("TEAMS_WEBHOOK_URL", True)]},
]


def _label_from_desc(desc: str) -> str:
    head = desc.split(". ")[0].strip().rstrip(".")
    for suffix in (" GraphQL", " OData REST", " REST"):
        if head.endswith(suffix):
            return head[: -len(suffix)].strip()
    return head


def connector_catalog() -> list[dict]:
    """The installer's source of truth for every connector and the env vars it
    needs. Each entry is ``{"name", "label", "env": [(ENV_NAME, is_secret), ...]}``.

    Connectors are always registered in the kernel; they only need their env
    vars set to work. The wizard reads this to know what to prompt for, and
    ``docs/connectors.md`` is generated from it.
    """
    out: list[dict] = []
    for spec in _SPECS + _GRAPHQL_SPECS:
        env = [(spec["base_url_env"], False), (spec["token_env"], True)]
        # Second credentials (APIM subscription keys etc.) are secrets too.
        env += [(e, True) for e in (spec.get("extra_headers_env") or {}).values()]
        out.append({
            "name": spec["name"],
            "label": _label_from_desc(spec["description"]),
            "env": env,
        })
    out.extend(_BESPOKE_CATALOG)
    out.sort(key=lambda e: e["name"])
    return out
