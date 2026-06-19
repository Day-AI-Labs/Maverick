# Patent Filing Guide + Disclosure Audit

> **Not legal advice.** This document is an engineering-side preparation package
> for patent counsel. It does not create an attorney–client relationship and is
> not a substitute for a registered patent attorney/agent. Do not rely on it for
> any filing decision without counsel review.

Prepared: 2026-06-19. Repo: `Day-AI-Labs/Maverick`.

---

## 0. READ THIS FIRST — the disclosure clock is already running

`Day-AI-Labs/Maverick` is a **PUBLIC** GitHub repository.

| Fact | Value | Source |
|---|---|---|
| Repo visibility | **public** | GitHub API `"visibility":"public"` |
| Repo created | 2026-05-25 | GitHub API `created_at` |
| Invention source files first committed | **2026-06-18** | `git log --diff-filter=A` on each file (see §3) |
| Last public push | 2026-06-18 | GitHub API `pushed_at` |

### What this means

1. **United States — you have a grace period, but it is finite.** Under 35 U.S.C.
   §102(b)(1), an inventor's own public disclosure starts a **12-month** clock to
   file. Based on the public commit date, the practical US deadline is **on or
   before ~2026-06-18, 2027.** File *well* before that; do not wait.

2. **Most of the rest of the world — rights may ALREADY be lost.** Europe (EPO),
   China, and most jurisdictions apply **absolute novelty**: any public
   disclosure *before* the filing date is a bar, with no grace period. Because
   the code has been public since ~2026-06-18, **foreign patent rights for the
   already-disclosed mechanisms are likely already forfeited** unless an
   application with a priority date predating the public push already exists.
   Confirm with counsel immediately; this is the single most expensive mistake
   available here.

3. **Action:** Verify the *exact* first public-disclosure date for each invention
   (the git dates below are the in-repo add dates; the public push may differ if
   history was squashed/imported). Counsel needs the true earliest public date to
   compute the US bar and to confirm whether any foreign route survives (e.g.,
   filing before any *further* disclosure of not-yet-shipped improvements).

> ⚠️ **Do not make additional public disclosures** of these mechanisms (blog
> posts, conference talks, new public commits that elaborate the mechanism,
> PyPI/release notes detailing them) until provisionals are on file. Each new
> disclosure can independently bar foreign rights and can complicate US filing.

---

## 1. What you're filing

Three inventions, each as its own application (do not combine — they are distinct
and the USPTO would likely issue a restriction requirement anyway):

| # | Working title | Disclosure memo | Tier |
|---|---|---|---|
| 1 | Tamper-evident, cross-language-verifiable audit trail for staged machine-learning capability rollouts | `01-...signed-learning-audit.md` | strongest §101 footing |
| 2 | Calibration-gated self-modifying agent with snapshot-replay learning-regression detection | `02-...calibration-gated-learning.md` | strongest differentiation |
| 3 | Governed shared-memory plane for heterogeneous third-party agents | `03-...fleet-memory.md` | strongest strategic moat |

---

## 2. The filing path (recommended: provisional-first)

Because the US clock is running and foreign rights are likely already impaired,
**file three US provisional applications now**, then decide within 12 months
which to convert to non-provisionals.

### Step-by-step

1. **Create your USPTO account.** Go to **Patent Center**
   (https://patentcenter.uspto.gov). You will:
   - Register for a **USPTO.gov account** (identity verification via ID.me or
     equivalent).
   - Obtain a **Customer Number** and, if filing yourself, a way to pay
     (credit card or USPTO deposit account).
   - For an entity (Day AI Labs), the company is the *applicant*; the humans are
     the *inventors*. You can still file pro se, but see §6 — get counsel.

2. **Determine entity size (affects every fee).**
   - **Micro entity** (≈75% off): gross income under the threshold (~$239K as of
     2026, indexed) **and** named on fewer than 5 prior non-provisional US
     applications, **and** not obligated to assign to a non-qualifying entity.
     A funded startup that has assigned rights to investors/a large entity often
     does **not** qualify — check carefully.
   - **Small entity** (50% off): generally <500 employees and rights not licensed
     to a large entity. Most early-stage startups qualify here.
   - **Large entity**: everyone else.
   - Provisional filing fee (2026): **$325 large / $130 small / $65 micro** per
     application. (Verify current numbers on the USPTO fee schedule at filing —
     fees change.) Page surcharge applies only beyond 100 pages.

3. **Assemble each provisional** (per invention):
   - **Specification** — use the body of the matching invention-disclosure memo
     (problem, detailed description, variations). Provisionals do **not** require
     formal claims, but **include the draft claims anyway** — they discipline the
     disclosure and define what the priority date actually covers.
   - **Drawings** — provide at least the flow/architecture figures described in
     each memo's "Drawings" section. Informal drawings are acceptable in a
     provisional.
   - **Cover sheet** (Patent Center provides the provisional cover sheet form):
     inventor names, title, applicant, correspondence address.
   - **Critical rule:** a provisional only protects what it actually describes.
     **Anything you later claim in the non-provisional must be supported by the
     provisional's text**, or it loses the early priority date. Err toward
     *more* technical detail and *more* variations.

4. **File + pay** in Patent Center. Save the **filing receipt** (it has the
   application number and filing date — that date is your priority date).

5. **Docket the 12-month deadline.** Within 12 months of each provisional you
   must file the corresponding **non-provisional** (and any **PCT** application
   if any foreign route still exists) or the priority date evaporates. Put hard
   calendar reminders at T-6mo, T-3mo, T-1mo.

6. **Prior-art search before converting.** Provisionals buy time to run a real
   search (§5) and decide which inventions justify the ~$8K–$20K each that a
   non-provisional costs.

---

## 3. Disclosure-date audit (evidence for counsel)

In-repo "file added" dates (`git log --diff-filter=A --follow`). All on the
public `main`-lineage history.

**Invention 1 — signed staged-learning audit**
- `packages/maverick-core/maverick/learning_rollout.py` — 2026-06-18
- `packages/maverick-core/maverick/audit/signing.py` — 2026-06-18
- `rust/maverick-verify-audit/src/canonical.rs` — 2026-06-18
- `rust/maverick-verify-audit/src/lib.rs` — 2026-06-18

**Invention 2 — calibration-gated evolution + hindsight**
- `packages/maverick-core/maverick/calibration.py` — 2026-06-18
- `packages/maverick-core/maverick/hindsight.py` — 2026-06-18
- `packages/maverick-core/maverick/dreaming.py` — 2026-06-18
- `packages/maverick-evolve/maverick_evolve/loop.py` — 2026-06-18
- `packages/maverick-evolve/maverick_evolve/archive.py` — 2026-06-18

**Invention 3 — governed fleet memory**
- `packages/maverick-core/maverick/fleet_memory.py` — 2026-06-18
- `packages/maverick-core/maverick/agent_trust.py` — 2026-06-18

> Counsel: confirm whether these in-repo dates equal the first *public push*
> date. If history was imported/squashed on 2026-06-18, the true public
> disclosure could be the same day or later — but assume 2026-06-18 as the
> conservative bar date until proven otherwise.

---

## 4. Inventorship (get this right — it is a validity issue)

US patents are invalid if inventorship is wrong. List **every person who
contributed to the conception** of each invention's novel elements (not people
who only implemented under direction, and not the AI tooling). This differs
per invention. Counsel will finalize; engineering should provide:

