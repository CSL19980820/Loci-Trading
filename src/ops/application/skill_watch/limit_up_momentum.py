"""涨停 momentum 接力监测：消费闸门/调参，输出结构化纸面候选。

只给观察与未验证候选，不下买卖指令；空仓窗口只出 watch，不出 picks。
"""
from __future__ import annotations


def _wudao_keys():
    """悟道键名表。**延迟导入**：``src.intel.__init__`` 会反向 import ``src.ops``，
    模块级导入直接成环（ImportError: partially initialized module）。
    """
    from src.intel.application import wudao_keys

    return wudao_keys


from collections.abc import Mapping
from typing import Any

from src.ops.application.skill_watch import payload as pl
from src.ops.application.skill_watch.market_regime import (
    disabled_market_gate,
    evaluate_market_gate,
    fetch_market_snapshot,
    today_trade_date,
)
from src.ops.application.skill_watch.paper_eligibility import filter_openable_picks
from src.ops.application.skill_watch.tuning import section, stage_enabled


def _promotion_rate(emotion: Any) -> float | None:
    direct = pl.metric(emotion, "promotion_rate")
    if direct is None:
        return None
    return direct / 100.0 if abs(direct) > 1.5 else direct


def _broken_rate(emotion: Any) -> float | None:
    direct = pl.metric(emotion, "broken_rate")
    if direct is None:
        return None
    return direct / 100.0 if abs(direct) > 1.5 else direct


def _score_ladder_row(row: Mapping[str, Any], *, promo: float | None) -> int:
    level = pl.field(row, "ladder_level") or 0.0
    score = min(40, int(float(level) * 12))
    if promo is not None and promo >= 0.35:
        score += 25
    elif promo is not None and promo >= 0.25:
        score += 12
    pct = pl.field(row, "pct_chg")
    if pct is not None and pct >= 9.5:
        score += 10
    return max(0, min(100, score))


def _score_broken_row(row: Mapping[str, Any], *, promo: float | None) -> int:
    score = 35
    if promo is not None and promo >= 0.3:
        score += 20
    pct = pl.field(row, "pct_chg")
    if pct is not None and pct > 0:
        score += 15
    return max(0, min(100, score))


