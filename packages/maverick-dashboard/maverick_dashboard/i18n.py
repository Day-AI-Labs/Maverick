"""Dashboard chrome i18n (roadmap 2027-H1 UX — "i18n expansion fr/de/ja/zh").

Translates the dashboard's *chrome* — navigation, headers, common buttons —
not user data (goal titles, run output stay verbatim). Deliberately tiny:
a dict catalog + a ``t(key)`` template helper, no gettext toolchain, because
the chrome is ~30 strings and a contributor adds a language by editing one
mapping (and the catalog test keeps every language complete).

Language resolution: ``?lang=`` query param → ``mvk_lang`` cookie →
``Accept-Language`` header prefix → English. Unknown keys render the English
string (or the key itself) so a missing translation can never blank the UI.
"""
from __future__ import annotations

LANGS = ("en", "fr", "de", "ja", "zh")
DEFAULT_LANG = "en"

# key -> {lang: text}. English is the reference set; the catalog test asserts
# every language covers every key.
MESSAGES: dict[str, dict[str, str]] = {
    "nav.goals":      {"en": "Goals", "fr": "Objectifs", "de": "Ziele", "ja": "ゴール", "zh": "目标"},
    "nav.chat":       {"en": "Chat", "fr": "Discussion", "de": "Chat", "ja": "チャット", "zh": "聊天"},
    "nav.approvals":  {"en": "Approvals", "fr": "Approbations", "de": "Freigaben", "ja": "承認", "zh": "审批"},
    "nav.oversight":  {"en": "Oversight", "fr": "Supervision", "de": "Aufsicht", "ja": "監督", "zh": "监管"},
    "nav.cost":       {"en": "Cost", "fr": "Coûts", "de": "Kosten", "ja": "コスト", "zh": "成本"},
    "nav.audit":      {"en": "Audit", "fr": "Audit", "de": "Audit", "ja": "監査", "zh": "审计"},
    "nav.channels":   {"en": "Channels", "fr": "Canaux", "de": "Kanäle", "ja": "チャネル", "zh": "渠道"},
    "label.status":   {"en": "Status", "fr": "Statut", "de": "Status", "ja": "状態", "zh": "状态"},
    "label.created":  {"en": "Created", "fr": "Créé", "de": "Erstellt", "ja": "作成日時", "zh": "创建时间"},
    "label.owner":    {"en": "Owner", "fr": "Propriétaire", "de": "Eigentümer", "ja": "所有者", "zh": "所有者"},
    "label.theme":    {"en": "Theme", "fr": "Thème", "de": "Design", "ja": "テーマ", "zh": "主题"},
    "label.font":     {"en": "Font", "fr": "Police", "de": "Schrift", "ja": "フォント", "zh": "字体"},
    "label.language": {"en": "Language", "fr": "Langue", "de": "Sprache", "ja": "言語", "zh": "语言"},
    "action.start":   {"en": "Start", "fr": "Démarrer", "de": "Starten", "ja": "開始", "zh": "开始"},
    "action.cancel":  {"en": "Cancel", "fr": "Annuler", "de": "Abbrechen", "ja": "キャンセル", "zh": "取消"},
    "action.approve": {"en": "Approve", "fr": "Approuver", "de": "Genehmigen", "ja": "承認する", "zh": "批准"},
    "action.deny":    {"en": "Deny", "fr": "Refuser", "de": "Ablehnen", "ja": "却下する", "zh": "拒绝"},
    "action.search":  {"en": "Search", "fr": "Rechercher", "de": "Suchen", "ja": "検索", "zh": "搜索"},
    "footer.local":   {"en": "self-hosted", "fr": "auto-hébergé", "de": "selbst gehostet", "ja": "セルフホスト", "zh": "自托管"},
    "font.default":   {"en": "Default", "fr": "Par défaut", "de": "Standard", "ja": "標準", "zh": "默认"},
    "font.dyslexic":  {"en": "Dyslexia-friendly", "fr": "Adaptée à la dyslexie", "de": "Legasthenie-freundlich", "ja": "ディスレクシア対応", "zh": "阅读障碍友好"},
}


def resolve_lang(request) -> str:
    """``?lang=`` → ``mvk_lang`` cookie → ``Accept-Language`` → en."""
    q = (request.query_params.get("lang") or "").strip().lower()
    if q in LANGS:
        return q
    c = (request.cookies.get("mvk_lang") or "").strip().lower()
    if c in LANGS:
        return c
    accept = (request.headers.get("Accept-Language") or "").lower()
    for part in accept.split(","):
        code = part.split(";")[0].strip()[:2]
        if code in LANGS:
            return code
    return DEFAULT_LANG


def t(key: str, lang: str = DEFAULT_LANG) -> str:
    """Translate a chrome string; fall back en → key (never blank)."""
    entry = MESSAGES.get(key)
    if not entry:
        return key
    return entry.get(lang) or entry.get(DEFAULT_LANG) or key


__all__ = ["LANGS", "DEFAULT_LANG", "MESSAGES", "resolve_lang", "t"]
