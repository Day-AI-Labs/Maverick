//! Python (PyO3) binding for `mvk-scan`. Compiles to the `maverick_native`
//! extension module; `maverick.safety.unicode_filter` imports it and falls
//! back to pure Python when it's absent.

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

/// Cheap boolean check (no NFKC), matching `unicode_filter.has_dangerous_unicode`.
#[pyfunction]
fn has_dangerous_unicode(text: &str) -> bool {
    mvk_scan::has_dangerous_unicode(text)
}

/// Strip dangerous Unicode; returns `(cleaned, removed_codepoints, categories)`
/// so the Python shim can rebuild its `UnicodeScanResult` without copying logic.
#[pyfunction]
#[pyo3(signature = (text, nfkc = true))]
fn normalize(text: &str, nfkc: bool) -> (String, Vec<u32>, Vec<String>) {
    let r = mvk_scan::normalize(text, nfkc);
    (r.cleaned, r.removed_codepoints, r.categories)
}

/// Secret scan: `(name, codepoint_start, codepoint_end)` triples in the exact
/// order/dedup of `secret_detector.scan`. Raises on any engine error so the
/// Python shim falls back to pure Python (fail-safe: never under-redact).
#[pyfunction]
fn secret_scan_spans(text: &str) -> PyResult<Vec<(String, usize, usize)>> {
    mvk_scan::secret::scan_spans(text).map_err(PyValueError::new_err)
}

/// PII scan: coalesced `(kind, codepoint_start, codepoint_end)` triples matching
/// `pii_detector.scan`. Raises on engine error or Luhn ambiguity (Python fallback).
#[pyfunction]
fn pii_scan_spans(text: &str) -> PyResult<Vec<(String, usize, usize)>> {
    mvk_scan::pii::scan_spans(text).map_err(PyValueError::new_err)
}

#[pymodule]
fn maverick_native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    m.add_function(wrap_pyfunction!(has_dangerous_unicode, m)?)?;
    m.add_function(wrap_pyfunction!(normalize, m)?)?;
    m.add_function(wrap_pyfunction!(secret_scan_spans, m)?)?;
    m.add_function(wrap_pyfunction!(pii_scan_spans, m)?)?;
    Ok(())
}
