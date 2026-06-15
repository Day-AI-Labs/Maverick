//! TypeScript / edge (WASM) binding for `mvk-scan`. Build with
//! `wasm-pack build --target web` to get an npm package the plugin-ts SDK (and
//! any edge runtime — Workers, Deno, browser) can import. Same logic as the
//! Python path, from the same core crate.

use serde::Serialize;
use wasm_bindgen::prelude::*;

#[derive(Serialize)]
struct ScanResult {
    cleaned: String,
    #[serde(rename = "removedCodepoints")]
    removed_codepoints: Vec<u32>,
    categories: Vec<String>,
}

/// `hasDangerousUnicode(text): boolean`
#[wasm_bindgen(js_name = hasDangerousUnicode)]
pub fn has_dangerous_unicode(text: &str) -> bool {
    mvk_scan::has_dangerous_unicode(text)
}

/// `normalize(text, nfkc?): { cleaned, removedCodepoints, categories }`
#[wasm_bindgen]
pub fn normalize(text: &str, nfkc: Option<bool>) -> Result<JsValue, JsValue> {
    let r = mvk_scan::normalize(text, nfkc.unwrap_or(true));
    let out = ScanResult {
        cleaned: r.cleaned,
        removed_codepoints: r.removed_codepoints,
        categories: r.categories,
    };
    serde_wasm_bindgen::to_value(&out).map_err(|e| JsValue::from_str(&e.to_string()))
}

#[derive(Serialize)]
struct Span {
    /// detector name (secrets) / kind (PII)
    name: String,
    /// codepoint start (matches Python `Match.span()`), not byte offset
    start: usize,
    end: usize,
}

fn spans_to_js(spans: Vec<(String, usize, usize)>) -> Result<JsValue, JsValue> {
    let out: Vec<Span> = spans
        .into_iter()
        .map(|(name, start, end)| Span { name, start, end })
        .collect();
    serde_wasm_bindgen::to_value(&out).map_err(|e| JsValue::from_str(&e.to_string()))
}

/// `secretScanSpans(text): [{ name, start, end }]` — parity with
/// `secret_detector.scan` (order + dedup preserved). Throws on engine error.
#[wasm_bindgen(js_name = secretScanSpans)]
pub fn secret_scan_spans(text: &str) -> Result<JsValue, JsValue> {
    let spans = mvk_scan::secret::scan_spans(text).map_err(|e| JsValue::from_str(&e))?;
    spans_to_js(spans)
}

/// `piiScanSpans(text): [{ name, start, end }]` — parity with `pii_detector.scan`
/// (coalesced). Throws on engine error or Luhn ambiguity.
#[wasm_bindgen(js_name = piiScanSpans)]
pub fn pii_scan_spans(text: &str) -> Result<JsValue, JsValue> {
    let spans = mvk_scan::pii::scan_spans(text).map_err(|e| JsValue::from_str(&e))?;
    spans_to_js(spans)
}
