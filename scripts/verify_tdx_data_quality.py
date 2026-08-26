r"""通达信 TDX 数据质量与覆盖验证：字段、精度、全市场覆盖、复权口径。

对照真实 market.db 已落盘日 K，逐票逐日比对 OHLCV，给出偏差分布。
"""
from __future__ import annotations

import random
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.benchmark_data_sources import tdx_conn, tdx_market  # noqa: E402


def db_path():
    from src.shared import paths
    
    return Path(paths.market_db())


def tdx_bars(code, count=400):
    api = tdx_conn()
    return api.get_security_bars(9, tdx_market(code), code, 0, count) or []


def show_fields():
    rows = tdx_bars("600000", 3)
    print("TDX 日线字段:")
    for key in sorted(rows[0]):
        print("   %-16s %s" % (key, rows[0][key]))
    return sorted(rows[0])


def coverage_check(conn):
    """TDX 能否覆盖库内全部标的（含北交所/科创板）。"""
    rows = conn.execute(
        "SELECT code FROM instruments WHERE instrument_type='STOCK' ORDER BY code"
    ).fetchall()
    codes = [str(r[0]) for r in rows]
    buckets = {}
    for code in codes:
        buckets.setdefault(code[:2], []).append(code)
    print("\n库内板块分布 (前缀 -> 只数):")
    for prefix in sorted(buckets):
        print("   %s  %d" % (prefix, len(buckets[prefix])))
    print("\nTDX 覆盖抽检 (每个前缀抽 3 只):")
    missing = []
    rng = random.Random(11)
    for prefix in sorted(buckets):
        picks = rng.sample(buckets[prefix], min(3, len(buckets[prefix])))
        got = []
        for code in picks:
            try:
                bars = tdx_bars(code, 5)
            except Exception as exc:
                bars = []
                print("   %s %s ERR %s" % (prefix, code, type(exc).__name__))
            got.append(len(bars))
            if not bars:
                missing.append(code)
        print("   %s  %s -> %s" % (prefix, picks, got))
    return missing


def accuracy_check(conn, sample=25, days=120):
    """逐票逐日比对 TDX 与库内已落盘 OHLCV，报偏差。"""
    rows = conn.execute(
        "SELECT code FROM instruments WHERE instrument_type='STOCK' ORDER BY code"
    ).fetchall()
    codes = [str(r[0]) for r in rows]
    rng = random.Random(23)
    picks = rng.sample(codes, min(sample, len(codes)))
    stats = {"cmp": 0, "px_bad": 0, "vol_bad": 0, "amt_bad": 0, "missing_db": 0}
    worst = []
    for code in picks:
        try:
            bars = tdx_bars(code, days)
        except Exception as exc:
            print(" %s TDX 取数失败 %s" % (code, type(exc).__name__))
            continue
        if not bars:
            continue
        tdx_map = {}
        for bar in bars:
            day = str(bar.get("datetime") or "")[:10].replace("/", "-")
            tdx_map[day] = bar
        db_rows = conn.execute(
            "SELECT trade_date, open, high, low, close, volume, amount FROM quotes_daily "
            "WHERE code = ? AND trade_date >= ? AND trade_date <= ? ORDER BY trade_date",
            (code, min(tdx_map), max(tdx_map)),
        ).fetchall()
        if not db_rows:
            stats["missing_db"] += 1
            continue
        for day, o, h, low_, c, vol, amt in db_rows:
            bar = tdx_map.get(str(day)[:10])
            if not bar:
                continue
            stats["cmp"] += 1
            for label, dbv, tv in (
                ("open", o, bar.get("open")), ("high", h, bar.get("high")),
                ("low", low_, bar.get("low")), ("close", c, bar.get("close")),
            ):
                if dbv is None or tv is None or not float(dbv):
                    continue
                rel = abs(float(tv) - float(dbv)) / max(abs(float(dbv)), 1e-9)
                if rel > 0.005:
                    stats["px_bad"] += 1
                    if len(worst) < 12:
                        worst.append((code, day, label, float(dbv), float(tv), round(rel, 4)))
            tvol = bar.get("vol")
            if vol and tvol:
                ratio = float(tvol) / max(float(vol), 1e-9)
                if not (0.9 < ratio < 1.1 or 90 < ratio < 110 or 0.009 < ratio < 0.011):
                    stats["vol_bad"] += 1
                    if len(worst) < 24:
                        worst.append((code, day, "vol_ratio", float(vol), float(tvol), round(ratio, 4)))
            tamt = bar.get("amount")
            if amt and tamt:
                ratio = float(tamt) / max(float(amt), 1e-9)
                if not 0.95 < ratio < 1.05:
                    stats["amt_bad"] += 1
                    if len(worst) < 36:
                        worst.append((code, day, "amt_ratio", float(amt), float(tamt), round(ratio, 4)))
    print("\n精度比对 (样本 %d 只 x %d 根):" % (len(picks), days))
    print("   比对格点 %d" % stats["cmp"])
    print("   价格偏差 >0.5%%: %d" % stats["px_bad"])
    print("   量比异常     : %d" % stats["vol_bad"])
    print("   额比异常     : %d" % stats["amt_bad"])
    print("   库内无数据票 : %d" % stats["missing_db"])
    if worst:
        print("   样例:")
        for item in worst[:16]:
            print("   %s %s %-10s db=%-14s tdx=%-14s r=%s" % item)
    return stats


def depth_check():
    """TDX 单票最深能翻多少历史（分页回溯）。"""
    api = tdx_conn()
    code = "600000"
    total = 0
    start = 0
    earliest = None
    began = time.perf_counter()
    while True:
        page = api.get_security_bars(9, 1, code, start, 800)
        if not page:
            break
        total += len(page)
        earliest = str(page[0].get("datetime") or "")[:10]
        start += len(page)
        if len(page) < 800 or start > 12000:
            break
    print("\n历史深度 600000: %d 根, 最早 %s, 翻页耗时 %.2fs"
          % (total, earliest, time.perf_counter() - began))
    return total, earliest


def main():
    path = db_path()
    conn = sqlite3.connect("file:%s?mode=ro" % path.as_posix(), uri=True, timeout=30)
    try:
        show_fields()
        missing = coverage_check(conn)
        print("\n抽检未覆盖: %s" % (missing or "无"))
        depth_check()
        accuracy_check(conn)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
