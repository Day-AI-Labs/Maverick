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

## Parity

`packages/maverick-core/tests/test_native_unicode_parity.py` proves the Python
native path equals the pure-Python path; `mvk-scan-wasm/test/parity.test.mjs`
proves the WASM path equals it too. All three run off the same `mvk-scan` core,
so they cannot diverge.

## Carve order (next)

Same pattern, profiler-gated: secret/PII detectors -> world-model access ->
blackboard/budget -> compaction/tokenization -> the native agent-host daemon
(density / cold-start). The ~80-90% that stays Python+TS: tools, packs, skills,
providers, dashboard, channels.
