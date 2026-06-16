"""Tokenizer-aware emergent codec -- codes that actually save *tokens*.

The token probe (``codec_probe``) proved the audit-safe sentinel codes ``⟦n⟧``
cost ~5 tokens each, because the guillemets are rare unicode. On realistic
coordination traffic the sentinel codec saves ~50% of *bytes* but *loses* tokens
-- so the Rust->WASM carve (which only makes encode/decode faster) optimizes the
wrong axis. The measured ceiling is ~+41% tokens if each code is a single token
in the target model's vocabulary. This module chases that ceiling.

The tension it resolves: token-cheap characters are *common* (so they collide
with real message text), while collision-proof characters are *rare* (so they
tokenize expensively -- exactly why the sentinels fail). The fix is
**byte-stuffing**, which keeps the audit contract ``decode(encode(x)) == x``
exact for *any* input while letting codes be cheap, ~2-token strings:

    code_i  = ESCAPE + MARKER[i]            # 2 tokens when ESCAPE/MARKER are 1 token
    encode  : double every literal ESCAPE (E -> EE), then replace phrases by codes
    decode  : left-to-right scan -- EE is a literal escape, E+MARKER is a code

``ESCAPE`` and the ``MARKER`` pool are *injected* single-token strings (the
caller picks them from the model's tokenizer), so this module stays pure and
tokenizer-agnostic. With no usable pool, ``learn`` returns an empty codebook --
the identity transform -- so it is never worse than sending plain English.

Audit layer preserved: ``decode`` expands every code back to exact English, so
the Shield / a human still reads plain text while agents move the compressed
form. The round-trip is property-tested against adversarial inputs (content that
literally contains the escape and marker characters).
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from .emergent_protocol import learn as _learn_phrases


@dataclass(frozen=True)
class TokenCodebook:
    """A token-aware phrase<->code map. ``escape`` is the reserved stuffing byte;
    each code is ``escape + marker``. The reverse map is the audit layer."""

    escape: str = ""
    forward: dict = field(default_factory=dict)   # phrase -> code (escape+marker)
    reverse: dict = field(default_factory=dict)   # marker -> phrase

    @property
    def size(self) -> int:
        return len(self.forward)

    def to_dict(self) -> dict:
        return {"escape": self.escape, "forward": dict(self.forward)}


def learn(messages, *, escape: str, markers, max_codes: int = 128,
          min_count: int = 2, max_words: int = 6) -> TokenCodebook:
    """Learn a token-aware codebook from a coordination corpus.

    Reuses the phrase-scoring of the sentinel codec (the phrases worth coding are
    the same), then assigns each a cheap ``escape + marker`` code. ``escape`` and
    ``markers`` are caller-supplied single-token strings; any marker equal to the
    escape, or already present, is skipped. An empty/duplicate pool yields fewer
    codes; a fully unusable one yields the identity transform.
    """
    if not escape or not markers:
        return TokenCodebook(escape=escape)

    phrase_book = _learn_phrases(messages, max_codes=max_codes,
                                 min_count=min_count, max_words=max_words)
    pool = [m for m in dict.fromkeys(markers) if m and m != escape]

    forward, reverse = {}, {}
    for phrase, marker in zip(phrase_book.forward, pool, strict=False):  # pool may be shorter
        forward[phrase] = escape + marker
        reverse[marker] = phrase
    return TokenCodebook(escape=escape, forward=forward, reverse=reverse)


def encode(text: str, book: TokenCodebook) -> str:
    """Compress ``text``: stuff literal escapes, then replace phrases by codes.

    Doubling every literal ``escape`` first guarantees that, in the output, a lone
    ``escape`` (one not paired with another) can only be the start of a code -- the
    property ``decode`` relies on. An empty codebook is the identity."""
    if not book.forward or not book.escape:
        return text
    text = text.replace(book.escape, book.escape + book.escape)  # byte-stuff literals
    for phrase in sorted(book.forward, key=len, reverse=True):    # longest phrase wins
        text = text.replace(phrase, book.forward[phrase])
    return text


def decode(text: str, book: TokenCodebook) -> str:
    """The audit layer: expand codes to exact English and un-stuff literal escapes.

    A left-to-right scan is required (not ``str.replace``): ``escape+escape`` is a
    literal escape, while ``escape+marker`` is a code -- a naive replace would
    mis-handle content that itself contains the code bytes."""
    esc = book.escape
    if not esc or not book.reverse:
        return text
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == esc and i + 1 < n:
            nxt = text[i + 1]
            if nxt == esc:               # EE -> a literal escape
                out.append(esc)
                i += 2
                continue
            phrase = book.reverse.get(nxt)
            if phrase is not None:        # E + marker -> a code
                out.append(phrase)
                i += 2
                continue
        out.append(c)
        i += 1
    return "".join(out)


def token_savings(messages, book: TokenCodebook, *, count_tokens) -> float:
    """Percent of tokens saved over ``messages`` (negative == the codec costs more).
    The honest scoreboard: the whole reason this module exists is to make this
    positive where the sentinel codec couldn't."""
    orig = enc = 0
    for m in messages:
        m = str(m)
        orig += count_tokens(m)
        enc += count_tokens(encode(m, book))
    return (1.0 - enc / orig) * 100.0 if orig else 0.0


def single_token_markers(count_tokens, candidates, *, escape: str,
                         corpus=(), limit: int = 256) -> list[str]:
    """Pick collision-cheap markers: single-token ``candidates`` absent from the
    corpus (so they never need stuffing), excluding the escape. Pure -- the
    tokenizer is injected via ``count_tokens``.

    ``corpus`` absence is a token-saving nicety, not a correctness requirement:
    byte-stuffing keeps decode exact even if a marker appears in content.
    """
    seen = Counter()
    for m in corpus:
        seen.update(str(m))
    out: list[str] = []
    for cand in candidates:
        if cand == escape or cand in out:
            continue
        if seen.get(cand):
            continue                      # in the corpus -> would force stuffing
        if count_tokens(cand) != 1:
            continue                      # not a 1-token marker -> not cheap
        out.append(cand)
        if len(out) >= limit:
            break
    return out


__all__ = [
    "TokenCodebook", "learn", "encode", "decode",
    "token_savings", "single_token_markers",
]
