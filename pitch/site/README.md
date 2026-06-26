# Lightwork — marketing site (Daybreak Labs)

A self-contained, premium marketing site for **Lightwork**, built in plain HTML +
CSS — no build step, no framework. Design: editorial restraint (warm paper, an
editorial serif for headlines, Inter for body, one accent, dark sections for the
proof/security moments). Every claim is verifiable from this repo.

## Pages
| File | What it is |
|---|---|
| `index.html` | Home — hero, problem, how it works, why, proof, security, who it's for, CTA |
| `product.html` | How it works — the chokepoint, seven components, governance, the Operating Record, learning, proof, deploy |
| `security.html` | Security & deployment — control→mechanism table, deployment models, audit/evidence, compliance status |
| `company.html` | Company, founder, contact |
| `styles.css` | The shared design system |

**Brand assets** (all derived from `Daybreak Labs Logo.jpg`): `daybreak-mark-dark.png`
(nav + footer mark chip), `daybreak-logo.png` (full logo, transparent — used on dark
sections), `favicon-32/180/512.png`, and `og.png` (1200×630 social card).

## Preview
Open `index.html` in any browser. Fonts (Newsreader / Inter / JetBrains Mono)
load from Google Fonts when online and fall back to system fonts offline.

## Deploy — live
Hosted on **Cloudflare Pages**, project `daybreak-labs`:
- Production: https://daybreak-labs.pages.dev
- Redeploy: `CLOUDFLARE_API_TOKEN=… CLOUDFLARE_ACCOUNT_ID=… npx wrangler pages deploy pitch/site --project-name=daybreak-labs --branch=main`

**Custom domain `daybreakailabs.com`** (+ `www`) is attached to the project and goes
live automatically once the domain's nameservers point at Cloudflare
(`aaden.ns.cloudflare.com`, `leia.ns.cloudflare.com`). Email stays on **Google
Workspace** — preserve the `MX` (`aspmx.l.google.com`) and the SPF/verification
`TXT` records through the switch.

## Demo form delivery (Web3Forms)
**Book a demo** / **Request access** submit to [Web3Forms](https://web3forms.com)
when an access key is present, and otherwise fall back to a pre-filled `mailto:`
(never a dead end). Set the key at deploy time **without editing `app.js`**, via
either:
- a `<meta name="web3forms-access-key" content="YOUR-KEY">` in each page `<head>`, or
- `window.LIGHTWORK_ACCESS_KEY = "YOUR-KEY";` (e.g. an uncommitted `config.js`).

The key is the only thing standing between the live form and direct-to-inbox
delivery — get a free one at web3forms.com (sends to info@daybreakailabs.com).

## Finish before launch
- Replace the founder-bio placeholder in `company.html` (marked with an HTML comment).
- Set the Web3Forms access key (above) so demo requests reach the inbox directly.
- Confirm the SOC 2 wording on `security.html` matches reality before publishing.
