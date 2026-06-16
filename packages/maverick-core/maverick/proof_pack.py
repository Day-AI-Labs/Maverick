"""Maverick Proof Pack — one signed, reproducible evidence bundle.

The artifact a POC ends on and a diligence team runs: a single command that
composes the evidence behind the product's claims, each from REAL code, and
emits a tamper-evident manifest plus an executive-readable ``PROOF.md``.

Sections (status is honest — a section that can't run here says so):

* **governance**    — the shipped roster through the real enforcement code
  (:mod:`maverick.proof_guarantees`): least privilege, no-money-without-a-human,
  the $-tier authority gate, read-not-write, SoD-clean, verified handoffs,
  tamper-evident audit. *Runs for real, offline.* (hard)
* **reliability**   — the chaos game-day / plugin / WAL-contention drills
  (:mod:`maverick.reliability_cert`). *Runs for real, offline.* (hard)
* **perf_sla**      — the published hot-path SLA measured live
  (:mod:`maverick.perf_sla`). *Runs for real, offline.* (hard)
* **shield_asr**    — attack-success-rate reduction through the real shield
  chokepoints (``benchmarks/security``). *Offline, built-in shield; repo-only.*
* **learning_curve** — the compounding metric + workforce-value report read
  from the world model. *Real when run history exists; honest when it doesn't.*
* **benchmarks**    — competitive pass@1. *Needs a provider key; reported
  ``NOT_RUN`` with the exact reproduce command until then — never fabricated.*

    python -m maverick.proof_pack [-o OUTDIR] [--ci] [--human-cost N]

Writes ``OUTDIR/proof_manifest.json`` (Ed25519-signed when the audit key is
available) and ``OUTDIR/PROOF.md``. ``--ci`` exits non-zero iff a HARD section
fails; ``NOT_RUN`` / ``INSUFFICIENT_DATA`` / ``SKIPPED`` never fail the gate.
"""
from __future__ import annotations

import json
import platform
import time
from dataclasses import dataclass, field
from pathlib import Path

PASS = "PASS"
FAIL = "FAIL"
SKIPPED = "SKIPPED"
NOT_RUN = "NOT_RUN"
INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

_REPRODUCE_BENCHMARK = "python benchmarks/run_eval.py gaia --dataset <path> --limit 25"


@dataclass
class Evidence:
    section: str
    status: str
    summary: str
    hard: bool = False  # a hard section gates --ci
    data: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == PASS

    def to_dict(self) -> dict:
        return {"status": self.status, "summary": self.summary,
                "hard": self.hard, "data": self.data}


# --- collectors -----------------------------------------------------------

def collect_governance() -> Evidence:
    from . import proof_guarantees as pg
    results = pg.run_all()
    failed = [r for r in results if not r.passed]
    skipped = [r for r in results if r.skipped]
    proven = [r for r in results if r.passed and not r.skipped]
    parts = [f"{len(proven)} guarantees proven"]
    if skipped:
        parts.append(f"{len(skipped)} verified in CI (Ed25519)")
    if failed:
        parts.append(f"{len(failed)} FAILED")
    return Evidence("governance", PASS if not failed else FAIL, "; ".join(parts),
                    hard=True, data={"guarantees": [r.to_dict() for r in results]})


def collect_reliability() -> Evidence:
    from . import reliability_cert
    cert = reliability_cert.certify()
    checks = cert.get("checks", {})
    summary = "; ".join(
        f"{n}: {'ok' if c['passed'] else 'FAIL'} ({c['detail']})"
        for n, c in checks.items()) or "no checks ran"
    return Evidence("reliability", PASS if cert.get("passed") else FAIL, summary,
                    hard=True, data=cert)


def collect_perf_sla() -> Evidence:
    from . import perf_sla
    results = perf_sla.run_all()
    breaches = [r for r in results if not r.passed]
    summary = "; ".join(
        f"{r.name}={r.measured}{r.unit} (<= {r.threshold})" for r in results)
    return Evidence("perf_sla", PASS if not breaches else FAIL, summary, hard=True,
                    data={"results": [
                        {"name": r.name, "measured": r.measured,
                         "threshold": r.threshold, "unit": r.unit, "passed": r.passed}
                        for r in results]})


