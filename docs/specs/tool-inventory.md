# Tool inventory — maintenance & risk audit

**Purpose.** Decision-support for the *breadth-vs-depth* question raised in
[`ROADMAP.md`](../ROADMAP.md) → "Current state & gap analysis" (thesis: "the
highest-value additions are not more breadth"). This audit buckets the **286** tool modules in
`packages/maverick-core/maverick/tools/` by **what they cost to maintain** and
**how much capability/risk they carry**, so the team can decide what stays in the
core and what should move to the community **plugin** tier.

> **Scope & honesty caveat.** This is a *static* audit (filename + capability
> reasoning). It does **not** measure how often each tool is actually invoked —
> that data doesn't exist yet. See [Recommendation](#recommendation); the first
> step is opt-in tool-usage telemetry, not cuts.

Counts exclude `__init__.py`, `_ssrf.py`, and `find_tools.py` (the meta-tool).

## Buckets

| # | Bucket | Count | Maintenance surface | Keep in core? |
|---|--------|-------|---------------------|---------------|
| 1 | **Agent-internal / kernel** — `agent_bus_tool`, `ask_user`, `budget_status`, `spend_report`, `notify`, `recall`, `learn`, `kv_memory`, `spawn`, `diagnose` | 10 | None (own code) | **Yes** — part of the loop |
| 2 | **Code & repo** — `apply_patch`, `ast_edit`, `str_edit`, `git_advanced`, `dep_graph`, `repo_map`, `test_impact`, `preview_diff`, `openapi_runner` | 9 | Low (local + git) | **Yes** — core differentiator |
| 3 | **System / local execution** — `shell`, `compute`, `computer`, `fs`, `clipboard`, `file_watcher`, `browser`, `android`, `ios_sim`, `voice` | 10 | Low–med (OS/driver) | **Yes** — core capability |
| 4 | **Knowledge & research** — `arxiv`, `wikipedia`, `hackernews`, `reddit_tool`, `semantic_scholar`, `web_search`, `youtube`, `newsapi_tool`, `http_fetch`, `dns_lookup`, `geocode`, `currency`, `translate`, `wolfram_tool`, `huggingface` | 15 | Mixed (keyless vs. keyed) | **Mostly** — keyless core; keyed ones reviewable |
| 5 | **Media & document** — `ffmpeg_tool`, `imagemagick_tool`, `ocr`, `pdf_reader`, `pandoc_tool`, `view_image`, `view_video`, `attachments`, `embeddings`, `a11y` | 10 | Low (local libs) | **Yes** — low-risk, local |
| 6 | **Data query (local)** — `pandas_query`, `sql_query` | 2 | Low | **Yes** |
| 7 | **External SaaS / cloud connectors** | **47** | **High (3rd-party API drift + credentials)** | **Candidate for plugin tier** |

Buckets 1–6 (**56** tools) are the differentiated, low-maintenance core. Bucket 7
(**47** tools) is the long tail the roadmap thesis is about.

## Bucket 7 detail — the connector tail (47)

| Sub-group | Tools |
|-----------|-------|
| PM / docs / calendar (10) | `airtable`, `asana`, `clickup`, `confluence`, `jira`, `linear`, `notion`, `trello`, `calendly`, `calendar` |
| Dev SaaS (3) | `bitbucket`, `github_actions`, `gitlab` |
| Comms — *send-as-user* (7) | `discord_bot`, `slack_bot`, `twilio`, `email_tool`, `gmail`, `zoom`, `msgraph` |
| CRM / marketing / analytics (6) | `hubspot`, `salesforce`, `mixpanel`, `ga4`, `plausible`, `posthog` |
| Cloud infra — *mutate / spend* (10) | `cloudflare`, `s3`, `ses`, `sns`, `lambda`, `dynamodb`, `vercel`, `redis`, `mongodb`, `elasticsearch` |
| Monitoring / ops (3) | `datadog`, `sentry`, `pagerduty` |
| Storage (2) | `dropbox`, `gdrive` |
| Payments / financial — *move money* (3) | `stripe`, `plaid`, `shopify` |
| Media SaaS (2) | `spotify`, `replicate` |
| Home / IoT — *controls physical devices* (1) | `home_assistant` |

Each connector independently tracks a third-party API (auth, schema, rate limits,
breaking changes) and ships a credential path — i.e. each is recurring maintenance
**and** attack surface, with little differentiation (these are table-stakes that
every agent offers).

## Primary-source / public-data connectors (read-only)

Separate from the bucket-7 SaaS connector tail, the platform ships **37 read-only
primary-source / public-data connectors** (SEC EDGAR, FRED, Treasury, World Bank,
FDIC, Census, BLS, EIA, openFDA, NPPES, ClinicalTrials, USAspending, SAM.gov,
CourtListener, Federal Register, GLEIF, OpenCorporates, NWS/NOAA weather, EPA,
Climatiq, ...). These are **GET-only, low-risk, deferred** and are auto-granted
to each analyst pack by suite (`SUITE_DATA_CONNECTORS`, layered in
`domain_capability`) for **primary-source data grounding** — ON by default, with
kill-switch `[workforce] data_grounding = false` (env
`MAVERICK_WORKFORCE_DATA_GROUNDING=off`) and an installer wizard step. Because
they are read-only and keyless/public, they belong in the **Low** risk tier
below and do not carry the credential/attack-surface cost of bucket 7.

Robustness note: connectors now return an ERROR string (rather than raising) on
a non-string op/path/query, hardened by the governance stress sweep.

## Risk tiers (capability, not maintenance)

Relevant to the "is the default ceiling safe for *non-technical* consumers?"
question (the product's stated audience).

- **High — irreversible / costly / external side effects:** `shell`, `compute`,
  `computer` (arbitrary execution); `stripe`, `plaid`, `shopify` (money); all
  *cloud-infra* connectors (mutate/spend); all *send-as-user comms*;
  `home_assistant` (physical devices).
- **Medium — mutate third-party state:** repo writes (`git_advanced`,
  `github_actions`, `gitlab`, `bitbucket`), PM/CRM writes, `browser`/`android`/
  `ios_sim` automation.
- **Low — read-only / local:** research reads, media processing, local query,
  agent-internal reads.

The kernel already has `tool_risk` + ACL + consent + killswitch; this tiering is
the input for deciding what the **default** posture allows before a consumer
configures anything.

## Recommendation

1. **Add opt-in tool-usage telemetry first.** Don't cut on intuition — instrument
   invocation counts (privacy-respecting, opt-in) so the keep/cut call is
   data-backed. This is the one prerequisite.
2. **Keep buckets 1–6 in core** (56 tools). They're differentiated and cheap.
3. **Re-home bucket 7 (47 connectors) into the plugin tier**, not delete. Per
   `CLAUDE.md` rules 5–6, each needs a config knob + wizard entry anyway; the
   plugin SDK ([`../plugins.md`](../plugins.md)) + MCP **Registry** (roadmap B2)
   is the natural home and gives the skill/connector marketplace a discovery
   backbone. Core stays lean; maintenance moves to the ecosystem.
4. **Tighten the default risk ceiling** for the consumer build using the tiers
   above (high-risk tools off-by-default / consent-gated).

## Questions for the team (tee-up for the breadth-vs-depth discussion)

- Is "freeze breadth, invest in depth" the actual call, or is wide connector
  coverage part of the consumer pitch?
- If we re-home connectors: ship the plugin tier + registry **first** (so nothing
  regresses), then migrate — what's the deprecation window?
- Telemetry: acceptable to add opt-in usage counts, or is even that off the table
  for a privacy-positioned product?
