//! Python (PyO3) binding for `mvk-scan`. Compiles to the `maverick_native`
//! extension module; `maverick.safety.unicode_filter` imports it and falls
//! back to pure Python when it's absent.

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

#[pymodule]
fn maverick_native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    m.add_function(wrap_pyfunction!(has_dangerous_unicode, m)?)?;
    m.add_function(wrap_pyfunction!(normalize, m)?)?;
    Ok(())
}
