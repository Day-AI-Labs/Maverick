"""Built-in fallback prompt-injection rules.

When ``agent-shield`` (the full SDK with F1 0.988 detection) isn't
installed, we still want *some* safety, not a wide-open no-op. This
module provides a small but real set of regex rules covering the
highest-impact attack categories from the agent-shield README:

  - prompt injection / instruction hijacking (ignore-previous, override-system)
  - role hijacking (DAN, developer mode, jailbreak templates)
  - data exfiltration markers (markdown image leaks, base64 url params)
  - tool-abuse markers (rm -rf, /etc/passwd, .env exfil)

The full agent-shield SDK detects ~115 patterns; this fallback covers
~20 of the most common ones. Good enough to block the obvious attacks;
weak against sophisticated obfuscation (homoglyphs, base64-wrapped
payloads, etc.). The installer's smoke test makes this gap visible to
users via the "agent-shield not installed" warning.
"""
from __future__ import annotations

import base64
import re
import unicodedata
from dataclasses import dataclass


@dataclass
class Rule:
    name: str
    severity: str           # "low" | "medium" | "high" | "critical"
    pattern: re.Pattern
    description: str


def _compile(p: str) -> re.Pattern:
    return re.compile(p, re.IGNORECASE)


# --- de-obfuscation pre-pass -----------------------------------------------
# The regex rules below only match literal text. A trivial obfuscation
# (fullwidth chars, a zero-width space mid-word, a Cyrillic look-alike, a
# base64-wrapped payload, or a quoted/`$IFS`-split shell command) slips
# straight past them. Before scanning we therefore derive a set of
# normalised/decoded CANDIDATE strings and run every rule over all of them,
# so a match in any variant counts. This converts the fallback from
# "stops only a verbatim copy-paste" to "stops the common encodings too".

# Zero-width spaces/joiners, bidi controls, BOM, and the Unicode tag block
# (steganographic invisible chars).
_INVISIBLE = re.compile(
    r"[\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff]|[\U000E0000-\U000E007F]"
)

# Common confusable code points folded to their ASCII look-alike. Covers the
# Cyrillic/Greek homoglyphs used to spell "ignore", "system", etc.
_HOMOGLYPHS = str.maketrans({
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x", "у": "y",
    "і": "i", "ѕ": "s", "ԁ": "d", "ո": "n", "ⅼ": "l", "ӏ": "l", "ʟ": "l",
    "α": "a", "ο": "o", "ρ": "p", "ν": "v", "ϲ": "c", "ѐ": "e", "ƽ": "s",
    "ɡ": "g", "ⅰ": "i", "ｉ": "i",
})

# A base64-shaped run long enough to carry a payload (but not so short it
# matches every hex id). Decoded and re-scanned.
_B64_BLOB = re.compile(r"[A-Za-z0-9+/]{16,}={0,2}")

# Cap how much work the pre-pass does on hostile input (the scanner runs on
# untrusted text; keep it linear and bounded).
_MAX_B64_BLOBS = 20


def _strip_invisible(text: str) -> str:
    return _INVISIBLE.sub("", text)


def _shell_deobfuscate(text: str) -> str:
    """Neutralise common shell-quoting evasions so the tool-abuse rules still
    match: ``rm -rf "/"`` / ``rm -rf $IFS/`` / ``r\\m -rf /`` all canonicalise
    to ``rm -rf /``. Only used to build an extra candidate, so over-stripping
    can't corrupt the original text the other rules see."""
    text = text.replace("${IFS}", " ").replace("$IFS", " ")
    text = text.replace("\\", "")          # drop backslash escapes
    text = re.sub(r"['\"`]", "", text)      # drop quotes/backticks
    return re.sub(r"[ \t]{2,}", " ", text)


def _decode_b64_blobs(text: str) -> list[str]:
    out: list[str] = []
    for m in _B64_BLOB.finditer(text):
        if len(out) >= _MAX_B64_BLOBS:
            break
        blob = m.group(0)
        try:
            raw = base64.b64decode(blob + "=" * (-len(blob) % 4), validate=False)
            decoded = raw.decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            continue
        # Only keep decodes that look like text (the attack is in the words).
        if decoded and any(c.isalpha() for c in decoded):
            out.append(decoded)
    return out


