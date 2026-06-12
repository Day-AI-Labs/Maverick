# Connectors

Maverick ships connectors to the systems enterprises actually run on. Every
connector follows the same house rules:

- **Explicit-env auth.** Each connector reads its credentials from named
  environment variables (e.g. `SERVICENOW_INSTANCE_URL` + `SERVICENOW_TOKEN`).
  Nothing uses ambient host credentials unless you opt in.
- **Writes are confirm-gated.** Any state-changing call (POST/PUT/PATCH/DELETE,
  GraphQL mutations, non-read SQL) is a dry run until you pass `confirm=true`.
- **Fail closed, fail loud.** Missing config or an API error returns an
  `ERROR:`-prefixed message; it never silently half-succeeds.

There are **217 enterprise connectors** below, part of **311+ total
tools** in the kernel. They span ITSM/ESM, CRM & sales, ERP & finance, HCM &
payroll, observability & APM, security/IAM/GRC, cloud & infra, DevOps/CI/CD,
data/BI/ETL, collaboration & content, marketing/commerce/CX, contact center,
and more.

## Enabling a connector

Set the connector's environment variables in `~/.maverick/.env` (chmod 600) or
your process environment. The interactive installer can do this for you:

```
maverick init        # advanced flow → "Connect any enterprise systems now?"
```

Pick the systems by name and the wizard prompts for each one's URL and token.
You can also add or edit them in `~/.maverick/.env` at any time.

## Catalog

Generic connectors expose one tool per system: `op` (get/post/put/patch/delete),
an API `path`, optional `params`/`body`, and `confirm` for writes. Bespoke
connectors (ServiceNow, Snowflake, SAP, Salesforce, ...) add system-specific
operations.

