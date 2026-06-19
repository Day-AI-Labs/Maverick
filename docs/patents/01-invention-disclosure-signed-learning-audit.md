# Invention Disclosure 1 — Tamper-Evident, Cross-Language-Verifiable Audit Trail for Staged Machine-Learning Capability Rollouts

> Not legal advice. Engineering disclosure prepared for patent counsel, 2026-06-19.
> Repo: `Day-AI-Labs/Maverick`. Public disclosure date (conservative): 2026-06-18.

## Administrative

- **Working title:** Tamper-evident, externally verifiable audit trail for staged machine-learning capability rollouts in an autonomous agent.
- **Inventors:** _[TO BE COMPLETED — everyone who conceived the novel combination]_
- **Assignee:** _[Day AI Labs, Inc. — confirm]_
- **Public disclosure:** source public since ~2026-06-18 (see `00-...audit.md`).

## 1. Field

Governance and auditability of self-modifying AI agents; cryptographic
verification of learning/model-capability updates; cross-language audit
verification.

## 2. The problem

A self-improving agent mutates its own behavior over time — it promotes, retires,
and quarantines learned "skills"/capabilities, and rolls them out across a fleet
of agents in stages. In regulated or enterprise settings, an operator (or an
*external* third-party auditor with no access to the agent's source or runtime)
must be able to prove, after the fact:

1. *Which* learning mutations were applied,
2. *In what order*,
3. *To which fraction of the fleet* (canary vs. half vs. full), and
4. that the record has **not been altered or reordered**,

— and to do all of this **independently**, using a tool that does not trust the
agent that produced the log.

Generic tamper-evident logging (hash chains, signed logs) is known and patented
(see prior-art notes). Two gaps remain unsolved by that art:

- **(A)** Existing audit logs record *actions/decisions*, not the *staged
  rollout of self-modifications* with the cohort fraction each stage reached.
- **(B)** Independent verification normally requires re-running the *same*
  serializer that produced the log. If the producer is Python and the auditor's
  trusted verifier is a different language/runtime, the hashes won't match unless
  the serialization is byte-identical — which standard JSON libraries are **not**
  across languages (spacing, number formatting, non-ASCII/`ensure_ascii`,
  surrogate handling all differ).

## 3. Summary of the invention

A system in which (i) each self-modification of a learning agent is emitted as a
**staged-rollout audit record** carrying the rollout cohort fraction
(`stage_fraction`) and phase, (ii) the records form a signed hash chain, and
(iii) the chain is **independently verifiable by a second-language verifier**
through a **byte-exact canonicalization scheme** that reproduces the producer's
serialization deterministically across runtimes — so an external auditor's tool
re-derives each record's hash and checks each signature without trusting, or
sharing code with, the producer.

The novel combination has three cooperating parts:

### 3.1 Staged-rollout learning-update records
Each learning mutation is gated behind a staged rollout (e.g., canary 10% → 50% →
100%) and **each stage** emits a signed audit record whose payload includes the
candidate identity, the `stage_fraction` reached, and the phase. The audit chain
therefore encodes a *cryptographically sequenced* history of how a self-modification
propagated across the fleet, including rollbacks.

Evidence: `packages/maverick-core/maverick/learning_rollout.py:104-131`
(staged promotion records a `LEARNING_UPDATE` audit event per stage, fail-safe so
audit failure degrades to no-op rather than bypassing governance).

### 3.2 Durable, key-rotatable signed hash chain
Each record stores:
- `prev_hash` — hex SHA-256 linking to the prior record,
- `hash` — SHA-256 over the canonicalized payload (excluding `hash`/`sig`),
- `sig` — an Ed25519 signature over the **raw 32 hash bytes** (not the hex text),
- `key_id` — a 16-hex-char identifier (SHA-256 of the public key, truncated)
  carried **per record**, enabling key rotation without re-signing history.

Durability ordering: canonicalize → hash → sign → write+`fsync` → only then
advance the in-memory chain head, so a crash mid-write cannot fork the chain.

Evidence: `packages/maverick-core/maverick/audit/signing.py:135-156`
(`key_id` derivation, rotation) and `:271-310` (write ordering, prev_hash,
sign-over-bytes, fsync-before-advance).

### 3.3 Cross-language byte-exact canonicalization + independent verifier
A second-runtime verifier (Rust binary, intended for external auditors)
**re-derives** each record's hash by reproducing the Python producer's
`json.dumps(obj, sort_keys=True, ensure_ascii=True)` output **byte-for-byte**,
including:
- keys sorted by Unicode code point,
- `", "` / `": "` separators with spaces,
- `ensure_ascii` lowercase `\uXXXX` escapes (incl. control chars and DEL 0x7f),
- **UTF-16 surrogate-pair** rendering of astral code points, and
- **verbatim numeric literals** (arbitrary precision; `1e+30`, `-0.0`, big ints
  round-trip unchanged).

The verifier then checks `prev_hash` linkage and verifies the Ed25519 signature
over the raw hash bytes, looking up the per-record `key_id`'s public key (with a
strict 16-hex-char key_id regex to prevent path traversal), caching keys across
records. It **fails closed** on encrypted/sealed segments (detects magic bytes
`MVKAR1`/`MVKAR2`/`MVKTEN1` and refuses to treat them as plaintext).

