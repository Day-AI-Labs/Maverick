"""Provider migration cost calculator (roadmap: 2027 H2 performance).

Answers the procurement question every multi-provider shop eventually asks:
"what would last month have cost on model X?". Given observed usage rows
(token volumes, optionally what they actually cost), :func:`reprice` replays
the *same token volumes* at a target model's list rate from the canonical
``llm.MODEL_PRICES`` catalog — the single pricing source of truth — and
reports the delta. :func:`compare_matrix` does it across several candidate
targets at once, cheapest first.

Honesty matters more than precision here, in three documented ways:

* **Token counts transfer, quality doesn't.** Different vendors tokenize the
  same text differently and produce different-quality output; replaying token
  volumes is lower-bound *arithmetic*, not a benchmark. :func:`render` says so
  in every output.
* **The current side prefers what was actually billed.** A row's
  ``cost_dollars`` (the recorded spend) wins over re-deriving it; only rows
  without one are priced from their ``model`` via ``MODEL_PRICES``.
* **Unpriceable rows are counted, never guessed.** A row with no recorded
  cost and no priceable model is excluded from BOTH sides (so the delta stays
  apples-to-apples) and surfaced in ``unpriceable_rows`` instead of being
  silently billed at some fallback rate.

Usage rows are duck-typed (dicts or attribute objects) with
``in_tokens``/``out_tokens`` (``input_tokens``/``output_tokens`` accepted) as
row totals, optional ``model``, ``cost_dollars`` and ``calls`` (metadata only
— tokens are already totals). :func:`gather_from_world` adapts a world
model's recent episodes (``EpisodeSpend.input_tokens/output_tokens/
cost_dollars``) into rows.

Pure library, stdlib-only, nothing runs unless called.
"""
from __future__ import annotations

from dataclasses import dataclass

_MTOK = 1_000_000.0

CAVEAT = (
    "Caveat: token counts transfer as-is, but tokenizers, context handling and output "
    "quality differ across vendors — this is lower-bound arithmetic on identical token "
    "volumes, not a benchmark."
)


@dataclass(frozen=True)
class MigrationEstimate:
    target_model: str
    current_dollars: float
    target_dollars: float
    delta_dollars: float    # target - current; negative = the move saves money
    delta_pct: float        # delta as % of current (0.0 when current is 0)
    unpriceable_rows: int   # rows excluded from both sides (no cost, no priceable model)


def _prices() -> dict[str, tuple[float, float]]:
    """The canonical model_id -> ($/Mtok in, $/Mtok out) catalog, read at call
    time so tests can pin it."""
    from .llm import MODEL_PRICES
    return MODEL_PRICES


def _bare(model: str) -> str:
    """Strip a ``provider:`` prefix — MODEL_PRICES keys bare ids."""
    return model.split(":", 1)[1] if ":" in model else model


def _field(row, *names: str, default=None):
    """Duck-typed row read: dict keys first, then attributes."""
    if isinstance(row, dict):
        for name in names:
            if name in row:
                return row[name]
        return default
    for name in names:
        value = getattr(row, name, None)
        if value is not None:
            return value
    return default


def reprice(rows: list, target_model: str) -> MigrationEstimate:
    """Re-price ``rows``' token volumes on ``target_model``.

    The target must resolve in ``llm.MODEL_PRICES`` (a ``provider:`` prefix is
    stripped); an unknown id raises ``ValueError`` listing the known ids so a
    typo is caught instead of silently priced wrong. Per row: the current side
    is ``cost_dollars`` when present, else the row's ``model`` priced via
    ``MODEL_PRICES``; rows priceable on neither side are counted in
    ``unpriceable_rows`` and excluded from both totals.
    """
    prices = _prices()
    bare_target = _bare(str(target_model or ""))
    target_rate = prices.get(bare_target)
    if target_rate is None:
        known = ", ".join(sorted(prices))
        raise ValueError(f"unknown target model {target_model!r}; known model ids: {known}")
    t_in, t_out = target_rate

    current = 0.0
    target = 0.0
    unpriceable = 0
    for row in rows or []:
        in_tokens = int(_field(row, "in_tokens", "input_tokens", default=0) or 0)
        out_tokens = int(_field(row, "out_tokens", "output_tokens", default=0) or 0)
        cost = _field(row, "cost_dollars", default=None)
        if cost is None:
            model = _field(row, "model", default=None)
            rate = prices.get(_bare(str(model))) if model else None
            if rate is None:
                unpriceable += 1
                continue  # excluded from BOTH sides — keep the delta honest
            cost = (in_tokens / _MTOK) * rate[0] + (out_tokens / _MTOK) * rate[1]
        current += float(cost)
        target += (in_tokens / _MTOK) * t_in + (out_tokens / _MTOK) * t_out

    delta = target - current
    delta_pct = (delta / current * 100.0) if current > 0 else 0.0
    return MigrationEstimate(
        target_model=str(target_model), current_dollars=current, target_dollars=target,
        delta_dollars=delta, delta_pct=delta_pct, unpriceable_rows=unpriceable,
    )


def compare_matrix(rows: list, targets: list[str]) -> list[MigrationEstimate]:
    """Re-price the same rows on each target; cheapest target first."""
    estimates = [reprice(rows, t) for t in targets or []]
    estimates.sort(key=lambda e: e.target_dollars)
    return estimates


def gather_from_world(world, *, limit: int = 500) -> list[dict]:
    """Adapt a world model's recent episodes into usage rows.

    Duck-typed: needs ``list_episodes(limit=...)`` yielding objects with
    ``input_tokens``/``output_tokens``/``cost_dollars`` (the SQLite backend's
    ``EpisodeSpend``). Episodes don't record which model served them, so the
    recorded ``cost_dollars`` carries the current side; an episode with tokens
    but no recorded cost shows up as an unpriceable row rather than being
    guessed. Episodes with no usage at all are skipped.
    """
    out: list[dict] = []
    for ep in world.list_episodes(limit=limit):
        in_tokens = int(getattr(ep, "input_tokens", 0) or 0)
        out_tokens = int(getattr(ep, "output_tokens", 0) or 0)
        cost = float(getattr(ep, "cost_dollars", 0) or 0)
        if in_tokens <= 0 and out_tokens <= 0 and cost <= 0:
            continue
        row: dict = {"in_tokens": in_tokens, "out_tokens": out_tokens}
        if cost > 0:
            row["cost_dollars"] = cost
        out.append(row)
    return out


def render(estimates: MigrationEstimate | list[MigrationEstimate]) -> str:
    """Comparison table; ALWAYS ends with the tokenizer/quality caveat."""
    if isinstance(estimates, MigrationEstimate):
        estimates = [estimates]
    lines = [
        "Provider migration estimate (same token volumes at target list rates)",
        f"{'target':<28} {'current $':>11} {'target $':>11} {'delta $':>11} "
        f"{'delta %':>8} {'unpriced':>8}",
    ]
    for e in estimates:
        lines.append(
            f"{e.target_model:<28} {e.current_dollars:>11.4f} {e.target_dollars:>11.4f} "
            f"{e.delta_dollars:>+11.4f} {e.delta_pct:>+7.1f}% {e.unpriceable_rows:>8}"
        )
    lines.append(CAVEAT)
    return "\n".join(lines)


__all__ = [
    "CAVEAT", "MigrationEstimate", "reprice", "compare_matrix",
    "gather_from_world", "render",
]
