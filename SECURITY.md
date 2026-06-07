# Security policy

Maverick is an AI agent that executes shell commands, reads files, and
calls external APIs. Vulnerabilities here can affect any host running it.
We take that seriously.

## Reporting

**Do not file public GitHub issues for vulnerabilities.** Use one of:

1. **GitHub Security Advisories** (preferred):
   https://github.com/Day-AI-Labs/Maverick/security/advisories/new
2. **Email**: `security@` the project's domain (or the maintainer's
   public email on their GitHub profile if no domain is set up).

Include:

- Affected version (`maverick version` output)
- Reproduction steps
- Impact assessment (what an attacker can achieve)
- Proposed fix, if you have one

## Coordinated disclosure

We follow a **90-day coordinated disclosure window** from initial report.
For unpatched critical issues we may extend by mutual agreement.

Public disclosure (advisory + CVE) happens after a patched release is
available. We credit reporters in the advisory unless they prefer to
stay anonymous.

## Supported versions

Only the latest minor release receives security fixes. Older releases
are not patched; users on `v0.1.x` should upgrade to the latest tagged
release.

| Version | Supported |
|---------|-----------|
| v0.2.x  | Yes (current) |
| v0.1.x  | No        |

## Threat model

Out of scope (will not be treated as vulns):

- LLM hallucinations / prompt-injection effects the user explicitly
  authorized via tool calls (e.g. `maverick` runs `rm` because the
  user told it to).
- Anything that requires already-arbitrary code execution on the host.

In scope:

- Privilege escalation beyond the sandbox backend (local subprocess,
  Docker `--network=none`, SSH-as-user).
- Prompt-injection chains that bypass `maverick-shield` (e.g. tool
  output injection, image vision-block injection, cross-turn replay).
- Webhook spoofing / signature bypass on channel adapters (Telegram,
  Twilio).
- Secret exfiltration via skill bodies, MCP tool descriptions, or
  plugin entry_points.
- Path traversal in attachments, skills, or world.db paths.
- DoS on the local FastAPI dashboard.

## Hardening tips

- Set `MAVERICK_DASHBOARD_TOKEN` on any VPS deployment exposed beyond
  `127.0.0.1`.
- Set `MAVERICK_PLUGINS_ALLOW` explicitly; the default is empty so
  pip-installed plugins do NOT auto-execute, but if you want to enable
  any, list them by name.
- Use `sandbox.backend = "docker"` for goals that run user-provided
  shell. Docker isolation is much stronger than the local subprocess
  backend.
- Rotate `ANTHROPIC_API_KEY` etc. on a schedule. Maverick reads from
  `~/.maverick/.env` (chmod 600).

## Execution posture (read this first)

The single most important thing to understand about Maverick's security:

> **By default, the agent executes model-generated shell commands. With the
> default `local` sandbox backend, those commands run directly on the host,
> and the safety Shield is an optional dependency that fails *open* if not
> installed.** A successful prompt injection on that configuration is host
> code execution.

This is a deliberate design trade-off (fast local iteration, no hard
dependency on the shield), not an oversight — but it means **the operator
chooses the blast radius**. Defense in depth, from outermost to innermost:

1. **Sandbox backend** — the real containment boundary. `local` = your host;
   `docker`/`podman` run each command in a throwaway container
   (`--network=none`, `--cap-drop=ALL`, `--security-opt=no-new-privileges`,
   `--pids-limit`); `firecracker`/`kubernetes`/`ssh` isolate further. The
   setup wizard defaults real installs to a container when one is available,
   and the kernel logs a one-time warning when it runs on `local` (louder
   when the shield is absent). **For any untrusted goal, use a container
   backend.**
2. **Agent Shield** (`maverick-shield`) — screens prompts, tool calls, and
   output. Optional and fail-open by design, so it is a *floor*, not a
   guarantee. Treat it as one layer, never the only one.
3. **Tool ACL + budget + killswitch** — `[tool_acl] denied_tools`, the
   `Budget` cap, and `~/.maverick/HALT` bound what a run can do and spend.

The consumer wizard (`maverick init`, "consumer" mode) fails closed: when no
container is available it **denies** the host-mutating tools (`shell`,
`write_file`, `apply_patch`) and runs the strictest shield profile.

## Security-relevant configuration

| Setting (env / config)                    | Effect                                                                 |
|-------------------------------------------|------------------------------------------------------------------------|
| `[sandbox] backend`                       | Execution isolation. `docker`/`podman` strongly recommended for untrusted goals. |
| `[sandbox] pids_limit` (default 512)      | Fork-bomb cap for container backends.                                  |
| `MAVERICK_SUPPRESS_SANDBOX_WARNING=1`     | Silences the unsandboxed-host warning (only set if you accept host execution). |
| `MAVERICK_DASHBOARD_TOKEN`                | Required for any non-loopback / proxied dashboard access (fail-closed). |
| `MAVERICK_PLUGINS_ALLOW`                  | Allowlist for plugin entry points (default empty = none auto-load).    |
| `MAVERICK_FETCH_ALLOW_PRIVATE=1`          | Disables the SSRF guard's private/metadata-IP block (do not set in prod). |
| `MAVERICK_MCP_TOKEN` / `MAVERICK_MCP_MAX_BODY` | Bearer auth (fail-closed) + request-body cap for the MCP HTTP transport. |
| `MAVERICK_A2A_TOKEN`                      | Bearer auth for the A2A task endpoint (off unless A2A is enabled).     |
| `[webhooks] secret` / `MAVERICK_WEBHOOK_SECRET` | HMAC secret for inbound webhooks; with no secret the receivers fail closed (401). |
| `SMS_BIND_HOST` / `WHATSAPP_BIND_HOST`    | Channel webhook bind address (default `127.0.0.1`; front with a proxy). |
| `*_ALLOWED_USER_IDS` (per channel)        | Mandatory default-deny sender allowlist for chat channels.             |

When in doubt, prefer the more restrictive setting: a container backend, an
explicit dashboard token, an empty plugin allowlist, and per-channel sender
allowlists.
