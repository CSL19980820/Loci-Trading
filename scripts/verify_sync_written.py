"""End-to-end correctness: what sync_quotes wrote vs what the source says.

Seeds a temp DB from the real one, runs the real sync, then re-reads the same
codes straight from TDX and compares every OHLCV grid point.
"""
from __future__ import annotations

import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.benchmark_sync_path import pick_codes, run_sync, seed_temp_db  # noqa: E402


def compare(conn, code, fresh):
    """逐日比对库内落盘值与源侧复查值。返回 (格点, 价格坏, 量坏, 缺日, 样例)。"""
    rows = conn.execute(
        "SELECT trade_date, open, high, low, close, volume FROM quotes_daily"
        " WHERE code = ? AND trade_date >= ?",
        (code, str(fresh["date"].iloc[0])),
    ).fetchall()
    stored = {str(r[0]): r for r in rows}
    checked = bad_price = bad_vol = missing = 0
    samples = []
    for rec in fresh.to_dict("records"):
        day = str(rec["date"])
        row = stored.get(day)
        if row is None:
            missing += 1
            samples.append("%s %s 库内缺该日" % (code, day))
            continue
        checked += 1
        for idx, field in enumerate(("open", "high", "low", "close"), start=1):
            want = float(rec[field])
            got = float(row[idx] or 0)
            if want and abs(got - want) / want > 1e-6:
                bad_price += 1
                samples.append("%s %s %s db=%s src=%s" % (code, day, field, got, want))
        want_vol = float(rec["volume"])
        got_vol = float(row[5] or 0)
        if want_vol and abs(got_vol - want_vol) / want_vol > 1e-6:
            bad_vol += 1
            samples.append("%s %s volume db=%s src=%s" % (code, day, got_vol, want_vol))
    return checked, bad_price, bad_vol, missing, samples


def main() -> int:
    codes = pick_codes(25, seed=77)
    tmp_dir, db_path = seed_temp_db(codes)
    try:
        report, wall = run_sync(db_path, codes, 12, 0.02, False, False, False)
        print("同步：成功 %d / 失败 %d / %.2fs" % (report.succeeded, report.failed, wall))

        from src.market.infrastructure.tdx_daily import fetch_daily_bars

        conn = sqlite3.connect(db_path.as_posix(), timeout=60)
        totals = [0, 0, 0, 0]
        samples = []
        for code in codes:
            try:
                fresh = fetch_daily_bars(code, bars=30)
            except Exception as exc:
                print("  %s 源侧复查失败 %s" % (code, type(exc).__name__))
                continue
            got = compare(conn, code, fresh)
            for i in range(4):
                totals[i] += got[i]
            samples.extend(got[4])
        conn.close()
        print("\n落盘校验：")
        print("  比对格点 %d" % totals[0])
        print("  价格不符 %d" % totals[1])
        print("  成交量不符 %d" % totals[2])
        print("  库内缺日 %d" % totals[3])
        for line in samples[:10]:
            print("   %s" % line)
        return 0 if (totals[1] == 0 and totals[2] == 0) else 1
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())

if __name__ == "__main__":
    raise SystemExit(main())
