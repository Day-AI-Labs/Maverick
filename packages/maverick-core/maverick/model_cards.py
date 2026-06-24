"""Per-model usage cards (roadmap: 2027 H2 safety).

Governance reviews ask a deceptively simple question: *which models does this
deployment actually use, for what, and how much?* The honest answer lives in
our own usage ledger, not in vendor marketing. This module aggregates local
usage rows into one :class:`ModelCard` per model id and renders them as a
markdown document an auditor can file.

Two hard rules keep the cards trustworthy:

1. **Numbers are this deployment's own ledger.** Calls, tokens and dollars
   come from the rows the caller feeds in (episodes, billing exports, ...).
   The rendered document says so explicitly so nobody mistakes a card for a
   vendor benchmark sheet.
2. **No invented vendor facts.** ``knowledge_cutoff`` is filled only from
   :data:`KNOWN_KNOWLEDGE_CUTOFFS`, which may list only model ids visible in
   :mod:`maverick.llm` (``MODEL_PRICES`` / ``ROLE_MODELS``) and only when the
   id string itself encodes a date. As of this writing every id there is a
   version/SKU string ("claude-opus-4-8", "gpt-5.5", "moonshot-v1-8k", ...)
   — none encodes a cutoff date — so the table is empty and every card says
   "not asserted". We render *unknown* rather than guess.

Input rows are duck-typed (plain dicts or attribute objects)::

    {model, provider?, role?, ts?, in_tokens?, out_tokens?, cost_dollars?}

``model`` may be a ``provider:model-id`` spec (the form :mod:`maverick.llm`
dispatches on); the prefix is split off as the provider when no explicit
provider field is present. Rows without a model are skipped — a card keyed
on nothing helps nobody.

:func:`gather_from_world` adapts a :class:`~maverick.world_model.WorldModel`
into those rows via ``list_episodes(limit=...)``. The stock episode schema
(``started_at/ended_at/cost_dollars/input_tokens/output_tokens/...``) does
**not** record which model served an episode, so against today's schema the
adapter yields rows only from backends/forks whose episode rows carry a
``model`` (or ``model_id``/``model_spec``) field — everything is read with
``getattr``-style duck typing and the adapter fails open to ``[]`` rather
than ever breaking a report. Stdlib-only; nothing here talks to a network.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

log = logging.getLogger(__name__)

DISCLAIMER = ("Generated from local usage; numbers are this deployment's own "
              "ledger, not vendor claims.")

# Knowledge cutoffs may ONLY be asserted for model ids present in
# maverick.llm.MODEL_PRICES / ROLE_MODELS, and only when the id string itself
# encodes a date. Every id currently there is a version string (claude-opus-4-8,
# gpt-5.4, deepseek-v4-pro, grok-4.3, kimi-k2, gemini-3.5-pro, qwen3-32b, ...),
# so this table is intentionally empty: we do not invent vendor facts.
KNOWN_KNOWLEDGE_CUTOFFS: dict[str, str] = {}


@dataclass
class ModelCard:
    """One model's footprint in this deployment, per our own ledger."""

    model_id: str
    provider: str = ""
    first_seen: float | None = None
    last_seen: float | None = None
    roles: set[str] = field(default_factory=set)
    calls: int = 0
    total_in_tokens: int = 0
    total_out_tokens: int = 0
    total_dollars: float = 0.0
    knowledge_cutoff: str | None = None
    notes: str = ""


# Fields an operator may declare about how THIS deployment uses a model. These
# are operator assertions about intended use / limitations / oversight, NOT
# vendor benchmark claims — exactly the deployer-side documentation ISO/IEC
# 42001 A.6.2.7 (technical documentation) and A.8.2 (information for users) ask
# for. Kept separate from the ledger-derived ModelCard so the two never blur:
# numbers come from our own usage, prose comes from the operator's config.
_METADATA_FIELDS = (
    "intended_use",
    "out_of_scope_use",
    "limitations",
    "risk_classification",  # operator-declared EU AI Act tier, e.g. "limited"
    "data_provenance",
    "human_oversight",
    "ethical_considerations",
)


