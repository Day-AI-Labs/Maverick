"""MongoDB tool.

Connect to a MongoDB cluster and run common CRUD operations from
inside an agent task. Auth + connection string from ``MONGODB_URI``;
optionally ``MONGODB_DB`` for the default database.

ops:
  - find(collection, filter, limit, sort)
  - find_one(collection, filter)
  - insert(collection, doc)
  - update(collection, filter, set_, upsert, confirm)   — needs confirm=true
  - delete(collection, filter, confirm)                 — needs confirm=true
  - count(collection, filter)
  - collections()                                       — list names

Mutations are gated by ``confirm=true`` so the agent can't blow away
a collection accidentally.

Requires::

    pip install 'maverick-agent[mongodb]'
"""
from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any

from . import Tool, as_bool

log = logging.getLogger(__name__)


_MONGO_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "op": {
            "type": "string",
            "enum": ["find", "find_one", "insert", "update",
                     "delete", "count", "collections"],
        },
        "db": {"type": "string", "description": "Database name (default: MONGODB_DB)."},
        "collection": {"type": "string"},
        "filter": {"type": "object", "description": "Mongo query filter."},
        "set_": {"type": "object", "description": "$set fields (update)."},
        "doc": {"type": "object", "description": "Doc to insert."},
        "limit": {"type": "integer"},
        "sort": {
            "type": "array",
            "items": {"type": "array", "items": [{"type": "string"}, {"type": "integer"}]},
            "description": "List of (field, direction) pairs. direction = 1 or -1.",
        },
        "upsert": {"type": "boolean"},
        "confirm": {"type": "boolean", "description": "Required true to mutate."},
    },
    "required": ["op"],
}


def _config() -> tuple[str, str]:
    uri = os.environ.get("MONGODB_URI", "").strip()
    db = os.environ.get("MONGODB_DB", "").strip()
    if not uri:
        raise RuntimeError("MongoDB requires MONGODB_URI.")
    return uri, db


# One MongoClient is built per _run() and closed in its finally (see below).
# The old code built a fresh MongoClient -- a connection pool plus background
# topology-monitor threads -- on every _op_* via _db_for and never closed it,
# leaking sockets + threads per tool call. The active client is stashed
# thread-locally so the _op_* helpers reuse it without signature changes.
_TL = threading.local()


def _client():
    cur = getattr(_TL, "client", None)
    if cur is not None:
        return cur
    # Fallback (e.g. a helper called directly outside _run): build a one-off.
    from pymongo import MongoClient
    uri, _db = _config()
    return MongoClient(uri, serverSelectionTimeoutMS=5000)


def _db_for(args: dict[str, Any]):
    _uri, default_db = _config()
    name = (args.get("db") or "").strip() or default_db
    if not name:
        return None, "ERROR: db not provided and MONGODB_DB unset"
    return _client()[name], None


def _serialize(obj: Any) -> Any:
    """ObjectId / datetime / bytes -> JSON-safe."""
    try:
        from bson import ObjectId
    except ImportError:
        ObjectId = None  # type: ignore
    import datetime as _dt
    if ObjectId is not None and isinstance(obj, ObjectId):
        return str(obj)
    if isinstance(obj, (_dt.datetime, _dt.date)):
        return obj.isoformat()
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialize(v) for v in obj]
    return obj


def _dump(obj: Any, max_chars: int = 3000) -> str:
    s = json.dumps(_serialize(obj), indent=2, default=str)
    if len(s) > max_chars:
        s = s[:max_chars] + "\n... (truncated)"
    return s


def _op_collections(args: dict[str, Any]) -> str:
    db, err = _db_for(args)
    if err:
        return err
    names = list(db.list_collection_names())
    return "\n".join(f"  {n}" for n in names) if names else "(no collections)"


def _op_find(args: dict[str, Any]) -> str:
    db, err = _db_for(args)
    if err:
        return err
    col = (args.get("collection") or "").strip()
    if not col:
        return "ERROR: find requires collection"
    flt = args.get("filter") if isinstance(args.get("filter"), dict) else {}
    limit = max(1, min(int(args.get("limit") or 25), 1000))
    sort_pairs = args.get("sort") or []
    cursor = db[col].find(flt)
    if sort_pairs:
        try:
            cursor = cursor.sort([(s[0], int(s[1])) for s in sort_pairs])
        except (TypeError, ValueError, IndexError):
            pass
    docs = list(cursor.limit(limit))
    if not docs:
        return "no docs"
    return _dump(docs)


