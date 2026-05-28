# Security policy

Maverick is an AI agent that executes shell commands, reads files, and
calls external APIs. Vulnerabilities here can affect any host running it.
We take that seriously.

## Reporting

**Do not file public GitHub issues for vulnerabilities.** Use one of:

1. **GitHub Security Advisories** (preferred):
   https://github.com/cdayAI/Maverick/security/advisories/new
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
