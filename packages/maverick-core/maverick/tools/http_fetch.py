"""HTTP fetch tool. Fetch a URL and return readable text.

For agents that need to read web pages without launching a full browser
session. Lighter than the `browser` tool: a single GET with retries +
HTML-to-text conversion.

Respects:
  - http(s) only (refuses file://, ftp://, etc.)
  - robots.txt when ``MAVERICK_FETCH_RESPECT_ROBOTS=1``
  - private IP ranges blocked unless ``MAVERICK_FETCH_ALLOW_PRIVATE=1``
"""
from __future__ import annotations

import ipaddress
import logging
import re
import socket
from typing import Any
from urllib.parse import urljoin, urlparse

from . import Tool

log = logging.getLogger(__name__)


_FETCH_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "url": {"type": "string", "description": "http or https URL to fetch."},
        "method": {
            "type": "string",
            "enum": ["GET", "POST", "HEAD"],
            "description": "HTTP method (default GET).",
        },
        "headers": {
            "type": "object",
            "description": "Additional request headers.",
        },
        "body": {
            "type": "string",
            "description": "Request body for POST (raw string).",
        },
        "render": {
            "type": "string",
            "enum": ["text", "html", "markdown", "raw"],
            "description": "Output rendering. Default 'markdown'.",
        },
        "max_bytes": {
            "type": "integer",
            "description": "Cap response body size (default 200_000).",
        },
    },
    "required": ["url"],
}


_HTML_BLOCK_TAGS = re.compile(r"<(p|br|div|li|tr|h[1-6])[^>]*>", re.IGNORECASE)


def _strip_html_to_text(html: str) -> str:
    """Convert HTML to plain text without an external dep.

    Not a full readability extractor -- just a cleanup: drop scripts/
    styles, render block tags as newlines, strip remaining tags.
    """
    html = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style[^>]*>.*?</style>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<!--.*?-->", " ", html, flags=re.DOTALL)
    html = _HTML_BLOCK_TAGS.sub("\n", html)
    html = re.sub(r"</(p|div|li|tr|h[1-6])>", "\n", html, flags=re.IGNORECASE)
    html = re.sub(r"<[^>]+>", " ", html)
    # Collapse whitespace.
    html = re.sub(r"[ \t]+", " ", html)
    html = re.sub(r"\n{3,}", "\n\n", html)
    # Unescape common entities (no external dep).
    entities = {
        "&amp;": "&", "&lt;": "<", "&gt;": ">",
        "&quot;": '"', "&#39;": "'", "&apos;": "'",
        "&nbsp;": " ", "&mdash;": "—", "&ndash;": "–",
        "&hellip;": "…",
    }
    for k, v in entities.items():
        html = html.replace(k, v)
    return html.strip()


def _to_markdown(html: str) -> str:
    """Cheap HTML -> markdown: preserve links + headings + lists."""
    out = html
    out = re.sub(r"<h1[^>]*>(.+?)</h1>", r"# \1\n", out, flags=re.DOTALL | re.IGNORECASE)
    out = re.sub(r"<h2[^>]*>(.+?)</h2>", r"## \1\n", out, flags=re.DOTALL | re.IGNORECASE)
    out = re.sub(r"<h3[^>]*>(.+?)</h3>", r"### \1\n", out, flags=re.DOTALL | re.IGNORECASE)
    out = re.sub(r"<h([4-6])[^>]*>(.+?)</h\1>", r"#### \2\n", out, flags=re.DOTALL | re.IGNORECASE)
    # Accept both single- and double-quoted href values; some HTML in
    # the wild uses ' instead of ".
    out = re.sub(
        r"""<a[^>]+href=["']([^"']+)["'][^>]*>(.+?)</a>""",
        lambda m: f"[{_strip_html_to_text(m.group(2))}]({m.group(1)})",
        out,
        flags=re.DOTALL | re.IGNORECASE,
    )
    out = re.sub(r"<li[^>]*>(.+?)</li>", r"- \1", out, flags=re.DOTALL | re.IGNORECASE)
    out = re.sub(r"<strong[^>]*>(.+?)</strong>", r"**\1**", out, flags=re.DOTALL | re.IGNORECASE)
    out = re.sub(r"<b[^>]*>(.+?)</b>", r"**\1**", out, flags=re.DOTALL | re.IGNORECASE)
    out = re.sub(r"<em[^>]*>(.+?)</em>", r"_\1_", out, flags=re.DOTALL | re.IGNORECASE)
    out = re.sub(r"<i[^>]*>(.+?)</i>", r"_\1_", out, flags=re.DOTALL | re.IGNORECASE)
    out = re.sub(r"<code[^>]*>(.+?)</code>", r"`\1`", out, flags=re.DOTALL | re.IGNORECASE)
    return _strip_html_to_text(out)


