"""The codec token probe -- the kill-switch experiment for the Emergent Substrate.

`maverick codebook` reports how many *bytes* the learned shorthand saves. But the
moat thesis is *frontier tokens*, and bytes and tokens do not move together: a
BPE tokenizer encodes common English phrases efficiently, while the codec
replaces them with rare sentinels (``⟦0⟧``) that may tokenize into *more* tokens
than the words they stand for. So a corpus that is 40% smaller in bytes can be
break-even -- or *worse* -- in tokens.

This module measures the truth directly: tokens of the plain English an agent
would emit today vs. tokens of the same messages once compressed. If the encoded
form isn't smaller in tokens, the entire token-savings case (and the Rust->WASM
carve built on it) is moot, and the codec is at best a bytes/bandwidth/audit
feature -- not a token moat.

There are two regimes, and the probe reports both so the decision is honest:

    READ-DECODED  -- the model reads plain English (codec only shrinks what's
                     stored/shipped between agents). Token cost UNCHANGED; the
                     token delta here is always ~0. Value is bytes only.
    READ-CODED    -- the model reads the compressed form. Per-message tokens
                     change by ``token_savings_pct`` -- BUT the model must carry
                     the codebook in context to understand the codes, a one-time
                     ``codebook_token_cost`` that has to be amortized across
                     messages before the swap pays for itself.

Pure + dependency-free: the token counter is injected, so the core needs no
tokenizer at all. Adapters for tiktoken (a free local BPE proxy) and the
Anthropic counting API live alongside; tests use a trivial stub.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from .emergent_protocol import Codebook, encode

# A token counter maps text -> token count. Injected so the core is tokenizer-agnostic.
Counter = Callable[[str], int]


@dataclass(frozen=True)
class TokenDelta:
    """Tokens (and bytes) of a corpus before vs after codec compression."""

    n_messages: int
    original_tokens: int       # plain English -- what the model emits today
    encoded_tokens: int        # compressed form -- if agents spoke the shorthand
    original_bytes: int
    encoded_bytes: int
    codebook_tokens: int       # one-time cost to carry the codebook in context

    @property
    def token_ratio(self) -> float:
        """encoded / original tokens. <1 saves tokens; >=1 means the codec costs more."""
        return (self.encoded_tokens / self.original_tokens) if self.original_tokens else 1.0

    @property
    def byte_ratio(self) -> float:
        return (self.encoded_bytes / self.original_bytes) if self.original_bytes else 1.0

    @property
    def token_savings_pct(self) -> float:
        """Percent of tokens saved per message (negative == the codec is *worse*)."""
        return (1.0 - self.token_ratio) * 100.0

    @property
    def byte_savings_pct(self) -> float:
        return (1.0 - self.byte_ratio) * 100.0

    @property
    def pays_off(self) -> bool:
        """The token thesis holds only if the compressed corpus is smaller in TOKENS."""
        return self.encoded_tokens < self.original_tokens

    @property
    def breakeven_messages(self) -> float:
        """READ-CODED regime: how many messages must reuse the codebook before the
        per-message token savings repay the one-time in-context codebook cost.
        ``inf`` when there is no per-message saving to repay it with."""
        saved_per_msg = (self.original_tokens - self.encoded_tokens) / self.n_messages \
            if self.n_messages else 0.0
        if saved_per_msg <= 0:
            return float("inf")
        return self.codebook_tokens / saved_per_msg

    def to_dict(self) -> dict:
        return {
            "n_messages": self.n_messages,
            "original_tokens": self.original_tokens,
            "encoded_tokens": self.encoded_tokens,
            "token_savings_pct": round(self.token_savings_pct, 2),
            "original_bytes": self.original_bytes,
            "encoded_bytes": self.encoded_bytes,
            "byte_savings_pct": round(self.byte_savings_pct, 2),
            "codebook_tokens": self.codebook_tokens,
            "breakeven_messages": self.breakeven_messages,
            "pays_off": self.pays_off,
        }


def codebook_token_cost(codebook: Codebook, *, count_tokens: Counter) -> int:
    """Tokens to express the codebook as an in-context preamble (the READ-CODED
    price of admission: the model can't act on codes it can't translate)."""
    if not codebook.forward:
        return 0
    preamble = "\n".join(f"{code}={phrase}" for phrase, code in codebook.forward.items())
    return count_tokens(preamble)


def measure(messages: Iterable[str], codebook: Codebook, *,
            count_tokens: Counter) -> TokenDelta:
    """Measure token + byte deltas of compressing ``messages`` with ``codebook``.

    For each message we count tokens of the plain English (what the model sees
    today) against tokens of its encoded form (sentinels in place of repeated
    phrases). The aggregate ``pays_off`` is the whole question: did frontier
    tokens actually fall, or did the rare sentinels cost more than they saved?
    """
    msgs = [str(m) for m in messages]
    orig_tok = enc_tok = orig_b = enc_b = 0
    for m in msgs:
        e = encode(m, codebook)
        orig_tok += count_tokens(m)
        enc_tok += count_tokens(e)
        orig_b += len(m)
        enc_b += len(e)
    return TokenDelta(
        n_messages=len(msgs),
        original_tokens=orig_tok, encoded_tokens=enc_tok,
        original_bytes=orig_b, encoded_bytes=enc_b,
        codebook_tokens=codebook_token_cost(codebook, count_tokens=count_tokens),
    )


def tiktoken_counter(encoding: str = "cl100k_base") -> Counter:
    """A free, local BPE token counter (OpenAI's tiktoken). Not Anthropic's exact
    vocabulary, but a faithful proxy for the question that matters here -- whether
    rare sentinel codes tokenize worse than the common English they replace
    (true of every BPE tokenizer trained on natural text). Needs ``pip install
    tiktoken``."""
    import tiktoken

    enc = tiktoken.get_encoding(encoding)
    return lambda text: len(enc.encode(text))


def anthropic_counter(model: str) -> Counter:
    """The exact Anthropic token count, via the messages counting API. Needs an
    API key and network -- use this on the Mac mini for the authoritative number;
    use ``tiktoken_counter`` for a free offline proxy."""
    from anthropic import Anthropic

    client = Anthropic()

    def _count(text: str) -> int:
        resp = client.messages.count_tokens(
            model=model, messages=[{"role": "user", "content": text or " "}])
        return int(resp.input_tokens)

    return _count


def resolve_counter(*, encoding: str = "cl100k_base", model: str | None = None) -> Counter:
    """Pick a token counter: the Anthropic API when a ``model`` is given (exact),
    else the local tiktoken proxy. Raises a helpful error if neither is available."""
    if model:
        return anthropic_counter(model)
    try:
        return tiktoken_counter(encoding)
    except Exception as exc:  # pragma: no cover -- environment-dependent
        raise RuntimeError(
            "no token counter available: `pip install tiktoken` for a free local "
            "proxy, or pass a --model (with ANTHROPIC_API_KEY set) for the exact count"
        ) from exc


__all__ = [
    "TokenDelta", "Counter", "measure", "codebook_token_cost",
    "tiktoken_counter", "anthropic_counter", "resolve_counter",
]