@dataclass
class ModelCardMetadata:
    """Operator-declared metadata for one model (intended use, limits, oversight).

    Every field is optional and free-text; ``evaluations`` is a ``{name: result}``
    map of the deployment's own eval results. Empty by default so a card with no
    declared metadata renders exactly as before. These are the Organization's
    assertions about its own use of the model — never invented vendor facts.
    """

    intended_use: str = ""
    out_of_scope_use: str = ""
    limitations: str = ""
    risk_classification: str = ""
    data_provenance: str = ""
    human_oversight: str = ""
    ethical_considerations: str = ""
    evaluations: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw) -> ModelCardMetadata:
        """Build from a partial dict, tolerating junk/missing keys (fail-soft).

        Unknown keys are ignored; string fields are stringified; ``evaluations``
        is taken only when it is a dict, with values stringified. A non-dict
        input yields an all-empty instance rather than raising.
        """
        if not isinstance(raw, dict):
            return cls()
        kwargs = {}
        for name in _METADATA_FIELDS:
            val = raw.get(name)
            if val is not None and str(val).strip():
                kwargs[name] = str(val).strip()
        evals = raw.get("evaluations")
        if isinstance(evals, dict):
            kwargs["evaluations"] = {
                str(k): str(v) for k, v in evals.items() if str(k).strip()
            }
        return cls(**kwargs)

    def is_empty(self) -> bool:
        """True when nothing has been declared (renders no metadata block)."""
        return not any(getattr(self, n) for n in _METADATA_FIELDS) and not self.evaluations


def _field(row, *names):
    """First non-None field among ``names``, from a dict or an object."""
    for name in names:
        if isinstance(row, dict):
            val = row.get(name)
        else:
            val = getattr(row, name, None)
        if val is not None:
            return val
    return None


def _as_int(val) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        return 0


def _as_float(val) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def build_cards(usage_rows) -> dict[str, ModelCard]:
    """Aggregate duck-typed usage rows into ``{model_id: ModelCard}``.

    Rows without a model are skipped; malformed numeric fields count as 0;
    an explicit ``provider`` field beats a ``provider:model`` spec prefix.
    First/last seen come from ``ts`` (epoch seconds) when present.
    """
    cards: dict[str, ModelCard] = {}
    for row in usage_rows or []:
        spec = _field(row, "model", "model_id")
        if not spec:
            continue
        model = str(spec).strip()
        provider = _field(row, "provider")
        if ":" in model:
            prefix, bare = model.split(":", 1)
            if bare.strip():
                model = bare.strip()
                if provider is None and prefix.strip():
                    provider = prefix.strip()
        if not model:
            continue

        card = cards.get(model)
        if card is None:
            card = ModelCard(model_id=model,
                             knowledge_cutoff=KNOWN_KNOWLEDGE_CUTOFFS.get(model))
            cards[model] = card

        if provider and not card.provider:
            card.provider = str(provider)
        role = _field(row, "role")
        if role:
            card.roles.add(str(role))
        ts = _field(row, "ts")
        if ts is not None:
            try:
                t = float(ts)
            except (TypeError, ValueError):
                t = None
            if t is not None:
                card.first_seen = t if card.first_seen is None else min(card.first_seen, t)
                card.last_seen = t if card.last_seen is None else max(card.last_seen, t)
        card.calls += 1
        card.total_in_tokens += _as_int(_field(row, "in_tokens", "input_tokens"))
        card.total_out_tokens += _as_int(_field(row, "out_tokens", "output_tokens"))
        card.total_dollars += _as_float(_field(row, "cost_dollars", "dollars"))
    return cards


def _iso(ts: float | None) -> str:
    if ts is None:
        return "unknown"
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%SZ")
    except (OverflowError, OSError, ValueError):
        return "unknown"


def _render_metadata(meta: ModelCardMetadata) -> list[str]:
    """Markdown lines for operator-declared metadata, or [] when nothing declared.

    Rendered under an explicit "operator-declared" heading so an auditor never
    confuses these assertions with the ledger-derived usage numbers above.
    """
    if meta is None or meta.is_empty():
        return []
    labels = {
        "intended_use": "intended use",
        "out_of_scope_use": "out-of-scope use",
        "limitations": "limitations",
        "risk_classification": "risk classification (operator-declared)",
        "data_provenance": "data provenance",
        "human_oversight": "human oversight",
        "ethical_considerations": "ethical considerations",
    }
    lines = ["", "Operator-declared (this deployment's assertions, not vendor claims):"]
    for name in _METADATA_FIELDS:
        val = getattr(meta, name)
        if val:
            lines.append(f"- {labels[name]}: {val}")
    if meta.evaluations:
        lines.append("- evaluations:")
        for name in sorted(meta.evaluations):
            lines.append(f"  - {name}: {meta.evaluations[name]}")
    return lines


def render_card(card: ModelCard, metadata: ModelCardMetadata | None = None) -> str:
    """One markdown section for one model (plus operator metadata when supplied)."""
    lines = [
        f"## {card.model_id}",
        "",
        f"- provider: {card.provider or 'unknown'}",
        f"- roles: {', '.join(sorted(card.roles)) if card.roles else 'unknown'}",
        f"- calls: {card.calls}",
        f"- input tokens: {card.total_in_tokens}",
        f"- output tokens: {card.total_out_tokens}",
        f"- spend: ${card.total_dollars:.4f}",
        f"- first seen: {_iso(card.first_seen)}",
        f"- last seen: {_iso(card.last_seen)}",
        f"- knowledge cutoff: {card.knowledge_cutoff or 'not asserted (no vendor claims)'}",
    ]
    if card.notes:
        lines.append(f"- notes: {card.notes}")
    lines.extend(_render_metadata(metadata))
    return "\n".join(lines)


