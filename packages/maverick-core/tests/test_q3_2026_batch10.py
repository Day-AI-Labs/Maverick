"""Q3 2026 batch 10: MongoDB, Redis, Sentry tools."""
from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock


# ---------- MongoDB ----------

def test_mongodb_requires_op():
    from maverick.tools.mongodb_tool import mongodb_tool
    assert "op is required" in mongodb_tool().fn({})


def test_mongodb_missing_pymongo(monkeypatch):
    monkeypatch.setitem(sys.modules, "pymongo", None)
    from maverick.tools.mongodb_tool import mongodb_tool
    out = mongodb_tool().fn({"op": "collections"})
    assert "pymongo not installed" in out


def _install_fake_mongo(monkeypatch, *, db_name="test", collections=None,
                       find_docs=None, find_one=None,
                       insert_id="abc", update_result=None,
                       delete_count=0, count=0):
    """Wire a minimal pymongo stub into sys.modules."""
    pymongo = types.ModuleType("pymongo")

    class _Cursor:
        def __init__(self, docs):
            self._docs = list(docs or [])

        def sort(self, *a, **k):
            return self

        def limit(self, n):
            return iter(self._docs[:n])

        def __iter__(self):
            return iter(self._docs)

    class _Col:
        def find(self, flt):
            return _Cursor(find_docs or [])

        def find_one(self, flt):
            return find_one

        def insert_one(self, doc):
            m = MagicMock()
            m.inserted_id = insert_id
            return m

        def update_many(self, flt, doc, upsert=False):
            return update_result or MagicMock(
                matched_count=1, modified_count=1, upserted_id=None,
            )

        def delete_many(self, flt):
            m = MagicMock()
            m.deleted_count = delete_count
            return m

        def count_documents(self, flt):
            return count

    class _DB:
        def list_collection_names(self):
            return collections or []

        def __getitem__(self, _name):
            return _Col()

    class _MongoClient:
        def __init__(self, *a, **k):
            pass

        def __getitem__(self, _name):
            return _DB()

    pymongo.MongoClient = _MongoClient
    monkeypatch.setitem(sys.modules, "pymongo", pymongo)


def test_mongodb_collections(monkeypatch):
    monkeypatch.setenv("MONGODB_URI", "mongodb://x")
    monkeypatch.setenv("MONGODB_DB", "test")
    _install_fake_mongo(monkeypatch, collections=["users", "orders"])
    from maverick.tools.mongodb_tool import mongodb_tool
    out = mongodb_tool().fn({"op": "collections"})
    assert "users" in out and "orders" in out


def test_mongodb_find(monkeypatch):
    monkeypatch.setenv("MONGODB_URI", "mongodb://x")
    monkeypatch.setenv("MONGODB_DB", "test")
    _install_fake_mongo(
        monkeypatch,
        find_docs=[{"_id": 1, "name": "alice"}, {"_id": 2, "name": "bob"}],
    )
    from maverick.tools.mongodb_tool import mongodb_tool
    out = mongodb_tool().fn({"op": "find", "collection": "users", "filter": {}})
    assert "alice" in out and "bob" in out


def test_mongodb_count(monkeypatch):
    monkeypatch.setenv("MONGODB_URI", "mongodb://x")
    monkeypatch.setenv("MONGODB_DB", "test")
    _install_fake_mongo(monkeypatch, count=42)
    from maverick.tools.mongodb_tool import mongodb_tool
    out = mongodb_tool().fn({"op": "count", "collection": "users",
                              "filter": {"active": True}})
    assert "42" in out


def test_mongodb_insert_dry_run(monkeypatch):
    monkeypatch.setenv("MONGODB_URI", "mongodb://x")
    monkeypatch.setenv("MONGODB_DB", "test")
    _install_fake_mongo(monkeypatch)
    from maverick.tools.mongodb_tool import mongodb_tool
    out = mongodb_tool().fn({
        "op": "insert", "collection": "users", "doc": {"name": "x"},
    })
    assert "DRY RUN" in out


