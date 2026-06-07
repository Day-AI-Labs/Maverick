# `web/` — static landing page

Single self-contained `index.html` (one HTML file, inline CSS + JS, no build step). Once `maverick.dev` is registered, deploy via GitHub Pages with this directory as the source.

## Why it's not the README

`README.md` at the repo root is a developer's first impression and shows up on PyPI / pkg-info. A landing page targets the consumer audience: a one-sentence pitch, a big download button that auto-detects the OS, and a "what it does" grid. Mixing the two audiences in one document serves neither.

## Local preview

```bash
python -m http.server -d web 8000
# open http://127.0.0.1:8000
```

## Deploy

Until `maverick.dev` is registered:

1. In repo Settings → Pages, set source to `main` branch / `/web` folder
2. The site appears at `https://day-ai-labs.github.io/maverick/`

After `maverick.dev` is registered:

3. Add a `web/CNAME` file containing `maverick.dev`
4. Point an A record at the four GitHub Pages IPs (185.199.108-111.153)
5. Enable "Enforce HTTPS" in Pages settings

## Updating release links

The primary CTA defaults to `releases/latest`. The JS at the bottom of `index.html` swaps it to a per-OS asset based on User-Agent — Windows/macOS/Linux. Asset filenames must match what the `binaries` job in `.github/workflows/release.yml` uploads (`maverick-{linux-x86_64,macos-arm64,windows-x86_64.exe}`). Update both together.

## What's intentionally missing

- Screenshots (the dashboard UI is still iterating; freeze the screenshot after Tier 2 lands)
- Pricing (open-source, no tier)
- Sign-up form (no service to sign up for)
- Trust badges (add after first signed release)
