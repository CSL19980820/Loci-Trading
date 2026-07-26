"""A 股个股持仓分析工具 - 主入口

用法:
    python analyze.py 002460 --cost 84.363 --shares 600
    python analyze.py 600519 --cost 1800 --shares 100 --days 120

参数:
    code          股票代码 (6位数字, 必填位置参数)
    --cost        持仓成本价 (必填)
    --shares      持仓股数 (必填)
    --days        K线回看天数 (默认 90)
    --output      输出根目录 (默认 ./output)
    --formats     输出格式: md,html,pdf,json,csv,all (默认 md,json,csv)
    --portfolio-csv  持仓 CSV, 用于组合分析
    --online-evidence Codex 在线核验证据 JSON
    --cover-image PDF/HTML 封面图资产
    --name        股票名称 (可选, 不传会自动获取)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from src.fetcher import StockFetcher
from src.indicators import (
    add_all_indicators, breakeven_probability, calc_chip_distribution,
    calc_volatility, calc_vwap,
)
from src.strategy import (
    analyze_fund_flow, classify_trend, diagnose_position,
    generate_strategies, identify_key_levels, recommend_scheme,
)
from src.toolbox import (
    analyze_portfolio,
    build_ai_context,
    build_buy_check,
    build_risk_radar,
    export_pdf_from_html,
    load_online_evidence,
    load_portfolio,
    render_html_document,
    write_json,
)
from src.reporter import ReportRenderer


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="A 股个股持仓分析工具 - 生成 Markdown 决策报告",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("code", help="股票代码 (6位数字)")
    p.add_argument("--cost", type=float, required=True, help="持仓成本价 (元/股)")
    p.add_argument("--shares", type=int, required=True, help="持仓股数")
    p.add_argument("--days", type=int, default=90, help="K线回看天数")
    p.add_argument("--output", default=str(HERE / "output"), help="输出根目录")
    p.add_argument("--name", default=None, help="股票名称 (不传会自动识别)")
    p.add_argument("--kline-csv", default=None,
                   help="离线模式: 从本地 CSV 读取 K 线 (网络不可用时使用)")
    p.add_argument("--portfolio-csv", default=None,
                   help="持仓组合 CSV: code,name,cost,shares,current_price")
    p.add_argument("--formats", default="md,json,csv",
                   help="输出格式, 逗号分隔: md,html,pdf,json,csv,all")
    p.add_argument("--online-evidence", default=None,
                   help="Codex 在线核验证据 JSON, 格式见 examples/online_evidence.sample.json")
    p.add_argument("--cover-image", default=None,
                   help="PDF/HTML 封面图路径, 默认可使用 assets/report-cover.png")
    p.add_argument("--evidence-only", action="store_true",
                   help="允许无真实 K 线时仅依据在线核验证据输出证据版报告")
    return p.parse_args()


def parse_formats(raw: str) -> set[str]:
    formats = {x.strip().lower() for x in raw.split(",") if x.strip()}
    if "all" in formats:
        return {"md", "html", "pdf", "json", "csv"}
    allowed = {"md", "html", "pdf", "json", "csv"}
    unknown = formats - allowed
    if unknown:
        raise ValueError(f"未知输出格式: {', '.join(sorted(unknown))}; 可选: {', '.join(sorted(allowed))}, all")
    return formats or {"md", "json", "csv"}


def main() -> int:
    args = parse_args()
    try:
        formats = parse_formats(args.formats)
    except ValueError as exc:
        print(f"[错误] {exc}")
        return 2

    print(f"\n{'='*60}")
    print(f"  A 股持仓分析: {args.code}")
    print(f"  持仓: {args.shares} 股 × 成本 {args.cost} 元 = {args.cost*args.shares:,.2f} 元")
    print(f"{'='*60}\n")

    # 1. 数据采集
    fetcher = StockFetcher(args.code, name=args.name)
    data = fetcher.fetch_all(kline_days=args.days)

    kline = data.get("kline")

    # 离线回退: 如指定 --kline-csv 或在线 K 线失败, 从本地读取
    if (kline is None or kline.empty) and args.kline_csv:
        print(f"  [离线模式] 从本地读取 K 线: {args.kline_csv}")
        kline = StockFetcher.load_kline_from_csv(args.kline_csv)
        data["kline"] = kline

    if kline is None or kline.empty:
        if not args.evidence_only:
            print("\n[错误] K 线获取失败，拒绝生成报告。")
            print("  当前不会再用占位值伪造行情数据。")
            print("  解决方案:")
            print("    1. 提供 --kline-csv PATH 使用真实离线 K 线")
            print("    2. 显式传入 --evidence-only，仅输出在线证据版报告")
            return 1
        print("\n[提示] K 线获取失败，进入证据版报告模式。")
        print("  当前仅输出在线核验与已获取财务数据，不生成任何伪行情结论。")
        data["evidence_only"] = True
        kline = None
    else:
        data["evidence_only"] = False

    if not data.get("name"):
        data["name"] = args.name or args.code

    # 2. 技术指标
    print("  -> 计算技术指标 ...")
    if kline is not None and not kline.empty:
        kline = add_all_indicators(kline)
        vwap30 = calc_vwap(kline, days=30)
        chip_dist = calc_chip_distribution(kline, days=30)
        vol = calc_volatility(kline, days=min(60, len(kline)))
    else:
        vwap30 = None
        chip_dist = pd.DataFrame(columns=["价格区间", "成交量", "占比"])
        vol = {"daily_vol": None, "annual_vol": None, "recent_drift": None}

    # 3. 持仓诊断 + 策略
    print("  -> 持仓诊断 + 策略生成 ...")
    if kline is not None and not kline.empty:
        position = diagnose_position(args.cost, args.shares, kline)
        levels = identify_key_levels(kline, args.cost)
        trend = classify_trend(kline)
    else:
        position = {
            "current": None,
            "cost": args.cost,
            "shares": args.shares,
            "total_cost": args.cost * args.shares,
            "market_value": None,
            "pnl": None,
            "pnl_pct": None,
            "need_up_pct": None,
            "cost_percentile_90d": None,
            "level": "待核验",
        }
        levels = {
            "current": None, "cost": args.cost, "MA5": None, "MA10": None, "MA20": None, "MA60": None,
            "BOLL_UP": None, "BOLL_DN": None, "d30_high": None, "d30_low": None, "d60_high": None, "d60_low": None,
            "recommend_stop_loss": None, "recommend_take_profit": None,
        }
        trend = {"trend": "unknown", "strength": "unknown", "macd_signal": "unknown"}
    fund_stance = analyze_fund_flow(data.get("fund_flow"), days=5)
    if position["current"] is not None and vol["daily_vol"] is not None:
        probs = breakeven_probability(
            current=position["current"],
            target=position["cost"],
            daily_vol=vol["daily_vol"],
            daily_drift=vol["recent_drift"] or 0.0,
        )
        strategies = generate_strategies(position, levels, trend)
        recommended = recommend_scheme(position, trend, fund_stance)
        buy_check = build_buy_check(position, levels, trend, fund_stance, vol, kline)
    else:
        probs = []
        strategies = []
        recommended = "待补齐真实 K 线后再运行规则观察"
        buy_check = {
            "score": None,
            "max_score": None,
            "score_pct": None,
            "grade": "待真实行情",
            "checks": [],
            "blockers": [{"name": "真实 K 线缺失", "detail": "未取得可验证的价格时间序列，规则引擎未运行"}],
            "decision_note": "当前未取得真实 K 线，买入辅助检查未运行。",
        }
    risk_radar = build_risk_radar(position, levels, trend, fund_stance, vol, data)
    try:
        holdings = load_portfolio(
            args.portfolio_csv,
            args.code,
            data.get("name") or args.code,
            position["current"] if position["current"] is not None else args.cost,
        )
    except Exception as exc:
        print(f"\n[错误] 持仓组合 CSV 读取失败: {exc}")
        return 1
    portfolio = analyze_portfolio(holdings)
    try:
        online_evidence = load_online_evidence(args.online_evidence)
    except Exception as exc:
        print(f"\n[错误] Codex 在线核验证据读取失败: {exc}")
        return 1
    cover_image = args.cover_image
    default_cover = HERE / "assets" / "report-cover.png"
    if cover_image is None and default_cover.exists():
        cover_image = str(default_cover)
    ai_context = build_ai_context(data, position, buy_check, risk_radar, portfolio, recommended, online_evidence)

    # 4. 生成报告
    print("  -> 渲染 Markdown 报告 ...")
    renderer = ReportRenderer(template_dir=HERE / "templates")
    report_md = renderer.render_holding_report(
        data=data,
        position=position,
        levels=levels,
        trend=trend,
        fund_stance=fund_stance,
        vwap30=vwap30,
        vol=vol,
        breakeven_probs=probs,
        chip_distribution=chip_dist,
        strategies=strategies,
        recommended_scheme=recommended,
        buy_check=buy_check,
        risk_radar=risk_radar,
        portfolio=portfolio,
        ai_context=ai_context,
        online_evidence=online_evidence,
        cover_image=cover_image,
        kline=kline,
    )

    # 5. 保存
    date_str = datetime.now().strftime("%Y%m%d")
    name = data.get("name") or args.code
    out_dir = Path(args.output) / f"{args.code}_{name}_{date_str}"
    out_dir.mkdir(parents=True, exist_ok=True)

    written: list[tuple[str, Path, str]] = []
    report_path = out_dir / f"{name}持仓决策报告.md"
    if "md" in formats:
        report_path.write_text(report_md, encoding="utf-8")
        written.append(("Markdown", report_path, "ok"))

    kline_path = out_dir / "kline.csv"
    if "csv" in formats:
        kline.to_csv(kline_path, index=False, encoding="utf-8-sig")
        written.append(("K线 CSV", kline_path, "ok"))
        if portfolio.get("available"):
            portfolio_path = out_dir / "portfolio_analysis.csv"
            pd.DataFrame(portfolio["holdings"]).to_csv(portfolio_path, index=False, encoding="utf-8-sig")
            written.append(("组合 CSV", portfolio_path, "ok"))

    html_path = out_dir / f"{name}持仓决策报告.html"
    if "html" in formats or "pdf" in formats:
        html_path.write_text(render_html_document(report_md, f"{name}持仓决策报告", cover_image=cover_image), encoding="utf-8")
        written.append(("HTML", html_path, "ok"))

    if "pdf" in formats:
        pdf_path = out_dir / f"{name}持仓决策报告.pdf"
        pdf_result = export_pdf_from_html(html_path, pdf_path)
        written.append(("PDF", pdf_result.path, pdf_result.status + f" ({pdf_result.message})"))

    summary_path = out_dir / "summary.json"
    summary = {
        "code": args.code,
        "name": name,
        "query_time": data["query_time"],
        "evidence_only": data.get("evidence_only", False),
        "position": position,
        "levels": levels,
        "trend": trend,
        "fund_stance": {k: v for k, v in fund_stance.items() if isinstance(v, (int, float, str, bool))},
        "vwap30": vwap30,
        "volatility": vol,
        "breakeven_probs": probs,
        "recommended_scheme": recommended,
        "buy_check": buy_check,
        "risk_radar": risk_radar,
        "portfolio": portfolio,
        "ai_context": ai_context,
        "online_evidence": online_evidence,
        "template_id": "stock_research_final_v1",
    }
    if "json" in formats:
        write_json(summary_path, summary)
        written.append(("摘要 JSON", summary_path, "ok"))
        ai_context_path = out_dir / "ai_context.json"
        write_json(ai_context_path, ai_context)
        written.append(("AI上下文 JSON", ai_context_path, "ok"))

    print(f"\n{'='*60}")
    print(f"  报告已生成:")
    for label, path, status in written:
        print(f"  - {label}: {path} [{status}]")
    print(f"{'='*60}")
    print(f"  持仓诊断: {position['level']}")
    if position["pnl"] is not None and position["pnl_pct"] is not None:
        print(f"  浮动盈亏: {position['pnl']:+.2f} 元 ({position['pnl_pct']:+.2f}%)")
    print(f"  趋势分类: {trend['trend']} ({trend['strength']}) | MACD: {trend['macd_signal']}")
    print(f"  资金态度: {fund_stance.get('stance', '未知')}")
    score_text = f"{buy_check['score_pct']:.1f}/100" if isinstance(buy_check.get("score_pct"), (int, float)) else "未运行"
    print(f"  买入辅助: {buy_check['grade']} | {score_text}")
    print(f"  风险雷达: {risk_radar['overall']}风险 | 均分 {risk_radar['avg_score']}")
    print(f"  在线核验: {'已合并' if online_evidence.get('available') else '未提供'} | 来源 {len(online_evidence.get('sources') or [])} 条")
    if portfolio.get("available"):
        print(f"  组合分析: {portfolio['concentration']}集中度 | 总盈亏 {portfolio['total_pnl']:+,.2f} 元 ({portfolio['total_pnl_pct']:+.2f}%)")
    print(f"  规则观察: 方案 {recommended}")
    print(f"{'='*60}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
