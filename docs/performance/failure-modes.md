# Failure-mode taxonomy

Lightwork agent runs fail in a manageable set of ways. This doc
enumerates them so we can:

1. Tag every failed run with a canonical class.
2. Route retries differently per class (already wired in
   `retry_classifier.py`).
3. Track per-class regression in releases.

Tested in `tests/test_q1_2026_batch3.py::test_retry_classifier_*`.

## Classes

### `rate_limit`
HTTP 429 / explicit "rate limit" / "quota" / "too many requests"
in the error message. Retry with long backoff; respect
`Retry-After` header if present.

### `transient_network`
Connection timeouts, DNS failures, connection-reset, connection-
refused. Retry with short backoff; up to 8 attempts.

### `server_5xx`
Provider's fault. 500, 502, 503, 504. Retry with medium backoff
(4 attempts). If still failing, fail loud — there's nothing the
agent can do.

### `content_filter`
Provider refused on content-policy grounds. **Terminal**: do not
retry. The agent kernel surfaces the refusal as a FINAL with a
clear note so the user can decide whether the request was actually
disallowed or whether the provider was over-cautious.

### `auth`
401 / 403 / "invalid API key" / "authentication failed". **Terminal**:
do not retry. The user has to fix config.

### `context_overflow`
"context length exceeded" / "prompt too long for window" / "maximum
context". **Terminal**: do not retry as-is. Trigger compaction
upstream and re-dispatch (the orchestrator handles this in the
compaction.py module).

### `malformed_response`
Provider returned a 200 OK but the body didn't parse (truncated
JSON, broken SSE chunk). Retry ONCE — usually a fluke.

### `unknown`
Catch-all. Conservative: short backoff, 2 retries.

## How we classify

`maverick/retry_classifier.py`:

1. If the exception has `status_code` / `code` attribute, map by code.
2. Otherwise, regex-match against `f"{type(name)}: {message}"`.
3. Default to `unknown`.

Patterns are deliberately permissive: false positives (wrongly
classified) are cheaper than false negatives (mis-routed retry
strategy). Adding a new pattern requires a test in `test_retry_
classifier_substring_patterns`.

## Per-class regression tracking

The Q1 2026 baseline freeze captures each class's:

- Frequency per 100 runs
- Per-class retry success rate
- Per-class time-to-resolution

Subsequent releases compare against this baseline; regressions
file a tracking issue.

## Open work

- **Provider-specific error class extensions** (Q3 2026 perf
  roadmap item): some providers expose richer error categories
  (e.g., Anthropic's `overloaded_error` vs `api_error`) that we
  currently lump into `unknown`.
- **Adaptive retry policy** (Q2 2027 perf roadmap): learn per-task-
  class `max_retries` from observed outcomes instead of static
  policy table.
- **Cross-provider class-frequency dashboard** (Q3 2026 UX): show
  which providers fail in which ways over time, on the dashboard.
