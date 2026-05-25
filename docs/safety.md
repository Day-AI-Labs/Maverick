# Safety

Maverick wraps its agent loop in [Agent Shield](https://github.com/texasreaper62/agent-shield) at three chokepoints:

1. **Input scan** — every user message goes through `shield.scan_input()` before the orchestrator sees it.
2. **Tool-call scan** — every `tool_use` request goes through `shield.scan_tool_call(name, args)` before the sandbox executes it.
3. **Output scan** — every final answer goes through `shield.scan_output()` before reaching the user.

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

Agent Shield covers (F1 0.988 on real-world benchmarks):

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

## When the shield is missing

Maverick still runs without `agent-shield` installed — it logs a startup warning and the scans become no-ops. This keeps the kernel useful as a research tool. For end-user installs, the wizard pulls in `agent-shield` by default.

To verify the shield is loaded:

```python
from maverick_shield import Shield
print(Shield().enabled)   # True if agent-shield is installed
```

## Privacy posture

- All Agent Shield detection runs **locally**. Nothing is sent to any external service.
- Your prompts go only to the LLM provider you chose during `maverick init`. If you pick Ollama, nothing leaves your machine.
- The world model (SQLite) lives in `~/.maverick/world.db`. Inspect, back up, or wipe it freely.
