"""按战法当前口径重算已入库候选的评分与理由（选股结果与裁决不变）。

用途：评分口径修正后（如三源原始横截面评分改为 0–100 评分百分位），让历史候选与新候选
在同一张表里可比。做法是对每个候选日按原战法重跑一次选股，只取已入库股票的因子重算
``score`` / 理由 / 证据；重跑未选出同一只股票（行情已修订等）的行保持原样并如实报告。
"""
from __future__ import annotations

import json
from collections.abc import Callable
from itertools import groupby
from typing import Any

from src.strategy.application.persist import factor_reason, score_from_factors

WATCH_REASON = "弱市低吸观察："


def plan_rescore(
    palace: Any, market: Any, strategy_slug: str, *, since: str | None = None,
    until: str | None = None, screen_fn: Callable[..., Any] | None = None,
) -> list[dict[str, Any]]:
    """逐行给出新旧评分；``status``：updated / unchanged / not_repicked / no_data / error。"""
    if screen_fn is None:
        from src.strategy.application.screener import screen as screen_fn
    rows = palace.candidate_scoring_rows(strategy_slug, since=since, until=until)
    plan: list[dict[str, Any]] = []
    for day, items in groupby(rows, key=lambda row: str(row["occurred_on"])):
        items = list(items)
        try:
            result = screen_fn(market, strategy_slug, trade_date=day, health_check=False, live_overlay=False)
        except Exception as exc:  # noqa: BLE001 — 单日失败只影响该日，其余日期照常预览
            plan.extend(_keep(item, "error", f"{type(exc).__name__}: {exc}") for item in items)
            continue
        if str(result.trade_date) != day:
            plan.extend(_keep(item, "no_data", f"行情库最近交易日为 {result.trade_date}，缺 {day}") for item in items)
            continue
        factors_by_code = {
            str(pick.get("code")): pick.get("factors") or {}
            for pick in [*(result.picks or []), *(getattr(result, "watch_picks", None) or [])]
        }
        for item in items:
            factors = factors_by_code.get(str(item["code"]))
            if not factors:
                plan.append(_keep(item, "not_repicked", "按当前行情重跑未选出该股，保留原评分"))
                continue
            reason = factor_reason(strategy_slug, factors)
            if WATCH_REASON in str(item["reason"]):
                reason = reason.replace("选中：", WATCH_REASON, 1)
            try:
                evidence = json.loads(item.get("evidence_json") or "{}")
            except ValueError:
                evidence = {}
            evidence = {**(evidence if isinstance(evidence, dict) else {}), **factors}
            new_score = score_from_factors(factors)
            old_score = item["score"]
            same = old_score is not None and new_score is not None and abs(float(old_score) - new_score) < 1e-9
            plan.append({**_base(item), "new_score": new_score, "reason": reason, "evidence": evidence,
                         "status": "unchanged" if same else "updated", "note": ""})
    return plan


def apply_rescore(palace: Any, plan: list[dict[str, Any]]) -> int:
    """只写 ``status=updated`` 的行；一个事务内全部成功或全部回滚。"""
    updates = [(row["id"], row["new_score"], row["reason"], row["evidence"])
               for row in plan if row["status"] == "updated"]
    return palace.update_candidate_scoring(updates) if updates else 0


def _base(item: dict[str, Any]) -> dict[str, Any]:
    return {"id": item["id"], "occurred_on": item["occurred_on"], "code": item["code"],
            "name": item["name"], "decision": item["decision"], "old_score": item["score"]}


def _keep(item: dict[str, Any], status: str, note: str) -> dict[str, Any]:
    return {**_base(item), "new_score": item["score"], "reason": item["reason"], "evidence": None,
            "status": status, "note": note}
