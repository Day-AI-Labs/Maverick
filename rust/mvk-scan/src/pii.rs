//! Native port of `maverick.safety.pii_detector.scan`.
//!
//! Faithful reproduction: the SAME six anchored patterns (email, ssn, ipv4,
//! ipv6, phone_us, street_address) emitted in that order, then Luhn-validated
//! credit cards, then the SAME overlap-coalescing (stable sort by
//! `(start, -len)`, merge clusters keeping the first kind). The phone and SSN
//! patterns use look-behind / look-ahead — the reason this carve needs
//! `fancy-regex` rather than the `regex` crate. We return only
//! `(kind, cp_start, cp_end)`; the Python shim attaches the constant mask and
//! splices, so it can never drift from the pure-Python redactor.

use crate::{byte_spans_to_char, compile_pattern};
use fancy_regex::Regex;
use std::sync::LazyLock;

// (kind, pattern). Order is load-bearing for the stable-sort tie-break in
// `coalesce`, so it mirrors the tuple order in pii_detector.scan exactly.
static DEFS: &[(&str, &str)] = &[
    (
        "email",
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
    ),
    (
        "ssn",
        r"\b(?!000|666|9\d{2})\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b",
    ),
    (
        "ipv4",
        r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b",
    ),
    (
        "ipv6",
        // Compressed + full forms, alternatives ordered by DESCENDING trailing
        // hextet count so leftmost-first picks the longest — identical to the
        // Python ordering and its comments.
        r"(?:(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}|:(?::[0-9a-fA-F]{1,4}){1,7}|[0-9a-fA-F]{1,4}:(?::[0-9a-fA-F]{1,4}){1,6}|(?:[0-9a-fA-F]{1,4}:){1,2}(?::[0-9a-fA-F]{1,4}){1,5}|(?:[0-9a-fA-F]{1,4}:){1,3}(?::[0-9a-fA-F]{1,4}){1,4}|(?:[0-9a-fA-F]{1,4}:){1,4}(?::[0-9a-fA-F]{1,4}){1,3}|(?:[0-9a-fA-F]{1,4}:){1,5}(?::[0-9a-fA-F]{1,4}){1,2}|(?:[0-9a-fA-F]{1,4}:){1,6}:[0-9a-fA-F]{1,4}|(?:[0-9a-fA-F]{1,4}:){1,7}:|::)",
    ),
    // Leading (?<!\d) look-behind stops a 10-digit sub-run of a longer number.
    (
        "phone_us",
        r"(?<!\d)(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b",
    ),
    (
        "street_address",
        r"\b\d{1,5}\s+(?:[A-Z][a-z]+\s+){1,3}(?:Street|St|Avenue|Ave|Boulevard|Blvd|Road|Rd|Lane|Ln|Drive|Dr|Court|Ct|Way|Parkway|Pkwy|Place|Pl)\b",
    ),
];

// Credit-card candidate: 13-19 digit-ish run; Luhn-checked separately.
static CC: &str = r"\b(?:\d[ -]*?){13,19}\b";

struct Compiled {
    kind: &'static str,
    re: Regex,
}

static PATTERNS: LazyLock<Vec<Compiled>> = LazyLock::new(|| {
    DEFS.iter()
        .map(|(kind, pat)| Compiled {
            kind,
            re: compile_pattern(pat).expect("pii pattern must compile"),
        })
        .collect()
});

static CC_RE: LazyLock<Regex> =
    LazyLock::new(|| compile_pattern(CC).expect("cc pattern must compile"));

