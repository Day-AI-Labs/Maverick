# Provider streaming parity audit (Q1 2026)

Status as of 2026-Q1 across all 8 BYOK + 5 session providers.

| Provider           | Sync `complete()` | Async `complete_async()` | Streams tokens | `on_delta` cb hook | Notes |
|--------------------|:-----------------:|:------------------------:|:--------------:|:-------------------:|-------|
| anthropic          | ✅                 | ✅                        | ✅              | ✅                  | Full streaming with thinking-block deltas. Reference impl. |
| openai             | ✅                 | ✅                        | partial         | —                   | Underlying SDK supports stream=True; current adapter is batch. **Action: enable stream by default.** |
| openrouter         | ✅                 | ✅                        | partial         | —                   | Inherits from openai adapter. Same upgrade unlocks this. |
| ollama             | ✅                 | ✅                        | partial         | —                   | Same. |
| moonshot           | ✅                 | ✅                        | partial         | —                   | Same. |
| deepseek           | ✅                 | ✅                        | partial         | —                   | Same. Bonus: cache-hit/miss tokens in usage. **Action: thread `prompt_cache_*_tokens` into Usage.** |
| xai                | ✅                 | ✅                        | partial         | —                   | Same. |
| gemini             | ✅                 | ✅                        | partial         | —                   | Same. Long context (1M); compaction matters less here. |
| chatgpt-session    | ✅                 | ✅                        | n/a (SSE)       | —                   | Native SSE parse already; result is single string. **Action: emit incremental updates.** |
| claude-session     | ✅                 | ✅                        | n/a (SSE)       | —                   | Same. |
| kimi-session       | ✅                 | ✅                        | n/a (SSE)       | —                   | Same. |
| grok-session       | ✅                 | ✅                        | n/a (NDJSON)    | —                   | Same. |
| gemini-session     | ✅                 | ✅                        | n/a (chunked)   | —                   | Same. |

## Concrete tracking issues

These are the gaps to file as individual issues; each is sized for
1-2 weeks of one engineer:

1. **openai_provider streaming-by-default**: replace `chat.completions.create(stream=False)` with the streaming SSE path; preserve current batch-style return semantics for callers that don't pass `on_delta`. Owner: providers maintainer.

2. **on_delta hook for the OpenAI-compatible family**: once #1 lands, wire `on_delta(text)` for openai / openrouter / ollama / moonshot / deepseek / xai / gemini. Anthropic adapter already does this — match its signature.

3. **DeepSeek context-caching usage fields**: pass through `prompt_cache_hit_tokens` and `prompt_cache_miss_tokens` from `Usage` into Maverick's `Budget.record_tokens(cache_read_tok=..., cache_write_tok=...)`.

4. **Gemini implicit-cache prefix ordering**: reorder messages so the system prompt + tools schema lands before any user content (Gemini 2.5 implicit-cache requires the prefix to be stable across requests).

5. **session-provider incremental emit**: refactor each session adapter's `_parse_*_response()` to emit partial text via an optional `on_delta` callback rather than only returning the final accumulated string.

6. **Anthropic prompt-caching audit**: verify `cache_control` breakpoints still fire as expected on Opus 4.7 + Sonnet 4.6 + Haiku 4.5; capture cache_read tokens in Budget. (Mostly working already; this is verification.)

## How we measure

- Add a `streaming_parity` regression test in `tests/test_provider_streaming.py` that uses a mock httpx server emitting SSE chunks; assert each provider's adapter emits N delta callbacks before terminating.
- Track `cache_read_tokens / total_input_tokens` ratio per provider in the Q1 baseline benchmark (see `baseline.q1-2026.json`).

## Done criteria

The audit closes when:
- Items 1-6 above are all merged.
- The regression test in `test_provider_streaming.py` covers every provider.
- The dashboard's per-provider health board (Q4 2026 perf item) shows non-zero stream_tokens for all providers.
