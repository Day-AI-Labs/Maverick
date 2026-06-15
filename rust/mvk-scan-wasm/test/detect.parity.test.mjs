// WASM parity for the secret/PII detectors: the wasm-pack package built from
// the SAME `mvk-scan` core must produce exactly the (name/kind, start, end)
// codepoint spans the Python and Rust paths do. Expected values are computed
// from the pure-Python `secret_detector`/`pii_detector` and pinned here.
// Run: wasm-pack build --target nodejs --out-dir pkg --release && node --test
import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const wasm = require("../pkg/mvk_scan_wasm.js");

const triples = (rows) => rows.map((r) => [r.name, r.start, r.end]);

test("secretScanSpans matches the Python scanner (incl. codepoint offsets)", () => {
  // Fake credentials: the recognizable prefix is split from its body so no whole
  // token literal sits in the file (GitHub push protection), while the runtime
  // string -- and thus the spans -- is unchanged. // pragma: allowlist secret
  assert.deepEqual(
    triples(wasm.secretScanSpans("key sk-" + "ant-abcdefghijklmnopqrstuvwxyz0123456 trailing")),
    [["anthropic_api_key", 4, 44]],
  );
  // env_secret redacts only the value span, not the NAME= prefix.
  assert.deepEqual(
    triples(wasm.secretScanSpans("export INTERNAL_API_TOKEN=" + "supersecret123")),
    [["env_secret", 26, 40]],
  );
  assert.deepEqual(
    triples(wasm.secretScanSpans("ghp_" + "1234567890abcdefghijklmnopqrstuvwxyz token")),
    [["github_pat_classic", 0, 40]],
  );
  // Multibyte prefix: spans are codepoint indices ("é漢😀 " = 4), not bytes.
  assert.deepEqual(
    triples(wasm.secretScanSpans("é漢😀 sk-" + "ant-abcdefghijklmnopqrstuvwxyz01 done")),
    [["anthropic_api_key", 4, 39]],
  );
  assert.deepEqual(triples(wasm.secretScanSpans("")), []);
});

test("piiScanSpans matches the Python scanner (coalesced, codepoint offsets)", () => {
  assert.deepEqual(
    triples(wasm.piiScanSpans("ssn 123-45-6789 email a@b.com")),
    [["ssn", 4, 15], ["email", 22, 29]],
  );
  assert.deepEqual(
    triples(wasm.piiScanSpans("v6 2001:db8::dead:beef end")),
    [["ipv6", 3, 22]],
  );
  assert.deepEqual(
    triples(wasm.piiScanSpans("card 4111 1111 1111 1111 ok")),
    [["credit_card", 5, 24]],
  );
  // Multibyte prefix ("é漢 " = 3 codepoints) before an IPv4.
  assert.deepEqual(
    triples(wasm.piiScanSpans("é漢 192.168.0.1 x")),
    [["ipv4", 3, 14]],
  );
  assert.deepEqual(triples(wasm.piiScanSpans("")), []);
});
