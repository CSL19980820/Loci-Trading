"""assistant_store 共享小工具，供主 Store 与 lifecycle mixin 复用。"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _dump(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, default=str)


def _load(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


_SECRET_KEY = re.compile(r"(key|secret|token|password|credential|authorization)", re.I)
_SECRET_VALUE = re.compile(r"(?:sk-|Bearer\s+)[A-Za-z0-9._-]+", re.I)
_URL = re.compile(r"https?://[^\s'\"]+", re.I)


def redact(value: Any) -> Any:
    """用于持久化和事件的最小脱敏，不改变内存中的实际执行参数。"""
    if isinstance(value, dict):
        return {str(k): "[REDACTED]" if _SECRET_KEY.search(str(k)) else redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return _URL.sub("[URL]", _SECRET_VALUE.sub("[REDACTED]", value))[:8000]
    return value


def _hash(value: Any) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
