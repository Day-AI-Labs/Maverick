"""Anthropic provider client.

Full implementation: prompt caching on system prompt + tool catalog
(ephemeral cache control), extended thinking on demand, streaming with
progress callbacks, sync + async client.

This is the canonical client; other providers translate to/from its
format.
"""
from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import Any

import anthropic

from ..budget import Budget
from ..llm import LLMResponse, ToolCall
from ..retry import async_retry, sync_retry

log = logging.getLogger(__name__)
# Module-level flag so we only emit the low-cache warning once per process.
_LOW_CACHE_WARNING_EMITTED: dict[str, bool] = {}


def _default_cache_ttl() -> str:
    """Wave 11: benchmark mode defaults to 5m TTL (no cross-instance
    reuse), interactive mode keeps 1h (multi-turn within a single
    long-running goal benefits from longer cache life).

    Explicit MAVERICK_ANTHROPIC_CACHE_TTL always wins.
    """
    explicit = os.environ.get("MAVERICK_ANTHROPIC_CACHE_TTL")
    if explicit:
        return explicit
    coding = os.environ.get("MAVERICK_CODING_MODE", "").lower() in ("1", "true", "yes")
    if coding:
        return "5m"
    return "1h"


def _ephemeral(obj: dict) -> dict:
    # Anthropic regressed the default cache TTL from 1h to 5m in early
    # March 2026 (issue #46829 on anthropics/claude-code). For agent
    # workloads -- where system prompts and tool catalogs are reused
    # across many turns inside a single goal -- 5m is too short and
    # forces ~20% extra spend on re-creates. Explicitly set 1h on every
    # cache control block so we get the discount we expect.
    # Wave 11: in coding-mode (SWE-bench style), default to 5m since
    # there is no cross-instance reuse and the 25% cache-write surcharge
    # on a 1h TTL is wasted.
    #
    # Wave 12 hotfix — minimum cacheable prompt size:
    # Claude Opus 4.5+, Sonnet 4.5+, and Haiku 4.5: the cumulative prompt
    # up to AND INCLUDING the cache breakpoint must be >= 4,096 tokens
    # or the breakpoint is silently ignored (no API error, no cache
    # write, no cache read on subsequent calls). Older Claude 4.x and
    # 3.x models use 1,024.
    #
    # Maverick's current system prompt (~1,085 tokens) + tool catalog
    # (~716 tokens) sit BELOW the 4,096 threshold individually, which
    # means cache_control on them is currently a no-op. The messages
    # breakpoint is the one that actually delivers caching on long
    # agent traces (history grows past 4k by turn 3-4). We still mark
    # system + tools with cache_control — it's harmless if the block
    # is too small, and starts working once the prompt expands.
    ttl = _default_cache_ttl()
    return {**obj, "cache_control": {"type": "ephemeral", "ttl": ttl}}


# Wave 12 hotfix: cacheable-block minimums per Anthropic model family.
# Used to warn / no-op cache_control when the prompt is too small.
_MIN_CACHE_TOKENS_4X = 4096
_MIN_CACHE_TOKENS_3X = 1024


def _min_cache_tokens(model_id: str) -> int:
    """Minimum cumulative prompt tokens (up to + including breakpoint)
    required for prompt caching to actually take effect.

    Claude 4.5+ (opus 4.5/4.6/4.7/4.8, sonnet 4.5/4.6, haiku 4.5): 4096.
    Earlier 4.x and all 3.x: 1024.
    """
    if (
        model_id.startswith("claude-opus-4-5")
        or model_id.startswith("claude-opus-4-6")
        or model_id.startswith("claude-opus-4-7")
        or model_id.startswith("claude-opus-4-8")
        or model_id.startswith("claude-sonnet-4-5")
        or model_id.startswith("claude-sonnet-4-6")
        or model_id.startswith("claude-haiku-4-5")
    ):
        return _MIN_CACHE_TOKENS_4X
    return _MIN_CACHE_TOKENS_3X


def _cached_system(text: str) -> list[dict]:
    return [_ephemeral({"type": "text", "text": text})]