def test_mongodb_insert_confirmed(monkeypatch):
    monkeypatch.setenv("MONGODB_URI", "mongodb://x")
    monkeypatch.setenv("MONGODB_DB", "test")
    _install_fake_mongo(monkeypatch, insert_id="newid")
    from maverick.tools.mongodb_tool import mongodb_tool
    out = mongodb_tool().fn({
        "op": "insert", "collection": "users", "doc": {"name": "x"},
        "confirm": True,
    })
    assert "newid" in out


def test_mongodb_update_dry_run(monkeypatch):
    monkeypatch.setenv("MONGODB_URI", "mongodb://x")
    monkeypatch.setenv("MONGODB_DB", "test")
    _install_fake_mongo(monkeypatch)
    from maverick.tools.mongodb_tool import mongodb_tool
    out = mongodb_tool().fn({
        "op": "update", "collection": "u", "filter": {"id": 1},
        "set_": {"name": "y"},
    })
    assert "DRY RUN" in out


def test_mongodb_delete_dry_run(monkeypatch):
    monkeypatch.setenv("MONGODB_URI", "mongodb://x")
    monkeypatch.setenv("MONGODB_DB", "test")
    _install_fake_mongo(monkeypatch)
    from maverick.tools.mongodb_tool import mongodb_tool
    out = mongodb_tool().fn({
        "op": "delete", "collection": "u", "filter": {"id": 1},
    })
    assert "DRY RUN" in out


# ---------- Redis ----------

def test_redis_requires_op():
    from maverick.tools.redis_tool import redis_tool
    assert "op is required" in redis_tool().fn({})


def test_redis_missing_lib(monkeypatch):
    monkeypatch.setitem(sys.modules, "redis", None)
    from maverick.tools.redis_tool import redis_tool
    out = redis_tool().fn({"op": "get", "key": "x"})
    assert "redis not installed" in out


def _install_fake_redis(monkeypatch, **overrides):
    class _Redis:
        def __init__(self, *a, **k):
            for k_, v in overrides.items():
                setattr(self, k_, MagicMock(return_value=v))

        @classmethod
        def from_url(cls, url, **k):
            return cls()

    redis_mod = types.ModuleType("redis")
    redis_mod.Redis = _Redis
    monkeypatch.setitem(sys.modules, "redis", redis_mod)


def test_redis_get_returns_value(monkeypatch):
    _install_fake_redis(monkeypatch, get="hello")
    monkeypatch.setenv("REDIS_URL", "redis://localhost")
    from maverick.tools.redis_tool import redis_tool
    out = redis_tool().fn({"op": "get", "key": "greeting"})
    assert "hello" in out


def test_redis_get_nil(monkeypatch):
    _install_fake_redis(monkeypatch, get=None)
    monkeypatch.setenv("REDIS_URL", "redis://localhost")
    from maverick.tools.redis_tool import redis_tool
    out = redis_tool().fn({"op": "get", "key": "missing"})
    assert "(nil)" in out


def test_redis_set_with_ttl(monkeypatch):
    _install_fake_redis(monkeypatch, set=True)
    monkeypatch.setenv("REDIS_URL", "redis://localhost")
    from maverick.tools.redis_tool import redis_tool
    out = redis_tool().fn({
        "op": "set", "key": "k", "value": "v", "ttl_seconds": 60,
    })
    assert "OK" in out and "ttl=60" in out


def test_redis_keys_scan(monkeypatch):
    class _Redis:
        def __init__(self, *a, **k):
            pass

        @classmethod
        def from_url(cls, url, **k):
            return cls()

        def scan(self, cursor=0, match=None, count=200):
            # one batch then done
            if cursor == 0:
                return (0, ["a", "b"])
            return (0, [])

    redis_mod = types.ModuleType("redis")
    redis_mod.Redis = _Redis
    monkeypatch.setitem(sys.modules, "redis", redis_mod)
    monkeypatch.setenv("REDIS_URL", "redis://localhost")
    from maverick.tools.redis_tool import redis_tool
    out = redis_tool().fn({"op": "keys", "pattern": "*"})
    assert "a" in out and "b" in out


