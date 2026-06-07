# Agent factory — roadmap

**Status:** living plan. The compartment safety substrate (Rungs 0–1) is merged
/ in review; this doc tracks the rest: domain packs, intake, knowledge upload,
multi-tenancy, and the UX that turns Maverick into a factory that *spits out*
tailored, sealed domain agents.

## The product

A business onboards via **intake** ("we do X"), **uploads its documents** (the
Cowork-style setup), and the factory emits a **tailored domain agent** (finance,
legal, privacy/compliance, generic) pre-loaded with that business's knowledge
and the right tools. Each domain is a **sealed compartment**: an attack on one
is contained and the rest are immune.

```
intake ─▶ DomainProfile ─▶ knowledge (docs) ─▶ spawn domain agent ─▶ operate
                              └──────────── all under compartments ───────────┘
```

## Decisions locked (2026-06-07)

- **Unseal (Rung 2):** both a **human** *and* the **orchestrator** may clear a
  latched sector seal — selectable per company via `[safety] compartment_unseal`
  (`human` | `orchestrator` | `both`).
- **Authoring:** support **both** — hand-authored TOML packs *and*
  intake-generated packs (same `DomainProfile` schema; provenance in `authoring`).
- **First domains:** all four — **finance, legal, generic, privacy/compliance**.
- **Knowledge:** **full vector RAG** (embeddings + vector store + semantic
  retrieval), scoped per domain, with shield-scanned ingestion.

## Workstreams

**1. Safety substrate (compartments)**
- `✅` Rung 0 immunity · `✅` Rung 1 containment · `▶` Rung 2 sector seal by domain
- `▶` domain/compartment tag on agent identity (the factory ↔ safety hinge)
- `◻` compartment observability (dashboard + CLI) · `◻` seal/immunity audit trail

**2. Domain packs (the unit the factory emits)** — `▶` in progress
- `▶` `DomainProfile` schema + TOML loader (`maverick/domain.py`)
- `▶` capability envelope derived from the profile (ties to `capability.py`)
- `▶` reference packs: finance → legal → privacy/compliance → generic
- `◻` spawn-from-profile (persona + attenuated capability + compartment tag → Agent)
- `◻` package-data wiring so built-in packs ship in the wheel

**3. Intake (onboard a business)**
- `◻` intake schema + flow (wizard now; conversational "intake agent" later)
- `◻` intake → DomainProfile generation (LLM-assisted) with a human approve step

**4. Knowledge / documents (full vector RAG)**
- `◻` ingest (upload + parse PDF/docx/md + chunk) · `◻` embed + vector store
- `◻` per-domain retrieval tool with citations
- `◻` **doc safety**: ingestion is shield-scanned (RAG poisoning is exactly what
  compartments defend — the two halves meet here)

**5. Multi-tenant isolation** — `◻` later
- workspace/business entity; hard isolation; per-tenant budget; deletion/residency

**6. Orchestration & routing** — `◻` later
- top-level router → right domain agent(s); cross-domain work that respects seals

**7. UX** — `◻` later
- wizard (domain select + intake + upload, rule 6); CLI (`business create / add-domain / upload-docs / run`); dashboard (compartment status, doc library)

**8. Productionization** — `◻` later
- persistence/DB; auth; deploy; **red-team harness** (prove an attack can't cross a sealed bulkhead)

## Sequence

P1 substrate (Rung 2 + domain tag) → P2 domain packs + spawn-from-profile + 4 domains
→ P3 vector-RAG knowledge + doc safety → P4 intake + LLM pack generation
→ P5 multi-tenancy → P6 UX/dashboard → P7 hardening/red-team.
Multi-tenancy is deliberately later — the single-business loop must work and be safe first.
