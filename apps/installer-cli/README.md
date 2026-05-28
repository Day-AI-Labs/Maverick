# maverick-installer

The interactive setup wizard. Installed as part of the kernel's
`[installer]` extra:

```bash
pipx install 'maverick-agent[installer]'
maverick init
```

If the kernel is already installed without the extra:

```bash
pipx inject maverick-agent maverick-installer
```

A standalone `maverick-init` entry point is also exposed.

Walks through:

1. Deployment target (Desktop / Docker / VPS / Phone companion)
2. AI providers (Anthropic / OpenAI / OpenRouter / Ollama)
3. Per-role model picks
4. Safety profile (Strict / Balanced / Permissive / Off)
5. Sandbox backend
6. Budget caps
7. API keys

Writes `~/.maverick/config.toml` (0o600) and `~/.maverick/.env` (0o600).