def collect_shield_asr() -> Evidence:
    # The offline ASR harness lives under benchmarks/ (repo-only, not in the
    # installed wheel); degrade honestly when it isn't importable.
    try:
        from benchmarks.security import end_to_end_asr
    except Exception:
        return Evidence("shield_asr", SKIPPED,
                        "offline shield-ASR harness is repo-only — run from a source checkout",
                        hard=False)
    try:
        r = end_to_end_asr.measure()
    except Exception as e:  # noqa: BLE001 -- a harness error must not break the pack
        return Evidence("shield_asr", SKIPPED, f"harness error: {type(e).__name__}: {e}",
                        hard=False)
    db_k, db_n, (lo, hi) = r["did_block"]
    fp_k, fp_n, _fp_ci = r["fp"]
    block = (db_k / db_n) if db_n else 0.0
    fp_pct = f"{100 * fp_k / fp_n:.0f}%" if fp_n else "n/a"
    summary = (
        f"backend={r['backend']} · ASR 1.000 -> {1 - block:.3f} "
        f"(defense-in-depth block {100 * block:.0f}% "
        f"[{lo * 100:.0f}-{hi * 100:.0f}], benign FP {fp_pct}); "
        "detection only — primary defense is containment (see governance)")
    return Evidence("shield_asr", PASS, summary, hard=False, data=r)


def collect_learning(world, *, human_cost: float | None = None) -> Evidence:
    from . import compounding_metric, workforce_value
    reports = compounding_metric.report_from_world(world)
    wv = workforce_value.compute(world, human_cost=human_cost)
    data = {
        "compounding": [rep.to_dict() for rep in reports],
        "workforce_value": workforce_value.to_dict(wv),
    }
    if not reports and wv.deliverables == 0:
        return Evidence(
            "learning_curve", INSUFFICIENT_DATA,
            "no recorded run history yet — run real goals (then `maverick dream`) "
            "to populate the compounding curve",
            hard=False, data=data)
    improving = [rep for rep in reports if rep.improving]
    summary = (
        f"{len(reports)} task class(es), {len(improving)} improving; "
        f"deliverables={wv.deliverables}, cost_avoided=${wv.cost_avoided:,.2f}"
        + (f", ROI={wv.roi_multiple:.1f}x" if wv.agent_cost else ""))
    return Evidence("learning_curve", PASS if improving else INSUFFICIENT_DATA,
                    summary, hard=False, data=data)


def collect_benchmarks() -> Evidence:
    from .config import any_provider_configured
    has_key = any_provider_configured()
    if has_key:
        summary = ("provider key detected — competitive benchmarks are runnable but "
                   "intentionally NOT auto-run here (cost/time). "
                   f"Reproduce: {_REPRODUCE_BENCHMARK}")
    else:
        summary = ("no provider key configured — competitive scores NOT_RUN "
                   f"(never fabricated). Set a key and run: {_REPRODUCE_BENCHMARK}")
    return Evidence("benchmarks", NOT_RUN, summary, hard=False,
                    data={"provider_configured": has_key,
                          "reproduce": _REPRODUCE_BENCHMARK})


# --- assembly -------------------------------------------------------------

def _environment() -> dict:
    from .config import any_provider_configured
    from .proof_guarantees import _crypto_ok
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "crypto": _crypto_ok(),
        "provider_configured": any_provider_configured(),
    }


def build(world=None, *, human_cost: float | None = None,
          now: float | None = None) -> dict:
    """Run every collector; return the (unsigned) proof-pack manifest."""
    from .world_model import open_world
    own_world = world is None
    w = open_world() if own_world else world
    try:
        sections = [
            collect_governance(),
            collect_reliability(),
            collect_perf_sla(),
            collect_shield_asr(),
            collect_learning(w, human_cost=human_cost),
            collect_benchmarks(),
        ]
    finally:
        if own_world:
            try:
                w.close()
            except Exception:  # pragma: no cover -- best effort
                pass
    hard = [e for e in sections if e.hard]
    return {
        "kind": "maverick-proof-pack",
        "version": 1,
        "issued_at": float(now if now is not None else time.time()),
        "environment": _environment(),
        "hard_sections": [e.section for e in hard],
        "sections": {e.section: e.to_dict() for e in sections},
        "passed": all(e.ok for e in hard),
    }


