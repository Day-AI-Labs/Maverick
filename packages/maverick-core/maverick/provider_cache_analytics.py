"""Provider-side caching analytics (roadmap: 2028 H2 Performance).

The anthropic provider records prompt-cache telemetry — ``cache_read``,
``cache_creation`` (write), and ``uncached`` input tokens, as
``maverick_llm_cache_tokens_total{kind=...}`` — but a stream of token counters
isn't an answer. This turns those recorded rows into a report: the cache **hit
rate** (``read / (read + uncached)``), the **dollars saved** by reads (and the
write surcharge paid to get them) at configured per-model input prices, a
**per-role** breakdown, and rule-based recommendations ("role ``planner`` has a
2% hit rate — its prompt prefix is unstable").

Pure over recorded metric rows: a list of telemetry rows in, a report dict out,
so it is tested offline with no provider and no network. A "row" is a dict (or
duck-typed object) with:
  * ``kind``   — "read" | "creation"/"write" | "uncached"/"input"; required.
  * ``tokens`` — token count for that kind (int); default 0.
  * ``role``   — optional role label (planner/verifier/...) for the breakdown.
  * ``model``  — optional model id, used to price savings.
"""
from __future__ import annotations

from dataclasses import dataclass

# Anthropic cache economics (mirrors maverick.budget): a cache *read* costs 0.1x
# the input rate (so 0.9x is saved vs paying full price), and a 5m-TTL *write*
# costs 1.25x (a 0.25x surcharge). These are the defaults; callers override the
# read multiplier for other providers (OpenAI auto-cache reads at 0.5x).
_DEFAULT_READ_MULT = 0.1
_DEFAULT_WRITE_MULT = 1.25
# Fallback input price ($/1M tokens) when a row's model isn't in the price map.
_DEFAULT_INPUT_PRICE = 3.0

# Hit-rate floors for the recommendations. A role below LOW_HIT with meaningful
# volume almost certainly has an unstable prompt prefix (a timestamp/UUID in the
# system prompt, an unstable tool order) — the cheapest regression to catch.
_LOW_HIT = 0.05
_MIN_TOKENS_FOR_ADVICE = 10_000


def _field(row, name, default):
    if isinstance(row, dict):
        return row.get(name, default)
    return getattr(row, name, default)


def _norm_kind(kind: str) -> str | None:
    k = (kind or "").strip().lower()
    if k in ("read", "cache_read", "cache-read"):
        return "read"
    if k in ("creation", "write", "cache_creation", "cache-write", "cache_write"):
        return "write"
    if k in ("uncached", "input", "miss"):
        return "uncached"
    return None


def _input_price(model: str | None, prices: dict[str, float] | None) -> float:
    if not model or not prices:
        return _DEFAULT_INPUT_PRICE
    return float(prices.get(model, _DEFAULT_INPUT_PRICE))


@dataclass(frozen=True)
class CacheBucket:
    read: int = 0
    write: int = 0
    uncached: int = 0
    saved: float = 0.0          # dollars saved by reads vs full price
    write_cost: float = 0.0     # surcharge dollars paid for writes

    @property
    def hit_rate(self) -> float:
        denom = self.read + self.uncached
        return round(self.read / denom, 4) if denom else 0.0

    def as_dict(self) -> dict:
        return {
            "read": self.read,
            "write": self.write,
            "uncached": self.uncached,
            "hit_rate": self.hit_rate,
            "saved": round(self.saved, 4),
            "write_cost": round(self.write_cost, 4),
            "net_saved": round(self.saved - self.write_cost, 4),
        }


def _accumulate(
    rows,
    *,
    prices: dict[str, float] | None,
    read_mult: float,
    write_mult: float,
) -> tuple[dict, dict]:
    """Return ``(overall_totals, per_role_totals)`` as raw mutable dicts."""
    blank = {"read": 0, "write": 0, "uncached": 0, "saved": 0.0, "write_cost": 0.0}
    overall = dict(blank)
    by_role: dict[str, dict] = {}
    for row in rows or []:
        kind = _norm_kind(str(_field(row, "kind", "")))
        if kind is None:
            continue
        try:
            tokens = int(_field(row, "tokens", 0) or 0)
        except (TypeError, ValueError):
            continue
        if tokens <= 0:
            continue
        role = str(_field(row, "role", "") or "default").strip() or "default"
        price = _input_price(_field(row, "model", None), prices)
        bucket = by_role.setdefault(role, dict(blank))
        for tgt in (overall, bucket):
            tgt[kind] += tokens
        if kind == "read":
            saved = (tokens / 1_000_000) * price * (1.0 - read_mult)
            overall["saved"] += saved
            bucket["saved"] += saved
        elif kind == "write":
            surcharge = (tokens / 1_000_000) * price * (write_mult - 1.0)
            overall["write_cost"] += surcharge
            bucket["write_cost"] += surcharge
    return overall, by_role


