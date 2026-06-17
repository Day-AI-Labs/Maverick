# Maverick — marketing site (Daybreak Labs)

A self-contained, premium marketing site for **Maverick**, built in plain HTML +
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

## Preview
Open `index.html` in any browser. Fonts (Newsreader / Inter / JetBrains Mono)
load from Google Fonts when online and fall back to system fonts offline.

## Deploy
It's static — host it anywhere:
- **Netlify / Vercel / Cloudflare Pages** — drag-and-drop this folder (or connect
  the repo), then point `daybreakailabs.com` at it.
- **Wix** — the classic Wix Editor can't render this directly. Either use it as
  the pixel-exact spec to rebuild in **Wix Studio**, or move the domain to static
  hosting above.

## Finish before launch
- Replace the founder-bio placeholder in `company.html` (marked with an HTML comment).
- Wire **Book a demo** / **Request access** to a real form (they're `mailto:` today).
- Add a favicon and a social-share (OpenGraph) image.
- Confirm the SOC 2 wording on `security.html` matches reality before publishing.