/// Standard Luhn over the ASCII digits in `candidate`.
///
/// Returns `Err` if the candidate carries a non-ASCII Unicode digit: Python's
/// `\d` / `int()` would fold those in with their decimal value, which Rust's
/// `to_digit` can't reproduce. Rather than risk a silent mismatch we signal
/// ambiguity so the caller falls back to pure Python. The CC regex only ever
/// matches `\d`, space and `-`, so any char outside `[0-9 -]` is exactly such a
/// Unicode digit.
fn luhn_ascii(candidate: &str) -> Result<bool, String> {
    let mut digits: Vec<u8> = Vec::with_capacity(candidate.len());
    for c in candidate.chars() {
        if c.is_ascii_digit() {
            digits.push((c as u8) - b'0');
        } else if c == ' ' || c == '-' {
            continue;
        } else {
            return Err("non-ascii digit in credit-card candidate".to_string());
        }
    }
    if !(13..=19).contains(&digits.len()) {
        return Ok(false);
    }
    let parity = digits.len() % 2;
    let mut total = 0u32;
    for (i, &d) in digits.iter().enumerate() {
        let mut d = d as u32;
        if i % 2 == parity {
            d *= 2;
            if d > 9 {
                d -= 9;
            }
        }
        total += d;
    }
    Ok(total.is_multiple_of(10)) // Python: total % 10 == 0
}

/// Mirror of `pii_detector.scan`, returning coalesced `(kind, cp_start, cp_end)`
/// triples. `Err` on any engine failure or Luhn ambiguity so the caller can fall
/// back to pure Python (fail-safe).
pub fn scan_spans(text: &str) -> Result<Vec<(String, usize, usize)>, String> {
    if text.is_empty() {
        return Ok(Vec::new());
    }
    // Raw byte-offset matches in Python's insertion order.
    let mut raw: Vec<(&'static str, usize, usize)> = Vec::new();
    for pat in PATTERNS.iter() {
        for m in pat.re.find_iter(text) {
            let m = m.map_err(|e| e.to_string())?;
            raw.push((pat.kind, m.start(), m.end()));
        }
    }
    for m in CC_RE.find_iter(text) {
        let m = m.map_err(|e| e.to_string())?;
        if luhn_ascii(m.as_str())? {
            raw.push(("credit_card", m.start(), m.end()));
        }
    }
    // Convert to codepoint spans BEFORE coalescing so the sort/merge runs in the
    // exact units Python uses (byte vs codepoint length can reorder equal-start
    // overlaps on non-ASCII input).
    let char_spans = byte_spans_to_char(text, raw);
    Ok(coalesce(char_spans))
}

/// Port of the coalescing tail of `pii_detector.scan`: stable sort by
/// `(start, -len)`, then merge each overlap cluster into one span keeping the
/// FIRST (sort-order) kind. `char_spans` is already in Python insertion order so
/// the stable sort breaks `(start, -len)` ties identically.
fn coalesce(mut char_spans: Vec<(String, usize, usize)>) -> Vec<(String, usize, usize)> {
    char_spans.sort_by(|a, b| {
        let la = a.2 - a.1;
        let lb = b.2 - b.1;
        a.1.cmp(&b.1).then(lb.cmp(&la)) // start asc, then length desc
    });
    let mut out: Vec<(String, usize, usize)> = Vec::new();
    for m in char_spans {
        match out.last_mut() {
            Some(prev) if m.1 < prev.2 => {
                // Overlaps the current cluster: extend its end if needed, keep kind.
                let merged_end = prev.2.max(m.2);
                if merged_end != prev.2 {
                    prev.2 = merged_end;
                }
            }
            _ => out.push(m),
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn kinds(text: &str) -> Vec<String> {
        scan_spans(text).unwrap().into_iter().map(|m| m.0).collect()
    }

    #[test]
    fn detects_email_and_ssn_and_ipv6() {
        assert_eq!(kinds("a@b.com"), vec!["email"]);
        assert_eq!(kinds("123-45-6789"), vec!["ssn"]);
        assert_eq!(kinds("addr 2001:db8::1 here"), vec!["ipv6"]);
    }

    #[test]
    fn ssn_rejects_invalid_area() {
        assert!(kinds("000-12-3456").is_empty());
        assert!(kinds("666-12-3456").is_empty());
    }

    #[test]
    fn phone_not_a_subrun_of_longer_number() {
        // (?<!\d) means a 13-digit run is not redacted as a phone.
        assert!(!kinds("1234567890123").contains(&"phone_us".to_string()));
    }

    #[test]
    fn credit_card_luhn() {
        assert_eq!(kinds("4111 1111 1111 1111"), vec!["credit_card"]);
        assert!(kinds("4111 1111 1111 1112").is_empty());
    }
}
