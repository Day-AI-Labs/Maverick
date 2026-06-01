"""Budget tracking. Long-horizon agents need hard caps.

v0.2 cost-correctness fix:
  - record_tokens() takes the actual model id (default falls back to
    Sonnet rate for back-compat). Before this, an Opus orchestrator
    call was billed at Sonnet rate, so max_dollars=5 was letting
    ~$25 of real spend through.
  - Cache tokens are priced correctly. Anthropic charges 0.1x for
    cache reads and 1.25x for cache writes. The provider used to
    collapse everything into ``input_tokens`` at full price.
"""
from __future__ import annotations

import math
import os
import threading
import time
from dataclasses import dataclass, field


class BudgetExceeded(Exception):
    pass


# Fallback price (Sonnet 4.6 list, no cache discount) in $/Mtok.
# Used only when the model id isn't in maverick.llm.MODEL_PRICES.
_FALLBACK_PRICE_IN = 3.0
_FALLBACK_PRICE_OUT = 15.0


def _coerce_count(v: object) -> int:
    """Coerce a usage count to a non-negative int, failing closed on bad data.

    Providers occasionally return ``None`` in ``usage`` on streaming refusals;
    that remains a zero count for backwards-compatible null-safety. Non-finite,
    unparseable, or negative counts are invalid accounting data. Raise
    ``BudgetExceeded`` so the run stops instead of silently recording a paid
    call as $0 and bypassing later budget checks.
    """
    if v is None:
        return 0
    try:
        if isinstance(v, float) and not math.isfinite(v):
            raise ValueError("non-finite")
        n = int(v or 0)
    except (TypeError, ValueError, OverflowError) as exc:
        raise BudgetExceeded(f"invalid token usage count: {v!r}") from exc
    if n < 0:
        raise BudgetExceeded(f"invalid token usage count: negative value {n}")
    return n

# Anthropic cache multipliers (over the list input price).
# Two TTLs: 5m default (1.25x write surcharge) and 1h (2.0x write surcharge).
# Wave 12: prior code collapsed all writes to 1.25x; long-TTL writes were
# under-billed by ~40%.
_CACHE_READ_MULT = 0.1     # Anthropic: 90% discount on cache reads (both TTLs)
_CACHE_WRITE_MULT_5M = 1.25
_CACHE_WRITE_MULT_1H = 2.0

# OpenAI / o-series / gpt-5 automatic prompt cache discounts cache reads ~50%
# (0.5x), NOT 90% like Anthropic. Billing those reads at 0.1x under-counted
# cached-input cost ~5x for every non-Anthropic provider with cache hits.
# Callers pass the provider-appropriate multiplier; default stays Anthropic's.
CACHE_READ_MULT_OPENAI = 0.5


def _cache_write_mult_from_ttl(ttl: str | None) -> float:
    """Map Anthropic cache TTL string to the write surcharge multiplier.

    Wave 12 hardening: strip + lowercase before matching so trailing
    whitespace ("1h ") or case variants ("1H") don't silently downgrade
    to the 5m rate. Also: anything >= 5m duration is billed at 2.0x to
    match Anthropic's published surcharge tiers (the SDK accepts more
    TTL strings than the original 3-value whitelist).
    """
    if not ttl:
        return _CACHE_WRITE_MULT_5M
    norm = ttl.strip().lower()
    # Known 1h-tier aliases.
    if norm in ("1h", "60m", "3600s", "1hour", "1 hour"):
        return _CACHE_WRITE_MULT_1H
    # Parse duration suffixes — anything > 5m bills at 1h rate.
    try:
        if norm.endswith("h"):
            return _CACHE_WRITE_MULT_1H if float(norm[:-1]) >= 1 else _CACHE_WRITE_MULT_5M
        if norm.endswith("m"):
            return _CACHE_WRITE_MULT_1H if float(norm[:-1]) > 5 else _CACHE_WRITE_MULT_5M
        if norm.endswith("s"):
            return _CACHE_WRITE_MULT_1H if float(norm[:-1]) > 300 else _CACHE_WRITE_MULT_5M
    except ValueError:
        pass
    return _CACHE_WRITE_MULT_5M