def test_redis_publish(monkeypatch):
    _install_fake_redis(monkeypatch, publish=3)
    monkeypatch.setenv("REDIS_URL", "redis://localhost")
    from maverick.tools.redis_tool import redis_tool
    out = redis_tool().fn({"op": "publish", "channel": "alerts", "message": "x"})
    assert "3 subscriber" in out


# ---------- Sentry ----------

def test_sentry_requires_op():
    from maverick.tools.sentry_tool import sentry_tool
    assert "op is required" in sentry_tool().fn({})


def test_sentry_missing_token(monkeypatch):
    monkeypatch.delenv("SENTRY_AUTH_TOKEN", raising=False)
    fake = types.ModuleType("httpx")
    fake.get = MagicMock()
    monkeypatch.setitem(sys.modules, "httpx", fake)
    from maverick.tools.sentry_tool import sentry_tool
    out = sentry_tool().fn({"op": "issues"})
    assert "SENTRY_AUTH_TOKEN" in out


def test_sentry_issues_requires_project(monkeypatch):
    monkeypatch.setenv("SENTRY_AUTH_TOKEN", "x")
    monkeypatch.delenv("SENTRY_ORG", raising=False)
    monkeypatch.delenv("SENTRY_PROJECT", raising=False)
    fake = types.ModuleType("httpx")
    fake.get = MagicMock()
    monkeypatch.setitem(sys.modules, "httpx", fake)
    from maverick.tools.sentry_tool import sentry_tool
    out = sentry_tool().fn({"op": "issues"})
    assert "SENTRY_ORG" in out and "SENTRY_PROJECT" in out


def test_sentry_issues_renders(monkeypatch):
    monkeypatch.setenv("SENTRY_AUTH_TOKEN", "x")
    monkeypatch.setenv("SENTRY_ORG", "org")
    monkeypatch.setenv("SENTRY_PROJECT", "proj")
    resp = MagicMock()
    resp.status_code = 200
    resp.json = MagicMock(return_value=[
        {"shortId": "PROJ-1", "level": "error", "count": 12,
         "userCount": 4, "title": "NullPointer in foo"},
    ])
    fake_httpx = types.ModuleType("httpx")
    fake_httpx.get = MagicMock(return_value=resp)
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)
    from maverick.tools.sentry_tool import sentry_tool
    out = sentry_tool().fn({"op": "issues"})
    assert "PROJ-1" in out and "NullPointer" in out


def test_sentry_resolve_dry_run(monkeypatch):
    monkeypatch.setenv("SENTRY_AUTH_TOKEN", "x")
    fake_httpx = types.ModuleType("httpx")
    fake_httpx.put = MagicMock()
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)
    from maverick.tools.sentry_tool import sentry_tool
    out = sentry_tool().fn({"op": "resolve", "issue_id": "123"})
    assert "DRY RUN" in out
    fake_httpx.put.assert_not_called()


def test_sentry_resolve_confirmed(monkeypatch):
    monkeypatch.setenv("SENTRY_AUTH_TOKEN", "x")
    resp = MagicMock()
    resp.status_code = 200
    resp.json = MagicMock(return_value={"status": "resolved"})
    fake_httpx = types.ModuleType("httpx")
    fake_httpx.put = MagicMock(return_value=resp)
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)
    from maverick.tools.sentry_tool import sentry_tool
    out = sentry_tool().fn({"op": "resolve", "issue_id": "123", "confirm": True})
    assert "resolved 123" in out


# ---------- registration smoke ----------

def test_new_tools_register(tmp_path):
    from maverick.sandbox.local import LocalBackend
    from maverick.tools import base_registry

    class _W:
        def open_questions(self, gid):
            return []

    reg = base_registry(_W(), LocalBackend(workdir=tmp_path))
    names = {t.name for t in reg.all()}
    for n in ("mongodb", "redis", "sentry"):
        assert n in names, f"{n} not registered"
