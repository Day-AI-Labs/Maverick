"""Q3 2026 batch 9: openapi_runner, ocr, posthog, shopify tools, llm_cache."""
from __future__ import annotations

import json
import sys
import time
import types
from unittest.mock import MagicMock

# ---------- OpenAPI runner ----------

_TINY_OAS = {
    "openapi": "3.0.0",
    "info": {"title": "Petstore", "version": "1.0"},
    "servers": [{"url": "https://api.example.com"}],
    "paths": {
        "/pets/{petId}": {
            "get": {
                "operationId": "getPet",
                "summary": "Get a pet by id",
                "parameters": [
                    {"name": "petId", "in": "path", "required": True,
                     "schema": {"type": "integer"}},
                ],
            },
            "delete": {
                "operationId": "deletePet",
                "summary": "Delete a pet",
                "parameters": [
                    {"name": "petId", "in": "path", "required": True,
                     "schema": {"type": "integer"}},
                ],
            },
        },
        "/pets": {
            "post": {
                "operationId": "createPet",
                "summary": "Create a pet",
                "requestBody": {
                    "content": {"application/json": {
                        "schema": {"type": "object",
                                   "properties": {"name": {"type": "string"}}},
                    }},
                },
            },
        },
    },
}


def _write_spec(tmp_path, name="spec.json"):
    import maverick.tools.openapi_runner as oas
    oas._spec_cache.clear()  # noqa: SLF001 - test reset
    p = tmp_path / name
    p.write_text(json.dumps(_TINY_OAS))
    return str(p)


def test_openapi_list_ops(tmp_path):
    from maverick.tools.openapi_runner import openapi_runner
    out = openapi_runner().fn({"op": "list_ops", "spec": _write_spec(tmp_path)})
    assert "getPet" in out and "createPet" in out and "deletePet" in out
    assert "GET" in out and "POST" in out


def test_openapi_describe(tmp_path):
    from maverick.tools.openapi_runner import openapi_runner
    out = openapi_runner().fn({
        "op": "describe", "spec": _write_spec(tmp_path), "op_id": "getPet",
    })
    assert "GET /pets/{petId}" in out
    assert "param (path): petId*" in out


def test_openapi_describe_unknown(tmp_path):
    from maverick.tools.openapi_runner import openapi_runner
    out = openapi_runner().fn({
        "op": "describe", "spec": _write_spec(tmp_path), "op_id": "bogus",
    })
    assert "not found" in out


def _patch_safe_client(monkeypatch, response, captured):
    """Stand in for maverick.tools._ssrf.safe_client (which pins the
    connection to a validated public IP). Captures the request and returns
    ``response`` so the offline unit tests don't do real DNS / sockets."""
    class _Client:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def request(self, method, url, **kw):
            captured["method"] = method
            captured["url"] = url
            captured["kw"] = kw
            captured["body"] = kw.get("json")
            return response

        def get(self, url, **kw):
            captured["url"] = url
            captured["kw"] = kw
            return response

    import maverick.tools._ssrf as _ssrf
    monkeypatch.setattr(_ssrf, "safe_client", lambda url, **kw: _Client())


def test_openapi_call_substitutes_path_param(tmp_path, monkeypatch):
    captured = {"url": None}
    resp = MagicMock()
    resp.status_code = 200
    resp.text = '{"id": 7, "name": "Fido"}'
    _patch_safe_client(monkeypatch, resp, captured)
    from maverick.tools.openapi_runner import openapi_runner
    out = openapi_runner().fn({
        "op": "call", "spec": _write_spec(tmp_path),
        "op_id": "getPet", "params": {"petId": 7},
    })
    assert "HTTP 200" in out and "Fido" in out
    assert captured["url"] == "https://api.example.com/pets/7"
    assert captured["method"] == "GET"


def test_openapi_call_missing_required_path_param(tmp_path, monkeypatch):
    # Missing path param is rejected before any fetch, so no client needed.
    from maverick.tools.openapi_runner import openapi_runner
    out = openapi_runner().fn({
        "op": "call", "spec": _write_spec(tmp_path),
        "op_id": "getPet", "params": {},
    })
    assert "required path param" in out


