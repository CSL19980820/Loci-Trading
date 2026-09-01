"""选股行情范围（universe）的口径解析——同步 `/api/strategies/screen` 与异步
`POST /api/screen/run` 共用的一份。

为什么单独成文件：这两个端点在 2026-08 被拆到了两个 router 模块里，而它们
必须给出**同一个** universe，否则「详情页里存的行情范围」在同步选股生效、
异步选股不生效（或反过来），用户看到两套不同的宇宙大小却找不到原因。
拷两份是这个 bug 的标准生成方式，所以这里只留一份。

本模块不含任何路由；它只是 api 层内部的共享 helper。
"""
from __future__ import annotations

from typing import Any

from src.shared.api_deps import ops_store


def effective_screen_universe(
    slug: str, requested: Any, *, ops_db: str | None = None
) -> dict[str, Any] | None:
    """请求体优先；未传则用详情页保存到 ``screen:{slug}`` 的行情范围。"""
    from src.ops.application.screen_job_config import resolve_screen_universe

    raw = (
        requested.model_dump(exclude_none=True)
        if requested is not None and hasattr(requested, "model_dump")
        else requested
    )
    with ops_store(ops_db) as store:
        return resolve_screen_universe(slug, raw if isinstance(raw, dict) else None, store=store)
