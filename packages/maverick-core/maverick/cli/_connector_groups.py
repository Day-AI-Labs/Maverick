"""``maverick connectors`` -- inspect + preview governed system-of-record writes.

Makes the governed-connector write path operable from the CLI: list the
connectors an operator has registered (``[governed_connectors]``) and SIMULATE a
write to preview its effect + approval requirement WITHOUT committing. Commit is
deliberately not exposed here -- a live system-of-record write needs an approver
and runs through the orchestrator's governed path, not a fire-and-forget CLI.

Registered by import at the end of the package __init__, like the other
``_*_groups`` modules.
"""
from __future__ import annotations

import json as _json

import click

from . import main


def _configured():
    """``(GovernedActions, {name: (read, write)})`` for the configured
    connectors, or a clean ClickException when none are set up."""
    from ..governed_rest import configured_governed_actions
    ga, registered = configured_governed_actions()
    if not registered:
        raise click.ClickException(
            "no governed connectors configured. Enable [governed_connectors] "
            "and list connectors (e.g. salesforce, servicenow), or set "
            "MAVERICK_GOVERNED_CONNECTORS=1.")
    return ga, registered


@main.group("connectors")
def connectors_group() -> None:
    """Inspect + preview governed system-of-record connectors.

    A governed write previews its effect, hits the approval floor
    ([actions] require_approval_at), and records tamper-evident lineage --
    instead of a bare confirm-gated tool call.
    """


@connectors_group.command("list")
def connectors_list_cmd() -> None:
    """List the registered governed connectors and their actions."""
    ga, registered = _configured()
    rows = []
    for name, (read_action, write_action) in sorted(registered.items()):
        write_spec = ga.get(write_action)
        rows.append({
            "connector": name,
            "read_action": read_action,
            "write_action": write_action,
            "write_risk": write_spec.risk,
            "write_requires_approval": ga.simulate(
                write_action, _placeholder(write_spec)).requires_approval,
        })
    click.echo(_json.dumps(rows, indent=2))


def _placeholder(spec) -> dict:
    """A minimal typed-valid param dict for a spec, so we can probe its approval
    requirement without real inputs (simulate has no side effects)."""
    sample = {str: "x", dict: {}, int: 0, float: 0.0, bool: False}
    return {k: sample.get(t, "x") for k, t in spec.params.items()}


@connectors_group.command("simulate")
@click.argument("action")
@click.option("--params", "params_json", default="{}",
              help='Typed params as a JSON object, e.g. '
                   '\'{"op":"post","path":"/x","body":{"Name":"Acme"}}\'.')
def connectors_simulate_cmd(action, params_json) -> None:
    """Preview ACTION's effect WITHOUT committing (simulate-before-commit).

    ACTION is a governed action name like ``salesforce.write``. Prints the
    previewed effect, risk tier, and whether a commit would require an approver.
    """
    ga, _registered = _configured()
    try:
        params = _json.loads(params_json)
        if not isinstance(params, dict):
            raise ValueError("params must be a JSON object")
    except ValueError as e:
        raise click.ClickException(f"invalid --params JSON: {e}") from e
    from ..governed_actions import ActionError
    try:
        preview = ga.simulate(action, params)
    except ActionError as e:
        raise click.ClickException(str(e)) from e
    click.echo(_json.dumps({
        "action": preview.action,
        "effect": preview.effect,
        "risk": preview.risk,
        "requires_approval": preview.requires_approval,
        "committed": False,
    }, indent=2))