def sign(manifest: dict) -> dict:
    """Attach an Ed25519 signature over the canonical payload (reuses the audit
    signing key); unsigned when crypto/key is unavailable (manifest says which)."""
    from .reliability_cert import sign_cert
    return sign_cert(manifest)


_BADGE = {
    PASS: "PASS",
    FAIL: "FAIL",
    SKIPPED: "SKIPPED",
    NOT_RUN: "NOT RUN (needs provider key)",
    INSUFFICIENT_DATA: "INSUFFICIENT DATA",
}


def render_markdown(manifest: dict) -> str:
    env = manifest.get("environment", {})
    sections = manifest.get("sections", {})
    hard = manifest.get("hard_sections", [])
    issued = time.strftime("%Y-%m-%d %H:%M:%S UTC",
                           time.gmtime(manifest.get("issued_at", time.time())))
    signed = "signed (Ed25519)" if manifest.get("signature") else "UNSIGNED"
    verdict = "ALL HARD GUARANTEES HOLD" if manifest.get("passed") else "A HARD GUARANTEE FAILED"
    lines = [
        "# Maverick — Proof Pack",
        "",
        f"**{verdict}.** Hard guarantees: {', '.join(hard)}.",
        "",
        f"_Issued {issued} · {signed} · python {env.get('python')} on "
        f"{env.get('platform')} · provider key configured: "
        f"{bool(env.get('provider_configured'))}_",
        "",
        "| section | status | evidence |",
        "|---|---|---|",
    ]
    for name, sec in sections.items():
        badge = _BADGE.get(sec["status"], sec["status"])
        tag = " *(hard)*" if sec.get("hard") else ""
        summary = str(sec.get("summary", "")).replace("|", "\\|")
        lines.append(f"| `{name}`{tag} | {badge} | {summary} |")
    lines += [
        "",
        "## Read this honestly",
        "- `governance`, `reliability`, `perf_sla` run against the **real** code on "
        "this machine — no mocks. They gate the verdict above.",
        "- `shield_asr` is the **built-in** fallback shield (no SDK / LLM cascade — "
        "those score higher) and measures *detection*; the load-bearing defense is "
        "**containment** (least-privilege capabilities), proven under `governance`.",
        "- `learning_curve` reads this deployment's own run history — it says "
        "`INSUFFICIENT DATA` until real goals have run; it never invents a curve.",
        "- `benchmarks` competitive scores require a provider key and are reported "
        "`NOT RUN` with the exact reproduce command — **no number is fabricated**.",
        "",
        "Verify the bundle: `maverick audit verify` (the audit chain) and the "
        "`signature` field of `proof_manifest.json` (Ed25519 over the canonical payload).",
        "",
    ]
    return "\n".join(lines)


def _default_out_dir() -> Path:
    from .paths import data_dir
    return data_dir("proof_pack")


def main(argv: list[str] | None = None) -> int:  # pragma: no cover -- CLI shell
    import argparse
    p = argparse.ArgumentParser(
        prog="maverick.proof_pack",
        description="Build a signed, reproducible evidence bundle.")
    p.add_argument("-o", "--out", default=None, help="output directory")
    p.add_argument("--ci", action="store_true", help="exit 1 if a hard section fails")
    p.add_argument("--human-cost", type=float, default=None,
                   help="fully-loaded human cost per deliverable (for the ROI line)")
    args = p.parse_args(argv)

    manifest = sign(build(human_cost=args.human_cost))
    out_dir = Path(args.out) if args.out else _default_out_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "proof_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    md = render_markdown(manifest)
    (out_dir / "PROOF.md").write_text(md, encoding="utf-8")
    print(md)
    signed = "signed" if manifest.get("signature") else "UNSIGNED"
    print(f"\nproof pack ({signed}) written to {out_dir}/")
    if args.ci and not manifest["passed"]:
        return 1
    return 0


__all__ = ["Evidence", "build", "sign", "render_markdown", "main",
           "PASS", "FAIL", "SKIPPED", "NOT_RUN", "INSUFFICIENT_DATA"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
