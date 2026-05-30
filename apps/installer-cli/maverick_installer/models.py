"""Curated catalog of supported models per provider.

Updated whenever providers ship new models. Each entry has an id, a
notes string the wizard shows, and a status marker.

All five providers are now wired up. Picking any of them in the wizard
generates a config that the agent kernel actually dispatches to via
the multi-provider LLM facade.
"""

ROLES: list[tuple[str, str]] = [
    ("orchestrator",    "Plans, decomposes, verifies. Use a large model here."),
    ("researcher",      "Searches and gathers information."),
    ("coder",           "Writes and tests code."),
    ("writer",          "Drafts longer-form prose."),
    ("analyst",         "Synthesises findings; reasoning-heavy."),
    ("revisor",         "Second-pass review when verification fails."),
    ("verifier",        "Independent final-answer check."),
    ("summarizer",      "Distillation. A small model is enough."),
    ("skill_distiller", "Turns trajectories into reusable skills."),
]


PROVIDERS: dict[str, dict] = {
    "anthropic": {
        "status": "ready",
        "label": "Anthropic Claude",
        "env": "ANTHROPIC_API_KEY",
        "models": [
            {"id": "claude-opus-4-8",      "notes": "Smartest. Best for orchestrator/revisor."},
            {"id": "claude-opus-4-8-fast", "notes": "Opus 4.8, ~2.5x faster output at 2x price ($10/$50)."},
            {"id": "claude-opus-4-7",      "notes": "Prior Opus generation."},
            {"id": "claude-sonnet-4-6",    "notes": "Balanced. Recommended workhorse."},
            {"id": "claude-haiku-4-5",     "notes": "Fast and cheap. Good for summarizer."},
        ],
    },
    "openai": {
        "status": "ready",
        "label": "OpenAI (ChatGPT / GPT)",
        "env": "OPENAI_API_KEY",
        "models": [
            {"id": "gpt-5.5",       "notes": "Most capable. Tool-use and long reasoning."},
            {"id": "gpt-5.4",       "notes": "Balanced workhorse."},
            {"id": "gpt-5.4-mini",  "notes": "Cheaper, fast."},
            {"id": "gpt-5.4-nano",  "notes": "Tiny, very cheap. Good for summarizer."},
        ],
    },
    "moonshot": {
        "status": "ready",
        "label": "Moonshot / Kimi",
        "env": "MOONSHOT_API_KEY",
        "models": [
            {"id": "kimi-k2",          "notes": "Latest Kimi. Strong agentic/code performance."},
            {"id": "kimi-k1.5",        "notes": "Cheaper, still solid."},
            {"id": "moonshot-v1-128k", "notes": "128k context window."},
        ],
    },
    "deepseek": {
        "status": "ready",
        "label": "DeepSeek",
        "env": "DEEPSEEK_API_KEY",
        "models": [
            {"id": "deepseek-chat",     "notes": "V3.2 chat. Cheap, capable workhorse."},
            {"id": "deepseek-reasoner", "notes": "R1-line reasoning. Slower, deeper."},
            {"id": "deepseek-v4-flash", "notes": "Very cheap. Good for summarizer."},
        ],
    },
    "xai": {
        "status": "ready",
        "label": "xAI Grok",
        "env": "XAI_API_KEY",
        "models": [
            {"id": "grok-4-latest",  "notes": "Flagship. Reasoning + tools."},
            {"id": "grok-4-mini",    "notes": "Cheaper sibling."},
            {"id": "grok-code-fast", "notes": "Code-tuned, low latency."},
        ],
    },
    "gemini": {
        "status": "ready",
        "label": "Google Gemini",
        "env": "GEMINI_API_KEY",
        "models": [
            {"id": "gemini-3.5-pro",   "notes": "Long context, smart."},
            {"id": "gemini-3.5-flash", "notes": "Fast and cheap."},
        ],
    },
    "openrouter": {
        "status": "ready",
        "label": "OpenRouter (200+ models via one API)",
        "env": "OPENROUTER_API_KEY",
        "models": [
            {"id": "auto",                       "notes": "OpenRouter picks for you."},
            {"id": "meta-llama/llama-3.3-70b",  "notes": "Open weight, strong general."},
            {"id": "google/gemini-pro-1.5",     "notes": "Long context."},
            {"id": "deepseek/deepseek-r1",      "notes": "Strong reasoning, cheap."},
        ],
    },
    "ollama": {
        "status": "ready",
        "label": "Ollama (local, free, private)",
        "env": None,
        "models": [
            {"id": "llama3.3:70b",         "notes": "Local, free, requires beefy machine."},
            {"id": "qwen2.5-coder:32b",    "notes": "Local, code-focused."},
            {"id": "phi3:14b",             "notes": "Local, small, fast."},
        ],
    },
    "tgi": {
        "status": "ready",
        "label": "HuggingFace TGI (self-hosted inference)",
        "env": None,
        "models": [
            {"id": "tgi",                  "notes": "Whatever model your TGI server serves; URL via TGI_BASE_URL env."},
        ],
    },
    "openai_compatible": {
        "status": "ready",
        "label": "OpenAI-compatible endpoint (LM Studio / llama.cpp / Together / Groq)",
        "env": "OPENAI_COMPATIBLE_API_KEY",
        "models": [
            {"id": "openai-compatible", "notes": "Set base_url to your endpoint; model id is whatever it serves."},
        ],
    },
    "chatgpt-session": {
        "status": "ready",
        "label": "ChatGPT browser session (use your Plus subscription, no API key)",
        "env": None,
        "session": True,
        "tool_support": False,
        "models": [
            {"id": "gpt-4o",      "notes": "Free for Plus subscribers. Best for summarizer/writer/analyst."},
            {"id": "gpt-4o-mini", "notes": "Free tier model. Use for cheap roles."},
        ],
    },
    "claude-session": {
        "status": "ready",
        "label": "Claude.ai browser session (use your Pro subscription, no API key)",
        "env": None,
        "session": True,
        "tool_support": False,
        "models": [
            {"id": "claude-sonnet-4-6", "notes": "Pro default. Best for summarizer/writer/analyst."},
            {"id": "claude-haiku-4-5",  "notes": "Faster, lower quota cost."},
        ],
    },
    "kimi-session": {
        "status": "ready",
        "label": "Kimi browser session (use your kimi.com subscription)",
        "env": None,
        "session": True,
        "tool_support": False,
        "models": [
            {"id": "kimi-k2",   "notes": "Latest Kimi. Strong agentic / code."},
            {"id": "kimi-k1.5", "notes": "Cheaper, lighter quota cost."},
        ],
    },
    "grok-session": {
        "status": "ready",
        "label": "Grok via x.com browser session (requires X Premium)",
        "env": None,
        "session": True,
        "tool_support": False,
        "models": [
            {"id": "grok-4-latest", "notes": "Flagship. Reasoning + tools."},
            {"id": "grok-4-mini",   "notes": "Cheaper sibling."},
        ],
    },
    "gemini-session": {
        "status": "ready",
        "label": "Gemini browser session (gemini.google.com Advanced)",
        "env": None,
        "session": True,
        "tool_support": False,
        "models": [
            {"id": "gemini-3.5-pro",   "notes": "Long context, smart."},
            {"id": "gemini-3.5-flash", "notes": "Fast and cheap."},
        ],
    },
}


def default_for_role(role: str) -> str:
    return {
        "orchestrator":    "anthropic:claude-opus-4-8",
        "researcher":      "anthropic:claude-sonnet-4-6",
        "coder":           "anthropic:claude-sonnet-4-6",
        "writer":          "anthropic:claude-sonnet-4-6",
        "analyst":         "anthropic:claude-sonnet-4-6",
        "revisor":         "anthropic:claude-opus-4-8",
        "verifier":        "anthropic:claude-sonnet-4-6",
        "summarizer":      "anthropic:claude-haiku-4-5",
        "skill_distiller": "anthropic:claude-sonnet-4-6",
    }[role]
