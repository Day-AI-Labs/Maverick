"""Compliance & governance CLI commands: soc2, enterprise, ropa, dpia, ai-act,
controls, hunt, remediate, assess, dsar.

Split out of cli/__init__.py; registered via import at the end of the package
__init__ so the @main.group/@main.command decorators fire on package import.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import click

from . import _soc2_posture_ready, main


@main.command("soc2")
@click.option("--json", "compact", is_flag=True,
              help="Emit compact single-line JSON (default: pretty, indent=2).")
def soc2(compact: bool) -> None:
    """Print a SOC 2 technical-posture snapshot as JSON.

    Serializes ``collect_soc2_evidence()`` -- which controls are ON in this
    deployment and whether the audit log verifies -- for auditors / CI /
    automation. The collector is fail-soft (it never raises), so this command
    always emits a JSON object. The command exits non-zero when required
    controls or audit-log checks are not in a SOC 2-ready state.
    """
    import json as _json

    from ..soc2 import collect_soc2_evidence
    evidence = collect_soc2_evidence()
    if compact:
        click.echo(_json.dumps(evidence, default=str))
    else:
        click.echo(_json.dumps(evidence, default=str, indent=2))
    if not _soc2_posture_ready(evidence):
        sys.exit(1)


# ----- Enterprise (regulated-deployment) posture -----------------------

@main.group("enterprise")
def enterprise_group() -> None:
    """Enterprise (regulated-deployment) posture."""


@enterprise_group.command("verify")
@click.option("--format", "fmt", type=click.Choice(["text", "json"]), default="text",
              help="Output format.")
@click.option("--require", "require", is_flag=True,
              help="Treat this as a deploy gate: exit non-zero unless every "
                   "boundary guarantee holds (same as setting "
                   "MAVERICK_REQUIRE_ENTERPRISE=1). Without it, the command still "
                   "exits non-zero on any failure but is advisory.")
def enterprise_verify(fmt: str, require: bool) -> None:
    """Actively verify the regulated-deployment guarantees (exits non-zero if any fail).

    Unlike 'maverick compliance' (which maps configured controls to articles),
    this *exercises* the load-bearing guarantees: it proves the egress lock
    refuses a cloud provider and that at-rest sealing round-trips on this box,
    upgrading "the flag is on" to "the boundary holds." Wire it into CI / a
    deploy gate the same way as 'maverick compliance --strict'.

    Pass --require to make it an explicit *preflight gate* (the same one the
    container/dashboard startup runs when MAVERICK_REQUIRE_ENTERPRISE=1): it
    prints a summary of which guarantees failed and exits non-zero so an unsafe
    deployment is blocked rather than merely reported.
    """
    from ..deployment import (
        _preflight_summary,
        all_passed,
        render_json,
        render_text,
        verify_deployment,
    )
    checks = verify_deployment()
    click.echo(render_json(checks) if fmt == "json" else render_text(checks))
    passed = all_passed(checks)
    if require and not passed:
        # Explicit deploy gate: surface which guarantees failed on stderr, the
        # same summary require_enterprise_or_die() raises at startup, and block.
        click.echo("", err=True)
        click.echo(_preflight_summary(checks), err=True)
    if not passed:
        sys.exit(1)


@main.command("ropa")
@click.option("--format", "fmt", type=click.Choice(["text", "json"]), default="text",
              help="Output format.")
@click.option("--output", "-o", type=click.Path(), default=None,
              help="Write to file (default stdout).")
def ropa_cmd(fmt: str, output) -> None:
    """Generate a GDPR Art. 30 record-of-processing scaffold for this deployment.

    Pre-fills the technical half from the live config and schema -- personal-data
    categories, recipients / international transfers (from the egress lock),
    retention, and the active Art. 32 security measures -- and marks the
    organizational fields (controller, DPO, lawful basis, purposes) for the
    controller to complete. A scaffold for a DPO to finish, not a legal
    attestation.
    """
    from ..ropa import generate_ropa, render_ropa_json, render_ropa_text
    record = generate_ropa()
    payload = render_ropa_json(record) if fmt == "json" else render_ropa_text(record)
    if output:
        try:
            fd = os.open(str(output), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload + "\n")
        except OSError as e:
            raise click.ClickException(f"could not write {output}: {e}") from e
        click.echo(f"wrote {output}")
    else:
        click.echo(payload)


@main.command("dpia")
@click.option("--format", "fmt", type=click.Choice(["text", "json"]), default="text",
              help="Output format.")
@click.option("--output", "-o", type=click.Path(), default=None,
              help="Write to file (default stdout).")
def dpia_cmd(fmt: str, output) -> None:
    """Generate a GDPR Art. 35 DPIA scaffold for this deployment.

    Pre-fills the processing description (consistent with 'maverick ropa') and a
    risk register of the agent-on-personal-data risks -- each mapped to the
    Maverick control that mitigates it and whether that control is active right
    now -- leaving necessity/proportionality and residual-risk sign-off to the
    controller. A scaffold for a DPO to finish, not a completed DPIA.
    """
    from ..dpia import generate_dpia, render_dpia_json, render_dpia_text
    dpia = generate_dpia()
    payload = render_dpia_json(dpia) if fmt == "json" else render_dpia_text(dpia)
    if output:
        try:
            fd = os.open(str(output), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload + "\n")
        except OSError as e:
            raise click.ClickException(f"could not write {output}: {e}") from e
        click.echo(f"wrote {output}")
    else:
        click.echo(payload)


@main.command("ai-act")
@click.option("--format", "fmt", type=click.Choice(["text", "json"]), default="text",
              help="Output format.")
def ai_act_cmd(fmt: str) -> None:
    """Classify this deployment under the EU AI Act (self-assessment).

    Reports the live Art. 50 transparency posture and hands you a checklist of
    the prohibited (Art. 5) and high-risk (Annex III) categories plus the
    obligations each tier triggers. A conversational agent that discloses it is
    AI is limited-risk by default -- but you must rule out those lists for your
    use case. A self-assessment aid, not a legal classification.
    """
    from ..ai_act import assess_ai_act, render_ai_act_json, render_ai_act_text
    report = assess_ai_act()
    click.echo(render_ai_act_json(report) if fmt == "json" else render_ai_act_text(report))


@main.command("controls")
@click.argument("query", nargs=-1, required=True)
@click.option("--limit", type=int, default=5, help="Max controls to return.")
def controls_cmd(query: tuple[str, ...], limit: int) -> None:
    """Find the privacy/security control(s) for a risk, with framework citations.

    Example: maverick controls vendor has no DPA
    """
    from ..controls import find_controls, render_control
    hits = find_controls(" ".join(query), limit=limit)
    if not hits:
        raise click.ClickException(f"no controls matched {' '.join(query)!r}")
    click.echo("\n".join(render_control(c) for c in hits))


@main.command("hunt")
@click.option("--format", "fmt", type=click.Choice(["text", "json"]), default="text",
              help="Output format.")
@click.option("--since", default=None, help="Only events on/after this UTC date (YYYY-MM-DD).")
@click.option("--until", default=None, help="Only events on/before this UTC date (YYYY-MM-DD).")
@click.option("--strict", is_flag=True,
              help="Exit non-zero if any attack signal is found (gate CI / monitoring).")
def hunt_cmd(fmt: str, since: str | None, until: str | None, strict: bool) -> None:
    """Hunt the audit trail for attacks by/against agents.

    Sweeps the audit log for security signals -- shield blocks (prompt
    injection), blocked egress (exfiltration attempts), capability/governance
    denials (escalation), the kill switch -- and reports them risk-ranked. With
    --strict, exits non-zero when any signal is present, so it can gate a
    monitoring job.
    """
    from ..threat_hunt import hunt, render_report_json, render_report_text
    report = hunt(all_days=(since is None and until is None), since=since, until=until)
    click.echo(render_report_json(report) if fmt == "json" else render_report_text(report))
    if strict and report.findings:
        raise click.ClickException(
            f"{len(report.findings)} attack signal type(s) found "
            f"(risk: {report.risk_rating})"
        )


@main.command("remediate")
@click.option("--apply", "do_apply", is_flag=True,
              help="Apply the auto-fixable remediations (needs enterprise mode + "
                   "[security] auto_fix opt-in).")
@click.option("--format", "fmt", type=click.Choice(["text", "json"]), default="text",
              help="Output format.")
def remediate_cmd(do_apply: bool, fmt: str) -> None:
    """Assess security posture and (bounded) auto-fix it.

    Reports control gaps + active breach signals and the remediation plan.
    Low-risk, reversible fixes to Maverick's OWN config are auto-applied with
    --apply -- but only under enterprise mode + a [security] auto_fix opt-in;
    everything behaviour-changing is proposed for a human. Every applied fix is
    audited and reports how to undo it.
    """
    from ..remediation import (
        apply_remediation,
        plan,
        render_plan_json,
        render_plan_text,
    )
    p = plan()
    click.echo(render_plan_json(p) if fmt == "json" else render_plan_text(p))
    if not do_apply:
        return
    click.echo("")
    applied_any = False
    for g in p.gaps:
        if not g.auto:
            continue
        res = apply_remediation(g, dry_run=False)
        if res.applied:
            applied_any = True
            click.echo(f"  applied: {g.title}  (undo: {res.undo})")
        else:
            click.echo(f"  skipped: {g.title}  ({res.reason})")
    if not applied_any:
        click.echo("  (nothing auto-applied)")


# ----- Compliance assessments (PIA / AIRA / vendor risk) ---------------

@main.group("assess")
def assess_group() -> None:
    """Conduct compliance assessments of a subject.

    Privacy: PIA, AIRA, vendor risk. Security: HIPAA, SOC 2, PCI DSS.
    Run 'maverick assess templates' for the full set.
    """


@assess_group.command("templates")
def assess_templates() -> None:
    """List the available assessment types."""
    from ..assessment import list_templates
    for t in list_templates():
        click.echo(
            f"  {t.type:12} {t.title}  "
            f"({t.framework}; {len(t.questions)} questions)"
        )


@assess_group.command("questions")
@click.argument("assessment_type")
@click.option("--format", "fmt", type=click.Choice(["text", "json"]), default="text",
              help="Output format.")
def assess_questions(assessment_type: str, fmt: str) -> None:
    """Print an assessment's questionnaire (so you -- or the agent -- can answer it)."""
    from ..assessment import get_template, render_questions_json, render_questions_text
    tpl = get_template(assessment_type)
    if tpl is None:
        raise click.ClickException(
            f"unknown assessment type {assessment_type!r}; see 'maverick assess templates'"
        )
    click.echo(render_questions_json(tpl) if fmt == "json" else render_questions_text(tpl))