def _op_find_one(args: dict[str, Any]) -> str:
    db, err = _db_for(args)
    if err:
        return err
    col = (args.get("collection") or "").strip()
    if not col:
        return "ERROR: find_one requires collection"
    flt = args.get("filter") if isinstance(args.get("filter"), dict) else {}
    doc = db[col].find_one(flt)
    if doc is None:
        return "no doc matched"
    return _dump(doc)


def _op_count(args: dict[str, Any]) -> str:
    db, err = _db_for(args)
    if err:
        return err
    col = (args.get("collection") or "").strip()
    if not col:
        return "ERROR: count requires collection"
    flt = args.get("filter") if isinstance(args.get("filter"), dict) else {}
    n = db[col].count_documents(flt)
    return f"{n} document(s) match"


def _op_insert(args: dict[str, Any]) -> str:
    db, err = _db_for(args)
    if err:
        return err
    if not as_bool(args.get("confirm")):
        return "DRY RUN: insert blocked. Re-run with confirm=true."
    col = (args.get("collection") or "").strip()
    doc = args.get("doc") if isinstance(args.get("doc"), dict) else None
    if not col or doc is None:
        return "ERROR: insert requires collection and doc"
    result = db[col].insert_one(doc)
    return f"inserted _id={result.inserted_id}"


def _op_update(args: dict[str, Any]) -> str:
    db, err = _db_for(args)
    if err:
        return err
    if not as_bool(args.get("confirm")):
        return "DRY RUN: update blocked. Re-run with confirm=true."
    col = (args.get("collection") or "").strip()
    flt = args.get("filter") if isinstance(args.get("filter"), dict) else None
    set_ = args.get("set_") if isinstance(args.get("set_"), dict) else None
    if not col or flt is None or set_ is None:
        return "ERROR: update requires collection, filter, set_"
    result = db[col].update_many(flt, {"$set": set_},
                                  upsert=bool(args.get("upsert")))
    return (
        f"matched={result.matched_count} modified={result.modified_count} "
        f"upserted_id={result.upserted_id}"
    )


def _op_delete(args: dict[str, Any]) -> str:
    db, err = _db_for(args)
    if err:
        return err
    if not as_bool(args.get("confirm")):
        return "DRY RUN: delete blocked. Re-run with confirm=true."
    col = (args.get("collection") or "").strip()
    flt = args.get("filter") if isinstance(args.get("filter"), dict) else None
    if not col or flt is None:
        return "ERROR: delete requires collection and filter"
    result = db[col].delete_many(flt)
    return f"deleted_count={result.deleted_count}"


def _run(args: dict[str, Any]) -> str:
    op = args.get("op")
    if not op:
        return "ERROR: op is required"
    try:
        import pymongo  # noqa: F401
    except ImportError:
        return (
            "ERROR: pymongo not installed. "
            "Run: pip install 'maverick-agent[mongodb]'"
        )
    # Build ONE client for this call and close it in finally so we don't leak a
    # pool + monitor threads per op.
    try:
        from pymongo import MongoClient
        uri, _db = _config()
        _TL.client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    except RuntimeError as e:
        return f"ERROR: {e}"
    except Exception as e:
        return f"ERROR: MongoDB request failed: {type(e).__name__}: {e}"
    try:
        if op == "collections":
            return _op_collections(args)
        if op == "find":
            return _op_find(args)
        if op == "find_one":
            return _op_find_one(args)
        if op == "count":
            return _op_count(args)
        if op == "insert":
            return _op_insert(args)
        if op == "update":
            return _op_update(args)
        if op == "delete":
            return _op_delete(args)
    except RuntimeError as e:
        return f"ERROR: {e}"
    except Exception as e:
        return f"ERROR: MongoDB request failed: {type(e).__name__}: {e}"
    finally:
        try:
            _TL.client.close()
        except Exception:
            pass
        _TL.client = None
    return f"ERROR: unknown op {op!r}"


def mongodb_tool() -> Tool:
    return Tool(
        name="mongodb",
        description=(
            "MongoDB CRUD. ops: collections, find (filter + sort + "
            "limit), find_one, count, insert, update (with $set + "
            "upsert), delete. Mutations gated by confirm=true. "
            "Auth: MONGODB_URI (+ MONGODB_DB)."
        ),
        input_schema=_MONGO_SCHEMA,
        fn=_run,
    )
