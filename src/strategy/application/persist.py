"""选股结果写入账本候选池（API 与 Job 共用）。"""
from __future__ import annotations

from typing import Any

#: 盘后/当日真选写入源（首页「昨选今涨 / 今日选股」只认这些）
LIVE_SCREEN_SOURCES: frozenset[str] = frozenset(
    {
        "job:screen",
        "api:screen",
        "api:screen_today",
        "api:screen_run",
    }
)
BACKFILL_SOURCE = "api:screen_backfill"

_FACTOR_ZH: dict[str, str] = {
    "vol_ratio_5d": "5日量比",
    "vol_ratio": "量比",
    "turnover": "换手率",
    "ma20": "MA20",
    "ma5": "MA5",
    "ma10": "MA10",
    "ROC5": "5日相对强度",
    "score": "评分",
    "hsl": "换手%",
    "zt": "涨停",
    "one_word": "一字板",
    "auction_ratio": "竞价比",
    "open_pct": "开盘涨幅%",
    "close_pct": "收盘涨幅%",
    "COST15": "筹码15%",
    "COST50": "筹码50%",
    "COST85": "筹码85%",
    "concentration": "集中度",
}
_RULE_LABELS: dict[str, str] = {
    "qianlong": "潜龙",
    "qianlong-auction": "潜龙",
    "qianlong-close": "潜龙",
    "qianlong-close-v2": "潜龙",
    "qianlong-close-v3": "潜龙",
    "qianlong-tail-v1": "潜龙",
    "sanyuan-tail-v1": "三源尾盘共振",
}


def factor_reason(slug: str, factors: dict[str, Any]) -> str:
    parts = [
        f"{_FACTOR_ZH.get(key, key)}={value:.2f}"
        for key, value in factors.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    ]
    body = "，".join(parts[:6]) or "（无数值因子）"
    label = _RULE_LABELS.get(str(slug).strip().lower(), str(slug).strip() or "战法")
    return f"{label}选中：{body}"[:500]


def score_from_factors(factors: dict[str, Any]) -> float | None:
    """把排序因子映射到候选池 score（0–100），便于列表按分降序。"""
    roc = factors.get("ROC5")
    if isinstance(roc, (int, float)) and not isinstance(roc, bool):
        # ROC5=CLOSE/REF(CLOSE,5) → 五日涨跌幅%，夹到 [0, 100]
        return round(max(0.0, min(100.0, (float(roc) - 1.0) * 100.0)), 4)
    for key in ("score", "横截面评分"):
        value = factors.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return round(max(0.0, min(100.0, float(value))), 4)
    return None


def is_backfill_source(source: str) -> bool:
    """事后回填 / 区间重放写入，不得冒充盘后真选。"""
    text = str(source or "").strip().lower()
    return "backfill" in text or text.endswith(":history")


def is_live_screen_source(source: str) -> bool:
    """是否为当日/盘后真选写入源。"""
    text = str(source or "").strip()
    if is_backfill_source(text):
        return False
    return text in LIVE_SCREEN_SOURCES or text.startswith("job:screen")


def persist_screen_candidates(
    result: Any,
    *,
    palace_db: str | None = None,
    names: dict[str, str] | None = None,
    pool_id: str | None = None,
    decision: str = "精选",
    source: str = "api:screen",
    top_n: int = 0,
) -> dict[str, Any]:
    """把选股 picks 写入 ``candidate_reviews``；同日同池先清空再写入。

    重选 0 只时只清空、不写新行，避免旧结果残留。

    回填源（``api:screen_backfill``）**只替换同池回填行**，绝不删除
    ``job:screen`` / ``api:screen_run`` 等真选，避免区间重跑污染昨选今涨。
    """
    from src.ledger import PalaceError, PalaceStore
    from src.shared.paths import palace_db as default_palace_db

    resolved_pool = pool_id or f"{result.strategy_slug}@{result.trade_date}"
    name_map = names or {}
    picks = list(result.picks or [])
    if top_n > 0:
        picks = picks[:top_n]
    resolved_source = str(source or "api:screen")

    written, failed, skipped = 0, [], 0
    with PalaceStore(palace_db or str(default_palace_db())) as palace:
        # 回填先取该池真选 code 集：record_candidate 按 (occurred_on, pool_id, code)
        # 幂等 upsert，不跳过会把真选行整体改写成回填行、从「仅真选」视图消失。
        protected_codes: set[str] = set()
        if is_backfill_source(resolved_source):
            protected_codes = {
                str(item["code"])
                for item in palace.candidates_payload(occurred_on=result.trade_date)
                if str(item["pool_id"]) == resolved_pool
            }
        if is_backfill_source(resolved_source):
            removed = palace.delete_candidates_for_pool(
                occurred_on=result.trade_date,
                pool_id=resolved_pool,
                sources_like="%backfill%",
            )
        else:
            removed = palace.delete_candidates_for_pool(
                occurred_on=result.trade_date,
                pool_id=resolved_pool,
            )
        for index, pick in enumerate(picks):
            code = str(pick.get("code") or "")
            if not code:
                continue
            if code in protected_codes:
                skipped += 1
                continue
            tier = str(pick.get("_tier") or ("core" if top_n <= 0 or index < top_n else "reserve"))
            pick_decision = str(pick.get("_decision") or decision)
            evidence = dict(pick.get("factors") or {})
            data_snapshot = getattr(result, "data_snapshot", None)
            if data_snapshot:
                evidence["_data_snapshot"] = dict(data_snapshot)
            strategy_revision = str(getattr(result, "strategy_revision", "") or "")
            effective_params = getattr(result, "effective_params", None)
            if effective_params is None:
                effective_params = getattr(result, "params", None)
            try:
                factors = pick.get("factors") or {}
                palace.record_candidate(
                    code=code,
                    name=name_map.get(code, ""),
                    decision=pick_decision,
                    reason=factor_reason(result.strategy_slug, factors),
                    occurred_on=result.trade_date,
                    pool_id=resolved_pool,
                    score=score_from_factors(factors if isinstance(factors, dict) else {}),
                    timing=result.entry_timing,
                    rule_version=result.strategy_slug,
                    strategy_slug=result.strategy_slug,
                    strategy_revision=strategy_revision,
                    effective_params=effective_params,
                    evidence=evidence,
                    tier=tier,
                    source=resolved_source,
                )
                written += 1
            except PalaceError as exc:
                failed.append({"code": code, "error": str(exc)[:200]})

    return {
        "pool_id": resolved_pool,
        "written": written,
        "removed": removed,
        "skipped": skipped,
        "failed": failed,
        "trade_date": result.trade_date,
    }
