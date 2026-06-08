"""Web search tool.

Supports multiple search backends; tries them in order until one
succeeds. No API key needed for DuckDuckGo; others use BYOK via env.

Backend order:
  1. Tavily  (TAVILY_API_KEY)        — best ranking, returns rich snippets
  2. Brave   (BRAVE_API_KEY)         — fast, good freshness
  3. SerpAPI (SERPAPI_API_KEY)       — broad coverage
  4. DuckDuckGo HTML (no key)        — last-resort, brittle but free

Override via ``MAVERICK_SEARCH_BACKEND=tavily|brave|serpapi|ddg`` to
force a specific backend (skips fall-through).

Each search returns up to ``num_results`` (default 10) entries with
title + URL + snippet.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any

from . import Tool

log = logging.getLogger(__name__)


_SEARCH_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "What to search for. Plain text, no quoting needed.",
        },
        "num_results": {
            "type": "integer",
            "description": "Max results to return (default 10, capped at 25).",
        },
        "site": {
            "type": "string",
            "description": "Optional site: filter (e.g. 'github.com').",
        },
    },
    "required": ["query"],
}


def _augment_query(query: str, site: str | None) -> str:
    if site:
        return f"site:{site} {query}"
    return query


def _format_results(results: list[dict]) -> str:
    """Render search results as a compact text block."""
    if not results:
        return "no results"
    lines: list[str] = []
    for i, r in enumerate(results, 1):
        title = (r.get("title") or "").strip()
        url = (r.get("url") or "").strip()
        snippet = (r.get("snippet") or "").strip()
        snippet = re.sub(r"\s+", " ", snippet)[:400]
        lines.append(f"{i}. {title}\n   {url}\n   {snippet}")
    return "\n\n".join(lines)


def _try_tavily(query: str, num: int) -> list[dict] | None:
    key = os.environ.get("TAVILY_API_KEY")
    if not key:
        return None
    try:
        import httpx
    except ImportError:
        return None
    try:
        resp = httpx.post(
            "https://api.tavily.com/search",
            json={
                "api_key": key,
                "query": query,
                "max_results": num,
                "include_answer": False,
            },
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        log.warning("tavily search failed: %s", e)
        return None
    out = []
    for r in (data.get("results") or [])[:num]:
        out.append({
            "title": r.get("title") or "",
            "url": r.get("url") or "",
            "snippet": r.get("content") or r.get("snippet") or "",
        })
    return out


def _try_brave(query: str, num: int) -> list[dict] | None:
    key = os.environ.get("BRAVE_API_KEY")
    if not key:
        return None
    try:
        import httpx
    except ImportError:
        return None
    try:
        resp = httpx.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": min(num, 20)},
            headers={"X-Subscription-Token": key, "Accept": "application/json"},
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        log.warning("brave search failed: %s", e)
        return None
    out = []
    for r in (data.get("web", {}).get("results") or [])[:num]:
        out.append({
            "title": r.get("title") or "",
            "url": r.get("url") or "",
            "snippet": r.get("description") or "",
        })
    return out


def _try_serpapi(query: str, num: int) -> list[dict] | None:
    key = os.environ.get("SERPAPI_API_KEY")
    if not key:
        return None
    try:
        import httpx
    except ImportError:
        return None
    try:
        resp = httpx.get(
            "https://serpapi.com/search.json",
            params={"q": query, "num": num, "api_key": key, "engine": "google"},
            timeout=20.0,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        # Redact the key: httpx errors embed the full request URL, which
        # carries api_key in the query string for serpapi.
        log.warning("serpapi search failed: %s", str(e).replace(key, "***"))
        return None
    out = []
    for r in (data.get("organic_results") or [])[:num]:
        out.append({
            "title": r.get("title") or "",
            "url": r.get("link") or "",
            "snippet": r.get("snippet") or "",
        })
    return out


def _try_duckduckgo(query: str, num: int) -> list[dict] | None:
    """Last-resort: DuckDuckGo HTML scrape via the official lite endpoint."""
    try:
        import httpx
    except ImportError:
        return None
    try:
        resp = httpx.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            headers={"User-Agent": "Mozilla/5.0 (compatible; Maverick/1.0)"},
            timeout=15.0,
            follow_redirects=True,
        )
        resp.raise_for_status()
        html = resp.text
    except Exception as e:
        log.warning("duckduckgo search failed: %s", e)
        return None
    # DDG HTML lite returns <a class="result__a" href="...">...</a> with
    # adjacent <a class="result__snippet">. Extract via regex (not a
    # general HTML parser -- the lite endpoint output is stable enough).
    pattern = re.compile(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.+?)</a>'
        r'.*?<a[^>]+class="result__snippet"[^>]*>(.+?)</a>',
        re.DOTALL,
    )
    out: list[dict] = []
    for m in pattern.finditer(html):
        url_redirect = m.group(1)
        title_html = re.sub(r"<.*?>", "", m.group(2)).strip()
        snippet_html = re.sub(r"<.*?>", "", m.group(3)).strip()
        # DDG wraps real URLs in a redirector ("/l/?uddg=..."); extract.
        real = url_redirect
        m_uddg = re.search(r"uddg=([^&]+)", url_redirect)
        if m_uddg:
            from urllib.parse import unquote
            real = unquote(m_uddg.group(1))
        if not real.startswith("http"):
            continue
        out.append({"title": title_html, "url": real, "snippet": snippet_html})
        if len(out) >= num:
            break
    return out


_BACKENDS = {
    "tavily":   _try_tavily,
    "brave":    _try_brave,
    "serpapi":  _try_serpapi,
    "ddg":      _try_duckduckgo,
}

# The third-party host each backend sends the query to (for the enterprise
# tool-egress gate -- the query leaves the boundary to whichever one runs).
_BACKEND_HOSTS = {
    "tavily":  "api.tavily.com",
    "brave":   "api.search.brave.com",
    "serpapi": "serpapi.com",
    "ddg":     "html.duckduckgo.com",
}


def _run_search(args: dict[str, Any]) -> str:
    query = (args.get("query") or "").strip()
    if not query:
        return "ERROR: query is required"
    num = max(1, min(int(args.get("num_results") or 10), 25))
    site = args.get("site")
    full_query = _augment_query(query, site)

    forced = os.environ.get("MAVERICK_SEARCH_BACKEND", "").strip().lower()
    if forced and forced in _BACKENDS:
        backends = [(forced, _BACKENDS[forced])]
    else:
        # Try in preference order; first one with credentials (or DDG
        # as last-resort) returns results.
        backends = [
            ("tavily",  _try_tavily),
            ("brave",   _try_brave),
            ("serpapi", _try_serpapi),
            ("ddg",     _try_duckduckgo),
        ]

    # Enterprise mode: the query egresses to a third-party search API. Keep only
    # backends whose host the operator allow-listed; if none, the boundary wins.
    from ..enterprise import egress_permitted, enterprise_enabled
    if enterprise_enabled():
        backends = [
            (name, fn) for name, fn in backends
            if egress_permitted(f"https://{_BACKEND_HOSTS.get(name, '')}")
        ]
        if not backends:
            return (
                "ERROR: web_search is disabled in enterprise mode -- the query would "
                "leave your boundary. Allow-list a search host (e.g. api.tavily.com) "
                "in [enterprise] allowed_hosts to enable it."
            )

    last_err: str | None = None
    for name, fn in backends:
        try:
            results = fn(full_query, num)
        except Exception as e:
            last_err = f"{name}: {type(e).__name__}: {e}"
            log.warning("backend %s raised: %s", name, e)
            continue
        if results is None:
            continue  # backend skipped (no key or no httpx)
        if not results:
            last_err = f"{name}: returned no results"
            continue
        log.info("web_search backend=%s query=%r num=%d", name, query, len(results))
        return f"[backend: {name}]\n\n" + _format_results(results)
    return f"ERROR: no search backend succeeded. last_err={last_err}"


def web_search() -> Tool:
    """Factory: builds the web_search tool."""
    return Tool(
        name="web_search",
        description=(
            "Search the web. Returns up to num_results (default 10) entries "
            "with title, URL, and snippet. Tries Tavily, Brave, SerpAPI, "
            "then DuckDuckGo in order based on which API keys are available. "
            "Use the 'site' arg to scope (e.g. site='github.com'). Use the "
            "'browser' tool to fetch specific URL contents."
        ),
        input_schema=_SEARCH_INPUT_SCHEMA,
        fn=_run_search,
    )
