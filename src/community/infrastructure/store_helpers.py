"""社区库共用辅助：ID、JSON、SHA256、slug、分页。

时钟统一走 ``domain.models.now_iso()``（本地时区 + 偏移 + 微秒），不在这里另开一套。
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from typing import Any, Mapping

from src.community.domain.models import now_iso, today_iso

#: 广场分页默认与上限。上限存在的意义是防「limit=100000 拖垮 SQLite」。
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

#: 榜单一次最多取多少条。
MAX_BOARD_SIZE = 200

_SLUG_STRIP = re.compile(r"[^a-z0-9\u4e00-\u9fff-]+")
_SLUG_DASH = re.compile(r"-{2,}")


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def loads(value: str | None, fallback: Any = None) -> Any:
    if not value:
        return {} if fallback is None else fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return {} if fallback is None else fallback


def content_hash(source_text: str, params: Any = None) -> str:
    """版本指纹：正文 + 参数的 sha256。

    克隆方拿 bundle 时会带上这个值，日后争「我抄的时候是不是这段代码」时可对账。
    参数用 ``sort_keys`` 序列化，保证同内容不同键序算出同一个哈希。
    """
    payload = (source_text or "") + "\n--params--\n" + dumps(params or {})
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def slugify(raw: str, *, fallback: str = "strategy") -> str:
    """生成人可读的 slug；中文原样保留（唯一性由 (owner, slug) 唯一索引保证）。"""
    text = (raw or "").strip().lower().replace(" ", "-")
    text = _SLUG_STRIP.sub("-", text)
    text = _SLUG_DASH.sub("-", text).strip("-")
    return text[:60] or fallback


def clamp_page(page: int | None, page_size: int | None) -> tuple[int, int]:
    current = max(1, int(page or 1))
    size = int(page_size or DEFAULT_PAGE_SIZE)
    size = max(1, min(MAX_PAGE_SIZE, size))
    return current, size


def row_to_dict(row: sqlite3.Row | Mapping[str, Any] | None) -> dict[str, Any]:
    if row is None:
        return {}
    return {key: row[key] for key in row.keys()} if isinstance(row, sqlite3.Row) else dict(row)


def json_columns(data: dict[str, Any], mapping: Mapping[str, tuple[str, Any]]) -> dict[str, Any]:
    """把 ``*_json`` 列就地解析成对象列。

    ``mapping`` 形如 ``{"tags_json": ("tags", [])}``：解析后写入新键并删掉原始列，
    让上层永远拿不到没解析过的字符串（拿到过一次就会有人 ``json.loads`` 第二遍）。
    """
    for column, (target, fallback) in mapping.items():
        if column in data:
            data[target] = loads(data.pop(column), fallback)
    return data


__all__ = [
    "DEFAULT_PAGE_SIZE",
    "MAX_BOARD_SIZE",
    "MAX_PAGE_SIZE",
    "clamp_page",
    "content_hash",
    "dumps",
    "json_columns",
    "loads",
    "new_id",
    "now_iso",
    "row_to_dict",
    "slugify",
    "today_iso",
]