def test_openapi_call_sends_body(tmp_path, monkeypatch):
    captured = {"body": None}
    resp = MagicMock()
    resp.status_code = 201
    resp.text = "{}"
    _patch_safe_client(monkeypatch, resp, captured)
    from maverick.tools.openapi_runner import openapi_runner
    out = openapi_runner().fn({
        "op": "call", "spec": _write_spec(tmp_path),
        "op_id": "createPet", "body": {"name": "Rex"},
    })
    assert "HTTP 201" in out
    assert captured["body"] == {"name": "Rex"}


def test_openapi_call_blocks_private_base_url(tmp_path, monkeypatch):
    # No client patch: safe_client must resolve 127.0.0.1, see it's
    # non-public, and refuse before any connection (works offline).
    from maverick.tools.openapi_runner import openapi_runner
    out = openapi_runner().fn({
        "op": "call", "spec": _write_spec(tmp_path),
        "op_id": "getPet", "params": {"petId": 7},
        "base_url": "http://127.0.0.1:8080",
    })
    assert "refusing to fetch" in out and "127.0.0.1" in out


# ---------- OCR tool ----------

def test_ocr_requires_op():
    from maverick.tools.ocr import ocr
    assert "op is required" in ocr().fn({})


def test_ocr_extract_validates_path():
    from maverick.tools.ocr import ocr
    out = ocr().fn({"op": "extract"})
    assert "requires path" in out


def test_ocr_missing_tesseract(tmp_path, monkeypatch):
    img = tmp_path / "x.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("shutil.which", lambda b: None)
    from maverick.tools.ocr import ocr
    out = ocr().fn({"op": "extract", "path": str(img)})
    assert "tesseract not on PATH" in out


def test_ocr_extract_runs_tesseract(tmp_path, monkeypatch):
    img = tmp_path / "x.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("shutil.which", lambda b: "/usr/bin/tesseract")
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **k: MagicMock(returncode=0, stdout="Hello world\n", stderr=""),
    )
    from maverick.tools.ocr import ocr
    out = ocr().fn({"op": "extract", "path": str(img)})
    assert "Hello world" in out


def test_ocr_hf_backend_requires_token(tmp_path, monkeypatch):
    img = tmp_path / "x.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("HUGGINGFACE_API_TOKEN", raising=False)
    fake_httpx = types.ModuleType("httpx")
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)
    from maverick.tools.ocr import ocr
    out = ocr().fn({"op": "extract", "path": str(img), "backend": "hf"})
    assert "HUGGINGFACE_API_TOKEN" in out


def test_ocr_extract_blocks_path_escape():
    from maverick.tools.ocr import ocr
    out = ocr().fn({"op": "extract", "path": "/etc/hosts"})
    assert "path escapes workspace" in out


def test_ocr_extract_url_blocks_private():
    # safe_get resolves 127.0.0.1, sees it's non-public, and refuses (offline).
    from maverick.tools.ocr import ocr
    out = ocr().fn({"op": "extract_url", "url": "http://127.0.0.1:8000/a.png"})
    assert "refusing to fetch" in out and "127.0.0.1" in out


def test_ocr_extract_url_uses_workspace_tempfile(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("shutil.which", lambda b: "/usr/bin/tesseract")
    monkeypatch.setattr("maverick.tools.ocr._run_tesseract", lambda *_a, **_k: "ok")

    class _Resp:
        status_code = 200
        headers = {"content-type": "image/png"}
        content = b"\x89PNG\r\n\x1a\n"

    # Patch the SSRF-safe fetcher (pins the connection) rather than httpx.
    import maverick.tools._ssrf as _ssrf
    monkeypatch.setattr(_ssrf, "safe_get", lambda url, **kw: _Resp())

    from maverick.tools.ocr import ocr
    out = ocr().fn({"op": "extract_url", "url": "http://example.com/a.png"})
    assert out == "ok"


# ---------- PostHog tool ----------

def test_posthog_requires_op():
    from maverick.tools.posthog_tool import posthog_tool
    assert "op is required" in posthog_tool().fn({})


def test_posthog_capture_missing_key(monkeypatch):
    monkeypatch.delenv("POSTHOG_API_KEY", raising=False)
    fake_httpx = types.ModuleType("httpx")
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)
    from maverick.tools.posthog_tool import posthog_tool
    out = posthog_tool().fn({
        "op": "capture", "event": "x", "distinct_id": "u",
    })
    assert "POSTHOG_API_KEY" in out


