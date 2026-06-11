# Decision: JIT / AOT compilation of the hot path (mypyc / Cython)

**Status:** Decided — do not adopt; revisit on a measured trigger · **Roadmap
ref:** 2027-H2 Performance "JIT consideration (mypyc/cython on hot path)" ·
**Date:** June 2026

## Question

Should Maverick compile its hot path (tool dispatch, compaction, world-model
access) with mypyc or Cython for speed?

## Measurements (the deciding input)

The published perf SLA (`docs/perf-sla.md`, `python -m maverick.perf_sla`)
measures the real hot paths on a cold runner:

| Path | Measured (p95 / single-pass) | SLA threshold |
|---|---|---|
| Tool dispatch overhead | ~0.5 ms | 5 ms |
| Compaction, 200-message history | ~0.8 ms | 250 ms |
| World-model write (WAL append) | ~0.3 ms | 25 ms |
| World-model read (goal + 50 events) | ~4.6 ms | 25 ms |

Every hot path is **one to two orders of magnitude inside its SLA**, and all
of them are dwarfed by the costs that actually dominate a run: an LLM call
(hundreds of ms to seconds), sandboxed shell (tens of ms to minutes), network
I/O. Python-side CPU is not the bottleneck anywhere a user can feel.

## Decision

**Do not adopt mypyc or Cython.** The upside is microseconds nobody observes;
the costs are concrete:

- **Build matrix tax.** Compiled wheels per (OS × arch × CPython version)
  versus today's single pure-Python wheel — a large, permanent CI/release
  burden for a self-hosted product that installs everywhere.
- **Debuggability.** Tracebacks, `pdb`, hot-reload, and the plugin/subinterpreter
  isolation modes all degrade or break under compiled extensions.
- **Memory-safety posture.** We just *moved* C-extension parsing of untrusted
  bytes out of process (`parser_isolation.py`); compiling our own kernel into
  C extensions runs against that direction.
- **Where speed was needed, narrower fixes already shipped:** orjson behind
  the `[perf-fastjson]` extra (serialization), prompt caching + the
  cache-aware DSL (the real latency lever), async/tiered/streaming compaction.

## Revisit trigger

Reopen this decision only if the perf SLA harness shows a Python-CPU-bound
path breaching its threshold on reference hardware — i.e. the measurement
that motivated "no" reverses. The harness runs in CI, so the trigger is
continuously evaluated, not remembered.
