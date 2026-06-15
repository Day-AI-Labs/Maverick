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