def _posthog_capture_url(monkeypatch, env):
    """Run a capture with the given env and return the URL events were POSTed to."""
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    captured = {"url": None, "json": None}

    def _post(url, *a, **k):
        captured["url"] = url
        captured["json"] = k.get("json")
        m = MagicMock()
        m.status_code = 200
        m.text = "1"
        return m

    fake_httpx = types.ModuleType("httpx")
    fake_httpx.post = _post
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)
    from maverick.tools.posthog_tool import posthog_tool
    out = posthog_tool().fn({
        "op": "capture", "event": "goal_done",
        "distinct_id": "user-1", "properties": {"cost": 0.42},
    })
    return out, captured


def test_posthog_capture_posts(monkeypatch):
    out, captured = _posthog_capture_url(monkeypatch, {"POSTHOG_API_KEY": "phc_xx"})
    assert "captured 'goal_done'" in out
    assert captured["json"]["event"] == "goal_done"
    assert captured["json"]["api_key"] == "phc_xx"
    # Default US region: events ingest on the dedicated i.posthog.com host.
    assert captured["url"] == "https://us.i.posthog.com/capture/"


def test_posthog_capture_uses_eu_ingestion_host(monkeypatch):
    _out, captured = _posthog_capture_url(monkeypatch, {
        "POSTHOG_API_KEY": "phc_xx", "POSTHOG_HOST": "https://eu.posthog.com",
    })
    assert captured["url"] == "https://eu.i.posthog.com/capture/"


def test_posthog_capture_honours_explicit_ingestion_host(monkeypatch):
    _out, captured = _posthog_capture_url(monkeypatch, {
        "POSTHOG_API_KEY": "phc_xx",
        "POSTHOG_HOST": "https://eu.posthog.com",
        "POSTHOG_INGESTION_HOST": "https://ph.internal.example.com",
    })
    assert captured["url"] == "https://ph.internal.example.com/capture/"


def test_posthog_capture_selfhosted_uses_same_host(monkeypatch):
    _out, captured = _posthog_capture_url(monkeypatch, {
        "POSTHOG_API_KEY": "phc_xx",
        "POSTHOG_HOST": "https://posthog.mycorp.internal",
    })
    # Self-hosted instances ingest on the same host (no i-subdomain split).
    assert captured["url"] == "https://posthog.mycorp.internal/capture/"


def test_posthog_insights_requires_keys(monkeypatch):
    monkeypatch.delenv("POSTHOG_PERSONAL_API_KEY", raising=False)
    monkeypatch.delenv("POSTHOG_PROJECT_ID", raising=False)
    fake_httpx = types.ModuleType("httpx")
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)
    from maverick.tools.posthog_tool import posthog_tool
    out = posthog_tool().fn({"op": "insights"})
    assert "POSTHOG_PERSONAL_API_KEY" in out


# ---------- Shopify tool ----------

def test_shopify_requires_op():
    from maverick.tools.shopify_tool import shopify_tool
    assert "op is required" in shopify_tool().fn({})


def test_shopify_missing_config(monkeypatch):
    monkeypatch.delenv("SHOPIFY_STORE", raising=False)
    monkeypatch.delenv("SHOPIFY_ACCESS_TOKEN", raising=False)
    fake = types.ModuleType("httpx")
    fake.Client = MagicMock()
    monkeypatch.setitem(sys.modules, "httpx", fake)
    from maverick.tools.shopify_tool import shopify_tool
    out = shopify_tool().fn({"op": "orders"})
    assert "SHOPIFY_STORE" in out and "SHOPIFY_ACCESS_TOKEN" in out


def test_shopify_orders_renders(monkeypatch):
    monkeypatch.setenv("SHOPIFY_STORE", "my-shop")
    monkeypatch.setenv("SHOPIFY_ACCESS_TOKEN", "shpat_xx")
    resp = MagicMock()
    resp.status_code = 200
    resp.json = MagicMock(return_value={"orders": [
        {"name": "#1001", "financial_status": "paid",
         "total_price": "49.99", "currency": "USD",
         "customer": {"email": "alice@x"}},
    ]})

    client = MagicMock()
    client.get = MagicMock(return_value=resp)
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    fake_httpx = types.ModuleType("httpx")
    fake_httpx.Client = MagicMock(return_value=client)
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)
    from maverick.tools.shopify_tool import shopify_tool
    out = shopify_tool().fn({"op": "orders"})
    assert "#1001" in out and "49.99 USD" in out
    assert "alice@x" in out