def _paper_pick(
    row: Mapping[str, Any],
    *,
    gate: Mapping[str, Any],
    kind: str,
    auction_cfg: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    from src.ops.application.skill_watch.actionable_line import enrich_actionable_fields

    code = str(row.get("code") or "")
    name = str(row.get("name") or code)
    score = row.get("score")
    close = pl.field(row, "price") or pl.field(row, "close")
    base = {
        "code": code,
        "name": name,
        "score": score,
        "close": close,
        # 盘后种子：当日收/价作次日昨收参考；日终滚动会再用日 K 覆盖校正
        "ref_close": close,
        "thesis": (
            f"{kind}；形态分 {score}；"
            f"市场闸门={gate.get('mode')}，{gate.get('reason')}"
        ),
        "validation": "unverified",
        "validation_label": "未经过前向验证",
        "veto": ["未通过竞价/开盘门闩不跟随", "晋级率转弱放弃"],
        "auction": dict(auction_cfg or {}),
        "auction_stance": row.get("auction_stance"),
        "auction_reason": row.get("auction_reason"),
        "source_evidence": {
            "trade_date": gate.get("trade_date"),
            "market_gate": gate.get("state"),
            "kind": kind,
            "score": score,
        },
    }
    return enrich_actionable_fields(base, score=score)


def scan_limit_up_momentum(
    call_tool: Any,
    *,
    tuning: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """确定性涨停接力扫描；信号只用于纸面候选，不代表买卖指令。"""
    day = today_trade_date()
    scan_cfg = section(tuning, "scan")
    candidate_score = float(scan_cfg["candidate_score"])
    max_candidates = int(scan_cfg["max_candidates"])
    allow_candidates = stage_enabled(tuning, "paper_candidates")

    emotion, ladder, themes = fetch_market_snapshot(call_tool, trade_date=day)
    # broken_limit_up 的 schema 不声明 limit（见 intel/README 的入参约束表）：多传一个
    # 它不认的键会被 INVALID_ARGUMENTS 整条拒掉，炸板池空手回来，「弱转强」这一路
    # 候选恒为空。要多少行在下面本地截（rows_by_code(limit=20)），不指望服务端。
    broken = call_tool(
        "broken_limit_up",
      # 键名走单一真相源：broken_limit_up 实测只认 date，硬编码 tradeDate
        # 的那阵子整条调用被服务端拒掉，上层读成「悟道没数据」。
        _wudao_keys().with_date(
            "broken_limit_up", day, format="json", detailLevel="standard"
        ),
    )

    if stage_enabled(tuning, "market_gate"):
        gate = evaluate_market_gate(
            emotion, ladder, themes, trade_date=day, params=section(tuning, "gate")
        )
    else:
        gate = disabled_market_gate(day)

    promo = _promotion_rate(emotion)
    broken_rate = _broken_rate(emotion)
    ladder_rows = list(pl.rows_by_code(ladder, limit=30).values())
    broken_rows = list(pl.rows_by_code(broken, limit=20).values())

    base = {
        "trade_date": day,
        "market_gate": gate,
        "promotion_rate": promo,
        "broken_rate": broken_rate,
        "ladder_count": len(ladder_rows),
        "validation": "unverified",
        "validation_label": "未经过前向验证",
    }

    ranked: list[dict[str, Any]] = []
    if promo is not None and promo >= 0.25 and ladder_rows:
        top = dict(ladder_rows[0])
        code = pl.clean_code(top.get("code"))
        if code:
            score = _score_ladder_row(top, promo=promo)
            ranked.append(
                {
                    "code": code,
                    "name": pl.text_field(top, "name", "stockName", "名称") or code,
                    "score": score,
                    "kind": "梯队前排",
                    "ladder_level": pl.field(top, "ladder_level"),
                }
            )
    if broken_rows and promo is not None and promo >= 0.25:
        row = dict(broken_rows[0])
        code = pl.clean_code(row.get("code"))
        if code and not any(item["code"] == code for item in ranked):
            score = _score_broken_row(row, promo=promo)
            ranked.append(
                {
                    "code": code,
                    "name": pl.text_field(row, "name", "stockName", "名称") or code,
                    "score": score,
                    "kind": "炸板弱转强",
                }
            )

    ranked.sort(key=lambda item: (-int(item["score"]), str(item["code"])))
    qualified = [row for row in ranked if float(row["score"]) >= candidate_score]

    # 与龙回头对齐：竞价窗内 confirm_leaders，写入 stance 再经 paper_eligibility 过滤
    from src.ops.application.skill_watch.auction_confirm import confirm_leaders

    auction_cfg = section(tuning, "auction")
    auction: dict[str, Any] = {"active": False, "stances": []}
    if stage_enabled(tuning, "auction_confirm") and qualified:
        leaders = [
            {"code": row["code"], "name": row.get("name") or row["code"]}
            for row in qualified[:max_candidates]
        ]
        auction = confirm_leaders(
            call_tool, leaders, trade_date=day, params=auction_cfg
        )
        stance_by = {
            str(s.get("code")): s
            for s in (auction.get("stances") or [])
            if isinstance(s, dict) and s.get("code")
        }
        for row in qualified:
            st = stance_by.get(str(row["code"]))
            if st is None:
                continue
            row["auction_stance"] = st.get("stance")
            row["auction_reason"] = st.get("reason")

    raw_picks = (
        [
            _paper_pick(
                row,
                gate=gate,
                kind=str(row["kind"]),
                auction_cfg=auction_cfg,
            )
            for row in qualified[:max_candidates]
        ]
        if gate.get("entry_allowed") and allow_candidates and max_candidates > 0
        else []
    )
    picks, excluded = filter_openable_picks(raw_picks)

    signals: list[dict[str, Any]] = []
    if not allow_candidates:
        signals.append(
            {
                "type": "watch_only",
                "code": "market",
                "reason": "纸面候选已关闭，本次只出观察信号",
                "validation": "unverified",
            }
        )
    elif gate.get("state") == "empty" or not gate.get("entry_allowed"):
        signals.append(
            {
                "type": "gate_empty" if gate.get("state") == "empty" else "watch_only",
                "code": "market",
                "reason": str(gate.get("reason") or "市场未进入进攻窗口"),
                "validation": "unverified",
            }
        )
    elif promo is not None and promo < 0.2:
        signals.append(
            {
                "type": "sell_hint",
                "code": "market",
                "reason": f"晋级率过低（{promo:.0%}），接力环境转弱",
                "validation": "unverified",
            }
        )
    elif picks:
        signals.extend(
            {
                "type": "paper_candidate",
                "code": item["code"],
                "name": item.get("name") or "",
                "score": item.get("score"),
                "reason": "梯队/弱转强与情绪同时通过，进入纸面候选",
                "validation": "unverified",
            }
            for item in picks
        )
    elif ranked:
        signals.append(
            {
                "type": "watch_only",
                "code": ranked[0]["code"],
                "name": ranked[0].get("name") or "",
                "score": ranked[0]["score"],
                "reason": "情绪尚可但形态分未达候选线",
                "validation": "unverified",
            }
        )
    else:
        signals.append(
            {
                "type": "watch_only",
                "code": "market",
                "reason": "梯队/炸板池暂无可评分标的",
                "validation": "unverified",
            }
        )

    if broken_rate is not None and broken_rate >= 0.45:
        signals.append(
            {
                "type": "sell_hint",
                "code": "market",
                "reason": f"炸板率偏高（{broken_rate:.0%}），接力风险上升",
                "validation": "unverified",
            }
        )

    return {
        **base,
        "auction": auction,
        "ranked": ranked[:5],
        "picks": picks,
        "auction_excluded": [
            str(row.get("code"))
            for row in excluded
            if isinstance(row, dict) and row.get("code")
        ],
        "signals": signals,
        "pool_size": len(ranked),
    }


__all__ = ["scan_limit_up_momentum"]
