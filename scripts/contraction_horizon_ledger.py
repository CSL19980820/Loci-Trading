"""All contraction signals, equal notional per signal, fixed trading-day horizons.

No portfolio engine, occupancy, fill/limit filters, stops, or compounding.
T is selection day. Entry is T+1 OPEN; independent marks are T+2/3/4 CLOSE.
Missing/non-traded fixed-date bars remain in the ledger with explicit status.
Source selection is frozen from the preceding study, never its accepted trades.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from math import isfinite
from pathlib import Path
import sqlite3

import numpy as np
import pandas as pd

from scripts.wechat_four_patterns_research import (
    DEFAULT_OUT as SOURCE, ROOT, load_snapshot, save_json, sha,
)
from src.strategy.application.wechat_four_patterns import WechatFourPatternsStrategy

OUT = ROOT / "data/research_runs/contraction_horizon_20260928"
HORIZONS = (2, 3, 4)
COST_PCT = 0.26
NOTIONAL = 10000.0


def positive(value: object) -> bool:
    return isinstance(value, (int, float, np.number)) and isfinite(float(value)) and float(value) > 0


def clean_number(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float, np.number)) and isfinite(float(value)) else None


def build_ledger(picks: pd.DataFrame, panels: dict[str, pd.DataFrame], calendar: list[str],
                 notional: float = NOTIONAL, cost_pct: float = COST_PCT) -> list[dict]:
    if not positive(notional) or not isfinite(cost_pct) or cost_pct < 0:
        raise ValueError("invalid notional/cost")
    if calendar != sorted(set(calendar)):
        raise ValueError("market calendar must be sorted and unique")
    if picks.duplicated(["signal_date", "code"]).any():
        raise ValueError("duplicate code on same signal day")
    if picks.groupby("signal_date").size().max() > 2:
        raise ValueError("daily shortlist exceeds two")
    ordered = picks.sort_values(["signal_date", "rank", "code"], kind="stable")
    positions = {day: i for i, day in enumerate(calendar)}
    cumulative = {h: 0.0 for h in HORIZONS}
    rows = []
    for item in ordered.itertuples(index=False):
        if item.signal_date not in positions:
            raise ValueError(f"signal day missing from market calendar: {item.signal_date}")
        offset = positions[item.signal_date]
        if offset + 4 >= len(calendar):
            raise ValueError("calendar must include four outcome sessions after last signal")
        code = str(item.code)
        def value(field: str, day: str) -> float | None:
            panel = panels[field]
            return clean_number(panel.at[day, code]) if day in panel.index and code in panel.columns else None
        entry_day = calendar[offset + 1]
        entry = value("open", entry_day)
        ef = value("__adjust_factor", entry_day)
        entry_ok = positive(entry) and positive(ef) and positive(value("volume", entry_day))
        row = {"id": len(rows) + 1, "signal_date": item.signal_date, "rank": int(item.rank),
               "code": code, "name": str(item.name), "signal_close": value("close", item.signal_date),
               "entry_date": entry_day, "entry_open": entry, "entry_factor": ef,
               "entry_status": "ok" if entry_ok else "missing_or_nontraded_entry", "notional": notional}
        for h in HORIZONS:
            day = calendar[offset + h]
            close, factor = value("close", day), value("__adjust_factor", day)
            mark_ok = positive(close) and positive(factor) and positive(value("volume", day))
            valid = entry_ok and mark_ok
            gross = (close * factor / (entry * ef) - 1) * 100 if valid else None
            raw_return = (close / entry - 1) * 100 if valid else None
            net = gross - cost_pct if valid else None
            if valid:
                cumulative[h] += gross
            prefix = f"t{h}_"
            row.update({prefix + "date": day, prefix + "close": close, prefix + "factor": factor,
                        prefix + "gross_pct": gross, prefix + "raw_price_pct": raw_return,
                        prefix + "net_pct": net, prefix + "gross_pnl": notional * gross / 100 if valid else None,
                        prefix + "cumulative_gross_pnl": notional * cumulative[h] / 100,
                        prefix + "cumulative_sum_pp": cumulative[h],
                        prefix + "adjustment_changed": bool(valid and not np.isclose(factor, ef, rtol=1e-12)),
                        prefix + "status": "ok" if valid else ("missing_or_nontraded_exit" if entry_ok else row["entry_status"])})
        rows.append(row)
    return rows


def summarize(rows: list[dict], period: str) -> list[dict]:
    result = []
    for h in HORIZONS:
        valid = [x for x in rows if x[f"t{h}_gross_pct"] is not None]
        g = np.array([x[f"t{h}_gross_pct"] for x in valid], dtype=float)
        n = np.array([x[f"t{h}_net_pct"] for x in valid], dtype=float)
        result.append({"period": period, "horizon": f"T+{h}", "signals": len(rows), "valid": len(valid),
                       "missing": len(rows) - len(valid), "mean_gross_pct": float(g.mean()) if len(g) else None,
                       "median_gross_pct": float(np.median(g)) if len(g) else None,
                       "mean_net_pct": float(n.mean()) if len(n) else None,
                       "wins": int((g > 1e-10).sum()), "losses": int((g < -1e-10).sum()),
                       "flat": int((abs(g) <= 1e-10).sum()),
                       "win_rate_pct": float((g > 1e-10).mean() * 100) if len(g) else None,
                       "net_win_rate_pct": float((n > 1e-10).mean() * 100) if len(n) else None,
                       "sum_gross_pp": float(g.sum()),
                       "equal_notional_gross_pnl": float(sum(x[f"t{h}_gross_pnl"] for x in valid)),
                       "equal_notional_net_pnl": float(sum(x["notional"] * x[f"t{h}_net_pct"] / 100 for x in valid)),
                       "total_allocated_notional": float(sum(x["notional"] for x in valid)),
                       "best_pct": float(g.max()) if len(g) else None, "worst_pct": float(g.min()) if len(g) else None,
                       "adjustment_changed_count": sum(x[f"t{h}_adjustment_changed"] for x in valid)})
    return result


def extend_tail(out: Path, raw: dict[str, pd.DataFrame], codes: list[str], database: Path) -> tuple[dict, list[str], str]:
    path = out / "tail_inputs.json"
    last = raw["close"].index[-1]
    if path.exists():
        tail = json.loads(path.read_text(encoding="utf-8"))
        if tail["after"] != last or tail["codes"] != codes:
            raise ValueError("tail cache belongs to different source/codes")
    else:
        con = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
        con.execute("PRAGMA query_only=ON")
        con.execute("BEGIN")
        try:
            dates = [r[0] for r in con.execute("SELECT trade_date FROM trading_calendar WHERE trade_date>? ORDER BY trade_date LIMIT 4", (last,))]
            if len(dates) != 4:
                raise ValueError("four market sessions required after snapshot end")
            placeholders = ",".join("?" for _ in codes)
            quote_columns = ["trade_date", "code", "open", "close", "volume", "source", "fetched_at"]
            quotes = con.execute(f"SELECT {','.join(quote_columns)} FROM quotes_daily WHERE trade_date>? AND trade_date<=? AND code IN ({placeholders}) ORDER BY trade_date,code", [last, dates[-1], *codes]).fetchall()
            fac = con.execute(f"SELECT trade_date,code,hfq_factor FROM adjust_factors WHERE trade_date>? AND trade_date<=? AND code IN ({placeholders}) ORDER BY trade_date,code", [last, dates[-1], *codes]).fetchall()
            coverage = con.execute("SELECT trade_date,count(*) FROM quotes_daily WHERE trade_date>? AND trade_date<=? GROUP BY trade_date", (last, dates[-1])).fetchall()
            if len(coverage) != 4 or min(x[1] for x in coverage) < 1000:
                raise ValueError("tail sessions lack broad market coverage")
        finally:
            con.rollback()
            con.close()
        tail = {"captured_at": datetime.now(timezone.utc).isoformat(), "after": last, "codes": codes,
                "calendar": dates, "quote_columns": quote_columns, "quotes": quotes,
                "factor_events": fac, "coverage": coverage, "usage": "outcome prices only; cannot change frozen signals"}
        save_json(path, tail)
    dates = tail["calendar"]
    calendar = list(raw["close"].index) + dates
    execution = {k: frame.reindex(index=calendar, columns=codes).copy() for k, frame in raw.items() if k in ("open", "close", "volume", "__adjust_factor")}
    for quote in tail["quotes"]:
        day, code, op, cl, vol = quote[:5]
        for key, val in (("open", op), ("close", cl), ("volume", vol)):
            execution[key].at[day, code] = val
    for day, code, factor in tail["factor_events"]:
        # Factors on non-session dates still become effective by the next session.
        future = [d for d in dates if d >= day]
        if future:
            execution["__adjust_factor"].at[future[0], code] = factor
    execution["__adjust_factor"] = execution["__adjust_factor"].ffill()
    return execution, calendar, sha(path)


def markdown_report(payload: dict) -> str:
    rows, meta = payload["rows"], payload["meta"]
    lines = ["# 缩量确认：全信号等额独立收益明细", "",
             "T日选出，T+1开盘买入，分别按T+2、T+3、T+4收盘价观察。三个窗口是三个替代卖出方案。", "",
             f"选股观察期2025-01-02—2026-08-31；{len(rows)}条信号，{meta['unique_stocks']}只不同股票，{meta['active_days']}个有信号日。每个信号独立投入同额，不因重复股票、持仓重叠或资金占用排除。未实施止损、止盈、涨跌停成交约束或资金账户复利。", "",
             "T+n按市场交易日推进；尾部仅补入2026-09-01—09-04结果行情，不扩展选股样本。主收益为复权因子校正的毛收益；金额为原始价格。星号表示买入与卖出之间复权因子变化。费用参考统一扣0.26个百分点，仅在汇总和CSV的净收益栏列出。", "",
             "等额汇总采用每个信号等权算术平均。累计金额按每笔1万元直接相加；累计百分数为收益百分点之和，不是可实现账户回报。", "",
             "## 全期汇总", "", "| 卖出窗口 | 样本数 | 平均毛收益 | 平均净收益 | 毛收益胜率 | 每笔1万元累计毛盈亏 |", "|---|---:|---:|---:|---:|---:|"]
    for x in payload["summary"][:3]:
        lines.append(f"| {x['horizon']} | {x['valid']} | {x['mean_gross_pct']:+.4f}% | {x['mean_net_pct']:+.4f}% | {x['win_rate_pct']:.2f}% | {x['equal_notional_gross_pnl']:+,.2f}元 |")
    month = None
    for r in rows:
        if month != r["signal_date"][:7]:
            month = r["signal_date"][:7]
            lines += ["", f"## {month}", "", "| 序号 | T选股日/顺位 | 股票 | T+1买入日/开盘 | T+2卖出日/收盘/毛收益 | T+3卖出日/收盘/毛收益 | T+4卖出日/收盘/毛收益 |", "|---:|---|---|---|---|---|---|"]
        fields = [str(r["id"]), f"{r['signal_date']} / {r['rank']}", f"{r['name']}（{r['code']}）", f"{r['entry_date']} / {r['entry_open']:.2f}" if r['entry_open'] else f"{r['entry_date']} / 缺失"]
        for h in HORIZONS:
            ret, close = r[f"t{h}_gross_pct"], r[f"t{h}_close"]
            fields.append(f"{r[f't{h}_date']} / {close:.2f} / {ret:+.2f}%" + ("*" if r[f't{h}_adjustment_changed'] else "") if ret is not None else f"{r[f't{h}_date']} / {r[f't{h}_status']}")
        lines.append("| " + " | ".join(fields) + " |")
    lines += ["", "## 计算与来源", "", "毛收益 = (卖出原始收盘×卖出日因子)/(买入原始开盘×买入日因子) - 1；净收益=毛收益-0.26%。价差收益另存CSV。复权因子变化的记录可核对CSV。", "",
              "名单沿用上一轮contraction_picks.csv和原排序：每条都必须通过缩量支撑确认，排序仍保留原来的多形态重合评分。本次不重新调参，不引入其他形态独立候选。", "",
              "历史股票状态不完整、当前股票池和代理成交额等前轮数据限制仍在。本表是全信号固定时点观察，不是账户实盘回放。缺失/无交易量价格不递延替代。", "",
              f"原快照SHA256：`{meta['source_snapshot_sha256']}`；名单SHA256：`{meta['source_picks_sha256']}`；尾部输入SHA256：`{meta['tail_sha256']}`。", "",
              "复现：`.\\.venv\\Scripts\\python.exe -m scripts.contraction_horizon_ledger --replay`。所有逐条计算保存在ledger.json和逐只收益明细.csv。"]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--database", type=Path, default=ROOT / "data/market.db")
    parser.add_argument("--replay", action="store_true")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    old = json.loads((out / "ledger.json").read_text(encoding="utf-8")) if args.replay else None
    picks_path = SOURCE / "contraction_picks.csv"
    picks = pd.read_csv(picks_path, dtype={"code": str}, float_precision="round_trip")
    raw, adjusted, _ = load_snapshot(SOURCE)
    engine = WechatFourPatternsStrategy()
    result = engine.compute(adjusted, {"pattern": "contraction"})
    expected = {(str(day), str(code)) for day, row in result.signals.loc["2025-01-01":"2026-08-31"].iterrows() for code in row.index[row]}
    observed = set(zip(picks.signal_date, picks.code))
    if expected != observed or len(observed) != len(picks):
        raise ValueError("frozen contraction shortlist differs from recomputed selection")
    panels, calendar, tail_hash = extend_tail(out, raw, sorted(picks.code.unique().tolist()), args.database)
    rows = build_ledger(picks, panels, calendar)
    summaries = summarize(rows, "全期")
    for year in ("2025", "2026"):
        summaries += summarize([r for r in rows if r["signal_date"].startswith(year)], year)
    monthly = []
    for month in sorted({r["signal_date"][:7] for r in rows}):
        monthly += summarize([r for r in rows if r["signal_date"].startswith(month)], month)
    meta = {"method": "equal_notional_independent_signal_horizons_v1", "signal_window": ["2025-01-02", "2026-08-31"],
            "signal_first": rows[0]["signal_date"], "signal_last": rows[-1]["signal_date"],
            "signal_count": len(rows), "unique_stocks": len({r['code'] for r in rows}),
            "active_days": len({r['signal_date'] for r in rows}), "max_daily": max(Counter(r['signal_date'] for r in rows).values()),
            "outcome_end": calendar[-1], "equal_notional": NOTIONAL, "cost_pct": COST_PCT,
            "source_snapshot_sha256": sha(SOURCE / "snapshot.npz"), "source_picks_sha256": sha(picks_path),
            "tail_sha256": tail_hash, "entry": "T+1 open", "exits": ["T+2 close", "T+3 close", "T+4 close"],
            "stock_status": "current metadata, not historical PIT", "all_signals_kept": True,
            "occupancy_filters": False, "limit_fill_filters": False, "stops": False, "compound_returns": False}
    payload = {"meta": meta, "summary": summaries, "monthly": monthly, "rows": rows}
    if old is not None and old != payload:
        raise ValueError("replay differs; old results retained")
    save_json(out / "ledger.json", payload)
    pd.DataFrame(rows).to_csv(out / "逐只收益明细.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(summaries).to_csv(out / "收益汇总.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(monthly).to_csv(out / "分月统计.csv", index=False, encoding="utf-8-sig")
    (out / "缩量确认_逐只收益明细.md").write_text(markdown_report(payload), encoding="utf-8")
    audit = {"checked_at": datetime.now(timezone.utc).isoformat(), "recomputed_shortlist_exact_match": True,
             "input_records": len(picks), "output_records": len(rows), "output_cells": len(rows) * 3,
             "max_daily": meta["max_daily"], "missing": {str(h): sum(r[f"t{h}_gross_pct"] is None for r in rows) for h in HORIZONS},
             "corporate_action_counts": {str(h): sum(r[f"t{h}_adjustment_changed"] for r in rows) for h in HORIZONS},
             "replay_passed": bool(args.replay), "script_sha256": sha(Path(__file__))}
    save_json(out / "audit.json", audit)
    print(json.dumps({"meta": meta, "summary": summaries, "audit": audit, "first_two": rows[:2], "last_two": rows[-2:]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