def test_shopify_refund_dry_run(monkeypatch):
    monkeypatch.setenv("SHOPIFY_STORE", "my-shop")
    monkeypatch.setenv("SHOPIFY_ACCESS_TOKEN", "shpat_xx")
    fake_httpx = types.ModuleType("httpx")
    fake_httpx.Client = MagicMock()
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)
    from maverick.tools.shopify_tool import shopify_tool
    out = shopify_tool().fn({
        "op": "refund_create", "order_id": 555, "amount_cents": 1000,
        "currency": "USD",
    })
    assert "DRY RUN" in out
    fake_httpx.Client.assert_not_called()


# ---------- LLM cache ----------

def test_llm_cache_key_stable():
    from maverick.llm_cache import cache_key
    a = cache_key(provider="anthropic", model="m", system="s",
                  messages=[{"role": "user", "content": "hi"}],
                  tools=[], max_tokens=100)
    b = cache_key(provider="anthropic", model="m", system="s",
                  messages=[{"role": "user", "content": "hi"}],
                  tools=[], max_tokens=100)
    c = cache_key(provider="anthropic", model="m", system="s",
                  messages=[{"role": "user", "content": "bye"}],
                  tools=[], max_tokens=100)
    assert a == b
    assert a != c


def test_llm_cache_lookup_miss_then_hit(tmp_path):
    from maverick.llm_cache import LLMCache
    cache = LLMCache(db_path=tmp_path / "c.db")
    key = "abc"
    assert cache.lookup(key) is None
    cache.store(key, provider="anthropic", model="m", text="hello there",
                stop_reason="end_turn")
    hit = cache.lookup(key)
    assert hit is not None
    assert hit.text == "hello there"
    assert hit.stop_reason == "end_turn"
    assert hit.hit_count == 1
    # Bump count
    hit2 = cache.lookup(key)
    assert hit2.hit_count == 2


def test_llm_cache_ttl_expires(tmp_path):
    from maverick.llm_cache import LLMCache
    cache = LLMCache(db_path=tmp_path / "c.db", ttl_seconds=1)
    cache.store("k", provider="p", model="m", text="x")
    assert cache.lookup("k") is not None
    # Lookup with a forced future timestamp drops the row.
    later = time.time() + 60
    assert cache.lookup("k", now=later) is None


def test_llm_cache_stats(tmp_path):
    from maverick.llm_cache import LLMCache
    cache = LLMCache(db_path=tmp_path / "c.db")
    cache.store("a", provider="p", model="m", text="1")
    cache.store("b", provider="p", model="m", text="2")
    cache.lookup("a")
    s = cache.stats()
    assert s["entries"] == 2
    assert s["hits"] >= 1


def test_llm_cache_purge_expired(tmp_path):
    from maverick.llm_cache import LLMCache
    cache = LLMCache(db_path=tmp_path / "c.db", ttl_seconds=10)
    cache.store("k", provider="p", model="m", text="x")
    # Force expiration window.
    deleted = cache.purge_expired(now=time.time() + 999)
    assert deleted == 1
    assert cache.lookup("k") is None


def test_llm_cache_clear(tmp_path):
    from maverick.llm_cache import LLMCache
    cache = LLMCache(db_path=tmp_path / "c.db")
    cache.store("a", provider="p", model="m", text="x")
    cache.clear()
    assert cache.lookup("a") is None


def test_llm_cache_enabled_via_env(monkeypatch):
    from maverick import llm_cache
    monkeypatch.setenv("MAVERICK_LLM_CACHE", "1")
    assert llm_cache.enabled() is True
    monkeypatch.setenv("MAVERICK_LLM_CACHE", "0")
    assert llm_cache.enabled() is False


# ---------- registration smoke ----------

def test_new_tools_register(tmp_path):
    from maverick.sandbox.local import LocalBackend
    from maverick.tools import base_registry

    class _W:
        def open_questions(self, gid):
            return []

    reg = base_registry(_W(), LocalBackend(workdir=tmp_path))
    names = {t.name for t in reg.all()}
    for n in ("openapi_runner", "ocr", "posthog", "shopify"):
        assert n in names, f"{n} not registered"
