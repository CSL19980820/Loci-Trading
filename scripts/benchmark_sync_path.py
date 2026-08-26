r"""线上同步路径基线：用真实 router / store 代码路径跑 sync_quotes。

为了不污染生产库，种一个临时库（instruments + 近窗日 K 从真实库复制），
再跑真实 ``sync_quotes``。测的是生产代码路径本身的吞吐。
"""
from __future__ import annotations

import argparse
import random
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _copy(src, dst, table, where="", params=()):
    """按目标库列名显式取数——真实库经过 ALTER 迁移，列序与新建库不同。"""
    cols = [r[1] for r in dst.execute("PRAGMA table_info(%s)" % table)]
    names = ", ".join(cols)
    rows = src.execute("SELECT %s FROM %s %s" % (names, table, where), params).fetchall()
    if rows:
        dst.executemany(
            "INSERT OR REPLACE INTO %s (%s) VALUES (%s)"
            % (table, names, ",".join("?" * len(cols))),
            rows,
        )
    return len(rows)


def seed_temp_db(codes, lookback_days=400):
    """从真实库复制这些票的近窗日 K + instruments 到临时库。"""
    from src.market import MarketStore
    from src.shared import paths
    
    src_path = Path(paths.market_db())
    tmp_dir = Path(tempfile.mkdtemp(prefix="loci-syncbench-"))
    dst_path = tmp_dir / "market.db"
    store = MarketStore(dst_path)
    store.close()
    
    src = sqlite3.connect("file:%s?mode=ro" % src_path.as_posix(), uri=True, timeout=60)
    dst = sqlite3.connect(dst_path.as_posix(), timeout=60)
    try:
        rows = src.execute(
            "SELECT trade_date FROM trading_calendar ORDER BY trade_date DESC LIMIT ?",
            (lookback_days,),
        ).fetchall()
        days = [str(r[0]) for r in rows]
        start, end = min(days), max(days)
        placeholders = ",".join("?" * len(codes))
        ncal = _copy(src, dst, "trading_calendar", "WHERE trade_date >= ?", (start,))
        nins = _copy(
            src, dst, "instruments", "WHERE instrument_type IN ('STOCK', 'INDEX')"
        )
        nq = _copy(
            src,
            dst,
            "quotes_daily",
            "WHERE trade_date >= ? AND trade_date <= ? AND code IN (%s)" % placeholders,
            [start, end] + list(codes),
        )
        nm = _copy(
            src, dst, "ingest_watermark",
            "WHERE code IN (%s)" % placeholders, list(codes),
        )
        dst.commit()
        print("  种库: %d 票 / 日 K %d 行 / 标的 %d / 日历 %d / 水位 %d"
              % (len(codes), nq, nins, ncal, nm))
    finally:
        src.close()
        dst.close()
    return tmp_dir, dst_path


def pick_codes(n, seed=31):
    from src.shared import paths
    
    conn = sqlite3.connect(
        "file:%s?mode=ro" % Path(paths.market_db()).as_posix(), uri=True, timeout=30
    )
    try:
        rows = conn.execute(
            "SELECT code FROM instruments WHERE instrument_type='STOCK' ORDER BY code"
        ).fetchall()
    finally:
        conn.close()
    codes = [str(r[0]) for r in rows]
    rng = random.Random(seed)
    rng.shuffle(codes)
    return sorted(codes[:n])


def run_sync(db_path, codes, workers, interval, force, with_factors, with_spot):
    from src.market import MarketStore
    from src.market.infrastructure.sync import sync_quotes
    
    started = time.perf_counter()
    report = sync_quotes(
        lambda: MarketStore(db_path),
        codes,
        workers=workers,
        min_interval=interval,
        force=force,
        with_factors=with_factors,
        with_today_spot=with_spot,
    )
    wall = time.perf_counter() - started
    return report, wall


def main():
    parser = argparse.ArgumentParser(description="线上同步路径基线")
    parser.add_argument("--codes", type=int, default=40)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--interval", type=float, default=0.15)
    parser.add_argument("--force", action="store_true", help="全量重拉")
    parser.add_argument("--factors", action="store_true", help="同时刷复权因子")
    parser.add_argument("--spot", action="store_true", help="同时补当日 spot")
    parser.add_argument("--keep", action="store_true", help="保留临时库")
    args = parser.parse_args()
    
    codes = pick_codes(args.codes)
    print("=" * 74)
    print("线上 sync_quotes 基线  票=%d workers=%d interval=%.3f force=%s "
          "factors=%s spot=%s"
          % (len(codes), args.workers, args.interval, args.force, args.factors, args.spot))
    print("=" * 74)
    
    tmp_dir, db_path = seed_temp_db(codes)
    try:
        report, wall = run_sync(
            db_path, codes, args.workers, args.interval,
            args.force, args.factors, args.spot,
        )
        rate = report.succeeded / wall if wall > 0 else 0.0
        universe = 5544
        print("\n结果:")
        print("  成功 %d / 跳过 %d / 失败 %d" % (report.succeeded, report.skipped, report.failed))
        print("  写入行数 %d" % report.rows_written)
        print("  墙钟 %.2fs  → %.2f 票/秒" % (wall, rate))
        if rate > 0:
            proj = universe / rate
            print("  折算全市场 %d 只: %.0fs (%.1f 分钟)" % (universe, proj, proj / 60))
        if report.selected_sources:
            print("  命中源: %s" % report.selected_sources)
        if report.failures:
            print("  失败样例:")
            for code, msg in report.failures[:5]:
                print("    %s %s" % (code, str(msg)[:110]))
    finally:
        if args.keep:
            print("\n临时库保留: %s" % tmp_dir)
        else:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
