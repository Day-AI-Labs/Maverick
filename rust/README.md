# Maverick native core (`rust/`)

The Rust "engine" carve. Per the architecture review (Karpathy / Cloudflare /
Pydantic / ServiceNow / Palo Alto): **rewrite the hot engine in Rust, keep the
ecosystem in Python + TypeScript.** One pure-logic core crate is exposed to both
runtimes through thin bindings — never a rewrite of the agent loop, the tools, or
the 1,022 packs.

```
mvk-scan/        core logic (pure Rust, no FFI) — the only place behaviour lives
mvk-scan-py/     PyO3 binding  -> Python extension module `maverick_native`
mvk-scan-wasm/   wasm-bindgen  -> npm/edge package (TypeScript, Workers, Deno)
```

## Why

The safety scanners run on **every** agent input and tool output and are pure
CPU — exactly the kind of hot, GIL-bound work that belongs in native code. The
pilot module is the unicode scanner (`maverick.safety.unicode_filter`); it's a
faithful port, and Python keeps a **fallback shim** so a build *without* the
native wheel is byte-identical to today. The native module is a drop-in
accelerator, never a new hard dependency.

## Measured speedup (native vs pure Python, same machine)

The reason the carve is worth it — the unicode scanner alone:

| call | input | speedup |
|---|---|---|
| `normalize` | ~30 B (a command) | **3.0×** |
| `normalize` | ~2 KB (a prompt) | **5.0×** |
| `normalize` | ~54 KB (a tool output) | **5.4×** |
| `has_dangerous_unicode` | ~54 KB | **50.7×** |

`has_dangerous_unicode` runs on *every* input; the per-char Python loop is the
worst case and Rust's short-circuit scan is ~50× faster. Even the smallest input
(where FFI overhead is highest) is 3×. This is per-call latency; the bigger win
is density — the native path is GIL-free, so parallel swarm scanning no longer
serializes.

## Build

Python wheel (the `maverick_native` extension):

```bash
cd rust/mvk-scan-py
maturin build --release          # -> rust/target/wheels/maverick_native-*.whl
pip install rust/target/wheels/maverick_native-*.whl
# maverick.safety.unicode_filter now uses it automatically; absent => pure Python
```

TypeScript / edge package (WASM):

```bash
cd rust/mvk-scan-wasm
wasm-pack build --target nodejs --out-dir pkg --release   # node/CommonJS
# or: --target web / --target bundler  for browsers / Workers / Deno
node --test test/parity.test.mjs                          # parity vs Python
```

Core unit tests: `cd rust && cargo test -p mvk-scan`.

## Modules carved so far

| core module | role | Python hot path | engine |
|---|---|---|---|
| `unicode` | accelerator | **wired in** (3–50× faster) | `unicode-normalization` |
| `secret` | edge/TS + parity | **pure `re`** (native was slower) | `fancy-regex` |
| `pii` | edge/TS + parity | **pure `re`** (native ~break-even) | `fancy-regex` |

The secret/PII carve is **carve #2**, and it taught a real lesson: not every hot
CPU module is a Rust win. Unlike the unicode scanner (a per-char *Python* loop),
the detectors already run on CPython's compiled `re`. Measured on the same
machine, the native port — 21 separate `fancy-regex` passes — was **~3× slower
for secrets** and roughly break-even for PII:

| scan | input | pure-Python `re` | native | result |
|---|---|---|---|---|
| `secret` | 2 KB / 60 KB (clean) | 0.44 / 12.9 ms | 1.31 / 39.4 ms | native **0.33×** |
| `pii` | 60 KB clean / dense | 32.6 / 30.1 ms | 30.8 / 27.6 ms | native ~1.06–1.09× |

So the detectors **stay pure `re` on the Python hot path** (the shield, the audit
log). The native build is retained for the **TypeScript / edge** runtimes
(Workers, Deno, browser) that have no `re` at all, where it's the only option —
and `test_native_detect_parity.py` keeps it byte-for-byte identical to Python so
the two never drift. The `regex` crate can't do the PII phone/SSN look-behind /
look-ahead, hence `fancy-regex`; and the detectors are security-critical, so the
native side **fails safe** — any engine error, or a Luhn-ambiguous
non-ASCII-digit card candidate, raises rather than guessing.

## Parity

Spans are reported as **codepoint** indices (Python `re.span()` semantics), not
byte offsets, so redaction is byte-identical on non-ASCII text.

- `tests/test_native_unicode_parity.py` — unicode native path == pure Python.
- `tests/test_native_detect_parity.py` — the native extension's secret + PII
  output == pure-Python `scan`, plus a deterministic differential fuzz (an
  offline run over 24k inputs found zero mismatches).
- `mvk-scan-wasm/test/{parity,detect.parity}.test.mjs` — the WASM path == pure
  Python too.

All run off the same `mvk-scan` core, so they cannot diverge.

## Carve order (next)

Same pattern, profiler-gated: ~~secret/PII detectors~~ (done) -> world-model
access -> blackboard/budget -> compaction/tokenization -> the native agent-host
daemon (density / cold-start). The ~80-90% that stays Python+TS: tools, packs,
skills, providers, dashboard, channels.
