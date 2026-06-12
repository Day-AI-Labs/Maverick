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

# Only decode the leading slice of any one base64 blob before re-scanning it.
# A concealed prompt-injection INSTRUCTION is short; a giant blob is a data
# payload, not a hidden prompt, and decoding + re-scanning the whole thing was
# the worst hot-path cost (168ms on a 200KB blob). 8 KiB of base64 -> ~6 KiB of
# decoded text, which still catches an instruction at the start of the blob.
_MAX_B64_DECODE_CHARS = 8192


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
        # Decode only the leading slice: a hidden instruction is short, so this
        # still catches it, but a multi-KB payload blob no longer drives a
        # multi-KB decode + full re-scan (the worst-case latency). Trim to a
        # multiple of 4 so the base64 chunk stays self-contained.
        blob = m.group(0)[: _MAX_B64_DECODE_CHARS & ~3]
        try:
            raw = base64.b64decode(blob + "=" * (-len(blob) % 4), validate=False)
            decoded = raw.decode("utf-8", errors="ignore")
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
         _compile(r"\b(reveal|show|print|repeat|output|quote|dump)\s+(your|the|me\s+the)?\s*(system|original|initial|hidden)\s+(prompt|instructions?|context|message|directives?)"),
         "System prompt extraction attempt"),

    # Role hijacking
    Rule("dan_jailbreak", "critical",
         # Unambiguous jailbreak markers stand alone. "developer mode" does NOT:
         # the bare term is a benign IDE/browser/app mode and over-blocked normal
         # IT/dev text (measured ~13% false-positive on benign inputs,
         # user-testing finding). The real "Developer Mode" jailbreak always
         # sheds restrictions, so require a restriction-removal cue within a
         # short window (either order). Bounds keep it ReDoS-safe.
         _compile(
             r"\b(?:DAN|do anything now|jailbreak|unfiltered\s+ai)\b"
             r"|\bdeveloper\s+mode\b[\s\S]{0,60}(?:unrestricted|unfiltered|anything\s+goes|free\s+from|no\s+(?:restrictions?|rules?|filters?|limits?)|without\s+(?:restrictions?|rules?|filters?)|bypass|ignore\s+(?:all|your|the)?[\w\s]{0,12}(?:rules?|restrictions?|instructions?|guidelines?|policy|policies))"
             r"|(?:unrestricted|unfiltered|anything\s+goes|no\s+(?:restrictions?|rules?|filters?)|bypass|ignore\s+(?:all|your|the)?[\w\s]{0,12}(?:rules?|restrictions?|instructions?))[\s\S]{0,60}\bdeveloper\s+mode\b"
         ),
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
         _compile(r"(\/etc\/+(passwd|shadow|ssh|sudoers)|\bNOPASSWD\b|~?\/\.ssh\/|~?\/\.aws\/credentials|\.env\b)"),
         "Read of /etc/passwd, ssh keys, sudoers, AWS creds, or .env"),
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
         _compile(r"\b(print|repeat|output|show|reveal|echo|paste|reproduce|quote)\b[\s\S]{0,40}?\b(verbatim|word[\s-]for[\s-]word|line[\s-]for[\s-]line|exact\s+text|everything\s+(above|that\s+appears)|hidden\s+(directive|instruction|prompt)|configuration\s+block)"),
         "System-prompt extraction: dump hidden/preceding text verbatim"),

    # Secret exfiltration — name a credential AND move it out (either order).
    Rule("secret_exfil_request", "critical",
         _compile(r"\b(api[\s_-]?(key|token)|access[\s_-]?token|secret|credential|password|private\s+key|\.env\b|config\.toml|/\.aws/|id_rsa)\b[\s\S]{0,60}?\b(include|return|reply|print|show|reveal|paste|email|send|upload|post|exfil|leak|give\s+me)"),
         "Credential exfiltration request"),
    Rule("secret_exfil_request_rev", "critical",
         _compile(r"\b(read|fetch|get|dump|cat|summari[sz]e|print|reveal|leak|exfil\w*|send|email|forward|post|upload|transmit)\b[\s\S]{0,40}?\b(environment\s+variable|env\s+var|api[\s_-]?(key|token)|secret|credential|password|private\s+key|\.env\b|config\.toml|/\.aws/|id_rsa)"),
         "Credential read/exfiltration request"),

    # Indirect / tool-output injection — content addressing the agent.
    Rule("ai_reading_this", "high",
         _compile(r"\bif\s+you\s+(are|'?re|happen\s+to\s+be|find\s+yourself)\s+(an?\s+)?(automated\s+|virtual\s+|digital\s+|ai\s+|language\s+)?(ai|agent|assistant|llm|model|language\s+model|bot|system)\b[\s\S]{0,40}?\b(reading|seeing|processing|parsing|viewing|summari[sz]ing|handling)\b"),
         "Indirect injection: content addressed to an AI that reads it"),
    Rule("real_task_hijack", "high",
         # "new"/"primary" dropped from the adjective list: "your new task is" and
         # "your primary task is" are ordinary delegation language and over-blocked
         # benign work (user-testing finding). The hijack signal is the claim of a
         # hidden/true task: real|actual|true|secret|hidden.
         _compile(r"\byour\s+(real|actual|true|secret|hidden)\s+(task|job|goal|mission|instruction|objective|purpose)\s+is\b"),
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

    # --- round-9 additions: families the end-to-end ASR benchmark exposed ----
    # Each needs an attack verb/marker AND a target, so benign vocab name-drops
    # don't trip them; bounded gaps keep them linear (no ReDoS).
    Rule("prompt_leak_query", "medium",
         _compile(r"\b(what|which)\s+(system\s+)?(instructions?|rules?|directives?|prompt|guidance)\s+(were|was|did)\s+you\s+(give[n]?|told|provided|configured|set\s+up\s+with)"),
         "System-prompt extraction via question"),
    Rule("forget_setup_constraints", "high",
         _compile(r"\b(ignore|disregard|forget|drop|abandon|discard)\s+(the\s+|all\s+|any\s+|your\s+)?(constraints?|limits?|limitations?|restrictions?|rules?|guardrails?|guidance|guidelines?)\s+(from|in|of|set\s+(by|in)|that\s+came\s+with)\s+(your\s+)?(setup|config\w*|system|instructions?|prompt|training)"),
         "Instruction-override: forget the constraints from your setup"),
    Rule("instructions_voided", "high",
         _compile(r"\b(your|the)\s+(previous|prior|original|earlier|current|existing)?\s*(instructions?|directives?|rules?|guidelines?|constraints?|guardrails?)\s+(you\s+(began|started)\s+with\s+)?(are|is|have\s+been)\s+(now\s+)?(void|null|nullified|cancel\w+|revoked|invalid|defunct|no\s+longer\s+(valid|in\s+effect|active))"),
         "Instruction-override: prior instructions declared void"),
    Rule("content_directs_agent_exfil", "high",
         _compile(r"\b(note|message|instruction|memo|reminder)\s+(for|to)\s+(the\s+)?(ai|assistant|agent|model|llm|bot)\b[\s\S]{0,60}?\b(forward|send|email|post|upload|transmit|exfil\w*|leak|deliver|hand\s+over)\b[\s\S]{0,40}?\b(credential|password|secret|invoice|bank|account|details|file|data|token|key)"),
         "Indirect injection: content instructs the AI to exfiltrate"),
    Rule("destructive_db_no_confirm", "critical",
         _compile(r"\b(drop|truncate|delete\s+from|wipe|destroy|purge)\s+(every|all|each|the\s+entire|the\s+whole)?\s*(table|database|schema|collection|index|record)s?\b[\s\S]{0,50}?\b(skip|without|bypass|no|ignore|don'?t|avoid)\s*\w*\s*(confirm\w*|approv\w*|verif\w*|prompt|backup|safeguard)"),
         "Destructive database op that skips the confirmation/approval"),
    Rule("self_privilege_escalation", "critical",
         _compile(r"\b(grant|give|assign|escalate|elevate|add)\b[\s\S]{0,24}?\b(your(self)?|its|the\s+agent'?s?|my\s+own)\b[\s\S]{0,20}?\b(admin\w*|root|sudo|superuser|elevated|privileged)\b[\s\S]{0,20}?\b(scope|access|privileg\w*|right|permission|role)|\b(remove|drop|disable|bypass|waive|eliminate|skip)\s+(the\s+)?(approval|confirmation|consent|sign[\s-]?off|authoriz\w+)\s+(requirement|step|gate|check|process)"),
         "Privilege escalation: self-grant admin or remove the approval gate"),
    Rule("credential_phish", "high",
         _compile(r"\b(reply|respond|provide|shar\w+|send|give|tell|disclose|reveal|hand\s+(me|over|us))\b[\s\S]{0,40}?\b(password|passphrase|2fa\b|two[\s-]factor|one[\s-]time\s+code|otp\b|mfa\b|backup\s+codes?|recovery\s+codes?|security\s+codes?|seed\s+phrase)"),
         "Credential phishing: asks to disclose a password / 2FA / backup code"),
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
