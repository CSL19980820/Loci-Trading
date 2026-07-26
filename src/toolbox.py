"""辅助分析工具箱与多格式导出。

本模块只做研究辅助和报告工程化，不输出确定性买卖建议。
"""
from __future__ import annotations

import html
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


DISCLAIMER = "股市有风险，入市需谨慎；以下内容为公开信息整理与研究辅助，不构成投资建议。"
FINAL_TEMPLATE_ID = "stock_research_final_v1"


def build_buy_check(position: dict[str, Any], levels: dict[str, Any], trend: dict[str, Any], fund_stance: dict[str, Any],
                    vol: dict[str, Any], kline: pd.DataFrame) -> dict[str, Any]:
    """生成买入适配度检查。

    评分越高表示观察条件越充分；不是买入建议。
    """
    if kline is None or kline.empty or position.get("current") is None:
        return {
            "score": None,
            "max_score": None,
            "score_pct": None,
            "grade": "待真实行情",
            "checks": [],
            "blockers": [{"name": "真实 K 线缺失", "detail": "未取得可验证的价格时间序列，规则引擎未运行"}],
            "decision_note": "当前未取得真实 K 线，买入辅助检查未运行。",
        }
    current = float(position["current"])
    ma20 = levels.get("MA20")
    ma60 = levels.get("MA60")
    rsi = kline.iloc[-1].get("RSI14") if not kline.empty else None
    annual_vol = float(vol.get("annual_vol") or 0)

    checks: list[dict[str, Any]] = []

    def add(name: str, passed: bool, weight: int, detail: str) -> None:
        checks.append({"name": name, "passed": bool(passed), "weight": weight, "detail": detail})

    add("趋势未破坏", trend.get("trend") != "downtrend", 22, f"趋势={trend.get('trend')}，强度={trend.get('strength')}")
    add("价格站上 MA20", bool(ma20 and current >= ma20), 18, f"当前价={current:.2f}，MA20={ma20:.2f}" if ma20 else "MA20 不可用")
    add("中期均线不压制", bool(ma60 and current >= ma60), 14, f"当前价={current:.2f}，MA60={ma60:.2f}" if ma60 else "MA60 不可用")
    add("资金面非明显流出", fund_stance.get("stance") not in ("大幅流出", "温和流出"), 16,
        f"资金态度={fund_stance.get('stance', '未知')}")
    add("RSI 未过热", bool(pd.notna(rsi) and float(rsi) < 70), 12, f"RSI14={float(rsi):.2f}" if pd.notna(rsi) else "RSI 不可用")
    add("波动可控", annual_vol <= 0.65, 10, f"年化波动率={annual_vol * 100:.2f}%")
    add("未出现散户接盘背离", not fund_stance.get("divergence_warning", False), 8,
        "主力净流出且小单净流入" if fund_stance.get("divergence_warning") else "未触发背离预警")

    max_score = sum(int(item["weight"]) for item in checks)
    score = sum(int(item["weight"]) for item in checks if item["passed"])
    score_pct = round(score / max_score * 100, 1) if max_score else 0.0

    if score_pct >= 75:
        grade = "观察条件较充分"
    elif score_pct >= 55:
        grade = "条件中性，需等待确认"
    else:
        grade = "风险条件偏多"

    blockers = [item for item in checks if not item["passed"] and item["weight"] >= 14]
    return {
        "score": score,
        "max_score": max_score,
        "score_pct": score_pct,
        "grade": grade,
        "checks": checks,
        "blockers": blockers,
        "decision_note": "仅表示研究条件成熟度，不代表可以买入或应当买入。",
    }


