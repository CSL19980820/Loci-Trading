"""桌面 WebView2 HTTP/代码缓存清理。

部署前端后若磁盘仍留旧 ``index.html`` / JS，窗口会继续打开过期页面。
每次启动在 WebView 占用用户目录前清掉可安全删除的缓存子树，保留 Cookie /
LocalStorage（登录态与本地偏好）。
"""
from __future__ import annotations

import logging
import os
import shutil
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

#: 相对 ``data/webview`` 的可删缓存目录（不含 Cookie / Local Storage）
_CACHE_RELATIVE = (
    "EBWebView/Default/Cache",
    "EBWebView/Default/Code Cache",
    "EBWebView/Default/GPUCache",
    "EBWebView/Default/GrShaderCache",
    "EBWebView/Default/ShaderCache",
    "EBWebView/Default/Service Worker/CacheStorage",
    "EBWebView/Default/Service Worker/ScriptCache",
    "EBWebView/Default/Service Worker/Database",
    # WebView2 实际把部分 GPU/组件缓存放在 EBWebView 根下（非 Default/）
    "EBWebView/GPUCache",
    "EBWebView/GrShaderCache",
    "EBWebView/ShaderCache",
    "EBWebView/GraphiteDawnCache",
    "EBWebView/component_crx_cache",
    "EBWebView/Component Crx Cache",
)


def webview_storage_dir() -> Path:
    """与 loci 桌面入口一致的 WebView 用户数据目录。"""
    override = os.environ.get("WEBVIEW2_USER_DATA_FOLDER", "").strip()
    if override:
        return Path(override)
    from src.shared.paths import writable_root

    return writable_root() / "data" / "webview"


def purge_webview_http_cache(storage: Path | None = None) -> list[str]:
    """删除 HTTP/代码缓存目录，返回已处理的相对路径列表。"""
    root = storage if storage is not None else webview_storage_dir()
    if not root.is_dir():
        return []
    cleared: list[str] = []
    for rel in _CACHE_RELATIVE:
        target = root.joinpath(*rel.split("/"))
        if not target.exists():
            continue
        try:
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
            cleared.append(rel)
        except OSError as exc:
            logger.warning("清理 WebView 缓存失败 %s: %s", target, exc)
    return cleared


def should_purge_on_boot() -> bool:
    """打包桌面默认清；开发/pytest 默认跳过，可用环境变量强制开/关。"""
    if os.environ.get("LOCI_SKIP_WEBVIEW_CACHE_PURGE", "").strip() in {"1", "true", "yes"}:
        return False
    if os.environ.get("LOCI_PURGE_WEBVIEW_CACHE", "").strip() in {"1", "true", "yes"}:
        return True
    return bool(getattr(sys, "frozen", False))


def purge_webview_http_cache_on_boot() -> list[str]:
    """按策略在启动时清理；返回已清理路径（跳过时为空列表）。"""
    if not should_purge_on_boot():
        return []
    cleared = purge_webview_http_cache()
    if cleared:
        logger.info("已清理 WebView 缓存：%s", ", ".join(cleared))
    return cleared
