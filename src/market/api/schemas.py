"""行情上下文的 HTTP 请求模型与 bootstrap 进度快照。

从组合根 `app/legacy/quant_common.py` 搬入。字段名对外是契约，不得改名。
"""
from __future__ import annotations

import threading
from typing import Any

from pydantic import Field

from src.shared.api_models import QuantModel


class SyncRequest(QuantModel):
    codes: list[str] | None = None
    limit: int = Field(default=0, ge=0, le=6000)
    workers: int = Field(default=4, ge=1, le=16)
    interval: float = Field(default=0.15, ge=0.0, le=5.0)
    force: bool = False
    refresh_instruments: bool = False
    with_factors: bool = True


class BootstrapRequest(QuantModel):
    """首次初始化历史日 K。全市场约 10–40 分钟，可断点续跑。"""

    workers: int = Field(default=4, ge=1, le=16)
    interval: float = Field(default=0.15, ge=0.0, le=5.0)
    limit: int = Field(default=0, ge=0, le=6000)
    with_factors: bool = False


_BOOTSTRAP_LOCK = threading.Lock()
_BOOTSTRAP: dict[str, Any] = {
    "status": "idle",
    "phase": "",
    "done": 0,
    "total": 0,
    "percent": 0.0,
    "code": "",
    "message": "",
    "report": None,
}


def bootstrap_snapshot() -> dict[str, Any]:
    with _BOOTSTRAP_LOCK:
        return dict(_BOOTSTRAP)


def bootstrap_update(**kwargs: Any) -> None:
    with _BOOTSTRAP_LOCK:
        _BOOTSTRAP.update(kwargs)
        total = int(_BOOTSTRAP.get("total") or 0)
        done = int(_BOOTSTRAP.get("done") or 0)
        if _BOOTSTRAP.get("status") == "done":
            _BOOTSTRAP["percent"] = 100.0
        elif total > 0:
            _BOOTSTRAP["percent"] = round(100.0 * done / total, 1)
        else:
            _BOOTSTRAP["percent"] = 0.0