def _lookup_price(model: str | None) -> tuple[float, float]:
    """Return (in_per_mtok, out_per_mtok) for a model id. Falls back to Sonnet."""
    if not model:
        return _FALLBACK_PRICE_IN, _FALLBACK_PRICE_OUT
    try:
        from .llm import MODEL_PRICES
    except ImportError:
        return _FALLBACK_PRICE_IN, _FALLBACK_PRICE_OUT
    if model in MODEL_PRICES:
        return MODEL_PRICES[model]
    # Strip a "provider:" prefix (e.g. "anthropic:claude-opus-4-7").
    bare = model.split(":", 1)[1] if ":" in model else model
    if bare in MODEL_PRICES:
        return MODEL_PRICES[bare]
    # Models the cost-router can SELECT but that aren't in MODEL_PRICES
    # (gpt-5-nano, gpt-5, gpt-5-pro, grok-4, gemini-2.5-*, the dated Haiku
    # id) used to silently bill at the Sonnet fallback rate. Consult the
    # router's own pricing table before giving up.
    try:
        from .cost_router import price_for_model
        priced = price_for_model(model) or price_for_model(bare)
        if priced is not None:
            return priced
    except ImportError:
        pass
    return _FALLBACK_PRICE_IN, _FALLBACK_PRICE_OUT