def _cached_tools(tools: list[dict]) -> list[dict]:
    if not tools:
        return tools
    # Wave 12 (council F13d): sort tools by name BEFORE sending so the
    # tool catalog is byte-identical across calls — Anthropic's prompt
    # cache key includes the tools[] block, and a non-deterministic
    # order silently busts the cache write. Stable order = predictable
    # cache hits = 30-50% input cost reduction over the run.
    # Wave 12 hardening: coerce key via str() so a malformed tool with
    # name=None or non-string doesn't blow sorted() with TypeError.
    out = [dict(t) for t in sorted(
        tools, key=lambda t: str(t.get("name") or ""),
    )]
    out[-1] = _ephemeral(out[-1])
    return out


def _add_messages_cache_breakpoint(messages: list[dict]) -> list[dict]:
    """Mark the last user/tool_result message for caching.

    Wave 10: Anthropic prompt caching caches everything up to AND
    including the marked breakpoint. The system prompt + tools are
    already cached; the third breakpoint slot is best spent on the
    most recent stable turn so multi-turn agent loops (which re-send
    the entire history every step) get cache reads instead of writes
    for the message body. Empirically a 40-55% input cost reduction
    on long tool-use trajectories.

    We mutate the last block of the most recent non-final user message
    to add `cache_control`. Anthropic accepts cache_control on text /
    tool_result / image blocks; we target the last block of any kind.
    """
    if not messages or len(messages) < 2:
        return messages
    # Find the most recent user message that's NOT the final one (the
    # final user message changes every turn -- caching it would write
    # a fresh cache entry every call, the OPPOSITE of what we want).
    target_idx = None
    for i in range(len(messages) - 2, -1, -1):
        if messages[i].get("role") == "user":
            target_idx = i
            break
    if target_idx is None:
        return messages
    msg = messages[target_idx]
    content = msg.get("content")
    if isinstance(content, str):
        # String content: convert to a single text block so we can attach
        # cache_control. Anthropic accepts mixed string + block forms.
        new_content = [{"type": "text", "text": content,
                        "cache_control": {"type": "ephemeral",
                                          "ttl": _default_cache_ttl()}}]
        new_messages = list(messages)
        new_messages[target_idx] = {**msg, "content": new_content}
        return new_messages
    if isinstance(content, list) and content:
        # Block list: copy + mark the LAST block with cache_control.
        new_blocks = [dict(b) for b in content]
        last = new_blocks[-1]
        last["cache_control"] = {
            "type": "ephemeral",
            "ttl": _default_cache_ttl(),
        }
        new_blocks[-1] = last
        new_messages = list(messages)
        new_messages[target_idx] = {**msg, "content": new_blocks}
        return new_messages
    return messages