Evidence: `rust/maverick-verify-audit/src/canonical.rs:1-119` (byte-exact
canonical JSON); `rust/maverick-verify-audit/src/lib.rs:62-64` (key_id
validation), `:76-236` (chain + signature verification, key cache), `:272-300`
(sealed-segment fail-closed). Parity is asserted against the live Python producer
in `rust/maverick-verify-audit/tests/parity.py` (tamper at row N → both
implementations fail at row N).

## 4. Why it is novel / non-obvious

- The **unit being signed is a staged self-modification with its cohort
  fraction**, not a generic action — directly answering "which learning update
  reached which fraction of the fleet, in order, provably."
- **Cross-runtime byte-exact verification** lets an *external* auditor verify
  with a tool that shares **no code** with the producer. This requires solving
  the cross-language JSON-canonicalization problem (surrogate pairs, verbatim
  numbers, `ensure_ascii`) — non-obvious and not provided by standard libraries
  (RFC 8785/JCS normalizes numbers differently; `serde_json` differs in spacing
  and escaping).
- **Signing the raw hash bytes** (not the serialized text) decouples signature
  verification from re-serialization fidelity at the signature step while still
  binding to canonical content via the hash.
- **Fail-closed on sealed segments** in the *external* verifier prevents an
  auditor from mistaking an encrypted segment for verified-clean plaintext.

## 5. Draft claims (sketch for counsel — not final)

**Independent (system).** A system comprising one or more processors and memory
storing instructions that cause the system to: (a) gate a modification to a
learned capability of an autonomous agent behind a multi-stage rollout across a
plurality of agent instances; (b) for each stage, emit an audit record comprising
an identifier of the modified capability, a cohort-fraction value indicating the
portion of the plurality to which the stage applied, a hash of a canonicalized
serialization of the record payload, a reference hash of the immediately
preceding record, and a digital signature computed over the raw bytes of said
hash; (c) persist each record durably before advancing an in-memory chain head;
and (d) expose the chain for verification by a verifier executing in a different
programming-language runtime that re-derives each record's hash by reproducing
the producer's serialization byte-for-byte.

**Independent (verification method).** A method comprising, at a verifier sharing
no executable code with a producer: reading a chain of audit records; for each
record, re-deriving an expected hash by serializing the record's payload using a
canonicalization that sorts keys by code point, emits ASCII-only escapes
including surrogate-pair encodings of astral code points, and preserves numeric
literals verbatim; comparing the expected hash to the stored hash; verifying the
stored hash matches the next record's preceding-hash reference; verifying a
signature over the raw hash bytes using a public key selected by a per-record key
identifier; and, upon detecting a sealed-segment marker, reporting the segment as
unverifiable rather than verified.

**Dependent (sketch).** ...wherein the cohort fractions form a monotonic
canary→partial→full sequence and a rollback emits a corresponding record;
...wherein the signature is Ed25519 and the key identifier is a truncated hash of
the public key enabling rotation without re-signing prior records; ...wherein the
canonicalization preserves scientific-notation and signed-zero literals;
...wherein the verifier caches public keys keyed by the per-record identifier;
...wherein durably persisting comprises fsync before advancing the chain head.

## 6. Alternatives / variations (broaden coverage)

- Signature scheme: Ed25519 → ECDSA/RSA/post-quantum (Dilithium).
- Hash: SHA-256 → SHA-3/BLAKE3.
- Verifier runtime: Rust → WASM/Go/JS; "different runtime" is the point.
- Chain → Merkle tree / accumulator for O(log n) inclusion proofs.
- Cohort fraction → arbitrary rollout policy descriptor (ring, percentage, tenant set).
- Canonicalization target → any deterministic producer serializer, not only CPython JSON.
- Sealed-segment handling → per-tenant keys; verifier with/without decryption authority.

## 7. Drawings to prepare

1. **Fig. 1** — end-to-end flow: learning mutation → staged rollout (canary/half/full)
   → per-stage record emission → chain.
2. **Fig. 2** — record structure (fields: candidate, stage_fraction, phase,
   prev_hash, hash, sig, key_id).
3. **Fig. 3** — durability ordering (canonicalize→hash→sign→write→fsync→advance).
4. **Fig. 4** — cross-language verification: Python producer vs. Rust verifier,
   byte-exact canonicalization box, pass/fail at row N.
5. **Fig. 5** — key rotation timeline (records under key A then key B, both
   verifiable).

## 8. Evidence index (file:line)

- `packages/maverick-core/maverick/learning_rollout.py:104-131`
- `packages/maverick-core/maverick/audit/signing.py:135-156, 186-200, 271-310, 317-365`
- `rust/maverick-verify-audit/src/canonical.rs:1-119`
- `rust/maverick-verify-audit/src/lib.rs:62-64, 76-236, 272-300`
- `rust/maverick-verify-audit/tests/parity.py` (cross-language parity test)
