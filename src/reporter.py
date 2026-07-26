"""Markdown 报告生成器 (基于 Jinja2 模板)"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape


MARKET_NAMES = {
    "sh": "上交所主板/科创板",
    "sz": "深交所主板/创业板",
    "bj": "北交所",
}


def _safe_float(v: Any) -> float | None:
    """尝试转 float, 失败返回 None (用于财务数据清洗)"""
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _summarize_financial(df: pd.DataFrame | None) -> list[dict]:
    """从完整财务表中提取归母净利润/营收/扣非净利润等关键指标"""
    if df is None or df.empty:
        return []
    out: list[dict] = []
    key_map = {
        "归母净利润": "归母净利润",
        "营业总收入": "营业总收入",
        "扣非净利润": "扣非净利润",
        "每股收益": "每股收益",
    }
    for label, indicator in key_map.items():
        try:
            row = df[df["指标"] == indicator]
            if row.empty:
                continue
            r = row.iloc[0]
            cols = [c for c in r.index if c not in ("选项", "指标")]
            if len(cols) < 2:
                continue
            cols_sorted = sorted(cols, reverse=True)
            latest_col = cols_sorted[0]
            prev_col = cols_sorted[1] if len(cols_sorted) > 1 else None
            v_latest = _safe_float(r[latest_col])
            v_prev = _safe_float(r[prev_col]) if prev_col else None
            if v_latest is None:
                continue
            unit = "亿" if abs(v_latest) > 1e7 else ""
            v_display = f"{v_latest/1e8:.2f} 亿" if unit else f"{v_latest:.4f}"
            if v_prev is not None and v_prev != 0:
                chg = (v_latest - v_prev) / abs(v_prev) * 100
                chg_str = f"{chg:+.1f}%"
            else:
                chg_str = "-"
            out.append({
                "name": f"{label}({latest_col})",
                "value": v_display,
                "change": chg_str,
            })
        except Exception:
            continue
    return out


def _summarize_reports(df: pd.DataFrame | None, limit: int = 5) -> list[dict]:
    """整理机构研报摘要"""
    if df is None or df.empty:
        return []
    out = []
    for _, r in df.head(limit).iterrows():
        try:
            eps_col = "2026-盈利预测-收益"
            pe_col = "2026-盈利预测-市盈率"
            eps = r.get(eps_col)
            pe = r.get(pe_col)
            if pd.notna(eps) and pd.notna(pe):
                eps_pe = f"{eps:.2f} / {pe:.1f}倍"
            else:
                eps_pe = "-"
            out.append({
                "org": r.get("机构", "-"),
                "rating": r.get("东财评级", "-"),
                "date": str(r.get("日期", "-"))[:10],
                "eps_pe": eps_pe,
            })
        except Exception:
            continue
    return out


def _build_key_levels_sorted(levels: dict, cost: float) -> list[dict]:
    """关键价位按价格降序排列, 用于报告 ASCII 图"""
    items = []
    label_map = {
        "BOLL_UP": "BOLL 上轨",
        "d30_high": "30 日高点",
        "d60_high": "60 日高点",
        "MA5": "MA5",
        "MA10": "MA10",
        "current": "【当前价】",
        "cost": "【您的成本】",
        "MA20": "MA20 (短中期支撑)",
        "MA60": "MA60 (中长期支撑)",
        "recommend_stop_loss": "【建议止损位】",
        "d30_low": "30 日低点",
        "d60_low": "60 日低点",
        "BOLL_DN": "BOLL 下轨",
    }
    for k, label in label_map.items():
        v = levels.get(k)
        if v is None:
            continue
        items.append({"price": v, "label": label})
    items.sort(key=lambda x: -x["price"])
    return items


def _get_kline_highlights(kline: pd.DataFrame, top_n: int = 5) -> list[str]:
    """提取 K 线关键拐点: 单日异动超过 ±5% 的日期"""
    if kline is None or kline.empty or "涨跌幅" not in kline.columns:
        return []
    d = kline.copy()
    d["abs_chg"] = d["涨跌幅"].abs()
    big_moves = d[d["abs_chg"] >= 5].nlargest(top_n, "abs_chg")
    out = []
    for _, r in big_moves.iterrows():
        sign = "✨ 拉升" if r["涨跌幅"] > 0 else "⚠️ 大跌"
        out.append(
            f"**{r['日期']}** {sign} **{r['涨跌幅']:+.2f}%**, "
            f"收盘 {r['收盘']:.2f}, 换手 {r['换手率']:.2f}%"
        )
    out.sort()
    return out


def _macd_interpretation(signal: str) -> str:
    return {
        "golden": "金叉形成, 短期动能转强",
        "dead": "死叉形成, 短期动能减弱",
        "above_zero": "红柱区间, 多头动能中",
        "below_zero": "绿柱区间, 空头动能中",
    }.get(signal, "中性")


class ReportRenderer:
    """Jinja2 模板渲染器"""

    def __init__(self, template_dir: Path | str):
        self.env = Environment(
            loader=FileSystemLoader(str(template_dir)),
            autoescape=select_autoescape(disabled_extensions=("md", "txt")),
            trim_blocks=False,
            lstrip_blocks=False,
        )

    def render_holding_report(
        self,
        *,
        data: dict,
        position: dict,
        levels: dict,
        trend: dict,
        fund_stance: dict,
        vwap30: float,
        vol: dict,
        breakeven_probs: list,
        chip_distribution: pd.DataFrame,
        strategies: list,
        recommended_scheme: str,
        buy_check: dict,
        risk_radar: dict,
        portfolio: dict,
        ai_context: dict,
        online_evidence: dict,
        cover_image: str | None,
        kline: pd.DataFrame,
    ) -> str:
        template = self.env.get_template("holding_report.md.j2")

        realtime = data.get("realtime") or {}
        rt_change = realtime.get("涨跌幅")
        rt_change_str = f"{rt_change:+.2f}%" if rt_change is not None else ""

        chip_table = chip_distribution.copy()
        if not chip_table.empty and "价格区间" in chip_table.columns:
            chip_table["价格区间"] = chip_table["价格区间"].astype(str)

        lhb = data.get("lhb")
        lhb_latest = ""
        if lhb is not None and not lhb.empty:
            r0 = lhb.iloc[0]
            lhb_latest = (
                f"{r0.get('上榜日', '')} {r0.get('上榜原因', '')[:30]}; "
                f"解读: {r0.get('解读', '')[:50]}"
            )

        kline_last10 = []
        kline_highlights = []
        last_rsi = None
        if kline is not None and not kline.empty:
            kline_last10 = kline.tail(10).to_dict("records")
            kline_highlights = _get_kline_highlights(kline)
            rsi_value = kline.iloc[-1].get("RSI14")
            last_rsi = float(rsi_value) if pd.notna(rsi_value) else None

        ctx = {
            "data": data,
            "code": data["code"],
            "name": data.get("name") or data["code"],
            "market_full": MARKET_NAMES.get(data.get("market", ""), ""),
            "query_time": data["query_time"],
            "realtime_change": rt_change_str,
            "position": position,
            "vwap30": vwap30,
            "kline_tail": kline,
            "kline_last10": kline_last10,
            "kline_highlights": kline_highlights,
            "levels": levels,
            "trend": trend,
            "macd_interpretation": _macd_interpretation(trend.get("macd_signal", "")),
            "last_rsi": last_rsi,
            "chip_distribution": chip_table.to_dict("records"),
            "fund_stance": fund_stance,
            "lhb_count": len(lhb) if lhb is not None else 0,
            "lhb_latest": lhb_latest,
            "lhb_table": lhb is not None and not lhb.empty,
            "financial_summary": _summarize_financial(data.get("financial")),
            "reports_summary": _summarize_reports(data.get("reports")),
            "key_levels_sorted": _build_key_levels_sorted(levels, position["cost"]),
            "vol": vol,
            "breakeven_probs": breakeven_probs,
            "strategies": strategies,
            "recommended_scheme": recommended_scheme,
            "buy_check": buy_check,
            "risk_radar": risk_radar,
            "portfolio": portfolio,
            "ai_context": ai_context,
            "online_evidence": online_evidence,
            "cover_image": cover_image,
            "template_id": "stock_research_final_v1",
        }
        return template.render(**ctx)