class AnthropicClient:
    DEFAULT_MODEL = "claude-sonnet-4-6"

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        # May 26 council fix (long-tail audit #1): strip whitespace.
        # `export ANTHROPIC_API_KEY=$(cat key.txt)` is a common source of
        # trailing newline; without strip, every API call 401s and the
        # operator sees "API outage" instead of the real "key has
        # whitespace" issue.
        key = (api_key or os.environ.get("ANTHROPIC_API_KEY") or "").strip() or None
        from .base import llm_http_timeout
        kw: dict = {"api_key": key}
        timeout = llm_http_timeout()
        if timeout is not None:
            kw["timeout"] = timeout
        self.client = anthropic.Anthropic(**kw)
        self.aclient = anthropic.AsyncAnthropic(**kw)

    def _build_request(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict] | None,
        max_tokens: int,
        thinking_budget: int | None,
        model: str | None,
    ) -> dict[str, Any]:
        # Wave 10: cache the most recent stable user message so repeated
        # tool-use turns hit the cache for the history (40-55% input
        # token cost cut on long trajectories). Toggle via env var so
        # the dashboard can A/B it.
        if os.environ.get("MAVERICK_CACHE_MESSAGES", "1") != "0":
            messages_out = _add_messages_cache_breakpoint(messages)
        else:
            messages_out = messages

        kwargs: dict[str, Any] = {
            "model": model or self.DEFAULT_MODEL,
            "system": _cached_system(system),
            "messages": messages_out,
            "max_tokens": max_tokens,
        }
        if tools:
            kwargs["tools"] = _cached_tools(tools)

        # Wave 12 hotfix: note (at DEBUG, once per model) when system+tools is
        # below the min-cache threshold. The cache_control markers are silently
        # ignored in that case — we still set them so caching kicks in if/when
        # the prompt grows. Kept at debug, not warning: the consumer CLI installs
        # no log handler, so a WARNING bleeds straight onto the terminal in the
        # middle of a normal `chat` / `start` run. Operators who want it can
        # raise the log level (e.g. MAVERICK_DEBUG=1).
        model_for_min = kwargs["model"] or ""
        min_tokens = _min_cache_tokens(model_for_min)
        if not _LOW_CACHE_WARNING_EMITTED.get(model_for_min):
            # Heuristic token estimate: 4 chars/token.
            sys_tok = len(system or "") // 4
            tools_tok = (
                sum(len(str(t)) for t in (tools or [])) // 4
            )
            if sys_tok + tools_tok < min_tokens:
                log.debug(
                    "prompt cache no-op: system+tools=%d tok (~%d sys + ~%d tools) "
                    "< %d-token min for %s. cache_control on system/tools "
                    "is ignored; only the messages breakpoint will cache "
                    "once history grows past %d tokens. Expand the system "
                    "prompt or tool descriptions to unlock system/tool caching.",
                    sys_tok + tools_tok, sys_tok, tools_tok,
                    min_tokens, model_for_min, min_tokens,
                )
                _LOW_CACHE_WARNING_EMITTED[model_for_min] = True
        # Wave 12 hotfix: thinking + interleaved-thinking handling per
        # Anthropic's May 2026 docs (platform.claude.com/docs/.../adaptive-thinking):
        #
        #   - Opus 4.7:  ONLY adaptive mode accepted. Manual
        #                `thinking={"type":"enabled"}` returns 400.
        #                Interleaved thinking is automatic — no header.
        #   - Opus 4.6 / Sonnet 4.6 / Haiku 4.5: interleaved is automatic
        #                in adaptive mode; the beta header is deprecated
        #                and ignored.
        #   - Sonnet 4.5 / Opus 4.5 and older: the
        #                `interleaved-thinking-2025-05-14` header is
        #                still required to get interleaved behavior.
        #
        # An earlier Wave 12 commit set the beta header unconditionally
        # for any "claude-opus-/claude-sonnet-4" prefix — that breaks
        # against Opus 4.7 (400) and is wasted noise on 4.6.
        model_id = (model or self.DEFAULT_MODEL) or ""
        # Opus 4.7 AND 4.8 (the current default, incl. its `-fast` variant)
        # only accept adaptive thinking; manual `enabled` returns 400.
        # Gating on 4-7 alone left the default model on the `enabled` path.
        is_opus_47 = (
            model_id.startswith("claude-opus-4-7")
            or model_id.startswith("claude-opus-4-8")
        )
        is_modern_4x = (
            model_id.startswith("claude-opus-4-6")
            or model_id.startswith("claude-opus-4-7")
            or model_id.startswith("claude-opus-4-8")
            or model_id.startswith("claude-sonnet-4-6")
            or model_id.startswith("claude-haiku-4-5")
        )
        legacy_thinking_header_required = (
            model_id.startswith("claude-opus-4-5")
            or model_id.startswith("claude-sonnet-4-5")
        )

        if thinking_budget and thinking_budget > 0:
            kwargs["max_tokens"] = max(max_tokens, thinking_budget + 1024)
            if is_opus_47:
                # Opus 4.7 rejects explicit "enabled"; only "adaptive"
                # is supported. Drop budget_tokens — adaptive auto-sizes.
                kwargs["thinking"] = {"type": "adaptive"}
            else:
                kwargs["thinking"] = {
                    "type": "enabled", "budget_tokens": thinking_budget,
                }

        # Beta header gating — only set on legacy models that still need it.
        if legacy_thinking_header_required and "thinking" in kwargs:
            extra_headers = kwargs.get("extra_headers", {})
            beta = extra_headers.get("anthropic-beta", "")
            betas = [b.strip() for b in beta.split(",") if b.strip()]
            if "interleaved-thinking-2025-05-14" not in betas:
                betas.append("interleaved-thinking-2025-05-14")
            extra_headers["anthropic-beta"] = ",".join(betas)
            kwargs["extra_headers"] = extra_headers
        # For 4.6 and 4.7 models, interleaved is automatic in adaptive
        # mode — no header needed. Note: even WITHOUT thinking_budget,
        # callers may want adaptive default on Opus 4.7. Surface that:
        if is_opus_47 and "thinking" not in kwargs:
            # Opus 4.7 with no explicit thinking spec: let the model
            # decide via adaptive. This matches the docs' "adaptive is
            # the only supported mode" guidance.
            kwargs["thinking"] = {"type": "adaptive"}
            # May 26 council fix (API audit #18): adaptive thinking
            # can spend the entire `max_tokens` budget on thinking and
            # leave nothing for the tool_use / text output, producing
            # an empty response. Bump headroom for adaptive runs.
            kwargs["max_tokens"] = max(max_tokens, 16384)
        _ = is_modern_4x  # documented above; kept for future logic
        # Wave 10 (D1): orchestrator best-of-N sets MAVERICK_TEMPERATURE
        # per attempt to force candidate diversity. Wire it through here
        # so the provider actually honours it -- before this fix the env
        # var was set but read by nothing, and best-of-N produced
        # N identical answers.
        # Thinking models reject explicit temperature (400). Gate on whether
        # `thinking` actually ended up in the request -- not on thinking_budget,
        # which misses the adaptive-thinking auto-injected for Opus 4.7/4.8 just
        # above (that path set thinking_budget=None yet still sends thinking, so
        # the old gate let temperature through and the API 400'd).
        temp_str = os.environ.get("MAVERICK_TEMPERATURE")
        if temp_str and "thinking" not in kwargs:
            try:
                kwargs["temperature"] = float(temp_str)
            except ValueError:
                pass
        return kwargs

    def _parse_response(
        self,
        resp: Any,
        budget: Budget | None,
        model: str | None = None,
    ) -> LLMResponse:
        text_parts: list[str] = []
        thinking_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        # May 26 council fix (API audit #1): preserve PER-BLOCK
        # signatures. With Opus 4.7 interleaved thinking, a single
        # turn can emit multiple thinking blocks, each with its own
        # signature derived from that block's text. Concatenating
        # text but keeping only the first signature broke the
        # second turn (Anthropic rejects the assistant message
        # because the signature doesn't match the text).
        thinking_blocks: list[tuple[str, str | None]] = []
        # May 28 fix: capture blocks in their ORIGINAL order. Anthropic
        # rejects a rearranged thinking-block sequence ("the latest
        # assistant message ... cannot be modified"), which the old
        # bucket-by-type reconstruction triggered on interleaved Opus
        # 4.7 turns (thinking between tool_use). We replay these verbatim.
        content_blocks: list[dict] = []
        for block in resp.content:
            t = getattr(block, "type", None)
            if t == "text":
                text_parts.append(block.text)
                content_blocks.append({"type": "text", "text": block.text})
            elif t == "thinking":
                text = getattr(block, "thinking", "")
                sig = getattr(block, "signature", None)
                thinking_parts.append(text)
                thinking_blocks.append((text, sig))
                tb: dict = {"type": "thinking", "thinking": text}
                if sig:
                    tb["signature"] = sig
                content_blocks.append(tb)
            elif t == "redacted_thinking":
                # Opaque, signature-bearing block. The old loop dropped
                # these entirely, which also breaks the "must match the
                # original response" contract — echo it back unchanged.
                data = getattr(block, "data", None)
                rb: dict = {"type": "redacted_thinking"}
                if data is not None:
                    rb["data"] = data
                content_blocks.append(rb)
            elif t == "tool_use":
                tool_calls.append(ToolCall(id=block.id, name=block.name, input=dict(block.input)))
                content_blocks.append({
                    "type": "tool_use", "id": block.id,
                    "name": block.name, "input": dict(block.input),
                })

        # Wave 12 (council F13c) + hardening: nullsafe usage parsing.
        # If resp.usage itself is None (streaming refusal), getattr
        # chains through 0 defaults. Coerce all values via int() inside
        # a try block to catch non-int truthy values (string "100" from
        # a mock, Decimal from a future SDK schema).
        usage = getattr(resp, "usage", None)

        def _safe_int(value, default=0) -> int:
            try:
                return int(value) if value is not None else default
            except (TypeError, ValueError):
                return default

        cache_creation = _safe_int(getattr(usage, "cache_creation_input_tokens", 0))
        cache_read = _safe_int(getattr(usage, "cache_read_input_tokens", 0))
        in_tok = _safe_int(getattr(usage, "input_tokens", 0))
        out_tok = _safe_int(getattr(usage, "output_tokens", 0))

        if budget is not None:
            # ``usage.input_tokens`` is non-cached input only. Cache reads
            # and writes are billed separately at different rates.
            budget.record_tokens(
                in_tok, out_tok,
                model=model,
                cache_read_tok=cache_read,
                cache_write_tok=cache_creation,
                # Wave 12: pass TTL so write surcharge math matches the
                # actual breakpoint TTL (5m vs 1h).
                cache_write_ttl=_default_cache_ttl(),
            )

        # Per-turn observability — log model + cache stats so operators
        # can verify caching is actually engaging on real API calls.
        # Gated on MAVERICK_LOG_TURNS to keep production logs quiet.
        # Print direct to stderr so it survives default-level logging
        # filters (log.info doesn't print by default).
        if os.environ.get("MAVERICK_LOG_TURNS"):
            import sys as _sys
            _sys.stderr.write(
                f"llm_turn model={model or 'default'} "
                f"in={in_tok} out={out_tok} "
                f"cache_read={cache_read} cache_write={cache_creation} "
                f"stop={resp.stop_reason}\n"
            )
            _sys.stderr.flush()

        return LLMResponse(
            text="\n".join(text_parts).strip(),
            thinking="\n".join(thinking_parts).strip() or None,
            thinking_blocks=thinking_blocks,
            thinking_signature=(
                thinking_blocks[0][1] if thinking_blocks else None
            ),
            content_blocks=content_blocks,
            tool_calls=tool_calls,
            stop_reason=resp.stop_reason,
            cache_creation_tokens=cache_creation,
            cache_read_tokens=cache_read,
            raw=resp,
        )

    def complete(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        budget: Budget | None = None,
        max_tokens: int = 4096,
        thinking_budget: int | None = None,
        model: str | None = None,
        on_delta: Callable[[str], None] | None = None,
    ) -> LLMResponse:
        kwargs = self._build_request(system, messages, tools, max_tokens, thinking_budget, model)
        if on_delta is None:
            resp = sync_retry(lambda: self.client.messages.create(**kwargs))
            return self._parse_response(resp, budget, model=kwargs.get("model"))

        # Council finding: wrapping the streaming path in sync_retry
        # would replay every on_delta callback after a mid-stream
        # failure, so consumers see duplicate prefixes. Streaming is
        # called from interactive paths (CLI --stream, dashboard chat);
        # surface the error directly and let the caller retry the
        # higher-level request without partial output.
        with self.client.messages.stream(**kwargs) as stream:
            for event in stream.text_stream:
                on_delta(event)
            final = stream.get_final_message()
        return self._parse_response(final, budget, model=kwargs.get("model"))

    async def complete_async(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        budget: Budget | None = None,
        max_tokens: int = 4096,
        thinking_budget: int | None = None,
        model: str | None = None,
    ) -> LLMResponse:
        kwargs = self._build_request(system, messages, tools, max_tokens, thinking_budget, model)
        resp = await async_retry(lambda: self.aclient.messages.create(**kwargs))
        return self._parse_response(resp, budget, model=kwargs.get("model"))
