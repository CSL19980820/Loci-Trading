"""提前发现雷达规则引擎。

本模块只做公开信息整理和观察池排序，不输出买卖建议。
核心思想：产业逻辑先行，公告/互动证据确认，量价资金验证，风险反证剔除。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from src.indicators import add_all_indicators


DISCOVERY_DISCLAIMER = "以上仅为公开信息整理与观察框架，不构成投资建议。"


@dataclass(frozen=True)
class WatchItem:
    code: str
    name: str
    theme: str = ""
    sector_rank: float | None = None
    sector_position: float | None = None
    chain_depth: float | None = None
    industry_signal: float | None = None
    evidence_score: float | None = None
    notes: str = ""


def normalize_code(value: Any) -> str:
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) > 6:
        digits = digits[-6:]
    return digits.zfill(6)


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    text = str(value).strip()
    if not text or text in {"-", "--", "nan", "None"}:
        return None
    text = text.replace("%", "").replace(",", "")
    multiplier = 1.0
    if text.endswith("亿"):
        multiplier = 100_000_000.0
        text = text[:-1]
    elif text.endswith("万"):
        multiplier = 10_000.0
        text = text[:-1]
    try:
        return float(text) * multiplier
    except ValueError:
        return None


def load_watchlist(path: str | Path) -> list[WatchItem]:
    df = pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")
    if "code" not in df.columns:
        raise ValueError("watchlist CSV 必须包含 code 列")
    items: list[WatchItem] = []
    for _, row in df.iterrows():
        code = normalize_code(row.get("code"))
        if not code or code == "000000":
            continue
        items.append(
            WatchItem(
                code=code,
                name=str(row.get("name") or code).strip() or code,
                theme=str(row.get("theme") or row.get("sector") or "").strip(),
                sector_rank=_to_float(row.get("sector_rank")),
                sector_position=_to_float(row.get("sector_position")),
                chain_depth=_to_float(row.get("chain_depth")),
                industry_signal=_to_float(row.get("industry_signal")),
                evidence_score=_to_float(row.get("evidence_score")),
                notes=str(row.get("notes") or "").strip(),
            )
        )
    return items


def prepare_kline(kline: pd.DataFrame | None) -> pd.DataFrame | None:
    if kline is None or kline.empty:
        return None
    required = {"开盘", "收盘", "最高", "最低", "成交量"}
    if not required.issubset(set(kline.columns)):
        return None
    out = kline.copy()
    if "日期" in out.columns:
        out = out.sort_values("日期").reset_index(drop=True)
    for col in ["开盘", "收盘", "最高", "最低", "成交量", "涨跌幅", "成交额", "换手率"]:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out.dropna(subset=["开盘", "收盘", "最高", "最低", "成交量"]).reset_index(drop=True)
    if out.empty:
        return None
    return add_all_indicators(out)


def _pct_at(df: pd.DataFrame, idx: int) -> float | None:
    if df.empty:
        return None
    i = idx if idx >= 0 else len(df) + idx
    if i < 0 or i >= len(df):
        return None
    row = df.iloc[i]
    raw = row.get("涨跌幅")
    if pd.notna(raw):
        return float(raw)
    if i <= 0:
        return None
    prev = float(df.iloc[i - 1]["收盘"])
    if prev == 0:
        return None
    return (float(row["收盘"]) / prev - 1) * 100


def _volume_ratio(df: pd.DataFrame, idx: int = -1, lookback: int = 5) -> float | None:
    i = idx if idx >= 0 else len(df) + idx
    if i <= 0 or i >= len(df):
        return None
    start = max(0, i - lookback)
    base = df.iloc[start:i]["成交量"].astype(float).mean()
    if pd.isna(base) or base <= 0:
        return None
    return float(df.iloc[i]["成交量"]) / float(base)


def classify_t1_pattern(df: pd.DataFrame) -> dict[str, Any]:
    """用最新完整日线作为 T-1，分类 A/B/C/D/E。"""
    if df is None or len(df) < 6:
        return {"pattern": "U", "score": 0, "hard_reject": False, "reason": "K线不足"}
    pct = _pct_at(df, -1)
    vr = _volume_ratio(df, -1, 5)
    close_now = float(df.iloc[-1]["收盘"])
    close_t3 = float(df.iloc[-3]["收盘"]) if len(df) >= 3 else close_now
    pct3d = (close_now / close_t3 - 1) * 100 if close_t3 else 0.0
    pct = 0.0 if pct is None else pct
    vr = 0.0 if vr is None else vr

    if pct >= 5 or pct3d >= 12:
        return {"pattern": "D", "score": 0, "hard_reject": True, "reason": "最新日线已进入续涨动量区"}
    if vr >= 2.0 and abs(pct) <= 2:
        return {"pattern": "E", "score": 0, "hard_reject": True, "reason": "最新日线放量滞涨"}
    if -2 <= pct <= 3 and 0.7 <= vr <= 1.6:
        return {"pattern": "A", "score": 6, "hard_reject": False, "reason": "小阳/小阴蓄势"}
    if -6 <= pct <= -0.5:
        return {"pattern": "B", "score": 5, "hard_reject": False, "reason": "趋势回踩"}
    if -7 <= pct <= -3 and vr <= 1.8:
        return {"pattern": "C", "score": 4, "hard_reject": False, "reason": "反包预备"}
    return {"pattern": "U", "score": 2, "hard_reject": False, "reason": "未归类形态"}


def detect_volume_stagnation(df: pd.DataFrame) -> list[str]:
    """放量滞涨反证，命中任一项即不纳入提前观察池。"""
    reasons: list[str] = []
    if df is None or len(df) < 6:
        return reasons
    latest = df.iloc[-1]
    pct = _pct_at(df, -1) or 0.0
    vr = _volume_ratio(df, -1, 5) or 0.0
    high = float(latest["最高"])
    low = float(latest["最低"])
    close = float(latest["收盘"])
    open_ = float(latest["开盘"])
    amplitude = (high - low) / close * 100 if close else 0.0
    upper_shadow = high - max(open_, close)
    body = abs(close - open_)

    if vr >= 2.0 and abs(pct) <= 2:
        reasons.append("A: 单日放量滞涨")

    if len(df) >= 4:
        last3 = df.tail(3)
        vols = list(last3["成交量"].astype(float))
        pct3 = (float(last3.iloc[-1]["收盘"]) / float(last3.iloc[0]["收盘"]) - 1) * 100
        if vols[0] < vols[1] < vols[2] and pct3 < 3:
            reasons.append("B: 三日堆量不涨")

    if vr >= 1.8 and ((amplitude >= 5 and abs(pct) <= 2) or upper_shadow > body):
        reasons.append("C: 高振幅收平或长上影")

    if len(df) >= 4:
        tail = df.tail(4).copy()
        obv = [0.0]
        for i in range(1, len(tail)):
            close_i = float(tail.iloc[i]["收盘"])
            close_prev = float(tail.iloc[i - 1]["收盘"])
            vol_i = float(tail.iloc[i]["成交量"])
            if close_i > close_prev:
                obv.append(obv[-1] + vol_i)
            elif close_i < close_prev:
                obv.append(obv[-1] - vol_i)
            else:
                obv.append(obv[-1])
        pct3 = (float(tail.iloc[-1]["收盘"]) / float(tail.iloc[-3]["收盘"]) - 1) * 100
        if obv[-1] < obv[-3] and pct3 < 3:
            reasons.append("D: OBV proxy 下行且价格未走强")

    return reasons


def score_fund_flow(fund_df: pd.DataFrame | None) -> dict[str, Any]:
    if fund_df is None or fund_df.empty:
        return {"available": False, "score": 0, "details": ["资金流数据未取得"]}
    details: list[str] = []
    score = 0
    df = fund_df.tail(5).copy()
    main_col = "主力净流入-净额"
    small_col = "小单净流入-净额"
    if main_col not in df.columns:
        return {"available": False, "score": 0, "details": ["资金流字段缺失"]}
    main = pd.to_numeric(df[main_col], errors="coerce").fillna(0)
    main3 = float(main.tail(3).sum())
    main5 = float(main.tail(5).sum())
    if main3 > 0:
        score += 7
        details.append("近 3 日主力净流入")
    if main5 > 0:
        score += 5
        details.append("近 5 日主力净流入")
    if small_col in df.columns:
        small5 = float(pd.to_numeric(df[small_col], errors="coerce").fillna(0).tail(5).sum())
        if not (main5 < 0 and small5 > 0 and abs(small5) > abs(main5) * 0.5):
            score += 3
            details.append("未触发主力流出/小单接盘背离")
        else:
            details.append("触发主力流出/小单接盘背离")
    return {
        "available": True,
        "score": min(score, 15),
        "main3": main3,
        "main5": main5,
        "details": details,
    }


def _period_columns(financial: pd.DataFrame) -> list[str]:
    cols = [str(c) for c in financial.columns[1:]]
    dated: list[tuple[pd.Timestamp, str]] = []
    for col in cols:
        dt = pd.to_datetime(col, errors="coerce")
        if pd.notna(dt):
            dated.append((dt, col))
    if dated:
        return [col for _, col in sorted(dated, reverse=True)]
    return cols


def _financial_row(financial: pd.DataFrame, keywords: tuple[str, ...]) -> pd.Series | None:
    label_col = financial.columns[0]
    labels = financial[label_col].astype(str)
    for kw in keywords:
        hit = financial[labels.str.contains(kw, regex=False, na=False)]
        if not hit.empty:
            return hit.iloc[0]
    return None


def score_financial_signals(financial: pd.DataFrame | None) -> dict[str, Any]:
    if financial is None or financial.empty or len(financial.columns) < 3:
        return {"available": False, "score": 0, "details": ["财务前置信号未取得"]}
    periods = _period_columns(financial)
    if len(periods) < 2:
        return {"available": False, "score": 0, "details": ["财务期数不足"]}

    latest, previous = periods[0], periods[1]
    checks = [
        (("营业收入", "主营业务收入"), "营收改善", 3),
        (("净利润", "归母净利润"), "利润改善", 3),
        (("销售毛利率", "毛利率"), "毛利率改善", 2),
        (("经营现金流", "经营活动产生的现金流量净额"), "经营现金流改善", 2),
    ]
    score = 0
    details: list[str] = []
    for keywords, label, weight in checks:
        row = _financial_row(financial, keywords)
        if row is None:
            continue
        now = _to_float(row.get(latest))
        prev = _to_float(row.get(previous))
        if now is None or prev is None:
            continue
        if now > prev:
            score += weight
            details.append(label)
    if not details:
        details.append("未识别到明确改善项")
    return {
        "available": True,
        "score": min(score, 10),
        "latest_period": latest,
        "previous_period": previous,
        "details": details,
    }


def _manual_evidence_score(item: WatchItem) -> dict[str, Any]:
    score = 0
    details: list[str] = []
    if item.sector_rank is not None:
        if item.sector_rank <= 3:
            score += 8
            details.append("题材强度 TOP3")
        elif item.sector_rank <= 8:
            score += 5
            details.append("题材强度 TOP8")
        elif item.sector_rank <= 15:
            score += 2
            details.append("题材仍在前排")
    if item.sector_position is not None:
        if 3 <= item.sector_position <= 20:
            score += 6
            details.append("同板块位置避开龙一龙二")
        elif item.sector_position <= 2:
            details.append("同板块位置偏龙头，非提前发现区")
    if item.chain_depth is not None:
        if item.chain_depth in {2, 3}:
            score += 5
            details.append("产业链二三层环节")
        elif item.chain_depth >= 4:
            score += 3
            details.append("产业链更深层环节")
    if item.industry_signal is not None:
        added = max(0, min(6, item.industry_signal))
        score += added
        if added:
            details.append(f"产业先行信号 {added:g}/6")
    if item.evidence_score is not None:
        added = max(0, min(6, item.evidence_score))
        score += added
        if added:
            details.append(f"公告/互动证据 {added:g}/6")
    if not details:
        details.append("缺少手工产业证据评分")
    return {"score": min(round(score, 1), 25), "details": details}


def analyze_discovery_candidate(
    item: WatchItem,
    kline: pd.DataFrame | None,
    fund_flow: pd.DataFrame | None = None,
    financial: pd.DataFrame | None = None,
) -> dict[str, Any]:
    prepared = prepare_kline(kline)
    if prepared is None or len(prepared) < 30:
        return {
            "code": item.code,
            "name": item.name,
            "theme": item.theme,
            "score": 0,
            "tier": "数据不足",
            "hard_rejects": ["真实 K 线缺失或不足 30 根"],
            "metrics": {},
            "components": {},
            "notes": item.notes,
        }

    latest = prepared.iloc[-1]
    close = float(latest["收盘"])
    ma5 = latest.get("MA5")
    ma20 = latest.get("MA20")
    ma60 = latest.get("MA60")
    pct1 = _pct_at(prepared, -1)
    pct10 = (close / float(prepared.iloc[-10]["收盘"]) - 1) * 100 if len(prepared) >= 10 else None
    pct20 = (close / float(prepared.iloc[-20]["收盘"]) - 1) * 100 if len(prepared) >= 20 else None
    high60 = float(prepared.tail(60)["最高"].max()) if len(prepared) >= 60 else float(prepared["最高"].max())
    dist_high60 = (close / high60 - 1) * 100 if high60 else None
    vr = _volume_ratio(prepared, -1, 5)
    t1 = classify_t1_pattern(prepared)
    stagnation = detect_volume_stagnation(prepared)
    fund = score_fund_flow(fund_flow)
    fin = score_financial_signals(financial)
    manual = _manual_evidence_score(item)

    hard_rejects: list[str] = []
    if t1.get("hard_reject"):
        hard_rejects.append(str(t1["reason"]))
    hard_rejects.extend(stagnation)
    if item.sector_position is not None and item.sector_position <= 2:
        hard_rejects.append("同板块龙一/龙二，非提前潜伏区")

    trend_score = 0
    trend_details: list[str] = []
    if pd.notna(ma20) and close >= float(ma20):
        trend_score += 5
        trend_details.append("收盘站上 MA20")
    if pd.notna(ma5) and pd.notna(ma20) and pd.notna(ma60) and float(ma5) >= float(ma20) >= float(ma60):
        trend_score += 8
        trend_details.append("均线多头或准多头")
    elif pd.notna(ma20) and pd.notna(ma60) and float(ma20) >= float(ma60):
        trend_score += 5
        trend_details.append("MA20 未弱于 MA60")
    if pct10 is not None and 2 <= pct10 <= 12:
        trend_score += 7
        trend_details.append("近 10 日涨幅处于未透支区")
    elif pct10 is not None and -3 <= pct10 <= 15:
        trend_score += 3
        trend_details.append("近 10 日未明显过热")
    if dist_high60 is not None and dist_high60 <= -5:
        trend_score += 5
        trend_details.append("距 60 日高点仍有空间")
    elif dist_high60 is not None and dist_high60 < 0:
        trend_score += 2
        trend_details.append("未创 60 日新高")
    trend_score = min(trend_score, 25)

    volume_score = 0
    volume_details: list[str] = []
    if vr is not None:
        if 0.6 <= vr <= 1.5:
            volume_score += 10
            volume_details.append("量比温和")
        elif 1.2 <= vr <= 1.8:
            volume_score += 7
            volume_details.append("温和放量")
        elif 0.4 <= vr < 2.0:
            volume_score += 3
            volume_details.append("量能未极端")
    if pct1 is not None and -6 <= pct1 <= 4:
        volume_score += 5
        volume_details.append("最新涨跌幅未透支")
    volume_score += int(t1.get("score") or 0)
    volume_details.append(f"T-1 形态 {t1.get('pattern')}: {t1.get('reason')}")
    if not stagnation:
        volume_score += 4
        volume_details.append("未触发放量滞涨反证")
    volume_score = min(volume_score, 25)

    fund_fin_score = min(25, fund["score"] + fin["score"])
    components = {
        "industry_evidence": manual,
        "trend_position": {"score": trend_score, "details": trend_details},
        "volume_price": {"score": volume_score, "details": volume_details},
        "fund_financial": {
            "score": fund_fin_score,
            "details": list(fund.get("details") or []) + list(fin.get("details") or []),
            "fund": fund,
            "financial": fin,
        },
    }

    score = round(
        manual["score"] + trend_score + volume_score + fund_fin_score,
        1,
    )
    if hard_rejects:
        tier = "剔除"
    elif score >= 75:
        tier = "重点观察"
    elif score >= 65:
        tier = "观察"
    elif score >= 55:
        tier = "待证据"
    else:
        tier = "不纳入"

    positives = (
        manual["details"]
        + trend_details
        + volume_details
        + list(fund.get("details") or [])
        + list(fin.get("details") or [])
    )

    return {
        "code": item.code,
        "name": item.name,
        "theme": item.theme,
        "score": score,
        "tier": tier,
        "hard_rejects": hard_rejects,
        "positives": positives[:12],
        "metrics": {
            "date": str(latest.get("日期", "")),
            "close": round(close, 3),
            "pct1": round(pct1, 2) if pct1 is not None else None,
            "pct10": round(pct10, 2) if pct10 is not None else None,
            "pct20": round(pct20, 2) if pct20 is not None else None,
            "volume_ratio": round(vr, 2) if vr is not None else None,
            "dist_high60": round(dist_high60, 2) if dist_high60 is not None else None,
            "ma20": round(float(ma20), 3) if pd.notna(ma20) else None,
            "ma60": round(float(ma60), 3) if pd.notna(ma60) else None,
            "t1_pattern": t1.get("pattern"),
        },
        "components": components,
        "notes": item.notes,
        "disclaimer": DISCOVERY_DISCLAIMER,
    }


def flatten_result(result: dict[str, Any]) -> dict[str, Any]:
    metrics = result.get("metrics") or {}
    comps = result.get("components") or {}
    return {
        "code": result.get("code"),
        "name": result.get("name"),
        "theme": result.get("theme"),
        "tier": result.get("tier"),
        "score": result.get("score"),
        "date": metrics.get("date"),
        "close": metrics.get("close"),
        "pct1": metrics.get("pct1"),
        "pct10": metrics.get("pct10"),
        "volume_ratio": metrics.get("volume_ratio"),
        "dist_high60": metrics.get("dist_high60"),
        "t1_pattern": metrics.get("t1_pattern"),
        "industry_score": (comps.get("industry_evidence") or {}).get("score"),
        "trend_score": (comps.get("trend_position") or {}).get("score"),
        "volume_score": (comps.get("volume_price") or {}).get("score"),
        "fund_financial_score": (comps.get("fund_financial") or {}).get("score"),
        "hard_rejects": "；".join(result.get("hard_rejects") or []),
        "positives": "；".join(result.get("positives") or []),
        "notes": result.get("notes"),
    }


def render_discovery_markdown(results: list[dict[str, Any]], *, title: str = "提前发现雷达") -> str:
    ranked = sorted(results, key=lambda x: float(x.get("score") or 0), reverse=True)
    observed = [r for r in ranked if r.get("tier") in {"重点观察", "观察", "待证据"}]
    rejected = [r for r in ranked if r.get("hard_rejects")]
    hard_rejected = [r for r in ranked if r.get("tier") == "剔除"]
    data_issues = [r for r in ranked if r.get("tier") in {"数据不足", "异常"}]
    lines = [
        f"# {title}",
        "",
        DISCOVERY_DISCLAIMER,
        "",
        "## 摘要",
        "",
        f"- 样本数：{len(results)}",
        f"- 重点观察/观察/待证据：{len(observed)}",
        f"- 反证剔除：{len(hard_rejected)}",
        f"- 数据不足/异常：{len(data_issues)}",
        "",
        "## 观察池",
        "",
        "| 排名 | 代码 | 名称 | 题材 | 分层 | 得分 | 量比 | 10日涨幅 | T-1 | 核心理由 |",
        "|---:|---|---|---|---|---:|---:|---:|---|---|",
    ]
    for i, r in enumerate(observed, 1):
        m = r.get("metrics") or {}
        reason = "；".join((r.get("positives") or [])[:4])
        lines.append(
            f"| {i} | {r.get('code')} | {r.get('name')} | {r.get('theme') or '-'} | "
            f"{r.get('tier')} | {r.get('score')} | {m.get('volume_ratio') or '-'} | "
            f"{m.get('pct10') or '-'} | {m.get('t1_pattern') or '-'} | {reason or '-'} |"
        )
    if not observed:
        lines.append("| - | - | - | - | - | - | - | - | - | 无观察候选 |")

    lines.extend([
        "",
        "## 剔除/数据不足",
        "",
        "| 代码 | 名称 | 得分 | 原因 |",
        "|---|---|---:|---|",
    ])
    for r in rejected:
        lines.append(
            f"| {r.get('code')} | {r.get('name')} | {r.get('score')} | "
            f"{'；'.join(r.get('hard_rejects') or [])} |"
        )
    if not rejected:
        lines.append("| - | - | - | 未触发硬剔除 |")

    lines.extend([
        "",
        "## 使用规则",
        "",
        "1. 先维护行业池：只放有真实景气变化的方向。",
        "2. 再维护公司池：补充 `sector_rank`、`sector_position`、`chain_depth`、`industry_signal`、`evidence_score`。",
        "3. 每日收盘后运行雷达，重点看温和量比、未透支涨幅、资金和财务前置信号。",
        "4. 命中放量滞涨、续涨透支、龙一龙二时直接从提前观察池剔除。",
        "5. 公告和互动证据建议从巨潮资讯、交易所公告、上证 e 互动、深交所互动易核验。",
        "",
        "## 字段口径",
        "",
        "- `sector_rank`：题材/行业强度排名，越小越强。",
        "- `sector_position`：个股在同板块涨幅/辨识度位置，3-20 更符合提前观察区。",
        "- `chain_depth`：产业链层级，2/3 代表二三层环节。",
        "- `industry_signal`：产业先行信号手工分，0-6。",
        "- `evidence_score`：公告、互动、业绩说明会等公开证据手工分，0-6。",
    ])
    return "\n".join(lines) + "\n"