@assess_group.command("score")
@click.argument("assessment_type")
@click.option("--subject", required=True,
              help="What is being assessed (the vendor / system / activity).")
@click.option("--answers", "answers_file", required=True,
              type=click.Path(exists=True),
              help="JSON {question_id: answer}; answer is yes/no/na/unknown "
                   "or {\"answer\":..., \"note\":...}.")
@click.option("--format", "fmt", type=click.Choice(["text", "json"]), default="text",
              help="Output format.")
@click.option("--no-save", is_flag=True, help="Don't persist the assessment.")
def assess_score(assessment_type: str, subject: str, answers_file: str,
                 fmt: str, no_save: bool) -> None:
    """Score a completed answer set into findings + a risk rating, and save it."""
    import json as _json

    from ..assessment import (
        AssessmentSession,
        get_template,
        render_result_json,
        render_result_text,
        save_session,
    )
    if get_template(assessment_type) is None:
        raise click.ClickException(
            f"unknown assessment type {assessment_type!r}; see 'maverick assess templates'"
        )
    try:
        raw = _json.loads(Path(answers_file).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise click.ClickException(f"could not read answers: {e}") from e
    if not isinstance(raw, dict):
        raise click.ClickException("answers file must be a JSON object {question_id: answer}")
    session = AssessmentSession(type=assessment_type, subject=subject)
    for qid, val in raw.items():
        answer = val.get("answer") if isinstance(val, dict) else val
        note = val.get("note", "") if isinstance(val, dict) else ""
        try:
            session.record(str(qid), str(answer), str(note))
        except (KeyError, ValueError) as e:
            raise click.ClickException(str(e)) from e
    result = session.evaluate()
    click.echo(render_result_json(result) if fmt == "json" else render_result_text(result))
    if not no_save:
        click.echo(f"\nsaved: {save_session(session)}")


@assess_group.command("list")
def assess_list() -> None:
    """List saved assessments, newest first."""
    from ..assessment import list_saved
    rows = list_saved()
    if not rows:
        click.echo("No saved assessments.")
        return
    for r in rows:
        click.echo(
            f"  {r['id']:20} {r['type']:12} {r['risk_rating']:8} "
            f"{r['findings']} finding(s)  {r['subject']}"
        )


@assess_group.command("show")
@click.argument("assessment_id")
@click.option("--format", "fmt", type=click.Choice(["text", "json"]), default="text",
              help="Output format.")
def assess_show(assessment_id: str, fmt: str) -> None:
    """Show a saved assessment by id."""
    import json as _json

    from ..assessment import AssessmentResult, Finding, load_saved, render_result_text
    data = load_saved(assessment_id)
    if data is None:
        raise click.ClickException(f"no saved assessment {assessment_id!r}")
    if fmt == "json":
        click.echo(_json.dumps(data, indent=2, default=str))
        return
    res = data["result"]
    result = AssessmentResult(
        type=res["type"], subject=res["subject"], risk_rating=res["risk_rating"],
        findings=[Finding(**f) for f in res["findings"]],
        answered=res["answered"], total=res["total"],
    )
    click.echo(render_result_text(result))


# ----- DSAR subject-data export ----------------------------------------

@main.group("dsar")
def dsar_group() -> None:
    """Data-subject access requests (GDPR Art. 15 / 20)."""


@dsar_group.command("export")
@click.option("--user", "user_id", required=True,
              help="The channel user_id (subject) to export.")
@click.option("--tenant", default=None, help="Tenant to read from (default: active).")
@click.option("--output", "-o", type=click.Path(), default=None,
              help="Write JSON to file (default stdout).")
@click.option("--json", "compact", is_flag=True,
              help="Emit compact single-line JSON (default: pretty, indent=2).")
def dsar_export(user_id: str, tenant: str | None, output, compact: bool) -> None:
    """Export everything Maverick holds for a subject as a JSON bundle.

    Serializes ``export_subject_data()`` -- the subject's conversations, the
    turns/goals/episodes those reference, and their audit rows -- for the
    right of access / portability. The exporter is fail-soft (an unknown
    subject or empty install yields a structured, empty bundle), so this
    command always emits a JSON object and exits 0.
    """
    import json as _json

    from ..dsar import export_subject_data
    bundle = export_subject_data(user_id, tenant=tenant)
    payload = (
        _json.dumps(bundle, default=str)
        if compact
        else _json.dumps(bundle, default=str, indent=2)
    )
    if output:
        # A DSAR export carries the subject's full conversation content.
        # Create it 0o600 (not the umask's world-readable 0644) so a
        # co-tenant can't read it, and fail cleanly instead of dumping a
        # traceback on a bad/unwritable path.
        try:
            fd = os.open(str(output), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
        except OSError as e:
            raise click.ClickException(f"could not write {output}: {e}") from e
        click.echo(f"exported to {output}")
    else:
        click.echo(payload)
