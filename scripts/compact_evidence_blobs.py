r"""一次性:把 ops.db 里已经写进去的巨型作业结果压回正常大小。

`finish_run` 现在会在写库前压缩逐票证据(见 `jobs/evidence.py`),但那只管
**以后**。已经躺在库里的历史行不会自己变小——实测 694 行 `job_runs` 里
`result_json` 合计 5.64 GB、单条最高 257 MB,`GET /api/jobs/runs` 因此
一次返回 1.5 GB、耗时 97 秒。

安全性:

- 只改 `job_runs.result_json`,不删行、不动其它表。
- 压掉的是**逐票证据**,权威副本在 `market.db.source_route_receipts`;
  压缩后 payload 里会留 `receipts_total` / `receipts_source` 指路。
- 解析不了的 JSON 原样跳过,不猜、不删。
- `--dry-run` 只统计不写。

用法(仓库根目录)::

    .\\.venv\\Scripts\\python.exe scripts\\compact_ops_job_results.py --dry-run
    .\\.venv\\Scripts\\python.exe scripts\\compact_ops_job_results.py
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

#: 小于这个大小的行不值得动——重写反而增加写放大与风险。
MIN_BYTES = 64 * 1024

def _compact_table(
    db: Path, table: str, id_col: str, blob_col: str, min_bytes: int, dry: bool
) -> tuple[int, int, int]:
    """压一张表的 JSON 大字段;返回 (重写行数, 跳过行数, 省下字节)。"""
    from src.shared.evidence_compact import compact_job_result

    conn = sqlite3.connect(str(db), timeout=120)
    rows = conn.execute(
        "SELECT %s, LENGTH(COALESCE(%s,'')) AS n FROM %s WHERE n >= ? ORDER BY n DESC"
        % (id_col, blob_col, table),
        (min_bytes,),
    ).fetchall()
    print("  %s: 超 %d KB 的行 %d 条,合计 %.2f GB" % (
        table, min_bytes // 1024, len(rows), sum(r[1] for r in rows) / 1e9))

    touched = skipped = saved = 0
    for row_id, size in rows:
        raw = conn.execute(
            "SELECT %s FROM %s WHERE %s = ?" % (blob_col, table, id_col), (row_id,)
        ).fetchone()[0]
        try:
            payload = json.loads(raw)
        except Exception:
            skipped += 1
            continue
        if not compact_job_result(payload):
            skipped += 1
            continue
        new_raw = json.dumps(payload, ensure_ascii=False)
        if len(new_raw) >= size:
            skipped += 1
            continue
        touched += 1
        saved += size - len(new_raw)
        print("    %-24s %8.1f MB -> %7.1f KB" % (
            str(row_id)[:24], size / 1e6, len(new_raw) / 1024.0))
        if not dry:
            conn.execute(
                "UPDATE %s SET %s = ? WHERE %s = ?" % (table, blob_col, id_col),
                (new_raw, row_id),
            )
    if not dry:
        conn.commit()
        # 不 VACUUM 的话页还挂在 freelist 上,文件不会变小,
        # 「库有多大」这件事就还是错的。
        print("  VACUUM %s ..." % db.name)
        conn.execute("VACUUM")
    conn.close()
    return touched, skipped, saved


def main() -> int:
    parser = argparse.ArgumentParser(description="压缩历史证据大字段(ops.db + palace.db)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--min-bytes", type=int, default=MIN_BYTES)
    args = parser.parse_args()

    from src.shared import paths

    targets = (
        (Path(paths.ops_db()), "job_runs", "id", "result_json"),
        (Path(paths.palace_db()), "candidate_reviews", "id", "evidence_json"),
    )
    total_saved = 0
    for db, table, id_col, blob_col in targets:
        if not db.exists():
            continue
        before = db.stat().st_size
        print("=" * 70)
        print("%s (%.2f GB)" % (db, before / 1e9))
        touched, skipped, saved = _compact_table(
            db, table, id_col, blob_col, args.min_bytes, args.dry_run
        )
        total_saved += saved
        print("  重写 %d 条,跳过 %d 条,省下 %.2f GB" % (touched, skipped, saved / 1e9))
        if not args.dry_run:
            print("  %s %.2f GB -> %.2f GB" % (db.name, before / 1e9, db.stat().st_size / 1e9))
    print()
    print("合计省下 %.2f GB%s" % (total_saved / 1e9, "(--dry-run,未写库)" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