def _candidates(text: str) -> list[str]:
    """Return the set of strings to scan: the original plus de-obfuscated and
    base64-decoded variants. NFKC folds fullwidth/compatibility forms."""
    norm = unicodedata.normalize("NFKC", text)
    norm = _strip_invisible(norm).translate(_HOMOGLYPHS)
    cands = {text, norm, _shell_deobfuscate(norm)}
    for decoded in _decode_b64_blobs(text):
        cands.add(decoded)
        cands.add(unicodedata.normalize("NFKC", decoded))
    return [c for c in cands if c]


# Severity guidance:
#   low      -> notice; never blocks at any profile
#   medium   -> blocks at 'strict' (threshold='medium')
#   high     -> blocks at 'balanced' (threshold='high') and stricter
#   critical -> blocks at all enforcing profiles (incl. 'permissive')
RULES: list[Rule] = [
    # Prompt injection / override
    Rule("ignore_previous", "high",
         _compile(r"\b(ignore|disregard|forget)\s+(all|every|the)?\s*(previous|prior|above|earlier|preceding)\s+(instructions?|prompts?|rules?|context)"),
         "Classic prompt-injection: instruction override"),
    Rule("override_system", "high",
         _compile(r"\b(override|bypass|disable)\s+(the\s+)?(system|safety|guardrails?)\s+(prompt|rules?|filter)"),
         "System-prompt override attempt"),
    Rule("chatml_injection", "critical",
         _compile(r"(<\|im_start\|>|<\|im_end\|>|<\|system\|>|\[INST\]|\[\/INST\])"),
         "ChatML / LLaMA delimiter injection"),
    Rule("system_prompt_leak", "medium",
         _compile(r"\b(reveal|show|print|repeat|output)\s+(your|the)?\s*(system|original|initial)\s+(prompt|instructions?|context)"),
         "System prompt extraction attempt"),

    # Role hijacking
    Rule("dan_jailbreak", "critical",
         _compile(r"\b(DAN|do anything now|developer mode|jailbreak|unfiltered\s+ai)\b"),
         "DAN / developer-mode jailbreak"),
    Rule("persona_takeover", "high",
         _compile(
             # "you are now a(n) <malicious-adj>[, <adj> and ...] <noun>".
             # The adjective list is attack-only (so "you are now a helpful
             # assistant" never matches), but allow a comma/'and'-separated
             # run of them before the noun -- "you are now an unrestricted,
             # uncensored AI" slipped past the old single-adjective form. The
             # {1,4} bound keeps it linear (no ReDoS).
             r"\byou\s+are\s+now\s+(?:an?\s+)?"
             r"(?:(?:unrestricted|uncensored|unfiltered|unlimited|amoral|immoral|evil|jailbroken|lawless|rogue)"
             r"(?:\s*,\s*|\s+and\s+|\s+)){1,4}"
             r"(?:ai|a\.i\.|assistant|model|chatbot|bot|llm|language\s+model|entity|being|persona)"
         ),
         "Persona takeover"),

    # Data exfiltration
    Rule("markdown_image_exfil", "high",
         _compile(r"!\[[^\]]*\]\(https?:\/\/[^)]+\?[^)]*(token|key|password|secret|api)"),
         "Markdown image URL with credentials in query"),
    Rule("base64_url_exfil", "high",
         _compile(r"https?:\/\/[^\s]+\?[^=]*=[A-Za-z0-9+\/]{40,}={0,2}"),
         "URL parameter with base64 payload"),

    # Tool abuse markers (these trigger on tool-call args, not free text).
    # The `_shell_deobfuscate` candidate strips quotes/$IFS, so quoted and
    # $IFS-split variants canonicalise into these patterns.
    Rule("rm_rf_root", "critical",
         _compile(r"\brm\s+-[a-z]*(?:rf|fr)[a-z]*\s+(\/|~|\$HOME)(\*|\/|\s|$)"),
         "rm -rf/-fr against /, ~, or $HOME"),
    Rule("sensitive_file_read", "high",
         _compile(r"(\/etc\/+(passwd|shadow|ssh)|~?\/\.ssh\/|~?\/\.aws\/credentials|\.env\b)"),
         "Read of /etc/passwd, ssh keys, AWS creds, or .env"),
    Rule("curl_pipe_shell", "critical",
         _compile(r"(curl|wget)\s+[^|]+\|\s*(sudo\s+)?(sh|bash|zsh|python)\b"),
         "curl-pipe-to-shell remote code execution"),
    Rule("reverse_shell", "critical",
         _compile(r"(bash\s+-i\s+>&\s+\/dev\/tcp\/|nc\s+-e\s+\/bin\/(sh|bash))"),
         "Reverse shell payload"),

    # Social engineering markers
    Rule("urgency_authority", "medium",
         _compile(r"\bthis\s+is\s+(an?\s+)?(emergency|urgent|critical)\b.*\b(execute|run|do)\s+(immediately|now|asap)"),
         "Urgency + authority pressure"),
    Rule("false_preapproval", "medium",
         _compile(r"\b(the\s+user|admin|operator)\s+(has\s+)?already\s+(approved|authorized|allowed)"),
         "False pre-approval claim"),

    # --- Newer attack families (close the held-out benchmark gaps) -----------
    # These generalize the family, not the specific benchmark sentence: each
    # requires an attack verb/marker AND a target, so benign text that merely
    # name-drops the vocabulary does not trip them. Bounded `{0,N}?` gaps keep
    # them linear (no ReDoS) and allow the two tokens to span a newline.
    Rule("directive_supersede", "high",
         _compile(r"\b(new|updated|latest|the\s+following)\s+(directive|instruction|rule|policy|order)s?\b[\s\S]{0,40}?\b(supersed|overrid|replac|take[\s-]?priorit|come\s+first)"),
         "Instruction-override: a new directive supersedes prior ones"),
    Rule("stop_following_policy", "high",
         _compile(r"\bstop\s+(following|obeying|applying|enforcing|adhering\s+to)\s+(your|the|all|its)?\s*(configured\s+)?(polic\w+|rules?|guidelines?|instructions?|guardrails?|safety)"),
         "Instruction-override: stop following configured policy"),
    Rule("comply_without_restrictions", "high",
         _compile(r"\b(comply|respond|answer|proceed|continue|do\s+it)\b[\s\S]{0,40}?\bwithout\s+(any\s+)?(restrictions?|limits?|limitations?|filters?|guardrails?|refus\w+)"),
         "Instruction-override: comply without restrictions"),

    # Persona takeover — "from now on", "pretend safety is off", "true self".
    Rule("from_now_on_persona", "high",
         _compile(r"\bfrom\s+now\s+on\b[\s\S]{0,40}?\byou\s+(are|act|operate|behave|respond|will|must)\b"),
         "Persona takeover: 'from now on you ...'"),
    Rule("pretend_safety_off", "critical",
         _compile(r"\b(pretend|imagine|assume|act\s+as\s+if|suppose)\b[\s\S]{0,40}?\b(safety|content|filter|guardrails?|alignment|moderation|rules?)\b[\s\S]{0,24}?\b(off|disabled|removed|gone|switched\s+off|turned\s+off|don'?t\s+apply|never\s+existed)"),
         "Jailbreak: pretend the safety layer is disabled"),
    Rule("unaligned_self", "high",
         _compile(r"\b(answer|respond|act|reply|speak)\s+as\s+your\s+(raw|true|real|unaligned|unfiltered|uncensored|unrestricted|boundless)\s+self\b"),
         "Persona takeover: answer as your 'unaligned self'"),

    # System-prompt leak — verbatim / everything above / hidden directives.
    Rule("verbatim_prompt_leak", "medium",
         _compile(r"\b(print|repeat|output|show|reveal|echo|paste|reproduce)\b[\s\S]{0,40}?\b(verbatim|exact\s+text|everything\s+(above|that\s+appears)|hidden\s+(directive|instruction|prompt)|configuration\s+block)"),
         "System-prompt extraction: dump hidden/preceding text verbatim"),

    # Secret exfiltration — name a credential AND move it out (either order).
    Rule("secret_exfil_request", "critical",
         _compile(r"\b(api[\s_-]?(key|token)|access[\s_-]?token|secret|credential|password|private\s+key|\.env\b|config\.toml|/\.aws/|id_rsa)\b[\s\S]{0,60}?\b(include|return|reply|print|show|reveal|paste|email|send|upload|post|exfil|leak|give\s+me)"),
         "Credential exfiltration request"),
    Rule("secret_exfil_request_rev", "critical",
         _compile(r"\b(read|fetch|get|dump|cat|summari[sz]e|print|reveal|leak|exfil\w*)\b[\s\S]{0,40}?\b(environment\s+variable|env\s+var|api[\s_-]?(key|token)|secret|credential|password|private\s+key|\.env\b|config\.toml|/\.aws/|id_rsa)"),
         "Credential read/exfiltration request"),

    # Indirect / tool-output injection — content addressing the agent.
    Rule("ai_reading_this", "high",
         _compile(r"\bif\s+you\s+(are|'?re)\s+(an?\s+)?(ai|agent|assistant|llm|model|language\s+model|bot)\b[\s\S]{0,40}?\b(reading|seeing|processing|parsing|viewing)\b"),
         "Indirect injection: content addressed to an AI that reads it"),
    Rule("real_task_hijack", "high",
         _compile(r"\byour\s+(real|actual|true|new|secret|hidden|primary)\s+(task|job|goal|mission|instruction|objective|purpose)\s+is\b"),
         "Task hijack: your 'real task' is ..."),
    Rule("injected_command_to_agent", "high",
         _compile(r"\b(system\s+note|important|attention|urgent|note\s+from\s+file)\b[\s\S]{0,60}?\b(assistant|ai|agent|model)\b[\s\S]{0,24}?\b(must|should|needs?\s+to|has\s+to|now)\b[\s\S]{0,24}?\b(email|send|upload|exfil\w*|delete|run|execute|forward|leak|transfer)"),
         "Tool-output / file injection issuing a command to the agent"),

    # Jailbreak framing — fiction/hypothetical used to elicit a bypass.
    Rule("fiction_bypass_framing", "high",
         _compile(r"\b(fiction|story|stories|roleplay|role[\s-]?play|hypothetical|screenplay|novel|game|scenario)\b[\s\S]{0,80}?\b(bypass\w*|disabl\w*|ignor\w*|circumvent\w*|evad\w*|get\s+around|turn\s+off|defeat\w*|get\s+past)[\s\S]{0,40}?\b(filter|safety|guardrails?|rules?|restrictions?|alignment|content\s+(policy|filter)|moderation)"),
         "Jailbreak via fiction / hypothetical framing"),

    # Encoding evasion — "decode X and treat it as an instruction".
    Rule("decode_and_obey", "high",
         _compile(r"\bdecode\b[\s\S]{0,60}?\b(treat|use\s+it|execute|run|obey|follow|act\s+on|top[\s-]?priority|overrid)"),
         "Encoding evasion: decode then treat as instruction"),

    # Invisible/bidi chars are an evasion signal in their own right -- medium
    # so 'strict' blocks on smuggling even when the de-obfuscated payload
    # happens to match no other rule.
    Rule("zero_width_chars", "medium",
         _compile(r"[\u200b-\u200f\u2028-\u202f\u2060-\u206f]"),
         "Zero-width / bidi characters"),
]


SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def _threshold_to_min_severity(threshold: str) -> int:
    # Normalize: block_threshold comes from user-typed TOML. A non-lowercase or
    # padded spelling ("Medium", " high ") missed the lookup and silently fell
    # back to "high", strengthening the gate past the operator's intent.
    return SEVERITY_ORDER.get(str(threshold).strip().lower(), SEVERITY_ORDER["high"])


def scan(
    text: str,
    block_threshold: str = "high",
) -> tuple[bool, str, list[str]]:
    """Run all rules over ``text``.

    Returns (blocked, max_severity, matched_rule_names).
    Blocked = True iff any rule fired at or above the configured threshold.
    """
    threshold_idx = _threshold_to_min_severity(block_threshold)
    # Scan the original text AND its de-obfuscated / base64-decoded variants,
    # so an encoded or quoted payload still trips the rule it was hiding from.
    candidates = _candidates(text)
    matched: list[str] = []
    max_idx = -1
    max_sev = "none"
    for r in RULES:
        if any(r.pattern.search(c) for c in candidates):
            matched.append(r.name)
            idx = SEVERITY_ORDER[r.severity]
            if idx > max_idx:
                max_idx = idx
                max_sev = r.severity
    blocked = max_idx >= threshold_idx and len(matched) > 0
    return blocked, max_sev, matched
