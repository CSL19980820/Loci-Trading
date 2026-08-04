"""WebView HTTP 缓存清理。"""
from __future__ import annotations

from pathlib import Path

from src.shared.webview_cache import purge_webview_http_cache, should_purge_on_boot


def test_purge_removes_cache_dirs_keeps_others(tmp_path: Path, monkeypatch) -> None:
    storage = tmp_path / "webview"
    cache = storage / "EBWebView" / "Default" / "Cache"
    cache.mkdir(parents=True)
    (cache / "f").write_text("x", encoding="utf-8")
    local = storage / "EBWebView" / "Default" / "Local Storage"
    local.mkdir(parents=True)
    (local / "keep").write_text("y", encoding="utf-8")

    cleared = purge_webview_http_cache(storage)
    assert "EBWebView/Default/Cache" in cleared
    assert not cache.exists()
    assert (local / "keep").read_text(encoding="utf-8") == "y"


def test_should_purge_respects_skip(monkeypatch) -> None:
    monkeypatch.setenv("LOCI_SKIP_WEBVIEW_CACHE_PURGE", "1")
    monkeypatch.setenv("LOCI_PURGE_WEBVIEW_CACHE", "1")
    assert should_purge_on_boot() is False


def test_should_purge_when_forced(monkeypatch) -> None:
    monkeypatch.delenv("LOCI_SKIP_WEBVIEW_CACHE_PURGE", raising=False)
    monkeypatch.setenv("LOCI_PURGE_WEBVIEW_CACHE", "1")
    assert should_purge_on_boot() is True
