"""Apply or roll back the reviewed missing-turnover plan on PostgreSQL."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.market.infrastructure.store import MarketStore
from src.market.infrastructure.write_lock import market_write_lock
from src.shared.paths import market_db


def _same(left, right) -> bool:
    if left is None or right is None:
        return left is None and right is None
    return abs(float(left) - float(right)) <= 1e-9


def _backup_table(run_id: str) -> str:
    digest = hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:12]
    safe = re.sub(r"[^a-z0-9]+", "_", run_id.lower()).strip("_")[:30]
    return f"market.turnover_backup_{safe}_{digest}"


def _manifest_schema(store: MarketStore) -> None:
    store.conn.raw.execute(
        """
        CREATE TABLE IF NOT EXISTS market.turnover_repair_manifest(
            run_id TEXT PRIMARY KEY,
            backup_table TEXT NOT NULL,
            status TEXT NOT NULL,
            planned_rows BIGINT NOT NULL,
            updated_rows BIGINT NOT NULL DEFAULT 0,
            plan_sha256 TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            finished_at TIMESTAMPTZ,
            details JSONB NOT NULL DEFAULT '{}'::jsonb
        )
        """
    )
    store.conn.raw.commit()


def _plan_rows(path: Path) -> list[dict]:
    document = json.loads(path.read_text(encoding="utf-8"))
    rows = document.get("changes")
    if not isinstance(rows, list):
        raise ValueError("计划文件缺少 changes 数组")
    return rows


def apply_plan(args: argparse.Namespace) -> int:
    plan_path = Path(args.plan)
    rows = _plan_rows(plan_path)
    plan_sha = hashlib.sha256(plan_path.read_bytes()).hexdigest()
    store = MarketStore(Path(market_db()))
    try:
        if not getattr(store, "_use_postgres", False):
            raise RuntimeError("该修复工具仅支持 PostgreSQL")
        _manifest_schema(store)
        existing = store.conn.raw.execute(
            "SELECT status FROM market.turnover_repair_manifest WHERE run_id=%s",
            (args.run_id,),
        ).fetchone()
        store.conn.raw.commit()
        if existing is not None:
            raise RuntimeError(f"run_id 已存在：{args.run_id} ({existing['status']})")
        backup = _backup_table(args.run_id)
        with market_write_lock(
            Path(market_db()), label=f"turnover-repair:{args.run_id}"
        ), store._transaction() as cursor:
            selected: list[tuple] = []
            skipped: list[dict] = []
            for item in rows:
                code = str(item["code"])
                trade_date = str(item["trade_date"])
                cursor.execute(
                    "SELECT q.*, i.instrument_type FROM market.quotes_daily q "
                    "LEFT JOIN market.instruments i ON i.code=q.code "
                    "WHERE q.code=? AND q.trade_date=?",
                    (code, trade_date),
                )
                current = cursor.fetchone()
                if current is None:
                    skipped.append({"code": code, "trade_date": trade_date, "reason": "missing"})
                    continue
                if not args.include_indexes and str(current["instrument_type"] or "STOCK") == "INDEX":
                    skipped.append({"code": code, "trade_date": trade_date, "reason": "index"})
                    continue
                old_turnover = current["turnover"]
                if old_turnover is not None and float(old_turnover) > 0:
                    skipped.append(
                        {"code": code, "trade_date": trade_date, "reason": "turnover_already_set"}
                    )
                    continue
                if not (
                    _same(current["volume"], item["volume"])
                    and _same(current["amount"], item["amount"])
                    and _same(current["close"], item["close"])
                    and _same(current["outstanding_share"], item["old_outstanding_share"])
                ):
                    skipped.append(
                        {"code": code, "trade_date": trade_date, "reason": "source_values_changed"}
                    )
                    continue
                selected.append(
                    (
                        code,
                        trade_date,
                        old_turnover,
                        current["outstanding_share"],
                        float(item["turnover"]),
                        float(item["shares_asof"]),
                        current["volume"],
                        current["amount"],
                        current["close"],
                        current["source"],
                    )
                )
            if args.dry_run:
                print(
                    f"只读预演：计划 {len(rows)} 行，可安全更新 {len(selected)} 行，"
                    f"跳过 {len(skipped)} 行"
                )
                return 0
            if not selected:
                raise RuntimeError("没有可安全应用的计划行")
            cursor.execute(
                f"""
                CREATE TABLE {backup}(
                    code TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    old_turnover DOUBLE PRECISION,
                    old_outstanding_share DOUBLE PRECISION,
                    new_turnover DOUBLE PRECISION NOT NULL,
                    new_outstanding_share DOUBLE PRECISION NOT NULL,
                    volume DOUBLE PRECISION,
                    amount DOUBLE PRECISION,
                    close DOUBLE PRECISION,
                    source TEXT,
                    PRIMARY KEY(code, trade_date)
                )
                """
            )
            cursor.executemany(
                f"INSERT INTO {backup} VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                selected,
            )
            cursor.executemany(
                """
                UPDATE market.quotes_daily
                   SET outstanding_share=%s, turnover=%s
                 WHERE code=%s AND trade_date=%s
                   AND (turnover IS NULL OR turnover <= 0)
                """,
                [
                    (row[5], row[4], row[0], row[1])
                    for row in selected
                ],
            )
            updated = max(0, int(cursor.rowcount))
            store._bump_revisions(cursor, "quotes")
            cursor.execute(
                """
                INSERT INTO market.turnover_repair_manifest(
                    run_id, backup_table, status, planned_rows, updated_rows,
                    plan_sha256, finished_at, details
                ) VALUES(%s,%s,'applied',%s,%s,%s,CURRENT_TIMESTAMP,%s::jsonb)
                """,
                (
                    args.run_id,
                    backup,
                    len(rows),
                    updated,
                    plan_sha,
                    json.dumps({"skipped": skipped}, ensure_ascii=False),
                ),
            )
        print(
            f"换手率修复完成：计划 {len(rows)} 行，安全更新 {updated} 行，"
            f"跳过 {len(skipped)} 行；备份表 {backup}"
        )
        return 0
    finally:
        store.close()


def rollback(args: argparse.Namespace) -> int:
    store = MarketStore(Path(market_db()))
    try:
        if not getattr(store, "_use_postgres", False):
            raise RuntimeError("该修复工具仅支持 PostgreSQL")
        _manifest_schema(store)
        manifest = store.conn.raw.execute(
            "SELECT * FROM market.turnover_repair_manifest WHERE run_id=%s",
            (args.run_id,),
        ).fetchone()
        store.conn.raw.commit()
        if manifest is None:
            raise RuntimeError(f"找不到 run_id：{args.run_id}")
        if manifest["status"] == "rolled_back":
            print("该 run_id 已回滚")
            return 0
        backup = str(manifest["backup_table"])
        if not re.fullmatch(r"market\.turnover_backup_[a-z0-9_]+", backup):
            raise RuntimeError(f"备份表名不合法：{backup}")
        with market_write_lock(
            Path(market_db()), label=f"turnover-repair-rollback:{args.run_id}"
        ), store._transaction() as cursor:
            cursor.execute(
                f"""
                UPDATE market.quotes_daily q
                   SET turnover=b.old_turnover,
                       outstanding_share=b.old_outstanding_share
                  FROM {backup} b
                 WHERE q.code=b.code AND q.trade_date=b.trade_date
                   AND q.turnover=b.new_turnover
                   AND q.outstanding_share=b.new_outstanding_share
                """
            )
            restored = max(0, int(cursor.rowcount))
            cursor.execute(
                "UPDATE market.turnover_repair_manifest "
                "SET status='rolled_back', finished_at=CURRENT_TIMESTAMP WHERE run_id=%s",
                (args.run_id,),
            )
            store._bump_revisions(cursor, "quotes")
        print(f"回滚完成：恢复 {restored} 行")
        return 0
    finally:
        store.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="应用或回滚换手率修复计划")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--rollback", action="store_true")
    parser.add_argument("--include-indexes", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    return rollback(args) if args.rollback else apply_plan(args)


if __name__ == "__main__":
    raise SystemExit(main())
