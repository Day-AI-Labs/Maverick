"""Backwards-compat tooling: ``maverick migrate`` (roadmap: 2027 H2 distribution).

Upgrades change what config means; this is the tool that walks an existing
``~/.maverick/config.toml`` forward. Three honest pieces:

* **Advisories** — real, currently-known migration paths (e.g. the Twilio
  WhatsApp adapter → the first-party Cloud API adapter). Advisories never
  rewrite config; they tell the operator what to change and why.
* **Config lint** — unknown top-level sections (typos: ``[budgets]`` for
  ``[budget]``) flagged against the known-section table, since a misspelled
  section silently no-ops and the operator thinks the knob is on.
* **Rewrites** — mechanical key renames, applied only with ``--apply`` and
  only after a timestamped backup of the config file. The rewrite table is
  empty today — no key has been renamed yet — but the machinery (backup,
  atomic write, stamp) is what a 2.0 rename lands on.

Dry-run is the default; nothing is written without ``--apply``, and nothing
is ever written without a backup.
"""
from __future__ import annotations

import logging
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

# Top-level config sections the runtime actually reads. A section outside
# this table is almost always a typo that silently no-ops.
# Every top-level section some runtime reader consumes. Enumerated from the
# load_config().get("<section>") call sites across the packages (platform-test
# finding: this list held 44 names while the runtime reads ~90, so `migrate`
# told users that wizard-written sections like [models] / [capabilities] /
# [security] "silently do nothing" -- advice that would delete live config).
# When adding a new config section, add it here or migrate will lint it.
KNOWN_SECTIONS = frozenset({
    "a2a", "adaptive_compute", "agent", "agent_trust", "analytics", "approval",
    "approval_delegation", "attachments", "audit", "auth", "autonomy",
    "deployment",
    "benchmark", "billing", "budget", "cache", "calendar", "calibration",
    "capabilities", "catalogs", "channels", "coding", "compaction",
    "compliance", "computer_use", "consequence", "containment", "context",
    "credit", "data_engine",
    "dashboard", "director", "durable", "ebpf_monitor", "effort", "egress",
    "emergent_codec", "emergent_protocol",
    "email", "embedded", "encryption", "energy", "enterprise", "erp",
    "experience", "features", "federation", "finance", "github",
    "governance", "grpc", "grpc_dispatch", "intake", "kms", "knowledge",
    "langchain", "latency", "limits", "local_first", "local_runtime",
    "logging", "lsp", "mcp_registries", "mcp_servers", "memory",
    "model_proxy", "models", "notifications", "observability", "obsidian",
    "operations_scientist",
    "perf", "persona", "planning", "plugins", "privacy",
    "provider_failover", "providers", "queue", "quotas", "reflexion",
    "retention", "role_assignments", "roles", "routing", "safety",
    "sandbox", "screening", "search", "security", "self_learning",
    "session_providers", "sharing", "shield", "skill_synthesis", "skills",
    "system", "telemetry", "template_registries", "tenancy", "thinking",
    "tools", "tui", "verification", "voice", "webhooks", "workspace",
    "world_model",
})


@dataclass
class Finding:
    kind: str          # "advisory" | "lint" | "rewrite"
    id: str
    message: str
    applied: bool = False


@dataclass
class MigrationReport:
    findings: list[Finding] = field(default_factory=list)
    backup_path: Path | None = None
    wrote: bool = False
    apply_requested: bool = False

    @property
    def clean(self) -> bool:
        return not self.findings


def _advisory_whatsapp_cloud(cfg: dict) -> Finding | None:
    channels = cfg.get("channels") or {}
    wa = channels.get("whatsapp") or {}
    if wa.get("enabled") and not (channels.get("whatsapp_cloud") or {}).get("enabled"):
        return Finding(
            "advisory", "whatsapp-twilio-to-cloud",
            "[channels.whatsapp] rides Twilio's Business API (per-message cost, "
            "third-party webhooks). The first-party Meta Cloud API adapter "
            "([channels.whatsapp_cloud]) has no middleman; see "
            "maverick_channels/whatsapp_cloud.py for the four credentials it "
            "needs. The Twilio adapter keeps working — migrate when ready.",
        )
    return None


def _lint_unknown_sections(cfg: dict) -> list[Finding]:
    out = []
    for section in sorted(cfg):
        if not isinstance(cfg.get(section), dict):
            continue
        if section not in KNOWN_SECTIONS:
            close = _closest(section)
            hint = f" (did you mean [{close}]?)" if close else ""
            out.append(Finding(
                "lint", f"unknown-section-{section}",
                f"[{section}] is not a section the runtime reads{hint}; "
                "it silently does nothing.",
            ))
    return out


