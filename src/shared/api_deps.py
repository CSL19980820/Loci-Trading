"""HTTP 入站适配器共用的依赖打开器与能力缺失映射。

放 `src/shared` 而不是组合根：`missing_dependency` 被 6 个上下文的 api 层各引一次，
store 打开器被 4 个上下文引用。留在 `src/app` 会让「限界上下文 → 组合根」这条反向
依赖长期存在，任何一个 DTO 改字段都要动组合根。

对各上下文的引用一律**函数内懒导入**：本模块因此不静态依赖任何限界上下文，
同时保住「依赖没装齐 → 503 而不是 500」的行为。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import HTTPException

from src.shared.paths import palace_db as _default_palace_db

#: 技能包等上传体积上限。
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
#: 兼容保留（外部可能导入）。**新代码不要用它**：import 期求值，不认租户。
DEFAULT_PALACE_DB = str(_default_palace_db())

CAPABILITY_MISSING_HEADER = "X-Loci-Reason"
CAPABILITY_MISSING_VALUE = "capability-missing"


def missing_dependency(exc: ImportError) -> HTTPException:
    """缺依赖返回 503 而不是 500：这是环境没装齐，不是代码出错。"""
    return HTTPException(
        status_code=503,
        detail=f"该能力所需的依赖未安装（{exc.name}）。请在 requirements.txt 对应项装齐后重启。",
        headers={CAPABILITY_MISSING_HEADER: CAPABILITY_MISSING_VALUE},
    )


def market_store(market_db: str | None) -> Any:
    try:
        from src.market import MarketStore
    except ImportError as exc:
        raise missing_dependency(exc) from exc
    return MarketStore(market_db)


def market_hot_store(hot_db: str | None = None) -> Any:
    """打开滚动热读库（近 700 交易日窗口）；None 时用默认 ``market_hot.db``。"""
    try:
        from src.market import open_market_hot
    except ImportError as exc:
        raise missing_dependency(exc) from exc
    return open_market_hot(hot_db)


def ops_store(ops_db: str | None) -> Any:
    try:
        from src.ops import OpsStore
    except ImportError as exc:
        raise missing_dependency(exc) from exc
    return OpsStore(ops_db)


def palace_store(palace_db: str | None) -> Any:
    from src.ledger import PalaceStore

    # 惰性解析：多租户下这一行决定了「谁的账本」。用 import 期常量等于
  # 把所有人写进同一个文件，而且不报错。
    return PalaceStore(palace_db or str(_default_palace_db()))


def should_sync_today(market_db: str | Path | None = None) -> bool:
    """判断是否需要在选股前触发同步。"""
    from datetime import date as _date

    try:
        from src.market import MarketStore

        with MarketStore(market_db) as store:
            if not store.list_instruments():
                return True
            cov = store.coverage()
        last = str(cov.get("last_date") or "")
        return not last or last < _date.today().isoformat()
    except Exception:
        return True
