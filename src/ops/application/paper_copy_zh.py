"""纸面量化舱「给人看」的中文文案：空值写暂无，不 dump 机器字段。"""
from __future__ import annotations

import re
from typing import Any

STATUS_ZH = {
    "bought": "已买",
    "missed": "错过",
    "new_pick": "今日新入池",
    "sold": "已卖",
    "bought_and_sold": "买过又卖",
    "held": "持有中",
}

LESSON_KIND_ZH = {
    "mistake": "失误",
    "revise": "纠偏",
    "win": "兑现",
    "note": "备忘",
    "miss": "错过",
    "dodge": "躲过",
    "hold": "持仓",
    "env": "环境",
}

BUY_RULE_KEY_ZH = {
    "gap_up_default": "高开",
    "flat_default": "平开",
    "gap_down_default": "低开",
    "auction": "竞价",
    "veto": "否决",
    "entry_mode": "买法",
}

BUY_RULE_VAL_ZH = {
    "no_chase": "不追高",
    "buy_in_band": "区间内接",
    "buy_dip_in_band": "低吸带内接",
    "buy_at_open": "开盘接",
    "judge_only_until_0925": "仅纠偏至09:25",
    "limit_up_one_word_skip": "一字涨停放弃",
    "scenario": "按情景",
    "next_open": "次日开盘接",
}

FILL_ACTION_ZH = {
    "open": "开仓",
    "add": "加仓",
    "buy": "买入",
    "buy_dip": "低吸",
    "take_profit": "止盈",
    "trim_high": "高位减仓",
    "reduce": "减仓",
    "sell": "卖出",
    "stop_cut": "止损",
    "close": "清仓",
}

NODE_KIND_ZH = {
    "strategy": "战法",
    "rule": "规则",
    "watch": "观察",
    "lesson": "教训",
    "scenario": "情景",
    "critique": "评语",
}

EDGE_REL_ZH = {
    "has_rule": "含规则",
    "watches": "观察点",
    "learned_from": "学自",
    "absorbed_into": "吸入",
    "reinforces": "强化",
    "contradicts": "矛盾",
    "about": "关于",
}


def strategy_display_name(slug: str) -> str:
    """给人看的战法名；优先注册表中文名，再落监测短名，避免露出英文 slug。"""
    raw = str(slug or "").strip()
    if not raw:
        return "本战法"
    try:
        from src.strategy import get as get_strategy

        name = str(getattr(get_strategy(raw), "name", "") or "").strip()
        if name and not re.search(r"[A-Za-z]", name):
            return name
        if name and name != raw:
            return name
    except Exception:  # noqa: BLE001
        pass
    try:
        from src.ops.application.skill_watch.watch_labels import watch_short_name

        short = watch_short_name(slug=raw)
        if short and short != "战法":
            return short
    except Exception:  # noqa: BLE001
        pass
    return "本战法"


def human_num(value: Any, *, suffix: str = "", empty: str = "暂无") -> str:
    if value is None or value == "":
        return empty
    return f"{value}{suffix}"


def lesson_kind_zh(kind: Any) -> str:
    key = str(kind or "").strip()
    return LESSON_KIND_ZH.get(key, key or "备忘")


def buy_rules_zh(rules: dict[str, Any]) -> str:
    parts: list[str] = []
    for key, val in rules.items():
        k = BUY_RULE_KEY_ZH.get(str(key), str(key))
        v = BUY_RULE_VAL_ZH.get(str(val), str(val) if val is not None else "暂无")
        parts.append(f"{k}={v}")
    return "；".join(parts) if parts else "暂无"


def format_lookback_digest(pack: dict[str, Any] | None) -> str:
    """企微/日终推送用的短回看：只报计数与有内容的票，不灌空环境行。"""
    if not pack:
        return ""
    bought = list(pack.get("bought") or [])
    missed = list(pack.get("missed") or [])
    new_picks = list(pack.get("new_picks") or [])
    sold = list(pack.get("sold") or [])
    lines = [
        f"📊【五日回看】池内 {pack.get('universe_size') or 0} · "
        f"买过 {len(bought)} · 错过 {len(missed)} · "
        f"新入池 {len(new_picks)} · 卖过 {len(sold)}"
    ]
    for row in missed[:5]:
        lines.append(
            f"· 错过 {row.get('name') or row.get('code')} "
            f"入池后 {human_num(row.get('since_attention_return_pct'), suffix='%')}"
        )
    for row in bought[:4]:
        # 买过的票要报「你这笔怎么样」。标的整窗涨跌会被读成自己的盈亏，
        # 而窗口前半段根本还没建仓。
        lines.append(
            f"· 买过 {row.get('name') or row.get('code')} "
            f"买入后 {human_num(row.get('trade_return_pct'), suffix='%')}"
        )
    for row in new_picks[:4]:
        lines.append(f"· 新入池 {row.get('name') or row.get('code')}")
    return "\n".join(lines)


