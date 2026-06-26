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

/// Average-hash of row-major RGB `pixels`, as 16 hex chars. Mirrors
/// `perceptual_hash.average_hash_from_pixels`; raises `ValueError` on a
/// dimension mismatch so the Python shim falls back to pure Python.
#[pyfunction]
fn average_hash_from_pixels(
    pixels: Vec<(i64, i64, i64)>,
    width: usize,
    height: usize,
) -> PyResult<String> {
    mvk_scan::phash::average_hash_from_pixels(&pixels, width, height)
        .map_err(PyValueError::new_err)
}

/// Average-hash of a contiguous row-major RGB byte buffer (e.g. PIL's
/// `Image.tobytes()`). The hot path: the image crosses FFI as one `bytes`
/// object, not a million tuples. Mirrors `average_hash_from_pixels` bit-for-bit.
#[pyfunction]
fn average_hash_from_rgb_bytes(rgb: &[u8], width: usize, height: usize) -> PyResult<String> {
    mvk_scan::phash::average_hash_from_rgb_bytes(rgb, width, height)
        .map_err(PyValueError::new_err)
}

/// Bit distance between two 16-hex-char hashes. Mirrors `perceptual_hash.hamming`.
#[pyfunction]
fn hamming(a: &str, b: &str) -> PyResult<u32> {
    mvk_scan::phash::hamming(a, b).map_err(PyValueError::new_err)
}

#[pymodule]
fn maverick_native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    m.add_function(wrap_pyfunction!(has_dangerous_unicode, m)?)?;
    m.add_function(wrap_pyfunction!(normalize, m)?)?;
    m.add_function(wrap_pyfunction!(secret_scan_spans, m)?)?;
    m.add_function(wrap_pyfunction!(pii_scan_spans, m)?)?;
    m.add_function(wrap_pyfunction!(average_hash_from_pixels, m)?)?;
    m.add_function(wrap_pyfunction!(average_hash_from_rgb_bytes, m)?)?;
    m.add_function(wrap_pyfunction!(hamming, m)?)?;
    Ok(())
}
