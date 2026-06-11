"""Skill-marketplace federation — signed listing bundles between instances.

``export_listings`` packs this instance's marketplace listings (the real
storage: :func:`maverick.catalog.load_catalog` entries — the merged, curated
catalog indexes this host trusts) into a versioned, Ed25519-signed envelope::

    {"schema": "maverick-marketplace-fed/1", "origin", "created_at",
     "listings": [...], "pubkey", "key_id", "sig"}

``import_listings`` applies a peer's envelope, **fail-closed**:

  1. signature verified against the *pinned* key for the envelope's origin
     (``[federation] marketplace_peers``); bad/missing signature, unknown
     origin, or a missing ``cryptography`` library all reject the whole
     envelope and persist nothing;
  2. every listing is re-run through the LOCAL moderation gauntlet
     (``maverick.tools.marketplace_moderation._scan`` — projected as
     ``{title: name, description: summary, tags: [kind]}``, the closest
     honest mapping of a catalog entry onto the gauntlet's fields); only
     APPROVE becomes visible, REVIEW/REJECT are recorded with reasons;
  3. a declared ``donation_url`` is re-validated
     (``marketplace_donations.validate_donation_url``); invalid links are
     stripped (the listing itself may still be fine — the link is the risk);
  4. accepted listings are namespaced ``"<origin>/<name>"``. Origins are
     restricted to ``[a-z0-9._-]`` (no ``/``), so an imported name can never
     equal a plain local listing name — imports cannot shadow local entries.

Imports persist to ``data_dir("marketplace_federation_imports.json")``
(atomic, 0600), where one import *replaces* that origin's previous set (a
re-sync, so renames/withdrawals propagate and the store stays bounded).
Browse/install surfaces opt in by merging :func:`imported_listings`; nothing
auto-installs.

**Ratings do NOT federate.** Local ratings (``marketplace_ratings``) are the
operator's own first-person stars; a peer's aggregates are self-asserted
numbers whose provenance this protocol cannot verify (no per-rater identity
or signature), so exports strip ``rating``/``ratings_count`` — along with
``verified`` and ``install_count``, which are equally self-asserted display
fields.
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from .catalog import VALID_KINDS, CatalogEntry
from .federation_envelope import (
    local_origin,
    peer_allowlist,
    sign_envelope,
    verify_envelope,
)
from .marketplace_donations import validate_donation_url

log = logging.getLogger(__name__)

SCHEMA = "maverick-marketplace-fed/1"
MAX_LISTINGS_PER_ENVELOPE = 500

# The identity/install fields a listing federates with. Self-asserted display
# aggregates (rating, ratings_count, verified, install_count) are intentionally
# absent — see module docstring. donation_url is carried when the raw listing
# declares one (CatalogEntry does not model it, so entry-built exports won't).
_EXPORT_KEYS = ("name", "version", "kind", "summary", "source", "sha256",
                "author", "spec", "donation_url")


def _iso(now: float) -> str:
    return datetime.fromtimestamp(now, tz=timezone.utc).isoformat()


def _listing_for_export(raw: object) -> dict | None:
    if isinstance(raw, CatalogEntry):
        raw = raw.to_dict()
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name") or "").strip()
    kind = raw.get("kind")
    if not name or kind not in VALID_KINDS:
        return None
    out = {k: raw[k] for k in _EXPORT_KEYS if raw.get(k) not in (None, "", {}, [])}
    out["name"] = name
    return out


def export_listings(
    kinds: list[str] | tuple[str, ...] | None = None,
    *,
    entries: list | None = None,
    origin: str | None = None,
    now: float | None = None,
) -> dict:
    """Build a signed ``maverick-marketplace-fed/1`` envelope of local listings.

    ``entries`` injects the listings directly (``CatalogEntry`` objects or raw
    listing dicts) — the offline/test seam. Without it, listings come from the
    real storage, :func:`maverick.catalog.load_catalog`, per kind (which serves
    its on-disk cache when offline). Raises
    :class:`maverick.federation_envelope.FederationError` if signing is
    unavailable — an unsigned bundle is never produced.
    """
    if entries is None:
        from .catalog import load_catalog
        entries = []
        for kind in (kinds or VALID_KINDS):
            try:
                entries.extend(load_catalog(kind))
            except Exception as e:  # one bad kind must not hide the rest
                log.warning("marketplace federation: load_catalog(%s) failed: %s", kind, e)
    listings = []
    for raw in entries[:MAX_LISTINGS_PER_ENVELOPE]:
        listing = _listing_for_export(raw)
        if listing is not None:
            listings.append(listing)
    payload = {
        "schema": SCHEMA,
        "origin": origin or local_origin(),
        "created_at": _iso(time.time() if now is None else now),
        "listings": listings,
    }
    return sign_envelope(payload)


# ---------------------------------------------------------------------------
# Import side
# ---------------------------------------------------------------------------

def _store_path(path: Path | None = None) -> Path:
    if path is not None:
        return Path(path)
    from .paths import data_dir
    return data_dir() / "marketplace_federation_imports.json"


def _load_store(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_store(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True),
                   encoding="utf-8")
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:  # pragma: no cover - best-effort on exotic filesystems
        pass


def _moderate(name: str, summary: str, kind: str) -> dict:
    """Run the local moderation gauntlet on a federated listing.

    Projection onto the gauntlet's fields: title=name, description=summary,
    tags=[kind] (a catalog entry has no free-form tags; its kind is the one
    real category it carries).
    """
    from .tools.marketplace_moderation import _scan
    return _scan({"title": name, "description": summary, "tags": [kind]})


def import_listings(
    envelope: object,
    *,
    peers: dict[str, dict] | None = None,
    store_path: Path | None = None,
    now: float | None = None,
) -> dict:
    """Verify + apply a peer's listing bundle. Returns a report dict::

        {"ok", "reason", "origin", "accepted": [namespaced names],
         "rejected": [{"name", "reasons"}], "stripped_donations": [names]}

    Fail-closed: an envelope that fails signature/origin verification (or is
    oversized/malformed) persists **nothing** and reports ``ok=False``.
    """
    report: dict = {"ok": False, "reason": "", "origin": "", "accepted": [],
                    "rejected": [], "stripped_donations": []}
    if peers is None:
        peers = peer_allowlist("marketplace_peers")
    ok, reason = verify_envelope(envelope, expected_schema=SCHEMA, peers=peers)
    if not ok:
        report["reason"] = reason
        log.warning("marketplace federation: rejected envelope: %s", reason)
        return report
    assert isinstance(envelope, dict)  # verify_envelope guarantees this
    origin = envelope["origin"]
    report["origin"] = origin
    listings = envelope.get("listings")
    if not isinstance(listings, list):
        report["reason"] = "listings is not a list"
        return report
    if len(listings) > MAX_LISTINGS_PER_ENVELOPE:
        report["reason"] = (
            f"envelope carries {len(listings)} listings "
            f"(max {MAX_LISTINGS_PER_ENVELOPE})"
        )
        return report

    ts = time.time() if now is None else now
    accepted: dict[str, dict[str, dict]] = {}
    for raw in listings:
        listing = _listing_for_export(raw)
        if listing is None:
            name = str(raw.get("name", "?")) if isinstance(raw, dict) else "?"
            report["rejected"].append({"name": name, "reasons": ["malformed listing"]})
            continue
        name = listing["name"]
        kind = listing["kind"]
        verdict = _moderate(name, str(listing.get("summary", "")), kind)
        if verdict["decision"] != "APPROVE":
            report["rejected"].append(
                {"name": name,
                 "reasons": [f"moderation {verdict['decision']}"] + verdict["reasons"]})
            continue
        if "donation_url" in listing:
            d_ok, d_reason = validate_donation_url(listing["donation_url"])
            if not d_ok:
                listing.pop("donation_url")
                report["stripped_donations"].append(name)
                log.info("marketplace federation: stripped donation_url on %s/%s: %s",
                         origin, name, d_reason)
        namespaced = f"{origin}/{name}"
        listing["name"] = namespaced
        listing["fed_origin"] = origin
        listing["fed_name"] = name
        listing["imported_at"] = round(ts, 3)
        accepted.setdefault(kind, {})[namespaced] = listing
        report["accepted"].append(namespaced)

    path = _store_path(store_path)
    store = _load_store(path)
    # Re-sync semantics: this import replaces the origin's previous set, so
    # withdrawn/renamed listings disappear and the store stays bounded.
    for kind, by_name in store.items():
        if isinstance(by_name, dict):
            store[kind] = {n: v for n, v in by_name.items()
                           if not n.startswith(f"{origin}/")}
    for kind, by_name in accepted.items():
        store.setdefault(kind, {}).update(by_name)
    _save_store(path, store)
    report["ok"] = True
    report["reason"] = "ok"
    return report


def imported_listings(kind: str | None = None,
                      store_path: Path | None = None) -> list[dict]:
    """Federated listings that passed verification + moderation, sorted by name.

    Each carries ``fed_origin`` / ``fed_name`` / ``imported_at`` provenance and
    a namespaced ``name`` (``"<origin>/<name>"``). Display layers merge these
    alongside (never instead of) local catalog entries.
    """
    store = _load_store(_store_path(store_path))
    out: list[dict] = []
    for k, by_name in sorted(store.items()):
        if kind is not None and k != kind:
            continue
        if isinstance(by_name, dict):
            out.extend(v for _, v in sorted(by_name.items()) if isinstance(v, dict))
    return out


__all__ = [
    "SCHEMA",
    "MAX_LISTINGS_PER_ENVELOPE",
    "export_listings",
    "import_listings",
    "imported_listings",
]
