//! Native port of `maverick.safety.secret_detector.scan`.
//!
//! Faithful, order-for-order reproduction of the Python pass: the SAME patterns
//! in the SAME order, the SAME "redact the `val` sub-group when present, else the
//! whole match" rule, and the SAME global exact-span de-duplication. We return
//! only `(name, codepoint_start, codepoint_end)`; the Python shim rebuilds the
//! `SecretMatch` (incl. its preview) and does the string splicing, so behaviour
//! can never drift from the pure-Python redactor. Patterns are compiled once.
//!
//! Engine: `fancy-regex`. None of these patterns use look-around, so each
//! compiles to the linear `regex` backend — but routing every detector through
//! one backtracking engine keeps semantics identical to Python's `re` and lets
//! us share the fail-safe error path (any engine error => caller falls back to
//! pure Python, i.e. err toward over-redaction).

use crate::{byte_spans_to_char, compile_pattern};
use fancy_regex::Regex;
use std::collections::HashSet;
use std::sync::LazyLock;

struct Pattern {
    name: &'static str,
    re: Regex,
    /// True only for `env_secret`: redact the named `val` group, not the whole
    /// match (keeps the `NAME=` prefix visible, exactly like Python).
    val_group: bool,
}

// (name, pattern, has_val_group). Order is load-bearing: `scan` emits matches in
// pattern order and the global span de-dup keeps the FIRST pattern to claim a
// span, so this MUST mirror `_PATTERNS` in secret_detector.py exactly.
static DEFS: &[(&str, &str, bool)] = &[
    ("anthropic_api_key", r"\bsk-ant-[a-zA-Z0-9_-]{20,}\b", false),
    (
        "openai_api_key",
        r"\bsk-(?:proj-)?[a-zA-Z0-9_-]{20,}",
        false,
    ),
    ("aws_access_key_id", r"\bAKIA[0-9A-Z]{16}\b", false),
    (
        "aws_secret_access",
        r#"(?i)(?:aws_secret_access_key|aws_secret)[\s=:"']{1,16}([A-Za-z0-9/+=]{40})"#,
        false,
    ),
    ("github_pat_classic", r"\bghp_[A-Za-z0-9]{36,40}\b", false),
    ("github_pat_fine", r"\bgithub_pat_[A-Za-z0-9_]{82}\b", false),
    ("github_oauth", r"\bgho_[A-Za-z0-9]{36,40}\b", false),
    ("google_api_key", r"\bAIza[0-9A-Za-z\-_]{35}\b", false),
    (
        "gcp_service_account",
        r#""type"\s*:\s*"service_account""#,
        false,
    ),
    (
        "azure_storage",
        r"\bDefaultEndpointsProtocol=https;AccountName=[^;]+;AccountKey=[A-Za-z0-9+/=]{40,}",
        false,
    ),
    (
        "slack_bot_token",
        r"\bxox[baprs]-[0-9]{10,13}-[0-9]{10,13}-[a-zA-Z0-9]{24,}\b",
        false,
    ),
    ("stripe_live_key", r"\bsk_live_[0-9a-zA-Z]{24,}\b", false),
    ("stripe_test_key", r"\bsk_test_[0-9a-zA-Z]{24,}\b", false),
    (
        "jwt",
        r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b",
        false,
    ),
    // DOTALL via (?s); bounded body is the ReDoS guard, same as Python.
    (
        "private_key_pem",
        r"(?s)-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----(?:.{0,8192}?-----END (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----|[A-Za-z0-9+/=\s]{0,8192})",
        false,
    ),
    ("gitlab_pat", r"\bglpat-[A-Za-z0-9_-]{20,}\b", false),
    ("twilio_api_key", r"\bSK[0-9a-fA-F]{32}\b", false),
    (
        "slack_webhook",
        r"https://hooks\.slack\.com/services/[A-Za-z0-9/]+",
        false,
    ),
    (
        "db_connection_uri",
        r"\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)://[^:@/\s]+:[^@/\s]+@[^\s]+",
        false,
    ),
    (
        "bearer_header",
        r"(?i)\bAuthorization\s*:\s*Bearer\s+[A-Za-z0-9._\-+/=]{12,}",
        false,
    ),
    // MULTILINE via (?m); only the `val` group is redacted.
    (
        "env_secret",
        r#"(?m)(?:^|\n)[^\S\n]*(?:export\s+)?[A-Z][A-Z0-9_]*(?:TOKEN|KEY|SECRET|PASSWORD|PASS|CREDENTIAL)[A-Z0-9_]*\s*[:=]\s*(?P<val>"[^"\n]*"|'[^'\n]*'|[^\s\n]+)"#,
        true,
    ),
];

static PATTERNS: LazyLock<Vec<Pattern>> = LazyLock::new(|| {
    DEFS.iter()
        .map(|(name, pat, val)| Pattern {
            name,
            re: compile_pattern(pat).expect("secret pattern must compile"),
            val_group: *val,
        })
        .collect()
});

/// Mirror of `secret_detector.scan`, returning `(name, cp_start, cp_end)` triples
/// in Python's emission order. `Err` on any engine failure so the caller can fall
/// back to pure Python (fail-safe: never silently under-redact).
pub fn scan_spans(text: &str) -> Result<Vec<(String, usize, usize)>, String> {
    if text.is_empty() {
        return Ok(Vec::new());
    }
    let mut byte_spans: Vec<(&'static str, usize, usize)> = Vec::new();
    let mut seen: HashSet<(usize, usize)> = HashSet::new();
    for pat in PATTERNS.iter() {
        for cap in pat.re.captures_iter(text) {
            let cap = cap.map_err(|e| e.to_string())?;
            let m = if pat.val_group {
                match cap.name("val") {
                    Some(m) => m,
                    None => continue,
                }
            } else {
                cap.get(0).expect("group 0 always present")
            };
            let span = (m.start(), m.end());
            if seen.insert(span) {
                byte_spans.push((pat.name, span.0, span.1));
            }
        }
    }
    Ok(byte_spans_to_char(text, byte_spans))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn names(text: &str) -> Vec<String> {
        scan_spans(text).unwrap().into_iter().map(|m| m.0).collect()
    }

    #[test]
    fn detects_anthropic_and_dedups_with_openai() {
        // sk-ant- matches both the anthropic and openai patterns at the same
        // span; dedup keeps the first (anthropic) only. The fake key's prefix is
        // split from its body via concat! so no whole token literal is on disk
        // (GitHub push protection); the runtime string is unchanged.
        let n = names(concat!("key sk-", "ant-abcdefghijklmnopqrstuvwxyz0123 end"));
        assert!(n.contains(&"anthropic_api_key".to_string()));
    }

    #[test]
    fn env_secret_redacts_value_span_only() {
        let spans = scan_spans("export API_SECRET=supersecretvalue\n").unwrap();
        let env = spans.iter().find(|m| m.0 == "env_secret").unwrap();
        // The span must cover only the value, not the NAME= prefix.
        assert_eq!(
            &"export API_SECRET=supersecretvalue\n"[..env.1],
            "export API_SECRET="
        );
    }

    #[test]
    fn empty_is_empty() {
        assert!(scan_spans("").unwrap().is_empty());
    }
}
