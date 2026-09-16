r"""用权威源（通达信）全量重写生产行情库。

历史版本曾用 ``close × volume`` 合成腾讯日 K 的成交额。停止生成假值不会
自动修复已落库的历史；本脚本严格只请求通达信，保留真实来源回执。

安全性：

- 走 ``upsert``，**只覆盖不删行**：通达信不返回的老日期（如 000001 早于
  1991-04-03 的那几周）原样保留。
- 走 ``market_write_lock``，与线上调度 job 互斥，不会双写。
- 按批提交，中断前已写数据保留；重跑幂等。严格模式绕过水位，
  ``--no-force`` 仅重刷增量近窗，不代表按证券断点续跑。
- ``--dry-run`` 只统计不写。

用法（仓库根目录）::

    .\\.venv\\Scripts\\python.exe scripts\\resync_market_authoritative.py --dry-run
    .\\.venv\\Scripts\\python.exe scripts\\resync_market_authoritative.py --limit 200
    .\\.venv\\Scripts\\python.exe scripts\\resync_market_authoritative.py
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
#: 判定「这行的成交额疑似合成」的容差。腾讯合成值与 close*volume 完全相等。
#:
#: 这个判据有一层**误报底噪**：1991-92 年深市涨跌停加薄成交，一整天只成交在
#: 同一个价位是常事，那种日子真实 amount 本来就等于 close*volume（实测
#: ``000001 1991-04-23 close=45.0 vol=2800 amt=126000``）。通达信重写后这类行
#: 仍占其 0.7%%，它们是真数据不是假值。所以进度要看**来源构成**，
#: 「合成率」只在腾讯行内部看才有意义。
_SYNTH_EPSILON = 1.0

#: 会合成 amount 的源。腾讯日 K 的 amount 是 close×volume，不是真实成交额。
_FABRICATING_SOURCES = ("tencent", "tencent_spot")


def survey(db_path: Path) -> dict:
    """重同步前后都跑一次，用同一把尺子量。"""
    conn = sqlite3.connect("file:%s?mode=ro" % db_path.as_posix(), uri=True, timeout=60)
    try:
        by_source = conn.execute(
            "SELECT source, COUNT(*) FROM quotes_daily GROUP BY 1 ORDER BY 2 DESC"
        ).fetchall()
        placeholders = ",".join("?" * len(_FABRICATING_SOURCES))
        fabricated = conn.execute(
            "SELECT COUNT(*) FROM quotes_daily"
            " WHERE source IN (%s)" % placeholders
            + " AND amount IS NOT NULL AND volume > 0 AND close > 0 AND high <> low"
            "   AND ABS(amount - close*volume) < ?",
            list(_FABRICATING_SOURCES) + [_SYNTH_EPSILON],
        ).fetchone()[0]
        total = conn.execute("SELECT COUNT(*) FROM quotes_daily").fetchone()[0]
    finally:
        conn.close()
    return {
        "fabricated": fabricated,
        "total": total,
        "by_source": by_source,
    }


def print_survey(label: str, snap: dict) -> None:
    total = max(1, snap["total"])
    authoritative = sum(n for s, n in snap["by_source"] if str(s).startswith("tdx"))
    print("%s" % label)
    print(
        "  权威源(通达信)行数 %d / %d（%.1f%%）"
        % (authoritative, snap["total"], 100.0 * authoritative / total)
    )
    print(
        "  仍是合成成交额 %d 行（%.1f%%）"
        % (snap["fabricated"], 100.0 * snap["fabricated"] / total)
    )
    print("  来源构成: %s" % (snap["by_source"][:8],))

def stock_codes(db_path: Path) -> list[tuple[str, str]]:
    conn = sqlite3.connect("file:%s?mode=ro" % db_path.as_posix(), uri=True, timeout=60)
    try:
        rows = conn.execute(
            "SELECT code, instrument_type FROM instruments"
            " WHERE instrument_type IN ('STOCK','INDEX') ORDER BY code"
        ).fetchall()
    finally:
        conn.close()
    return [(str(code), str(kind)) for code, kind in rows]


def main() -> int:
    parser = argparse.ArgumentParser(description="用通达信全量重写生产行情库")
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 只（试水）")
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--interval", type=float, default=0.02)
    parser.add_argument("--chunk", type=int, default=40)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--codes",
        default="",
        help="只修这几只(逗号分隔)。定点补洞用:体检报出缺回执/假 amount 的票,"
        "不必为了十几行重扫全市场",
    )
    parser.add_argument(
        "--no-force",
        action="store_true",
        help="只补增量（默认 force 全量重拉，这才是修假 amount 的唯一办法）",
    )
    args = parser.parse_args()

    from src.market import MarketStore
    from src.market.infrastructure.sync import sync_quotes
    from src.market.infrastructure.write_lock import market_write_lock
    from src.shared import paths

    db_path = Path(paths.market_db())
    print("=" * 74)
    print("权威重同步  库=%s (%.1f GB)" % (db_path, db_path.stat().st_size / 1e9))
    print("=" * 74)
    before = survey(db_path)
    print_survey("改前:", before)

    pairs = stock_codes(db_path)
    wanted = {c.strip() for c in args.codes.split(",") if c.strip()}
    if wanted:
        pairs = [item for item in pairs if item[0] in wanted]
        missing = wanted - {code for code, _kind in pairs}
        if missing:
            # 不静默跳过:代码写错时「跑完了但没修到」比报错更难发现。
            print("!! 这些代码不在 instruments 表里,已忽略:%s" % sorted(missing))
    if args.limit > 0:
        pairs = pairs[: args.limit]
    codes = [code for code, _kind in pairs]
    types = {code: kind for code, kind in pairs}
    print("\n待同步 %d 只；force=%s workers=%d chunk=%d"
          % (len(codes), not args.no_force, args.workers, args.chunk))
    if args.dry_run:
        print("\n--dry-run：未写库。")
        return 0

    done = [0]
    began = time.perf_counter()

    def progress(count: int, total: int, code: str) -> None:
        done[0] = count
        if count % 200 and count != total:
            return
        spent = time.perf_counter() - began
        rate = count / spent if spent > 0 else 0.0
        left = (total - count) / rate if rate > 0 else -1
        print(
            "  %5d/%d  %.1f 票/秒  已用 %.0fs  预计剩余 %.0fs  (%s)"
            % (count, total, rate, spent, left, code),
            flush=True,
        )

    # 与桌面端 / 调度 job 共用同一把跨进程写锁：绝不双写。
    with market_write_lock(str(db_path), label="authoritative-resync"):
        report = sync_quotes(
            lambda: MarketStore(db_path),
            codes,
            instrument_types=types,
            workers=args.workers,
            min_interval=args.interval,
            force=not args.no_force,
            authoritative_only=True,
            with_factors=False,
            with_today_spot=False,
            chunk_size=args.chunk,
            progress=progress,
        )

    print("\n" + report.summary())
    if report.selected_sources:
        print("命中源: %s" % report.selected_sources)
    if report.failures:
        print("失败 %d 只，样例:" % len(report.failures))
        for code, msg in report.failures[:10]:
            print("  %s %s" % (code, str(msg)[:110]))

    after = survey(db_path)
    print()
    print_survey("改后:", after)
    fixed = before["fabricated"] - after["fabricated"]
    print("\n修正假成交额 %d 行" % fixed)
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