def build_risk_radar(position: dict[str, Any], levels: dict[str, Any], trend: dict[str, Any], fund_stance: dict[str, Any],
                     vol: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    """生成风险雷达。"""
    risks: list[dict[str, Any]] = []

    def add(name: str, level: str, detail: str) -> None:
        score_map = {"低": 1, "中": 2, "高": 3}
        risks.append({"name": name, "level": level, "score": score_map[level], "detail": detail})

    pnl_pct = position.get("pnl_pct")
    annual_vol = vol.get("annual_vol")
    if pnl_pct is None:
        add("持仓亏损风险", "中", "未取得真实行情，浮盈亏待核验")
    else:
        pnl_pct_f = float(pnl_pct)
        add("持仓亏损风险", "高" if pnl_pct_f <= -15 else "中" if pnl_pct_f < 0 else "低",
            f"当前浮动盈亏={pnl_pct_f:+.2f}%")
    add("趋势风险", "高" if trend.get("trend") == "downtrend" else "中" if trend.get("trend") in ("sideways", "unknown") else "低",
        f"趋势={trend.get('trend')}，MACD={trend.get('macd_signal')}")
    if annual_vol is None or pd.isna(annual_vol):
        add("波动风险", "中", "未取得真实 K 线，波动率待核验")
    else:
        annual_vol_f = float(annual_vol)
        add("波动风险", "高" if annual_vol_f > 0.8 else "中" if annual_vol_f > 0.45 else "低",
            f"近 60 日年化波动率={annual_vol_f * 100:.2f}%")
    add("资金拥挤/流出风险", "高" if fund_stance.get("stance") == "大幅流出" else "中" if fund_stance.get("stance") == "温和流出" else "低",
        f"资金态度={fund_stance.get('stance', '未知')}")
    current = position.get("current")
    ma20 = levels.get("MA20")
    if current is None or ma20 is None:
        add("关键位破位风险", "中", "未取得真实 K 线，关键位待核验")
    else:
        add("关键位破位风险", "高" if current < ma20 else "中",
            f"当前价={current:.2f}，MA20={ma20:.2f}")
    add("数据完整性风险", "中" if any(data.get(k) is None for k in ("financial", "reports", "fund_flow", "kline")) else "低",
        "部分外部数据源不可用时，报告以 K 线和已取得数据为主")

    avg_score = sum(r["score"] for r in risks) / len(risks)
    overall = "高" if avg_score >= 2.4 else "中" if avg_score >= 1.7 else "低"
    return {"overall": overall, "avg_score": round(avg_score, 2), "items": risks}


def load_portfolio(path: str | None, current_code: str, current_name: str, current_price: float) -> list[dict[str, Any]]:
    """读取持仓 CSV。

    支持列：code,name,cost,shares,current_price。current_price 可缺省，当前标的自动补最新价。
    """
    if not path:
        return []
    df = pd.read_csv(path, encoding="utf-8-sig")
    required = {"code", "cost", "shares"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"持仓 CSV 缺少列: {', '.join(sorted(missing))}")

    rows: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        code = str(row.get("code")).zfill(6)
        name = str(row.get("name") or code)
        cost = float(row.get("cost"))
        shares = int(row.get("shares"))
        raw_current = row.get("current_price")
        if pd.isna(raw_current):
            if code == str(current_code).zfill(6):
                current = current_price
                name = current_name or name
            else:
                current = cost
        else:
            current = float(raw_current)
        market_value = current * shares
        total_cost = cost * shares
        rows.append({
            "code": code,
            "name": name,
            "cost": cost,
            "shares": shares,
            "current_price": current,
            "total_cost": total_cost,
            "market_value": market_value,
            "pnl": market_value - total_cost,
            "pnl_pct": (current / cost - 1) * 100 if cost else 0.0,
        })
    return rows


def analyze_portfolio(holdings: list[dict[str, Any]]) -> dict[str, Any]:
    """组合持仓集中度与盈亏分析。"""
    if not holdings:
        return {"available": False, "holdings": []}
    total_cost = sum(float(h["total_cost"]) for h in holdings)
    total_value = sum(float(h["market_value"]) for h in holdings)
    for h in holdings:
        h["weight"] = float(h["market_value"]) / total_value * 100 if total_value else 0.0

    sorted_holdings = sorted(holdings, key=lambda x: x["weight"], reverse=True)
    top1 = sorted_holdings[0]["weight"] if sorted_holdings else 0.0
    top3 = sum(h["weight"] for h in sorted_holdings[:3])
    concentration = "高" if top1 >= 50 or top3 >= 80 else "中" if top1 >= 30 or top3 >= 60 else "低"
    return {
        "available": True,
        "holdings": sorted_holdings,
        "total_cost": total_cost,
        "total_value": total_value,
        "total_pnl": total_value - total_cost,
        "total_pnl_pct": (total_value / total_cost - 1) * 100 if total_cost else 0.0,
        "top1_weight": top1,
        "top3_weight": top3,
        "concentration": concentration,
    }


def load_online_evidence(path: str | None) -> dict[str, Any]:
    """读取 Codex 在线核验证据 JSON。"""
    if not path:
        return {"available": False, "template_id": FINAL_TEMPLATE_ID, "sources": [], "data_cross_checks": []}
    evidence_path = Path(path)
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("online evidence must be a JSON object")
    payload.setdefault("template_id", FINAL_TEMPLATE_ID)
    payload.setdefault("sources", [])
    payload.setdefault("data_cross_checks", [])
    payload.setdefault("open_questions", [])
    payload["available"] = True
    payload["path"] = str(evidence_path)
    return payload


def build_ai_context(data: dict[str, Any], position: dict[str, Any], buy_check: dict[str, Any],
                     risk_radar: dict[str, Any], portfolio: dict[str, Any], recommended_scheme: str,
                     online_evidence: dict[str, Any]) -> dict[str, Any]:
    """生成给本地/外部 AI 二次解读的结构化上下文。"""
    return {
        "template_id": FINAL_TEMPLATE_ID,
        "disclaimer": DISCLAIMER,
        "task_boundary": "只能做公开信息整理、风险列举和研究框架说明，不得输出确定性买卖建议。",
        "query_time": data.get("query_time"),
        "security": {
            "code": data.get("code"),
            "name": data.get("name"),
            "market": data.get("market"),
            "source": "AkShare 聚合（东方财富/新浪/同花顺口径）",
        },
        "position": position,
        "buy_check": {
            "score_pct": buy_check.get("score_pct"),
            "grade": buy_check.get("grade"),
            "blockers": buy_check.get("blockers"),
        },
        "risk_radar": risk_radar,
        "portfolio_summary": {k: v for k, v in portfolio.items() if k != "holdings"},
        "rule_engine_observation": recommended_scheme,
        "online_evidence": {
            "available": online_evidence.get("available", False),
            "query_time": online_evidence.get("query_time"),
            "source_count": len(online_evidence.get("sources") or []),
            "cross_check_count": len(online_evidence.get("data_cross_checks") or []),
            "open_questions": online_evidence.get("open_questions") or [],
        },
        "suggested_prompt": "请基于以上结构化数据，只输出事实、观察点、风险和需要继续核验的信息，不要给出买卖指令。",
    }


def render_html_document(markdown_text: str, title: str, cover_image: str | None = None) -> str:
    """将 Markdown 包装为可打印 HTML。优先使用 markdown 包，缺失时使用保守降级。"""
    try:
        import markdown  # type: ignore

        body = markdown.markdown(markdown_text, extensions=["tables", "fenced_code", "toc"])
    except Exception:
        body = "<pre>" + html.escape(markdown_text) + "</pre>"
    heading = html.escape(title)
    subtitle = "结构化研究报告 / Codex 定稿模板"
    cover_markup = (
        f'<section class="report-cover"><div class="cover-inner"><div class="cover-kicker">STOCK ANALYZER</div>'
        f'<h1>{heading}</h1><p>{subtitle}</p></div></section>'
    )
    cover_css = ""
    if cover_image:
        cover_uri = Path(cover_image).resolve().as_uri()
        cover_css = (
            ".report-cover { background-image: linear-gradient(135deg, rgba(12,24,38,.92), rgba(20,58,86,.55)), "
            f"url('{cover_uri}'); background-size: cover; background-position: center; color: #fff; "
            "padding: 64px 56px; min-height: 320px; display: flex; align-items: end; border-radius: 0 0 24px 24px; overflow: hidden; }"
        )
    else:
        cover_css = (
            ".report-cover { background: linear-gradient(135deg, #102235, #25556f 55%, #c08d2b); "
            "padding: 64px 56px; min-height: 320px; display: flex; align-items: end; border-radius: 0 0 24px 24px; overflow: hidden; color: #fff; }"
        )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>{html.escape(title)}</title>
  <style>
    :root {{ --report-bg: #eef2f6; --report-surface: #ffffff; --report-ink: #152132; --report-muted: #5e6a79; --report-border: #d8e0e8; --report-primary: #1f5f7a; --report-accent: #b98a31; --report-subtle: #f4f7fa; }}
    * {{ box-sizing: border-box; }}
    body {{ font-family: "Georgia", "Times New Roman", "Songti SC", "STSong", serif; line-height: 1.7; margin: 0; color: var(--report-ink); background:
      radial-gradient(circle at top left, rgba(31,95,122,0.10), transparent 30%),
      linear-gradient(180deg, #f4f7fa 0%, #e9eef3 100%); }}
    .page {{ max-width: 1120px; margin: 28px auto; padding: 0 20px 32px; }}
    main {{ background: var(--report-surface); box-shadow: 0 24px 70px rgba(20,33,50,0.10); border: 1px solid rgba(21,33,50,0.06); border-radius: 24px; overflow: hidden; }}
    .content {{ padding: 40px 48px 56px; }}
    h1, h2, h3 {{ color: var(--report-ink); letter-spacing: 0; }}
    .report-cover h1 {{ margin: 0; max-width: 720px; font-size: 38px; line-height: 1.15; color: #ffffff; }}
    .report-cover p {{ margin: 12px 0 0; font-size: 15px; color: rgba(255,255,255,0.82); }}
    .cover-kicker {{ display: inline-block; margin-bottom: 16px; padding: 6px 10px; border: 1px solid rgba(255,255,255,0.24); font: 600 11px/1.2 "Segoe UI", sans-serif; letter-spacing: 0.18em; color: rgba(255,255,255,0.86); }}
    .cover-inner {{ max-width: 760px; }}
    h1:not(.report-cover h1) {{ font-size: 31px; line-height: 1.2; margin: 0 0 18px; }}
    h2 {{ margin: 40px 0 18px; padding-top: 18px; border-top: 2px solid var(--report-primary); font-size: 22px; }}
    h3 {{ margin: 28px 0 14px; font-size: 18px; }}
    p, li, td, th, blockquote {{ font-size: 14px; }}
    table {{ border-collapse: collapse; width: 100%; margin: 18px 0 22px; background: #fff; }}
    th, td {{ border: 1px solid var(--report-border); padding: 10px 12px; text-align: left; vertical-align: top; }}
    th {{ background: #edf3f8; color: var(--report-ink); font-family: "Segoe UI", "Microsoft YaHei", sans-serif; font-weight: 600; }}
    tr:nth-child(even) td {{ background: #fbfcfd; }}
    blockquote {{ margin: 18px 0; padding: 14px 18px; border-left: 4px solid var(--report-accent); background: #faf7ef; color: #5e532f; }}
    code {{ padding: 1px 6px; background: #f1f4f7; border-radius: 4px; font-family: "Cascadia Code", "Consolas", monospace; }}
    pre {{ padding: 14px 16px; overflow-x: auto; background: #f5f7fa; border: 1px solid var(--report-border); border-radius: 10px; }}
    hr {{ border: 0; border-top: 1px solid var(--report-border); margin: 30px 0; }}
    ul {{ padding-left: 20px; }}
    ol {{ padding-left: 20px; }}
    {cover_css}
    @page {{ size: A4; margin: 12mm; }}
  </style>
</head>
<body>
<div class="page">
  <main>
    {cover_markup}
    <div class="content">
      {body}
    </div>
  </main>
</div>
</body>
</html>
"""


@dataclass(frozen=True)
class ExportResult:
    path: Path
    status: str
    message: str


def export_pdf_from_html(html_path: Path, pdf_path: Path) -> ExportResult:
    """从 HTML 导出 PDF。支持 weasyprint 或 wkhtmltopdf，缺失时返回 skipped。"""
    wkhtmltopdf_candidates = [
        shutil.which("wkhtmltopdf"),
        r"C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe",
        r"C:\Program Files (x86)\wkhtmltopdf\bin\wkhtmltopdf.exe",
    ]
    for candidate in wkhtmltopdf_candidates:
        if candidate and Path(candidate).exists():
            try:
                subprocess.run([candidate, str(html_path), str(pdf_path)], check=True, capture_output=True, text=True)
                return ExportResult(pdf_path, "ok", f"wkhtmltopdf ({candidate})")
            except Exception as exc:
                wkhtml_error = f"wkhtmltopdf failed: {type(exc).__name__}: {exc}"
                break
    else:
        wkhtml_error = "wkhtmltopdf not found"

    try:
        from weasyprint import HTML  # type: ignore

        HTML(filename=str(html_path)).write_pdf(str(pdf_path))
        return ExportResult(pdf_path, "ok", "weasyprint")
    except Exception as exc:
        weasy_error = f"{type(exc).__name__}: {exc}"
    return ExportResult(
        pdf_path,
        "skipped",
        f"未找到可用 PDF 后端；wkhtmltopdf: {wkhtml_error}；weasyprint: {weasy_error}",
    )


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
