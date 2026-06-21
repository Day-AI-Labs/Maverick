# Safety

Lightwork wraps its agent loop in [Agent Shield](https://github.com/cdayAI/agent-shield) at three chokepoints:

1. **Input scan** — every user message goes through `shield.scan_input()` before the orchestrator sees it.
2. **Tool-call scan** — every `tool_use` request goes through `shield.scan_tool_call(name, args)` before the sandbox executes it.
3. **Output scan** — every final answer goes through `shield.scan_output()` before reaching the user.

All three chokepoints additionally run a **decode/defang pre-pass** (`maverick_shield/deobfuscate.py`): base64 / hex / percent-encoded payloads are decoded and Unicode homoglyphs (Cyrillic/Greek lookalikes NFKC leaves alone) plus zero-width/bidi chars are folded, then the detectors re-run over each variant — so an *encoded* `rm -rf /` is caught even when the literal surface form hides it. This is part of the **built-in** shield (not the optional SDK), is monotonic (it can only turn an allowed scan into a block, never the reverse), bounded against decode bombs, and fail-open. Escape hatch: `MAVERICK_SHIELD_NO_DECODE=1`.

## Profiles

| Profile | Block threshold | Use case |
|---|---|---|
| `strict` | medium | Sensitive data, enterprise, regulated industries |
| `balanced` | high | Recommended default for personal use |
| `permissive` | critical | Research / experimentation |
| `off` | — | Not recommended. Kernel-only mode for debugging. |

Set in `~/.maverick/config.toml`:

```toml
[safety]
profile = "balanced"
block_threshold = "high"
```

## What gets caught

The **full Agent Shield SDK** (`pip install agent-shield`, ~115 patterns, F1 0.988 on real-world benchmarks) covers the categories below. Without it, Lightwork falls back to a **built-in ~20-pattern** subset — the F1 number does NOT apply to the fallback. The categories below describe the full SDK:

- **Prompt injection** — system prompt overrides, ChatML/LLaMA delimiters, instruction hijacking
- **Role hijacking** — DAN mode, developer mode, persona attacks, jailbreaks
- **Data exfiltration** — prompt extraction, markdown image leaks, DNS tunneling, side-channel encoding
- **Tool abuse** — shell execution attempts, SQL injection, path traversal, sensitive file access
- **Social engineering** — identity concealment, urgency + authority, gaslighting, false pre-approval
- **Obfuscation** — Unicode homoglyphs, zero-width chars, Base64/hex/ROT13/leetspeak
- **Indirect injection** — RAG poisoning, tool output injection, email/document payloads
- **Visual deception** — hidden HTML/CSS content, LaTeX phantom commands
- **Multi-language attacks** — 19 languages including CJK, Arabic, Cyrillic, Hindi
- **AI phishing** — fake AI login, QR phishing, MFA harvesting
- **Sybil attacks** — coordinated fake agents, voting collusion
- **Side channels** — DNS exfiltration, timing-based encoding, beaconing

> **Obfuscation is no longer SDK-only.** The built-in shield's decode/defang
> pre-pass (above) covers base64/hex/percent/homoglyph/zero-width evasion on all
> three surfaces, so an encoded payload is decoded and re-scanned against the
> built-in rules even without the full SDK. The SDK still adds breadth (ROT13,
> leetspeak, the wider pattern set); the *decoding* layer is now always present.

## When the shield is missing

Two layers can be missing, and they degrade differently:

- **Full `agent-shield` SDK absent** (but the `maverick-shield` wrapper present): detection uses the **built-in** layer — ~20 high-impact rules, the decode/defang pre-pass, and a cheap-probe (regex + Unicode heuristics, optionally ensembled with a trained linear model via `[shield] probe_model`). The F1 0.988 SDK ruleset is forgone, but scans — including obfuscation-decoding — still run.
- **Shield wrapper absent entirely**: scans are **skipped (fail-open)** with a startup warning, per the kernel's "runs without the shield" rule.

The installer does **not** pull in `agent-shield` automatically — install it with `pip install agent-shield` for the full ruleset.

To verify the shield is loaded:

```python
from maverick_shield import Shield
print(Shield().enabled)   # True if agent-shield is installed
```

## Privacy posture

- All Agent Shield detection runs **locally**. Nothing is sent to any external service.
- Your prompts go only to the LLM provider you chose during `maverick init`. If you pick Ollama, nothing leaves your machine.
- The world model (SQLite) lives in `~/.maverick/world.db`. Inspect, back up, or wipe it freely.

## Enterprise mode (private / sensitive data)

The kernel ships fail-open and cloud-capable by design — right for a personal agent,
wrong the moment it handles PHI / PII / financial / regulated data. **Enterprise mode**
is one switch that flips those defaults to *fail-closed* and guarantees the property an
enterprise needs before it lets an agent touch sensitive data: **the data never leaves
your boundary.**

```toml
[enterprise]
mode = true
# Optional: extra self-hosted providers to treat as local (e.g. an internal vLLM
# fronted by a generic OpenAI-compatible provider).
local_providers = ["my-internal-vllm"]
```

Or set `MAVERICK_ENTERPRISE=1`, or pick it in `maverick init`. **Off by default.**

The simplest way to select the whole regulated posture is the **named deployment
profile**: `MAVERICK_PROFILE=enterprise` (or `[profile] name = "enterprise"`).
`enterprise` turns on enterprise mode *plus* the deployment-specific secure
defaults below in one knob; `standard` (the default) keeps the zero-config happy
path. Every individual control still has its own explicit override, and a
compliance floor can force any control on — both win over the profile. When the
posture is on:

| Control | Default kernel behavior | Enterprise mode |
|---|---|---|
| **LLM egress** | any configured provider (incl. cloud) sees the prompt | **pinned to local/self-hosted** (`ollama`/`vllm`/`tgi` or an allow-listed endpoint); a cloud-routed call raises `EgressBlocked` **before any prompt is sent**, and the denial is audited |
| **Consent** | `auto-approve` | `ask` (and therefore *deny* in non-interactive contexts) |
| **Capabilities** | opt-in | enforced (least privilege; sub-agents can only narrow their grant) |
| **Sandbox** | `local` host shell (warned) | **container-default** — a `local`/unset backend is upgraded to an available container runtime (docker → podman); if none is installed it fails closed rather than running `shell=True` on the host (`[sandbox] backend` / `require_container`) |
| **Plugins** | in-process, lockfile off | **subprocess isolation** (third-party plugins run out-of-process) + **lock-enforce** (version/content drift refused once a lockfile exists) (`[plugins] isolation` / `lock_policy`) |

The egress lock is enforced at the single LLM dispatch chokepoint (`maverick.llm.LLM.complete`),
so it covers every agent, role, and tool-driven model call. An explicit env/config setting
still wins per control, but the egress lock can never be satisfied by a cloud provider.

## Compliance posture (`maverick compliance`)

`maverick compliance` reports which GDPR + EU AI Act controls are active for your
deployment, mapped to the article each supports, and flags the opt-in controls that are
still off — with the exact knob to enable each:

| Control | Article(s) | Status / enable with |
|---|---|---|
| AI transparency disclosure | EU AI Act Art. 50 | on by default (channel server) |
| Audit logging (record-keeping) | EU AI Act Art. 12, GDPR Art. 30 | always on |
| Tamper-evident audit | EU AI Act Art. 12 | `[audit] sign = true` |
| Human oversight (consent) | EU AI Act Art. 14 | `MAVERICK_CONSENT_MODE=ask` or enterprise mode |
| Kill switch | EU AI Act Art. 14 | `~/.maverick/HALT` |
| Data-subject access & portability | GDPR Art. 15 & 20 | `maverick export-user` |
| Right to erasure | GDPR Art. 17 | `maverick erase` |
| Storage limitation (retention) | GDPR Art. 5(1)(e) | `[retention]` + `maverick retention enforce` |
| Data-egress control | GDPR Art. 32 / AI Act Art. 15 | `[enterprise] mode = true` |
| Secret/PII redaction in logs | GDPR Art. 25 & 32 | always on |
| Encryption at rest (memory + world-DB content) | GDPR Art. 32 | `[encryption] at_rest = true` (implied by enterprise mode) — see [encryption.md](encryption.md) |
| Log data minimization | GDPR Art. 5(1)(c) | `[privacy] anonymous = true` |

`--format json` emits the same for pipelines/SIEM. **This is control coverage, not a
legal attestation** — full GDPR / EU AI Act compliance also requires a DPA, ROPA (Art. 30
records), a DPIA, AI-Act risk classification, and review by qualified counsel.