def _closest(name: str) -> str | None:
    import difflib
    matches = difflib.get_close_matches(name, KNOWN_SECTIONS, n=1, cutoff=0.75)
    return matches[0] if matches else None


# (old_dotted_key, new_dotted_key) — mechanical renames applied by --apply.
# Empty today: no config key has been renamed yet. A 2.0 rename lands here.
REWRITES: list[tuple[str, str]] = []


def _apply_rewrites(cfg: dict) -> list[Finding]:
    findings = []
    for old, new in REWRITES:  # pragma: no cover -- table is empty today
        old_parts, new_parts = old.split("."), new.split(".")
        node = cfg
        for p in old_parts[:-1]:
            node = node.get(p) or {}
        if old_parts[-1] in node:
            value = node.pop(old_parts[-1])
            dst = cfg
            for p in new_parts[:-1]:
                dst = dst.setdefault(p, {})
            dst.setdefault(new_parts[-1], value)
            findings.append(Finding("rewrite", f"rename-{old}",
                                    f"renamed {old} -> {new}", applied=True))
    return findings


def migrate(config_path: Path | None = None, *, apply: bool = False) -> MigrationReport:
    """Inspect (and with ``apply=True``, mechanically migrate) the config.

    Never writes without a timestamped backup; advisory/lint findings are
    informational either way.
    """
    try:
        import tomllib  # 3.11+
    except ModuleNotFoundError:  # Python 3.10
        import tomli as tomllib  # type: ignore[no-redef]

    if config_path is None:
        from .config import config_path as active_config_path
        config_path = active_config_path()
    config_path = Path(config_path)
    report = MigrationReport(apply_requested=apply)
    if not config_path.exists():
        report.findings.append(Finding(
            "lint", "no-config",
            f"no config at {config_path} — run `maverick init` first."))
        return report
    try:
        cfg = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as e:
        report.findings.append(Finding("lint", "unparseable", f"cannot parse config: {e}"))
        return report

    adv = _advisory_whatsapp_cloud(cfg)
    if adv:
        report.findings.append(adv)
    report.findings.extend(_lint_unknown_sections(cfg))

    rewrites = _apply_rewrites(cfg) if apply else []
    report.findings.extend(rewrites)
    if apply and any(f.applied for f in rewrites):  # pragma: no cover -- empty table
        backup = config_path.with_name(
            f"{config_path.name}.bak-{time.strftime('%Y%m%d-%H%M%S')}")
        shutil.copy2(config_path, backup)
        report.backup_path = backup
        _write_toml(config_path, cfg)
        report.wrote = True
    return report


def _write_toml(path: Path, cfg: dict) -> None:  # pragma: no cover -- no rewrites yet
    """Minimal TOML writer for the rewrite path (sections of scalar/list values)."""
    lines: list[str] = []
    scalars = {k: v for k, v in cfg.items() if not isinstance(v, dict)}
    for k, v in scalars.items():
        lines.append(f"{k} = {_toml_value(v)}")
    for section, table in cfg.items():
        if not isinstance(table, dict):
            continue
        lines.append(f"\n[{section}]")
        for k, v in table.items():
            if isinstance(v, dict):
                lines.append(f"\n[{section}.{k}]")
                for kk, vv in v.items():
                    lines.append(f"{kk} = {_toml_value(vv)}")
            else:
                lines.append(f"{k} = {_toml_value(v)}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _toml_value(v) -> str:  # pragma: no cover -- exercised via _write_toml
    import json
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    return json.dumps(str(v))


def render(report: MigrationReport) -> str:
    if report.clean:
        return "config is current: no migrations, advisories, or lint findings."
    lines = []
    for f in report.findings:
        tag = {"advisory": "ADVISE", "lint": "LINT", "rewrite": "REWROTE" if f.applied else "RENAME"}[f.kind]
        lines.append(f"[{tag}] {f.message}")
    if report.backup_path:
        lines.append(f"backup: {report.backup_path}")
    if not report.wrote:
        # Distinguish "ran --apply but there was nothing to mechanically
        # rewrite" from a plain dry run -- both used to print the identical
        # "(dry run …)" line, so an operator could not tell their --apply was
        # accepted (user-testing finding).
        if report.apply_requested:
            lines.append("(--apply: no mechanical rewrites were needed)")
        else:
            lines.append("(dry run — nothing was written; re-run with --apply to migrate)")
    return "\n".join(lines)


__all__ = ["migrate", "render", "MigrationReport", "Finding", "KNOWN_SECTIONS", "REWRITES"]
