//! Native safety scanners — pure logic shared by the Python (PyO3) and
//! TypeScript (WASM) bindings. No FFI here.
//!
//! This is a faithful port of `maverick.safety.unicode_filter`: strip
//! zero-width, bidi-override (Trojan Source) and Unicode tag-block characters,
//! NFKC-normalizing first so look-alikes canonicalize. The Python module keeps
//! a pure fallback so behaviour is identical whether or not this is compiled in.

use unicode_normalization::UnicodeNormalization;

/// Zero-width / invisible code points.
const ZERO_WIDTH: [u32; 5] = [0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF];

/// Bidirectional override block (the "Trojan Source" attack vector).
const BIDI_OVERRIDES: [u32; 12] = [
    0x200E, 0x200F, 0x061C, 0x202A, 0x202B, 0x202C, 0x202D, 0x202E, 0x2066, 0x2067, 0x2068, 0x2069,
];

/// Unicode tag block (E0000–E007F): invisible, used for steganographic injection.
const TAG_BLOCK_START: u32 = 0xE0000;
const TAG_BLOCK_END: u32 = 0xE007F;

/// Result of [`normalize`]: cleaned text + the code points that were stripped +
/// the (order-preserving, de-duplicated) categories that actually fired.
pub struct UnicodeScanResult {
    pub cleaned: String,
    pub removed_codepoints: Vec<u32>,
    pub categories: Vec<String>,
}

fn category_for(cp: u32) -> Option<&'static str> {
    if ZERO_WIDTH.contains(&cp) {
        Some("zero_width")
    } else if BIDI_OVERRIDES.contains(&cp) {
        Some("bidi_override")
    } else if (TAG_BLOCK_START..=TAG_BLOCK_END).contains(&cp) {
        Some("tag_block")
    } else {
        None
    }
}

/// Strip dangerous Unicode and (optionally) NFKC-normalize first.
///
/// Mirrors `unicode_filter.normalize`: empty input is returned untouched;
/// otherwise NFKC runs (when `nfkc`), then each char is kept or recorded as
/// removed by category.
pub fn normalize(text: &str, nfkc: bool) -> UnicodeScanResult {
    if text.is_empty() {
        return UnicodeScanResult {
            cleaned: String::new(),
            removed_codepoints: Vec::new(),
            categories: Vec::new(),
        };
    }
    let source: String = if nfkc { text.nfkc().collect() } else { text.to_string() };
    let mut cleaned = String::with_capacity(source.len());
    let mut removed: Vec<u32> = Vec::new();
    let mut categories: Vec<String> = Vec::new();
    for ch in source.chars() {
        let cp = ch as u32;
        match category_for(cp) {
            Some(cat) => {
                removed.push(cp);
                if !categories.iter().any(|c| c == cat) {
                    categories.push(cat.to_string());
                }
            }
            None => cleaned.push(ch),
        }
    }
    UnicodeScanResult { cleaned, removed_codepoints: removed, categories }
}

/// Cheap boolean check used by the shield's input scan; allocates nothing.
/// Matches `unicode_filter.has_dangerous_unicode` (no NFKC; raw text).
pub fn has_dangerous_unicode(text: &str) -> bool {
    text.chars().any(|ch| {
        let cp = ch as u32;
        ZERO_WIDTH.contains(&cp)
            || BIDI_OVERRIDES.contains(&cp)
            || (TAG_BLOCK_START..=TAG_BLOCK_END).contains(&cp)
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn strips_zero_width_and_bidi_in_order() {
        let r = normalize("a\u{200b}b\u{202e}c", true);
        assert_eq!(r.cleaned, "abc");
        assert_eq!(r.removed_codepoints, vec![0x200B, 0x202E]);
        assert_eq!(r.categories, vec!["zero_width", "bidi_override"]);
    }

    #[test]
    fn nfkc_canonicalizes_lookalikes() {
        // U+FB01 (fi ligature) -> "fi"; full-width A -> "A".
        let r = normalize("\u{fb01}x\u{ff21}", true);
        assert_eq!(r.cleaned, "fixA");
        assert!(r.removed_codepoints.is_empty());
    }

    #[test]
    fn tag_block_detected_and_stripped() {
        assert!(has_dangerous_unicode("x\u{e0001}y"));
        let r = normalize("x\u{e0001}y", true);
        assert_eq!(r.cleaned, "xy");
        assert_eq!(r.categories, vec!["tag_block"]);
    }

    #[test]
    fn clean_text_is_untouched() {
        assert!(!has_dangerous_unicode("perfectly normal text"));
        let r = normalize("perfectly normal text", true);
        assert_eq!(r.cleaned, "perfectly normal text");
        assert!(!r.had_dangerous_helper());
    }

    impl UnicodeScanResult {
        fn had_dangerous_helper(&self) -> bool {
            !self.removed_codepoints.is_empty()
        }
    }
}