def _bucket(d: dict) -> CacheBucket:
    return CacheBucket(
        read=d["read"], write=d["write"], uncached=d["uncached"],
        saved=d["saved"], write_cost=d["write_cost"],
    )


def _recommendations(overall: CacheBucket, by_role: dict[str, CacheBucket]) -> list[str]:
    out: list[str] = []
    total_in = overall.read + overall.uncached
    if total_in == 0:
        return ["no cacheable input tokens recorded — nothing to analyse."]
    out.append(
        f"overall hit rate {overall.hit_rate:.0%} "
        f"(${overall.saved:.2f} saved, ${overall.write_cost:.2f} write surcharge, "
        f"net ${overall.saved - overall.write_cost:+.2f}).")
    for role, b in sorted(by_role.items()):
        seen = b.read + b.uncached
        if seen >= _MIN_TOKENS_FOR_ADVICE and b.hit_rate < _LOW_HIT:
            out.append(
                f"role {role} has a {b.hit_rate:.0%} hit rate over {seen:,} input "
                "tokens — its prompt prefix looks unstable (check for a "
                "timestamp/UUID or shifting tool order).")
    if overall.write > 0 and overall.read == 0:
        out.append(
            "cache is being written but never read — prefixes are written once "
            "and not reused; the write surcharge is pure overhead here.")
    if len(out) == 1:
        out.append("caching looks healthy across roles.")
    return out


def analyze(
    rows,
    *,
    prices: dict[str, float] | None = None,
    read_mult: float = _DEFAULT_READ_MULT,
    write_mult: float = _DEFAULT_WRITE_MULT,
) -> dict:
    """Aggregate prompt-cache telemetry rows into a hit-rate / savings report.

    ``prices`` maps ``model_id -> input $/1M tokens`` (defaults to a flat rate
    when a model is absent or no map is given). ``read_mult`` / ``write_mult``
    are the provider's cache multipliers over the input rate (Anthropic
    0.1x / 1.25x; pass 0.5 read for OpenAI auto-cache).
    """
    overall_raw, by_role_raw = _accumulate(
        rows, prices=prices, read_mult=read_mult, write_mult=write_mult)
    overall = _bucket(overall_raw)
    by_role = {r: _bucket(d) for r, d in by_role_raw.items()}
    return {
        "overall": overall.as_dict(),
        "by_role": {r: b.as_dict() for r, b in sorted(by_role.items())},
        "recommendations": _recommendations(overall, by_role),
    }


def render(report: dict) -> str:
    """Render a cache-analytics report as a plain text table."""
    o = report.get("overall", {})
    total_in = o.get("read", 0) + o.get("uncached", 0)
    if total_in == 0:
        return "provider cache analytics: no cacheable input tokens recorded."
    lines = [
        f"provider cache analytics: {o['hit_rate']:.0%} hit rate "
        f"(read {o['read']:,} / uncached {o['uncached']:,} / write {o['write']:,})",
        f"  saved ${o['saved']:.2f}, write surcharge ${o['write_cost']:.2f}, "
        f"net ${o['net_saved']:+.2f}",
    ]
    by_role = report.get("by_role", {})
    if by_role:
        lines += ["", "by role:"]
        for role, b in by_role.items():
            lines.append(
                f"  {role:<12} {b['hit_rate']:>5.0%} hit  "
                f"net ${b['net_saved']:+.2f}  "
                f"(r{b['read']:,}/u{b['uncached']:,}/w{b['write']:,})")
    lines += ["", "recommendations:"]
    for r in report.get("recommendations", []):
        lines.append(f"  - {r}")
    return "\n".join(lines)


__all__ = ["CacheBucket", "analyze", "render"]