@dataclass
class Budget:
    max_input_tokens: int = 1_000_000
    max_output_tokens: int = 200_000
    max_dollars: float = 5.0
    max_wall_seconds: float = 3600.0
    max_tool_calls: int = 500

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    dollars: float = 0.0
    tool_calls: int = 0
    started_at: float = field(default_factory=time.time)

    # Legacy defaults; only used when ``model`` isn't passed.
    price_in_per_mtok: float = _FALLBACK_PRICE_IN
    price_out_per_mtok: float = _FALLBACK_PRICE_OUT

    def record_tokens(
        self,
        in_tok: int,
        out_tok: int,
        *,
        model: str | None = None,
        cache_read_tok: int = 0,
        cache_write_tok: int = 0,
        cache_write_ttl: str | None = None,
        cache_read_mult: float | None = None,
    ) -> None:
        """Add usage from one LLM call.

        ``in_tok`` is the number of input tokens billed at full rate
        (i.e. excludes the cache_read_tok and cache_write_tok counts).
        ``cache_read_tok`` is billed at ``cache_read_mult`` x the input rate
        (default 0.1x for Anthropic; pass ``CACHE_READ_MULT_OPENAI`` =0.5 for
        OpenAI/o-series/gpt-5 auto-cache). ``cache_write_tok`` at 1.25x (5m TTL)
        or 2.0x (1h TTL) — pass ``cache_write_ttl="1h"`` for a 1h breakpoint.

        Wave 12 nullsafety: ``None`` usage counts coerce to zero — Anthropic
        occasionally returns ``None`` in ``usage`` on streaming refusals; the
        prior code raised ``TypeError`` and the instance counted as $0 spent.
        Non-finite, unparseable, or negative counts now fail closed with
        ``BudgetExceeded`` instead of silently recording a paid call as zero.

        Council finding: cache reads/writes accumulate in separate
        counters so ``max_input_tokens`` reflects the BILLABLE input
        budget (non-cached only). Caching is a discount, so heavy
        caching should let you DO more work within the same input cap.
        """
        in_tok = _coerce_count(in_tok)
        out_tok = _coerce_count(out_tok)
        cache_read_tok = _coerce_count(cache_read_tok)
        cache_write_tok = _coerce_count(cache_write_tok)
        # Wave 12 (council F12b): make the accumulator atomic so a
        # future parallel best-of-N (or multi-agent swarm where two
        # agents share a Budget) can't lose updates. `+=` on float is
        # NOT atomic in CPython under threads — we'd silently undercount.
        # Wave 12 hardening: check() runs INSIDE the lock too — TOCTOU
        # otherwise lets two threads both pass check() with state that
        # the OTHER thread has already invalidated. check() does no I/O
        # and elapsed() is reentrant-safe, so holding the lock through
        # it is fine.
        with self._lock:
            self.input_tokens += in_tok
            self.cache_read_tokens += cache_read_tok
            self.cache_write_tokens += cache_write_tok
            self.output_tokens += out_tok

            in_rate, out_rate = _lookup_price(model)
            write_mult = _cache_write_mult_from_ttl(cache_write_ttl)
            # Provider-aware cache-read discount: Anthropic 0.1x (default),
            # OpenAI/o-series/gpt-5 auto-cache ~0.5x (caller passes it).
            read_mult = _CACHE_READ_MULT if cache_read_mult is None else float(cache_read_mult)
            self.dollars += (in_tok / 1_000_000) * in_rate
            self.dollars += (cache_read_tok / 1_000_000) * in_rate * read_mult
            self.dollars += (cache_write_tok / 1_000_000) * in_rate * write_mult
            self.dollars += (out_tok / 1_000_000) * out_rate
            self.check()

    def record_tool_call(self) -> None:
        with self._lock:
            self.tool_calls += 1
            self.check()

    def absorb(self, other: Budget) -> None:
        """Roll another Budget's consumption into this one atomically and
        enforce caps.

        Used when a child/attempt runs on its own Budget (e.g. best-of-N)
        and its spend must count against the parent cap. Replaces the raw
        ``self.dollars += other.dollars`` roll-up, which bypassed both the
        lock (lost updates under concurrency) and ``check()`` (so the
        parent silently busted its cap across attempts).
        """
        with self._lock:
            self.input_tokens += other.input_tokens
            self.output_tokens += other.output_tokens
            self.cache_read_tokens += other.cache_read_tokens
            self.cache_write_tokens += other.cache_write_tokens
            self.dollars += other.dollars
            self.tool_calls += other.tool_calls
            self.check()

    def elapsed(self) -> float:
        # Wave 12: use monotonic so NTP clock-skew doesn't bypass the wall
        # cap. `started_at` is captured in __post_init__ for monotonic.
        try:
            return time.monotonic() - self._started_monotonic
        except AttributeError:
            # Legacy path: dataclass instance created before __post_init__
            # extension landed. Fall back to wall clock.
            return time.time() - self.started_at

    def __post_init__(self) -> None:
        self._started_monotonic = time.monotonic()
        # Wave 12 (F12b): per-instance lock for atomic counter updates.
        self._lock = threading.Lock()
        # A non-finite cap (nan/inf) silently disables enforcement: every
        # `self.dollars > nan` comparison in check() is False, so the cap
        # never trips. TOML 1.0 has native nan/inf and `--max-dollars inf`
        # parses, so a cap could arrive non-finite from config or a flag.
        # Coerce any non-finite dollar/wall/token cap back to a safe default
        # rather than run uncapped. (Budget caps are not optional.)
        for _field, _default in (
            ("max_dollars", 5.0),
            ("max_wall_seconds", 3600.0),
            ("max_input_tokens", 1_000_000),
            ("max_output_tokens", 200_000),
        ):
            _v = getattr(self, _field)
            try:
                if not math.isfinite(float(_v)):
                    setattr(self, _field, _default)
            except (TypeError, ValueError):
                setattr(self, _field, _default)

    def __getstate__(self):
        """Wave 12 hardening: threading.Lock is unpicklable. Drop the
        non-picklable transient fields so a Budget can survive being
        sent to a multiprocessing worker (and the monotonic clock is
        per-process — reset on unpickle to avoid bogus elapsed math)."""
        state = self.__dict__.copy()
        state.pop("_lock", None)
        # Preserve consumed wall time across process boundaries.
        # Monotonic baselines are process-local, so serialize elapsed
        # duration and reconstruct a compatible baseline on restore.
        state["_elapsed_at_pickle"] = self.elapsed()
        state.pop("_started_monotonic", None)
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)
        self._lock = threading.Lock()
        elapsed = float(self.__dict__.pop("_elapsed_at_pickle", 0.0) or 0.0)
        self._started_monotonic = time.monotonic() - max(0.0, elapsed)

    def check(self) -> None:
        if self.input_tokens > self.max_input_tokens:
            raise BudgetExceeded(f"input tokens {self.input_tokens} > {self.max_input_tokens}")
        if self.output_tokens > self.max_output_tokens:
            raise BudgetExceeded(f"output tokens {self.output_tokens} > {self.max_output_tokens}")
        if self.dollars > self.max_dollars:
            raise BudgetExceeded(f"${self.dollars:.2f} > ${self.max_dollars:.2f}")
        if self.tool_calls > self.max_tool_calls:
            raise BudgetExceeded(f"tool calls {self.tool_calls} > {self.max_tool_calls}")
        if self.elapsed() > self.max_wall_seconds:
            raise BudgetExceeded(f"wall time {self.elapsed():.0f}s > {self.max_wall_seconds:.0f}s")

    def summary(self) -> str:
        return (
            f"tokens in={self.input_tokens} out={self.output_tokens} "
            f"$={self.dollars:.3f} tools={self.tool_calls} wall={self.elapsed():.0f}s"
        )