def _is_private_ip(host: str) -> bool:
    """Best-effort: refuse private/loopback addrs unless explicitly allowed."""
    try:
        addrs = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False  # Can't resolve -- httpx will error meaningfully.
    for fam, _stype, _proto, _name, sockaddr in addrs:
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local:
            return True
    return False


def _check_robots(url: str, user_agent: str = "Maverick") -> bool:
    """Return True if robots.txt allows ``url`` for ``user_agent``."""
    try:
        import httpx
    except ImportError:
        return True
    parsed = urlparse(url)
    robots_url = urljoin(f"{parsed.scheme}://{parsed.netloc}", "/robots.txt")
    try:
        resp = httpx.get(robots_url, timeout=5.0, follow_redirects=True)
        if resp.status_code >= 400:
            return True
    except Exception:
        return True
    # Very small parser: handles 'User-agent: *' + 'Disallow:' rules. We
    # don't implement the full spec; for that, use the browser tool with
    # a real Playwright context.
    body = resp.text
    in_section = False
    allowed = True
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip()
        if key == "user-agent":
            in_section = value == "*" or value.lower() == user_agent.lower()
        elif key == "disallow" and in_section:
            if value and parsed.path.startswith(value):
                allowed = False
    return allowed


def _run_fetch(args: dict[str, Any]) -> str:
    import os

    url = (args.get("url") or "").strip()
    if not url:
        return "ERROR: url is required"
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return f"ERROR: only http/https supported; got scheme={parsed.scheme!r}"
    if not parsed.netloc:
        return "ERROR: missing host in URL"
    if os.environ.get("MAVERICK_FETCH_ALLOW_PRIVATE") != "1":
        if _is_private_ip(parsed.hostname or ""):
            return (
                f"ERROR: refusing to fetch private/loopback address {parsed.hostname!r}. "
                "Set MAVERICK_FETCH_ALLOW_PRIVATE=1 to override."
            )
    if os.environ.get("MAVERICK_FETCH_RESPECT_ROBOTS") == "1":
        if not _check_robots(url):
            return f"ERROR: blocked by robots.txt for {url!r}"

    try:
        import httpx
    except ImportError:
        return "ERROR: httpx not installed. Run: pip install 'maverick-agent[session]'"

    method = (args.get("method") or "GET").upper()
    headers = dict(args.get("headers") or {})
    headers.setdefault("User-Agent", "Mozilla/5.0 (compatible; Maverick/1.0)")
    headers.setdefault("Accept", "text/html,application/xhtml+xml,*/*;q=0.8")
    body = args.get("body")
    max_bytes = int(args.get("max_bytes") or 200_000)
    render = (args.get("render") or "markdown").lower()

    try:
        with httpx.Client(timeout=30.0, follow_redirects=False) as client:
            resp = client.request(method, url, headers=headers, content=body)
    except httpx.HTTPError as e:
        return f"ERROR: {type(e).__name__}: {e}"

    raw_bytes = resp.content[:max_bytes]
    try:
        text = raw_bytes.decode(resp.encoding or "utf-8", errors="replace")
    except (LookupError, UnicodeDecodeError):
        text = raw_bytes.decode("utf-8", errors="replace")

    content_type = (resp.headers.get("content-type") or "").lower()
    looks_html = ("html" in content_type) or text.lstrip().startswith("<")

    if render == "raw" or not looks_html:
        rendered = text
    elif render == "html":
        rendered = text
    elif render == "text":
        rendered = _strip_html_to_text(text)
    else:  # markdown
        rendered = _to_markdown(text)

    header = (
        f"HTTP {resp.status_code} {resp.reason_phrase} "
        f"({content_type or 'unknown'}; {len(resp.content)} bytes)\n"
        f"URL: {resp.url}\n"
    )
    return header + "\n" + rendered


def http_fetch() -> Tool:
    """Factory: builds the http_fetch tool."""
    return Tool(
        name="http_fetch",
        description=(
            "Fetch an HTTP/HTTPS URL and return its content. Default render "
            "is 'markdown' (HTML → readable markdown with links/headings); "
            "set render='text' for plain text, 'html' for raw HTML, 'raw' "
            "for non-HTML bytes. Refuses private/loopback addresses unless "
            "MAVERICK_FETCH_ALLOW_PRIVATE=1; respects robots.txt when "
            "MAVERICK_FETCH_RESPECT_ROBOTS=1."
        ),
        input_schema=_FETCH_INPUT_SCHEMA,
        fn=_run_fetch,
    )
