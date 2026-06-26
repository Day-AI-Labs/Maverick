# Decision: no browser anti-bot evasion kit

**Status:** Decided — declined · **Roadmap ref:** 2027-H2 Capabilities
"Browser anti-bot evasion kit (opt-in)" · **Date:** June 2026 ·
**Precedent:** the corpus-release indicator policy (capability shipped
only where the safety posture holds).

## Question

Should the browser tool ship an "evasion kit" — fingerprint spoofing,
CAPTCHA solving, bot-detection bypass (stealth plugins, TLS/JA3
mimicry, behavioral-noise injection) — so agents can automate sites that
actively block automation?

## Decision

**No, including as an opt-in.** This is the one roadmap capability whose
*purpose* is to defeat an access control another operator deliberately put
up. A config flag does not change that: the value of an evasion kit is
precisely that it circumvents a site's stated "no automated access"
boundary, which is detection evasion against a third party. Shipping it —
even default-OFF, even labelled "use responsibly" — would make Lightwork a
turnkey tool for ToS violation, scraping past rate limits, and CAPTCHA
farming, and would put that capability one toggle away for every operator
regardless of intent. That is not a posture we can stand behind in a
commercially licensed enterprise product, and it is not a capability we are
willing to make broadly available.

This is a *decline on purpose-of-the-capability* grounds, not a
"too hard" punt. The mechanics (header/UA rotation, headless-flag
masking, solver APIs) are individually well known; the reason we don't
assemble them into a kit is that the assembled artifact has no
legitimate-use story that isn't already served by the supported path
below.

## What we support instead (and why it's enough for real work)

The browser tool (`tools/browser.py`, `[browser]` extra) does everything an
*authorized* automation needs against sites that *welcome* it:

- **Authenticated sessions you own.** The session-capture providers and the
  cookie/login flows drive sites you have an account on, as yourself —
  no spoofing required, because you are a real authorized user.
- **Public content + APIs.** Fetch, parse, fill forms, click, screenshot,
  extract the accessibility tree — the legitimate automation surface.
- **`robots.txt`-respecting fetches** and ordinary rate-limited access:
  cooperate with the site's stated boundary instead of defeating it.
- **First-party testing.** Automating *your own* app — including its bot
  defenses — is a legitimate need; do it against your own staging with
  your own credentials, where there is no third-party boundary to evade.

If a site blocks automation, the supported answer is to get authorization
(an API key, a partnership, an account whose ToS permits automation) — not
to defeat the block. That keeps the legitimate use cases fully served while
declining the one whose only function is circumvention.

## Revisit trigger

A narrowly scoped, **authorization-gated** capability could be reconsidered
if a concrete, verifiable consent signal exists — e.g. a site publishing an
automation-allowed policy the tool can check and honor, or a customer
automating infrastructure they own and attest to. Any such revisit ships
the *consent check* first; it does not ship the evasion mechanics on their
own.