| Connector | Tool name | Environment variables |
| --- | --- | --- |
| Acumatica | `acumatica` | `ACUMATICA_BASE_URL` *(url)*, `ACUMATICA_TOKEN` |
| Adobe Analytics 2.0 | `adobe_analytics` | `ADOBE_ANALYTICS_BASE_URL` *(url)*, `ADOBE_ANALYTICS_TOKEN` |
| ADP Workforce Now | `adp` | `ADP_BASE_URL` *(url)*, `ADP_TOKEN` |
| Adyen | `adyen` | `ADYEN_BASE_URL` *(url)*, `ADYEN_TOKEN` |
| Adobe Experience Manager | `aem` | `AEM_BASE_URL` *(url)*, `AEM_TOKEN` |
| Aircall | `aircall` | `AIRCALL_BASE_URL` *(url)*, `AIRCALL_TOKEN` |
| Apache Airflow | `airflow` | `AIRFLOW_BASE_URL` *(url)*, `AIRFLOW_TOKEN` |
| Akamai | `akamai` | `AKAMAI_BASE_URL` *(url)*, `AKAMAI_TOKEN` |
| Alibaba Cloud | `alibaba_cloud` | `ALIBABA_CLOUD_BASE_URL` *(url)*, `ALIBABA_CLOUD_TOKEN` |
| Amplitude Analytics | `amplitude` | `AMPLITUDE_BASE_URL` *(url)*, `AMPLITUDE_TOKEN` |
| Anaplan | `anaplan` | `ANAPLAN_BASE_URL` *(url)*, `ANAPLAN_TOKEN` |
| Apollo.io | `apollo` | `APOLLO_BASE_URL` *(url)*, `APOLLO_TOKEN` |
| AppDynamics | `appdynamics` | `APPDYNAMICS_BASE_URL` *(url)*, `APPDYNAMICS_TOKEN` |
| Argo CD | `argocd` | `ARGOCD_BASE_URL` *(url)*, `ARGOCD_TOKEN` |
| SAP Ariba | `ariba` | `ARIBA_BASE_URL` *(url)*, `ARIBA_TOKEN` |
| Auth0 Management | `auth0` | `AUTH0_BASE_URL` *(url)*, `AUTH0_TOKEN` |
| Microsoft Azure Resource Manager | `azure` | `AZURE_BASE_URL` *(url)*, `AZURE_TOKEN` |
| Azure DevOps | `azure_devops` | `AZURE_DEVOPS_BASE_URL` *(url)*, `AZURE_DEVOPS_TOKEN` |
| BambooHR | `bamboohr` | `BAMBOOHR_BASE_URL` *(url)*, `BAMBOOHR_TOKEN` |
| Basecamp | `basecamp` | `BASECAMP_BASE_URL` *(url)*, `BASECAMP_TOKEN` |
| BigCommerce | `bigcommerce` | `BIGCOMMERCE_BASE_URL` *(url)*, `BIGCOMMERCE_TOKEN` |
| Google BigQuery | `bigquery` | `BIGQUERY_PROJECT` *(url)*, `BIGQUERY_ACCESS_TOKEN` |
| Bill.com | `billdotcom` | `BILLDOTCOM_BASE_URL` *(url)*, `BILLDOTCOM_TOKEN` |
| Bitbucket | `bitbucket` | `BITBUCKET_ACCESS_TOKEN` |
| BlackLine REST (financial close) | `blackline` | `BLACKLINE_BASE_URL` *(url)*, `BLACKLINE_TOKEN` |
| BMC Helix / Remedy | `bmc_helix` | `BMC_HELIX_BASE_URL` *(url)*, `BMC_HELIX_TOKEN` |
| Boomi AtomSphere | `boomi` | `BOOMI_BASE_URL` *(url)*, `BOOMI_TOKEN` |
| Box content | `box` | `BOX_BASE_URL` *(url)*, `BOX_TOKEN` |
| Braze | `braze` | `BRAZE_BASE_URL` *(url)*, `BRAZE_TOKEN` |
| Brex REST (spend) | `brex` | `BREX_BASE_URL` *(url)*, `BREX_TOKEN` |
| Calendly | `calendly` | `CALENDLY_TOKEN` |
| Wolters Kluwer CCH Axcess (Tax/Document/Workstream) | `cch_axcess` | `CCH_AXCESS_BASE_URL` *(url)*, `CCH_AXCESS_TOKEN`, `CCH_AXCESS_SUBSCRIPTION_KEY` |
| CircleCI | `circleci` | `CIRCLECI_BASE_URL` *(url)*, `CIRCLECI_TOKEN` |
| Cisco Umbrella | `cisco_umbrella` | `UMBRELLA_BASE_URL` *(url)*, `UMBRELLA_TOKEN` |
| Clari | `clari` | `CLARI_BASE_URL` *(url)*, `CLARI_TOKEN` |
| Clearbit | `clearbit` | `CLEARBIT_BASE_URL` *(url)*, `CLEARBIT_TOKEN` |
| Cloudera Manager | `cloudera` | `CLOUDERA_BASE_URL` *(url)*, `CLOUDERA_TOKEN` |
| Cloudflare | `cloudflare` | `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ZONE_ID` *(url)* |
| Coda | `coda` | `CODA_BASE_URL` *(url)*, `CODA_TOKEN` |
| IBM Cognos Analytics | `cognos` | `COGNOS_BASE_URL` *(url)*, `COGNOS_TOKEN` |
| SAP Concur | `concur` | `CONCUR_BASE_URL` *(url)*, `CONCUR_TOKEN` |
| Confluence | `confluence` | `CONFLUENCE_URL` *(url)*, `CONFLUENCE_USER` *(url)*, `CONFLUENCE_API_TOKEN` |
| Confluent Cloud | `confluent` | `CONFLUENT_BASE_URL` *(url)*, `CONFLUENT_TOKEN` |
| Cornerstone OnDemand | `cornerstone` | `CORNERSTONE_BASE_URL` *(url)*, `CORNERSTONE_TOKEN` |
| Coupa spend/procurement | `coupa` | `COUPA_BASE_URL` *(url)*, `COUPA_TOKEN` |
| Creatio (bpm'online) | `creatio` | `CREATIO_BASE_URL` *(url)*, `CREATIO_TOKEN` |
| CrowdStrike Falcon | `crowdstrike` | `CROWDSTRIKE_BASE_URL` *(url)*, `CROWDSTRIKE_TOKEN` |
| Cvent REST (events) | `cvent` | `CVENT_BASE_URL` *(url)*, `CVENT_TOKEN` |
| CyberArk | `cyberark` | `CYBERARK_BASE_URL` *(url)*, `CYBERARK_TOKEN` |
| Relational database (SQLAlchemy URL) | `database` | `DATABASE_URL` |
| Databricks | `databricks` | `DATABRICKS_HOST` *(url)*, `DATABRICKS_TOKEN`, `DATABRICKS_WAREHOUSE_ID` *(url)* |
| Datadog | `datadog` | `DATADOG_API_KEY`, `DATADOG_APP_KEY` |
| dbt Cloud | `dbt` | `DBT_BASE_URL` *(url)*, `DBT_TOKEN` |
| Deel REST (global payroll/EOR) | `deel` | `DEEL_BASE_URL` *(url)*, `DEEL_TOKEN` |
| Microsoft Defender | `defender` | `DEFENDER_BASE_URL` *(url)*, `DEFENDER_TOKEN` |
| Dialpad | `dialpad` | `DIALPAD_BASE_URL` *(url)*, `DIALPAD_TOKEN` |
| DigitalOcean | `digitalocean` | `DIGITALOCEAN_BASE_URL` *(url)*, `DIGITALOCEAN_TOKEN` |
| Docker Hub | `dockerhub` | `DOCKERHUB_BASE_URL` *(url)*, `DOCKERHUB_TOKEN` |
| DocuSign eSignature | `docusign` | `DOCUSIGN_BASE_URL` *(url)*, `DOCUSIGN_TOKEN` |
| Domo | `domo` | `DOMO_BASE_URL` *(url)*, `DOMO_TOKEN` |
| Drata REST (GRC/compliance) | `drata` | `DRATA_BASE_URL` *(url)*, `DRATA_TOKEN` |
| Cisco Duo Admin | `duo` | `DUO_BASE_URL` *(url)*, `DUO_TOKEN` |
| Microsoft Dynamics 365 | `dynamics` | `DYNAMICS_RESOURCE_URL` *(url)*, `DYNAMICS_TOKEN`, `DYNAMICS_API_VERSION` *(url)* |
| Dynatrace | `dynatrace` | `DYNATRACE_BASE_URL` *(url)*, `DYNATRACE_TOKEN` |
| Elasticsearch | `elasticsearch` | `ES_URL` *(url)*, `ES_API_KEY` |
| Epicor ERP | `epicor` | `EPICOR_BASE_URL` *(url)*, `EPICOR_TOKEN` |
| Eventbrite | `eventbrite` | `EVENTBRITE_BASE_URL` *(url)*, `EVENTBRITE_TOKEN` |
| Fastly | `fastly` | `FASTLY_BASE_URL` *(url)*, `FASTLY_TOKEN` |
| Figma | `figma` | `FIGMA_BASE_URL` *(url)*, `FIGMA_TOKEN` |
| Five9 | `five9` | `FIVE9_BASE_URL` *(url)*, `FIVE9_TOKEN` |
| Fivetran | `fivetran` | `FIVETRAN_BASE_URL` *(url)*, `FIVETRAN_TOKEN` |
| Fortinet FortiGate/FortiManager | `fortinet` | `FORTINET_BASE_URL` *(url)*, `FORTINET_TOKEN` |
| Freshdesk | `freshdesk` | `FRESHDESK_BASE_URL` *(url)*, `FRESHDESK_TOKEN` |
| Freshservice ITSM | `freshservice` | `FRESHSERVICE_BASE_URL` *(url)*, `FRESHSERVICE_TOKEN` |
| Front REST (shared inbox) | `front` | `FRONT_BASE_URL` *(url)*, `FRONT_TOKEN` |
| Google Analytics 4 | `ga4` | `GA4_PROPERTY_ID` *(url)*, `GA4_MEASUREMENT_ID` *(url)*, `GA4_ACCESS_TOKEN`, `GA4_API_SECRET` |
| Gainsight | `gainsight` | `GAINSIGHT_BASE_URL` *(url)*, `GAINSIGHT_TOKEN` |
| Google Cloud REST (Compute/Resource Manager/...) | `gcp` | `GCP_BASE_URL` *(url)*, `GCP_TOKEN` |
| Genesys Cloud | `genesys` | `GENESYS_BASE_URL` *(url)*, `GENESYS_TOKEN` |
| Gladly | `gladly` | `GLADLY_BASE_URL` *(url)*, `GLADLY_TOKEN` |
| Gong revenue-intelligence | `gong` | `GONG_BASE_URL` *(url)*, `GONG_TOKEN` |
| Thomson Reuters GoSystem Tax RS | `gosystem_tax` | `GOSYSTEM_TAX_BASE_URL` *(url)*, `GOSYSTEM_TAX_TOKEN` |
| Grafana | `grafana` | `GRAFANA_BASE_URL` *(url)*, `GRAFANA_TOKEN` |
| Greenhouse Harvest | `greenhouse` | `GREENHOUSE_BASE_URL` *(url)*, `GREENHOUSE_TOKEN` |
| Gusto | `gusto` | `GUSTO_BASE_URL` *(url)*, `GUSTO_TOKEN` |
| Harness | `harness` | `HARNESS_BASE_URL` *(url)*, `HARNESS_TOKEN` |
| Help Scout | `helpscout` | `HELPSCOUT_BASE_URL` *(url)*, `HELPSCOUT_TOKEN` |
| HubSpot | `hubspot` | `HUBSPOT_TOKEN` |
| IBM Cloud | `ibm_cloud` | `IBM_CLOUD_BASE_URL` *(url)*, `IBM_CLOUD_TOKEN` |
| iCIMS REST (recruiting) | `icims` | `ICIMS_BASE_URL` *(url)*, `ICIMS_TOKEN` |
| IFS Cloud | `ifs` | `IFS_BASE_URL` *(url)*, `IFS_TOKEN` |
| Infor CloudSuite (ION) | `infor` | `INFOR_BASE_URL` *(url)*, `INFOR_TOKEN` |
| Informatica IICS | `informatica` | `INFORMATICA_BASE_URL` *(url)*, `INFORMATICA_TOKEN` |
| Intercom | `intercom` | `INTERCOM_BASE_URL` *(url)*, `INTERCOM_TOKEN` |
| Iterable | `iterable` | `ITERABLE_BASE_URL` *(url)*, `ITERABLE_TOKEN` |
| Ivanti Neurons / ITSM | `ivanti` | `IVANTI_BASE_URL` *(url)*, `IVANTI_TOKEN` |
| Jamf Pro | `jamf` | `JAMF_BASE_URL` *(url)*, `JAMF_TOKEN` |
| Jenkins | `jenkins` | `JENKINS_BASE_URL` *(url)*, `JENKINS_TOKEN` |
| JFrog Artifactory | `jfrog` | `JFROG_BASE_URL` *(url)*, `JFROG_TOKEN` |
| Klaviyo | `klaviyo` | `KLAVIYO_BASE_URL` *(url)*, `KLAVIYO_TOKEN` |
| Kubernetes API server | `kubernetes` | `KUBERNETES_BASE_URL` *(url)*, `KUBERNETES_TOKEN` |
| Kustomer | `kustomer` | `KUSTOMER_BASE_URL` *(url)*, `KUSTOMER_TOKEN` |
| Lever recruiting | `lever` | `LEVER_BASE_URL` *(url)*, `LEVER_TOKEN` |
| LogicGate Risk Cloud | `logicgate` | `LOGICGATE_BASE_URL` *(url)*, `LOGICGATE_TOKEN` |
| LogicMonitor | `logicmonitor` | `LOGICMONITOR_BASE_URL` *(url)*, `LOGICMONITOR_TOKEN` |
| Looker | `looker` | `LOOKER_BASE_URL` *(url)*, `LOOKER_TOKEN` |
| Lucid (Lucidchart) | `lucid` | `LUCID_BASE_URL` *(url)*, `LUCID_TOKEN` |
| Adobe Commerce (Magento) | `magento` | `MAGENTO_BASE_URL` *(url)*, `MAGENTO_TOKEN` |
| Mailchimp Marketing | `mailchimp` | `MAILCHIMP_BASE_URL` *(url)*, `MAILCHIMP_TOKEN` |
| ManageEngine ServiceDesk Plus | `manageengine` | `MANAGEENGINE_BASE_URL` *(url)*, `MANAGEENGINE_TOKEN` |
| Adobe Marketo Engage | `marketo` | `MARKETO_BASE_URL` *(url)*, `MARKETO_TOKEN` |
| Matillion | `matillion` | `MATILLION_BASE_URL` *(url)*, `MATILLION_TOKEN` |
| Metabase | `metabase` | `METABASE_BASE_URL` *(url)*, `METABASE_TOKEN` |
| MicroStrategy | `microstrategy` | `MICROSTRATEGY_BASE_URL` *(url)*, `MICROSTRATEGY_TOKEN` |
| Miro | `miro` | `MIRO_BASE_URL` *(url)*, `MIRO_TOKEN` |
| Mixpanel | `mixpanel` | `MIXPANEL_PROJECT_ID` *(url)*, `MIXPANEL_PROJECT_TOKEN`, `MIXPANEL_SERVICE_SECRET` |
| Mode Analytics | `mode` | `MODE_BASE_URL` *(url)*, `MODE_TOKEN` |
| monday.com | `monday` | `MONDAY_BASE_URL` *(url)*, `MONDAY_TOKEN` |
| MuleSoft Anypoint | `mulesoft` | `MULESOFT_BASE_URL` *(url)*, `MULESOFT_TOKEN` |
| Neo4j HTTP API (Cypher) | `neo4j` | `NEO4J_BASE_URL` *(url)*, `NEO4J_TOKEN` |
| Netskope | `netskope` | `NETSKOPE_BASE_URL` *(url)*, `NETSKOPE_TOKEN` |
| Oracle NetSuite SuiteTalk | `netsuite` | `NETSUITE_BASE_URL` *(url)*, `NETSUITE_TOKEN` |
| New Relic | `newrelic` | `NEWRELIC_BASE_URL` *(url)*, `NEWRELIC_TOKEN` |
| NICE CXone | `nice_cxone` | `NICE_CXONE_BASE_URL` *(url)*, `NICE_CXONE_TOKEN` |
| Octopus Deploy | `octopus_deploy` | `OCTOPUS_BASE_URL` *(url)*, `OCTOPUS_TOKEN` |
| Okta management | `okta` | `OKTA_BASE_URL` *(url)*, `OKTA_TOKEN` |
| OneLogin | `onelogin` | `ONELOGIN_BASE_URL` *(url)*, `ONELOGIN_TOKEN` |
| OneTrust | `onetrust` | `ONETRUST_HOSTNAME` *(url)*, `ONETRUST_TOKEN` |
| Red Hat OpenShift API | `openshift` | `OPENSHIFT_BASE_URL` *(url)*, `OPENSHIFT_TOKEN` |
| Opsgenie REST (incident mgmt) | `opsgenie` | `OPSGENIE_BASE_URL` *(url)*, `OPSGENIE_TOKEN` |
| Oracle (ORDS) | `oracle` | `ORACLE_ORDS_URL` *(url)*, `ORACLE_ORDS_TOKEN` |
| Outreach | `outreach` | `OUTREACH_BASE_URL` *(url)*, `OUTREACH_TOKEN` |
| PagerDuty | `pagerduty` | `PAGERDUTY_API_TOKEN`, `PAGERDUTY_EVENTS_KEY` |
| Palo Alto Networks (Cortex/Prisma) | `palo_alto` | `PALO_ALTO_BASE_URL` *(url)*, `PALO_ALTO_TOKEN` |
| Paychex Flex | `paychex` | `PAYCHEX_BASE_URL` *(url)*, `PAYCHEX_TOKEN` |
| Paylocity | `paylocity` | `PAYLOCITY_BASE_URL` *(url)*, `PAYLOCITY_TOKEN` |
| PayPal | `paypal` | `PAYPAL_BASE_URL` *(url)*, `PAYPAL_TOKEN` |
| Pega | `pega` | `PEGA_BASE_URL` *(url)*, `PEGA_TOKEN` |
| Pendo | `pendo` | `PENDO_BASE_URL` *(url)*, `PENDO_TOKEN` |
| Ping Identity (PingOne) | `pingone` | `PINGONE_BASE_URL` *(url)*, `PINGONE_TOKEN` |
| Pipedrive | `pipedrive` | `PIPEDRIVE_BASE_URL` *(url)*, `PIPEDRIVE_TOKEN` |
| Plaid | `plaid` | `PLAID_CLIENT_ID` *(url)*, `PLAID_SECRET` |
| Planview | `planview` | `PLANVIEW_BASE_URL` *(url)*, `PLANVIEW_TOKEN` |
| Plausible | `plausible` | `PLAUSIBLE_HOST` *(url)*, `PLAUSIBLE_SITE_ID` *(url)*, `PLAUSIBLE_API_KEY` |
| PostHog | `posthog` | `POSTHOG_HOST` *(url)*, `POSTHOG_PROJECT_ID` *(url)*, `POSTHOG_API_KEY`, `POSTHOG_PERSONAL_API_KEY` |
| Microsoft Power BI | `powerbi` | `POWERBI_BASE_URL` *(url)*, `POWERBI_TOKEN` |
| Proofpoint | `proofpoint` | `PROOFPOINT_BASE_URL` *(url)*, `PROOFPOINT_TOKEN` |
| Qlik Cloud | `qlik` | `QLIK_BASE_URL` *(url)*, `QLIK_TOKEN` |
| IBM QRadar | `qradar` | `QRADAR_BASE_URL` *(url)*, `QRADAR_TOKEN` |
| Qualys | `qualys` | `QUALYS_BASE_URL` *(url)*, `QUALYS_TOKEN` |
| QuickBooks Online | `quickbooks` | `QUICKBOOKS_BASE_URL` *(url)*, `QUICKBOOKS_TOKEN` |
| Ramp REST (spend) | `ramp` | `RAMP_BASE_URL` *(url)*, `RAMP_TOKEN` |
| Rapid7 InsightVM/IDR | `rapid7` | `RAPID7_BASE_URL` *(url)*, `RAPID7_TOKEN` |
| Replicate | `replicate` | `REPLICATE_API_TOKEN` |
| RingCentral | `ringcentral` | `RINGCENTRAL_BASE_URL` *(url)*, `RINGCENTRAL_TOKEN` |
| Rippling | `rippling` | `RIPPLING_BASE_URL` *(url)*, `RIPPLING_TOKEN` |
| Sage Intacct | `sage_intacct` | `SAGE_INTACCT_BASE_URL` *(url)*, `SAGE_INTACCT_TOKEN` |
| SailPoint IdentityNow | `sailpoint` | `SAILPOINT_BASE_URL` *(url)*, `SAILPOINT_TOKEN` |
| Salesforce | `salesforce` | `SALESFORCE_INSTANCE_URL` *(url)*, `SALESFORCE_ACCESS_TOKEN` |
| Salesforce Commerce Cloud (SCAPI/OCAPI) | `salesforce_commerce` | `SFCC_BASE_URL` *(url)*, `SFCC_TOKEN` |
| Salesloft | `salesloft` | `SALESLOFT_BASE_URL` *(url)*, `SALESLOFT_TOKEN` |
| SAP (OData) | `sap` | `SAP_BASE_URL` *(url)*, `SAP_TOKEN` |
| SAP Commerce Cloud (Hybris) OCC | `sap_commerce` | `SAP_COMMERCE_BASE_URL` *(url)*, `SAP_COMMERCE_TOKEN` |
| Twilio Segment Public API | `segment` | `SEGMENT_BASE_URL` *(url)*, `SEGMENT_TOKEN` |
| Twilio SendGrid | `sendgrid` | `SENDGRID_BASE_URL` *(url)*, `SENDGRID_TOKEN` |
| Microsoft Sentinel REST (Azure) | `sentinel` | `SENTINEL_BASE_URL` *(url)*, `SENTINEL_TOKEN` |
| SentinelOne | `sentinelone` | `SENTINELONE_BASE_URL` *(url)*, `SENTINELONE_TOKEN` |
| Sentry | `sentry` | `SENTRY_HOST` *(url)*, `SENTRY_AUTH_TOKEN` |
| ServiceNow | `servicenow` | `SERVICENOW_INSTANCE_URL` *(url)*, `SERVICENOW_TOKEN` |
| Salesforce Marketing Cloud | `sfmc` | `SFMC_BASE_URL` *(url)*, `SFMC_TOKEN` |
| Shopify | `shopify` | `SHOPIFY_STORE` *(url)*, `SHOPIFY_ACCESS_TOKEN` |
| Sisense | `sisense` | `SISENSE_BASE_URL` *(url)*, `SISENSE_TOKEN` |
| SmartRecruiters | `smartrecruiters` | `SMARTRECRUITERS_BASE_URL` *(url)*, `SMARTRECRUITERS_TOKEN` |
| Smartsheet | `smartsheet` | `SMARTSHEET_BASE_URL` *(url)*, `SMARTSHEET_TOKEN` |
| Snowflake | `snowflake` | `SNOWFLAKE_ACCOUNT` *(url)*, `SNOWFLAKE_TOKEN` |
| Snyk | `snyk` | `SNYK_BASE_URL` *(url)*, `SNYK_TOKEN` |
| SolarWinds Service Desk | `solarwinds` | `SOLARWINDS_BASE_URL` *(url)*, `SOLARWINDS_TOKEN` |
| SonarQube | `sonarqube` | `SONARQUBE_BASE_URL` *(url)*, `SONARQUBE_TOKEN` |
| Splunk | `splunk` | `SPLUNK_BASE_URL` *(url)*, `SPLUNK_TOKEN` |
| Sprinklr | `sprinklr` | `SPRINKLR_BASE_URL` *(url)*, `SPRINKLR_TOKEN` |
| Square | `square` | `SQUARE_BASE_URL` *(url)*, `SQUARE_TOKEN` |
| Stripe | `stripe` | `STRIPE_SECRET_KEY` |
| SAP SuccessFactors | `successfactors` | `SUCCESSFACTORS_BASE_URL` *(url)*, `SUCCESSFACTORS_TOKEN` |
| SugarCRM REST (v11+) | `sugarcrm` | `SUGARCRM_BASE_URL` *(url)*, `SUGARCRM_TOKEN` |
| Sumo Logic | `sumologic` | `SUMOLOGIC_BASE_URL` *(url)*, `SUMOLOGIC_TOKEN` |
| Tableau Server/Cloud | `tableau` | `TABLEAU_BASE_URL` *(url)*, `TABLEAU_TOKEN` |
| Talend Cloud | `talend` | `TALEND_BASE_URL` *(url)*, `TALEND_TOKEN` |
| Talkdesk | `talkdesk` | `TALKDESK_BASE_URL` *(url)*, `TALKDESK_TOKEN` |
| Microsoft Teams | `teams` | `TEAMS_WEBHOOK_URL` |
| Tenable.io | `tenable` | `TENABLE_BASE_URL` *(url)*, `TENABLE_TOKEN` |
| Teradata REST (Vantage) | `teradata` | `TERADATA_BASE_URL` *(url)*, `TERADATA_TOKEN` |
| Terraform Cloud/Enterprise | `terraform` | `TERRAFORM_BASE_URL` *(url)*, `TERRAFORM_TOKEN` |
| ThoughtSpot | `thoughtspot` | `THOUGHTSPOT_BASE_URL` *(url)*, `THOUGHTSPOT_TOKEN` |
| Trello | `trello` | `TRELLO_KEY`, `TRELLO_TOKEN` |
| Twilio | `twilio` | `TWILIO_ACCOUNT_SID` *(url)*, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER` *(url)* |
| UKG (Ultimate Kronos) | `ukg` | `UKG_BASE_URL` *(url)*, `UKG_TOKEN` |
| Unit4 ERP | `unit4` | `UNIT4_BASE_URL` *(url)*, `UNIT4_TOKEN` |
| Vanta REST (GRC/compliance) | `vanta` | `VANTA_BASE_URL` *(url)*, `VANTA_TOKEN` |
| HashiCorp Vault | `vault` | `VAULT_BASE_URL` *(url)*, `VAULT_TOKEN` |
| Google Vertex AI | `vertex` | `VERTEX_PROJECT` *(url)*, `VERTEX_LOCATION` *(url)*, `VERTEX_ACCESS_TOKEN` |
| Vonage | `vonage` | `VONAGE_BASE_URL` *(url)*, `VONAGE_TOKEN` |
| VMware vSphere | `vsphere` | `VSPHERE_BASE_URL` *(url)*, `VSPHERE_TOKEN` |
| Cisco Webex | `webex` | `WEBEX_BASE_URL` *(url)*, `WEBEX_TOKEN` |
| Wiz CNAPP | `wiz` | `WIZ_BASE_URL` *(url)*, `WIZ_TOKEN` |
| Workable REST (recruiting) | `workable` | `WORKABLE_BASE_URL` *(url)*, `WORKABLE_TOKEN` |
| Workato | `workato` | `WORKATO_BASE_URL` *(url)*, `WORKATO_TOKEN` |
| Workday | `workday` | `WORKDAY_BASE_URL` *(url)*, `WORKDAY_TOKEN` |
| Workiva (Wdesk) | `workiva` | `WORKIVA_BASE_URL` *(url)*, `WORKIVA_TOKEN` |
| Wrike work-management | `wrike` | `WRIKE_BASE_URL` *(url)*, `WRIKE_TOKEN` |
| Xero accounting | `xero` | `XERO_BASE_URL` *(url)*, `XERO_TOKEN` |
| xMatters | `xmatters` | `XMATTERS_BASE_URL` *(url)*, `XMATTERS_TOKEN` |
| Zapier NLA / | `zapier` | `ZAPIER_BASE_URL` *(url)*, `ZAPIER_TOKEN` |
| Zendesk Support | `zendesk` | `ZENDESK_BASE_URL` *(url)*, `ZENDESK_TOKEN` |
| Zoho CRM | `zoho` | `ZOHO_BASE_URL` *(url)*, `ZOHO_TOKEN` |
| Zoom | `zoom` | `ZOOM_USER_ID` *(url)*, `ZOOM_OAUTH_TOKEN` |
| ZoomInfo | `zoominfo` | `ZOOMINFO_BASE_URL` *(url)*, `ZOOMINFO_TOKEN` |
| Zscaler | `zscaler` | `ZSCALER_BASE_URL` *(url)*, `ZSCALER_TOKEN` |

Variables marked *(url)* are non-secret endpoints/identifiers; the rest are
secrets (tokens, keys, or `user:pass` for basic-auth connectors) and belong in
`.env`, never in `config.toml` or version control.

## Relational databases

The `database` tool connects to PostgreSQL, MySQL/MariaDB, SQL Server,
CockroachDB, Oracle, Amazon Redshift, and any other SQLAlchemy-supported
engine via a single `DATABASE_URL` (or a per-call `url`). Reads run; writes
(INSERT/UPDATE/DELETE/DDL) require `confirm=true`. Install the matching driver
(`psycopg`, `pymysql`, `pyodbc`, ...) for your database.

## Ambient-credential connectors

AWS (`s3`, `lambda`, `dynamodb`, `ses`, `sns`) and a few others (`airtable`,
`asana`, `clickup`, `vercel`, `gdrive`) can use ambient host credentials, so
they register only when `MAVERICK_ENABLE_CRED_TOOLS=1`. See
[env-vars.md](env-vars.md).

## Don't see your system?

Most enterprise SaaS exposes a token-authed JSON REST or GraphQL API, which
means a new connector is usually a one-line spec in
`packages/maverick-core/maverick/tools/enterprise_connectors.py` — no new
module. Open a request or add the spec and it registers automatically.
