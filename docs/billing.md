# Billing & collection model

Lightwork is sold as **annual enterprise contracts** (see
[`product-portfolio.md`](./product-portfolio.md)), not self-serve checkout. The
billing surface in the product reflects that: it **meters usage and produces
invoices**, and collection happens through your normal contract/AR process or a
payment processor you wire in. There is intentionally **no built-in card-checkout
flow** — a $18K–$500K/yr governed-platform sale closes on a signed order form and
an invoice, not a Stripe "Buy now" button.

## What the product does

- **Metering.** Per-principal, per-day usage (provider dollars + tokens) is
  recorded to a tenant-scoped ledger (`maverick.quotas.UsageLedger`).
- **Rating → invoice.** `maverick billing invoice <tenant> [--since --until]`
  (or `billing.generate_invoice`) rates the ledger through a `RateCard`
  (markup or token pricing, with a minimum charge) into an `Invoice`.
- **Idempotency.** An invoice for a **closed** period (both `--since` and
  `--until` given) carries a deterministic `invoice_id` (`inv_…`, keyed on
  tenant + period + currency, **not** the amount), so re-running billing for that
  period yields the same id and a downstream charge step can dedup and **never
  double-bill**. An **open-ended** invoice (a missing bound — including the CLI
  default with no `--since/--until`) has an **empty `invoice_id`**: its total
  grows as usage accrues, so it is deliberately *not* a safe dedup key. Always
  bill closed periods.
- **Per-tenant spend caps.** `maverick tenant quota <id> <usd/day>` enforces a
  daily ceiling at the channel door (a tenant over its cap is refused), and
  per-tenant plans gate features (`maverick billing entitlements <id>`).

## How money is actually collected

Pick one:

1. **Contract + AR (default).** Close on an order form; invoice on your finance
   system's cadence. Use `maverick billing invoice --json` to export the rated
   line items (and `invoice_id`) into your AR/ERP. This is the expected path for
   the enterprise tiers.
2. **Bring your own processor.** If you want programmatic collection (e.g. usage
   billing inside a contract), push the exported invoice to your processor keyed
   on `invoice_id` for idempotency. The bundled Stripe tool
   (`maverick.tools.stripe_tool`) is **read-mostly by design** — it answers
   account questions and (env-gated) refunds, and deliberately does **not** let
   an agent create charges. Charge-creation is an operator/finance action, not an
   agent capability.

## Why no self-serve checkout

For this product's ACV and buyer (regulated enterprise, security-reviewed,
contract-signed), a self-serve card flow is the wrong primitive: procurement
requires an order form, a DPA, and net terms — not a checkout page. Metering +
idempotent invoicing + AR export covers the real motion. If a lower-tier,
self-serve **Community/Team** SKU later needs card checkout, wire a processor at
that point keyed on `invoice_id`; nothing in the core blocks it.