def render_cards(cards: dict[str, ModelCard],
                 metadata: dict[str, ModelCardMetadata] | None = None) -> str:
    """One markdown document: header + disclaimer + a section per model.

    ``metadata`` maps ``model_id -> ModelCardMetadata`` (operator-declared);
    models without an entry render usage-only, exactly as before.
    """
    metadata = metadata or {}
    doc = ["# Model cards", "", DISCLAIMER, ""]
    if not cards:
        doc.append("(no model usage recorded)")
        return "\n".join(doc) + "\n"
    for model_id in sorted(cards):
        doc.append(render_card(cards[model_id], metadata.get(model_id)))
        doc.append("")
    return "\n".join(doc).rstrip("\n") + "\n"


def load_declared_metadata(raw=None) -> dict[str, ModelCardMetadata]:
    """Build ``{model_id: ModelCardMetadata}`` from a declared mapping, fail-soft.

    ``raw`` is a ``{model_id: {intended_use: ..., ...}}`` mapping (the shape of a
    ``[model_cards.<model_id>]`` config table). When ``raw`` is None it is read
    from ``[model_cards]`` in the live config, importing :mod:`maverick.config`
    lazily and degrading to ``{}`` on any error — model-card export must never be
    able to break on a malformed config. Junk per-model values are skipped.
    """
    if raw is None:
        try:
            from . import config
            raw = config.load_config().get("model_cards", {})
        except Exception as e:  # fail-open: no declared metadata rather than crash
            log.debug("model_cards: could not read declared metadata: %s", e)
            raw = {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, ModelCardMetadata] = {}
    for model_id, decl in raw.items():
        if isinstance(decl, dict) and str(model_id).strip():
            out[str(model_id)] = ModelCardMetadata.from_dict(decl)
    return out


def export_model_cards(world, *, metadata: dict[str, ModelCardMetadata] | None = None,
                       limit: int = 5000) -> str:
    """End-to-end export: gather usage from ``world``, merge operator metadata,
    render the markdown document an auditor can file (ISO 42001 A.6.2.7 / A.8.2).

    ``metadata`` defaults to the operator declarations in config
    (:func:`load_declared_metadata`). Fail-open throughout: a world that yields
    no attributed rows still produces a well-formed (disclaimer-carrying)
    document, and a metadata read error degrades to usage-only cards.
    """
    cards = build_cards(gather_from_world(world, limit=limit))
    if metadata is None:
        metadata = load_declared_metadata()
    return render_cards(cards, metadata)


def gather_from_world(world, limit: int = 5000) -> list[dict]:
    """Pull usage rows for :func:`build_cards` out of a world model.

    Duck-typed and fail-open: any world-ish object with ``list_episodes``
    works; missing method, a raising backend, or episode rows without model
    attribution (today's stock ``EpisodeSpend``) simply yield fewer/zero
    rows — never an exception. ``ended_at`` is preferred over ``started_at``
    as the row timestamp (it's when the spend became final).
    """
    lister = getattr(world, "list_episodes", None)
    if not callable(lister):
        log.debug("model_cards: world object has no list_episodes; no rows")
        return []
    try:
        try:
            episodes = lister(limit=limit)
        except TypeError:  # foreign signature without a limit kwarg
            episodes = lister()
    except Exception as e:
        log.warning("model_cards: cannot read episodes from world: %s", e)
        return []

    rows: list[dict] = []
    for ep in episodes or []:
        model = _field(ep, "model", "model_id", "model_spec")
        if not model:
            continue  # stock episode rows carry no model attribution
        rows.append({
            "model": model,
            "provider": _field(ep, "provider"),
            "role": _field(ep, "role"),
            "ts": _field(ep, "ended_at", "started_at", "ts"),
            "in_tokens": _field(ep, "input_tokens", "in_tokens"),
            "out_tokens": _field(ep, "output_tokens", "out_tokens"),
            "cost_dollars": _field(ep, "cost_dollars"),
        })
    return rows


__all__ = [
    "ModelCard", "ModelCardMetadata", "build_cards", "render_card", "render_cards",
    "load_declared_metadata", "export_model_cards",
    "gather_from_world", "KNOWN_KNOWLEDGE_CUTOFFS", "DISCLAIMER",
]
