"""Public safety bulletin RSS (roadmap: 2027 H2 safety).

Coordinated disclosure ends with *telling people*. This renders the
deployment's (or the project's) security bulletins — markdown files with a
small frontmatter — into a standards-shaped RSS 2.0 feed that any reader,
SIEM, or status page can subscribe to. Self-host first: the feed is a file
you serve (mkdocs static dir, the dashboard, a bucket), not a hosted service.

Bulletin format (``docs/security/bulletins/*.md`` by convention)::

    ---
    id: MAV-2027-001
    title: Sandbox escape via crafted args
    severity: high
    date: 2027-03-31
    ---

    Body in markdown. The first paragraph becomes the item description.

``maverick bulletins --dir <dir> --out feed.xml`` generates the feed;
ordering is newest-first by date; malformed bulletins are skipped loudly.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

_FRONT = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)
_SEVERITIES = ("low", "medium", "high", "critical")


@dataclass(frozen=True)
class Bulletin:
    id: str
    title: str
    severity: str
    date: date
    body: str

    @property
    def summary(self) -> str:
        for para in self.body.split("\n\n"):
            text = " ".join(para.split())
            if text:
                return text[:500]
        return ""


def parse_bulletin(path: Path) -> Bulletin:
    """Parse one bulletin file; raises ValueError with the reason on bad input."""
    text = path.read_text(encoding="utf-8")
    m = _FRONT.match(text)
    if not m:
        raise ValueError(f"{path.name}: missing frontmatter")
    front, body = m.group(1), m.group(2).strip()
    meta: dict[str, str] = {}
    for line in front.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            meta[k.strip().lower()] = v.strip()
    for req in ("id", "title", "severity", "date"):
        if not meta.get(req):
            raise ValueError(f"{path.name}: frontmatter missing {req!r}")
    sev = meta["severity"].lower()
    if sev not in _SEVERITIES:
        raise ValueError(f"{path.name}: severity must be one of {', '.join(_SEVERITIES)}")
    try:
        d = date.fromisoformat(meta["date"])
    except ValueError:
        raise ValueError(f"{path.name}: date must be ISO (YYYY-MM-DD)")
    return Bulletin(id=meta["id"], title=meta["title"], severity=sev, date=d, body=body)


def load_bulletins(directory: Path) -> tuple[list[Bulletin], list[str]]:
    """All parseable bulletins (newest first) + skip reasons for the rest."""
    bulletins: list[Bulletin] = []
    skipped: list[str] = []
    for p in sorted(Path(directory).glob("*.md")):
        try:
            bulletins.append(parse_bulletin(p))
        except (ValueError, OSError) as e:
            skipped.append(str(e))
    bulletins.sort(key=lambda b: (b.date, b.id), reverse=True)
    return bulletins, skipped


def render_rss(
    bulletins: list[Bulletin],
    *,
    base_url: str = "https://example.invalid/security/bulletins",
    title: str = "Maverick security bulletins",
) -> str:
    """RSS 2.0 over the bulletins. ``base_url`` is where the operator serves
    the bulletin pages (item links are ``<base_url>/<id>``)."""
    now = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
    items = []
    for b in bulletins:
        pub = datetime(b.date.year, b.date.month, b.date.day,
                       tzinfo=timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
        items.append(
            "    <item>\n"
            f"      <title>[{escape(b.severity.upper())}] {escape(b.title)}</title>\n"
            f"      <link>{escape(base_url.rstrip('/'))}/{escape(b.id)}</link>\n"
            f"      <guid isPermaLink=\"false\">{escape(b.id)}</guid>\n"
            f"      <pubDate>{pub}</pubDate>\n"
            f"      <description>{escape(b.summary)}</description>\n"
            "    </item>"
        )
    return (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
        "<rss version=\"2.0\">\n"
        "  <channel>\n"
        f"    <title>{escape(title)}</title>\n"
        f"    <link>{escape(base_url)}</link>\n"
        "    <description>Coordinated-disclosure bulletins</description>\n"
        f"    <lastBuildDate>{now}</lastBuildDate>\n"
        + ("\n".join(items) + "\n" if items else "")
        + "  </channel>\n"
        "</rss>\n"
    )


__all__ = ["Bulletin", "parse_bulletin", "load_bulletins", "render_rss"]