def format_lookback_for_prompt(pack: dict[str, Any], *, max_bars_per_name: int = 8) -> str:
    """压缩成可注入评头论足的中文文本；空值写「暂无」，不 dump 机器字段。"""
    days = [str(d) for d in (pack.get("lookback_trading_days") or []) if d]
    window = "、".join(days) if days else "暂无"
    label = strategy_display_name(str(pack.get("slug") or ""))
    lines = [
        f"【五交易日回看】{label} · 截止 {pack.get('trade_date') or '暂无'} · 窗口 {window}",
        f"池内 {pack.get('universe_size') or 0} 只 · 买过 {len(pack.get('bought') or [])} · "
        f"错过 {len(pack.get('missed') or [])} · 今日新入池 {len(pack.get('new_picks') or [])} · "
        f"卖过 {len(pack.get('sold') or [])}",
        "口径：错过=入池日早于复盘日且未买；今日新入池不算入池前涨幅的踏空；"
        "买过看「这笔收益」（自买入均价起，卖出按成交价、持有按窗末盯市），"
        "整窗收益是标的行情，买入前的涨跌不归因给这笔交易。",
    ]
    env = pack.get("environment") or {}
    lines.append(f"环境口径：{env.get('note') or '暂无'}")
    for day in env.get("by_day") or []:
        # 全空样本不占行，避免企微/正文刷「暂无×5」
        if not int(day.get("sample") or 0) and day.get("universe_amount") is None:
            continue
        lines.append(
            f"  {day.get('trade_date') or '暂无'} 成交额 {human_num(day.get('universe_amount'))} · "
            f"成交量 {human_num(day.get('universe_volume'))} · "
            f"均涨跌 {human_num(day.get('avg_pct'), suffix='%')} · "
            f"涨{day.get('up') or 0}/跌{day.get('down') or 0}/平{day.get('flat') or 0}"
        )
    if env.get("boards"):
        lines.append("板块/行业（末日均涨跌）：")
        for b in (env.get("boards") or [])[:8]:
            lines.append(
                f"  {b.get('board') or '未分类'} · {b.get('n') or 0} 只 · "
                f"均涨跌 {human_num(b.get('avg_pct_last'), suffix='%')}"
            )

    names = list(pack.get("names") or [])
    if names:
        lines.append("标的日K（窗口内）：")
    for row in names[:20]:
        status = STATUS_ZH.get(str(row.get("status") or ""), str(row.get("status") or "暂无"))
        head = (
            f"- {row.get('name') or '未知'} {row.get('code') or ''}（{status}）"
            f" 板块={row.get('board') or '暂无'} 行业={row.get('industry') or '暂无'}"
            f" 整窗收益={human_num(row.get('window_return_pct'), suffix='%')}"
            f" 入池后收益={human_num(row.get('since_attention_return_pct'), suffix='%')}"
        )
        if row.get("trade_return_pct") is not None:
            head += f" 这笔收益={human_num(row.get('trade_return_pct'), suffix='%')}"
        if row.get("post_exit_return_pct") is not None:
            head += f" 卖出后={human_num(row.get('post_exit_return_pct'), suffix='%')}"
        lines.append(
            f"{head}"
            f" 入池日={row.get('first_attention') or '暂无'}"
            f" K线根数={row.get('bars_count') or 0}"
        )
        for bar in (row.get("bars") or [])[-max_bars_per_name:]:
            lines.append(
                f"    {bar.get('trade_date') or '暂无'}"
                f" 开={human_num(bar.get('open'))}"
                f" 高={human_num(bar.get('high'))}"
                f" 低={human_num(bar.get('low'))}"
                f" 收={human_num(bar.get('close'))}"
                f" 量={human_num(bar.get('volume'))}"
                f" 额={human_num(bar.get('amount'))}"
                f" 换手={human_num(bar.get('turnover'))}"
                f" 涨跌={human_num(bar.get('pct'), suffix='%')}"
            )

    if pack.get("missed"):
        lines.append("错过（入池日早于复盘日，关注后未买入）后市：")
        for m in pack["missed"][:12]:
            lines.append(
                f"  · {m.get('name')} {m.get('code')} 入池 {m.get('first_attention') or '暂无'} "
                f"入池后收益 {human_num(m.get('since_attention_return_pct'), suffix='%')} "
                f"（整窗 {human_num(m.get('window_return_pct'), suffix='%')}，勿把入池前涨幅当踏空）"
            )
    if pack.get("new_picks"):
        lines.append("今日新入池（不算错过；入池前涨幅不归因）：")
        for m in pack["new_picks"][:12]:
            lines.append(
                f"  · {m.get('name')} {m.get('code')} 入池 {m.get('first_attention') or '暂无'} "
                f"整窗参考 {human_num(m.get('window_return_pct'), suffix='%')}"
            )

    cf = pack.get("capital_flow") or []
    if cf:
        lines.append("资金流（可选观测）：")
        for item in cf[:8]:
            if item.get("status") == "ok":
                lines.append(f"  · {item.get('code')} 已观测 {len(item.get('rows') or [])} 条")
            else:
                lines.append(
                    f"  · {item.get('code') or '未知'} 暂无观测"
                    + (f"（{item.get('error')}）" if item.get("error") else "")
                )
    return "\n".join(lines)
