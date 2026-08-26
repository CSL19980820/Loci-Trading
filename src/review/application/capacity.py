"""容量校验：回测里完美，实盘按你的仓位买不进去。

按目标仓位反查「成交额占比 ≤ X%」。
超了就标注 NOT_EXECUTABLE，不是禁止，是提示。
"""
from __future__ import annotations

from src.market import MarketStore, normalize_code


def _recent_amounts_batch(
    market_store: MarketStore, codes: list[str], *, limit: int = 5
) -> dict[str, list[float]]:
    """一次 ``history_many`` 取回所有票的近 N 根，再抽 amount 列。

    为什么批量：一批 picks 常有几十到几百只，逐票 ``recent_amounts``
    就是同等数量的 SQLite 查询（全市场扫出来的候选更多）；
    ``history_many`` 一条 ``IN (...)`` 全取回。不改 store 层。
    """
    if not codes:
        return {}
    batcher = getattr(market_store, "history_many", None)
    if callable(batcher):
        try:
            # amount 不是价格列，不需复权；adjust="none" 还能省掉因子查询。
            frames = batcher(codes, end=None, adjust="none", limit=limit)
        except Exception:  # noqa: BLE001
            frames = None
        if isinstance(frames, dict):
            batched: dict[str, list[float]] = {}
            for code, frame in frames.items():
                if frame is None or getattr(frame, "empty", True):
                    continue
                if "amount" not in getattr(frame, "columns", []):
                    continue
                values: list[float] = []
                for raw in frame["amount"]:
                    # None / NaN = 当日没成交额，跟原来一样丢弃，不能当 0 平均
                    if raw is None or raw != raw:
                        continue
                    values.append(float(raw))
                if values:
                    batched[str(code)] = values
            return batched
    # 没有批量接口（或批量查失败）才逐票回退，降级行为与原来一致。
    fallback: dict[str, list[float]] = {}
    for code in codes:
        amounts = market_store.recent_amounts(code, limit=limit)
        if amounts:
            fallback[code] = list(amounts)
    return fallback


def check_capacity(
    picks: list[dict],
    market_store: MarketStore,
    position_size_yuan: float = 100_000,
    max_impact_pct: float = 5.0,
) -> list[dict]:
    """为每个 pick 标注流动性容量。

    读取近 5 日均成交额，计算仓位占比。
    超过 max_impact_pct 标注 capacity=limited，否则 ok。

    ``market_store`` 应由调用方注入**热读库**（``open_market_hot``）；
    近窗成交额不必扫全量写库。
    """
    # 先归一一遍代码：非法代码与空代码跟原来 recent_amounts 一样当作无数据。
    normalized_codes: list[str | None] = []
    for pick in picks:
        code = str(pick.get("code", ""))
        if not code:
            normalized_codes.append(None)
            continue
        try:
            normalized_codes.append(normalize_code(code))
        except Exception:  # noqa: BLE001
            normalized_codes.append(None)
    wanted = list(
        dict.fromkeys(code for code in normalized_codes if code is not None)
    )
    amounts_by_code = _recent_amounts_batch(market_store, wanted, limit=5)

    results = []
    for pick, normalized in zip(picks, normalized_codes):
        annotated = dict(pick)

        if normalized is None:
            annotated["capacity"] = "ok"
            results.append(annotated)
            continue

        amounts = amounts_by_code.get(normalized) or []
        if not amounts:
            annotated["capacity"] = "ok"
            results.append(annotated)
            continue

        avg_daily_amount = sum(amounts) / len(amounts)
        if avg_daily_amount <= 0:
            annotated["capacity"] = "ok"
            results.append(annotated)
            continue

        impact_pct = position_size_yuan / avg_daily_amount * 100
        annotated["capacity"] = "limited" if impact_pct > max_impact_pct else "ok"
        results.append(annotated)

    return results
