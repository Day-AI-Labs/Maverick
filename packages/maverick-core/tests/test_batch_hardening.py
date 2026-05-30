"""Tests for the batched pre-launch hardening fixes."""
import pytest


def test_calendly_uuid_rejects_path_traversal():
    from maverick.tools.calendly_tool import _safe_uuid
    assert _safe_uuid("AAAA-BBBB-1234")
    assert _safe_uuid("abc_def")
    assert not _safe_uuid("me/../users")
    assert not _safe_uuid("a/b")
    assert not _safe_uuid("../x")
    assert not _safe_uuid("")


def test_shopify_store_rejects_ssrf_chars(monkeypatch):
    from maverick.tools import shopify_tool
    monkeypatch.setenv("SHOPIFY_ACCESS_TOKEN", "tok")
    for bad in ("evil.com#", "evil.com/", "user@evil.com", "evil.com:8080"):
        monkeypatch.setenv("SHOPIFY_STORE", bad)
        with pytest.raises(RuntimeError, match="invalid SHOPIFY_STORE"):
            shopify_tool._config()


def test_shopify_store_clean_subdomain_expands(monkeypatch):
    from maverick.tools import shopify_tool
    monkeypatch.setenv("SHOPIFY_ACCESS_TOKEN", "tok")
    monkeypatch.setenv("SHOPIFY_STORE", "my-store")
    store, tok = shopify_tool._config()
    assert store == "my-store.myshopify.com"
    assert tok == "tok"