- [ ] Named inventors for Invention 1: ____________________
- [ ] Named inventors for Invention 2: ____________________
- [ ] Named inventors for Invention 3: ____________________
- [ ] Assignment status (who owns it — the company? confirm employee IP
      assignment agreements are signed): ____________________

---

## 5. Preliminary prior-art notes (informal — not a clearance search)

A professional search ($1–3K) is still required before converting. Early flags:

- **Invention 1:** Generic **hash-chained, signed, tamper-evident audit logs are
  well-known and patented** — e.g., USPTO 9,338,013 / 10,027,473 / 11,032,065 /
  11,849,023 ("Verifiable redactable audit log"), and OSS like
  NousResearch/hermes-agent's SHA-256 hash-chained action log. **Do not claim the
  chain itself.** The defensible novelty is the *combination*: signing
  **staged-rollout learning updates** (canary→half→full `stage_fraction`) +
  **byte-exact cross-language (Python-producer / Rust-verifier) canonicalization**
  enabling an *external* auditor to verify which learning mutations reached which
  fleet cohort without code access. Claims must be drafted around that combination.
- **Invention 2:** Closest art is the academic literature on self-improving
  agents, evolutionary/quality-diversity search, and verifier ensembles
  (e.g., Darwin-Gödel-Machine-style work; Multi-Agent Verification,
  arXiv:2502.20379). Novelty hinges on the **calibration-discrimination interlock
  that freezes-and-resumes learning** and the **snapshot-replay regression
  detector that needs no agent re-execution or LLM calls**. Search these
  specifically.
- **Invention 3:** Search RAG access control, multi-tenant memory governance, and
  MCP/agent-interop memory. Novelty hinges on **symmetric write-side scope gating
  (anti-memory-poisoning)** + **hard retrieval-layer scope filtering** for
  *heterogeneous third-party* agents on a shared learning plane.

Search resources: Google Patents, USPTO Patent Public Search (ppubs.uspto.gov),
Espacenet, Lens.org, plus arXiv/Semantic Scholar for the ML art.

---

## 6. Use a patent attorney (strong recommendation)

These are software/AI inventions where **§101 subject-matter eligibility
(*Alice*)** is the main risk: claims must recite a concrete technical
improvement, not an abstract idea. Invention 1 is the easiest to frame
(cryptographic verification = concrete); Inventions 2 and 3 need careful drafting
to avoid "abstract idea" rejections. A registered practitioner with **AI/ML +
post-*Alice*** experience is worth it. Provisionals can be filed pro se to lock
the date cheaply, but have counsel review/redraft before the non-provisional.

---

## 7. Your checklist

- [ ] Confirm true first-public-disclosure date with counsel (foreign-rights triage)
- [ ] Stop further public disclosure of these mechanisms until provisionals filed
- [ ] Create USPTO.gov + Patent Center account; get Customer Number
- [ ] Determine entity size (micro / small / large)
- [ ] Confirm inventorship + assignment for each invention (§4)
- [ ] Engage a patent attorney (AI/ML, §101-aware)
- [ ] File 3 provisionals using the disclosure memos as specifications + draft claims + drawings
- [ ] Save filing receipts (priority dates)
- [ ] Docket 12-month non-provisional / PCT deadlines (T-6/T-3/T-1 reminders)
- [ ] Commission professional prior-art search before converting
- [ ] Decide which to convert to non-provisional (and whether any PCT route survives)