_BUDGET_KEY_TYPES = {
    "max_input_tokens": int,
    "max_output_tokens": int,
    "max_dollars": float,
    "max_wall_seconds": float,
    "max_tool_calls": int,
}


def budget_from_config(*, defaults: dict | None = None, **overrides) -> Budget:
    """Build a Budget that honors the ``[budget]`` section of config.toml.

    Precedence, lowest to highest:
      ``defaults`` (a caller's own fallback, e.g. the background runner's
      conservative caps) < the ``[budget]`` config section < explicit
      ``overrides`` (e.g. a CLI ``--max-dollars`` flag). A ``None`` value
      in either ``defaults`` or ``overrides`` is treated as "unset", so a
      caller can pass an optional flag straight through.

    ``config.get_budget_overrides()`` already existed but was never wired,
    so the ``[budget]`` section had no effect on any run. This is the single
    funnel that fixes that; malformed values are skipped (keep prior layer)
    rather than crashing the run.
    """
    kwargs: dict = {}
    if defaults:
        for key, val in defaults.items():
            if key in _BUDGET_KEY_TYPES and val is not None:
                kwargs[key] = val
    try:
        from .config import get_budget_overrides
        cfg = get_budget_overrides() or {}
    except Exception:
        cfg = {}
    for key, caster in _BUDGET_KEY_TYPES.items():
        if cfg.get(key) is not None:
            try:
                cast = caster(cfg[key])
                # Reject non-finite caps from config (TOML nan/inf) -- they
                # would disable the cap rather than set it. Skip -> prior layer.
                if isinstance(cast, float) and not math.isfinite(cast):
                    continue
                kwargs[key] = cast
            except (TypeError, ValueError):
                pass  # malformed config value -> fall back to prior layer
    # Env override for the documented MAVERICK_BUDGET_DOLLARS. The cookbooks
    # use `MAVERICK_BUDGET_DOLLARS=0.5 maverick start ...` to cap a single
    # invocation, but nothing read it -- so the cap silently did nothing and
    # users ran at the default. Sits above [budget] config, below an explicit
    # CLI override (--max-dollars). Malformed / non-finite -> keep prior layer.
    env_dollars = os.environ.get("MAVERICK_BUDGET_DOLLARS")
    if env_dollars:
        try:
            cast = float(env_dollars)
            if math.isfinite(cast):
                kwargs["max_dollars"] = cast
        except (TypeError, ValueError):
            pass
    for key, val in overrides.items():
        if val is not None and key in _BUDGET_KEY_TYPES:
            kwargs[key] = val
    return Budget(**kwargs)
