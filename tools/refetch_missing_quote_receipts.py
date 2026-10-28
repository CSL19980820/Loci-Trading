r"""Refetch retained daily bars from TDX to replace missing provenance links.

The production database has historical quote rows whose values were migrated
without a ``source_route_receipts`` link. Old archive files cannot prove that
they describe the same fetch, so this tool deliberately performs a new,
authoritative TDX request for the retained window (at most 800 bars) and writes
a fresh receipt together with the returned bars.

Only rows that currently have ``receipt_id IS NULL`` are selected. Before an
apply run, every selected row is copied to a PostgreSQL backup table. The
manifest and backup support an exact, conditional rollback.

Examples::

    docker exec -w /app -e PYTHONPATH=/app qianlong-loci \
      python /app/tools/refetch_missing_quote_receipts.py --dry-run --limit 20

    docker exec -w /app -e PYTHONPATH=/app qianlong-loci \
      python /app/tools/refetch_missing_quote_receipts.py --apply \
      --run-id receipts-20261027

    docker exec -w /app -e PYTHONPATH=/app qianlong-loci \
      python /app/tools/refetch_missing_quote_receipts.py --rollback \
      --run-id receipts-20261027
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import time
from typing import Any, Iterable, Sequence

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.market.infrastructure.history_floor import trade_date_floor
from src.market.infrastructure.store import MarketStore
from src.market.infrastructure.tdx_daily import fetch_daily_many
from src.market.infrastructure.write_lock import market_write_lock
from src.shared.clock import utc_now
from src.shared.paths import market_db

DEFAULT_RUN_ID = f"missing-receipts-{date.today():%Y%m%d}"
DEFAULT_BARS = 800
QUOTE_FIELDS = ("open", "high", "low", "close", "volume", "amount")


def _safe_identifier(value: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_]+", "_", str(value)).strip("_").lower()
    if not safe:
        raise ValueError("run id 不能为空")
    return safe[:40]


def _backup_table(run_id: str) -> str:
    digest = hashlib.sha256(str(run_id).encode("utf-8")).hexdigest()[:10]
    return f"market.qdr_backup_{_safe_identifier(run_id)}_{digest}"


def _target_rows(
    store: MarketStore,
    *,
    codes: Sequence[str] | None = None,
    limit: int = 0,
    include_indexes: bool = False,
) -> tuple[list[tuple[str, str]], dict[str, set[str]]]:
    """Return target securities and their missing-receipt dates."""
    wanted = [str(code).strip() for code in codes or () if str(code).strip()]
    where = "q.receipt_id IS NULL"
    params: list[Any] = []
    if wanted:
        where += " AND q.code = ANY(%s)"
        params.append(wanted)
    sql = (
        "SELECT q.code, COALESCE(i.instrument_type, 'STOCK') AS instrument_type "
        "FROM (SELECT DISTINCT code FROM market.quotes_daily "
        f"      WHERE {where.replace('q.', '')}) q "
        "LEFT JOIN market.instruments i ON i.code = q.code "
        "ORDER BY q.code"
    )
    # PostgreSQL is required for the production backup/rollback path.
    if not getattr(store, "_use_postgres", False):
        raise RuntimeError("该生产回执修复工具仅支持 PostgreSQL")
    with store.conn.raw.cursor() as cursor:
        cursor.execute(sql, params)
        instruments = [(str(row["code"]), str(row["instrument_type"])) for row in cursor]
    if limit > 0:
        instruments = instruments[:limit]
    if not include_indexes:
        instruments = [
            (code, kind) for code, kind in instruments if kind.upper() != "INDEX"
        ]
    if not instruments:
        return [], {}
    selected = [code for code, _kind in instruments]
    with store.conn.raw.cursor() as cursor:
        cursor.execute(
            "SELECT code, trade_date FROM market.quotes_daily "
            "WHERE receipt_id IS NULL AND code = ANY(%s) "
            "ORDER BY code, trade_date",
            (selected,),
        )
        missing: dict[str, set[str]] = defaultdict(set)
        for row in cursor:
            missing[str(row["code"])].add(str(row["trade_date"]))
    return instruments, dict(missing)


def _existing_values(
    store: MarketStore,
    codes: Sequence[str],
) -> dict[tuple[str, str], tuple[Any, ...]]:
    if not codes:
        return {}
    with store.conn.raw.cursor() as cursor:
        cursor.execute(
            "SELECT code, trade_date, open, high, low, close, volume, amount "
            "FROM market.quotes_daily "
            "WHERE receipt_id IS NULL AND code = ANY(%s)",
            (list(codes),),
        )
        return {
            (str(row["code"]), str(row["trade_date"])): tuple(
                row[field] for field in QUOTE_FIELDS
            )
            for row in cursor
        }


def _same_number(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return left is None and right is None
    try:
        left_f = float(left)
        right_f = float(right)
    except (TypeError, ValueError):
        return str(left) == str(right)
    if math.isnan(left_f) or math.isnan(right_f):
        return math.isnan(left_f) and math.isnan(right_f)
    return left_f == right_f


def _within_repair_tolerance(field: str, left: Any, right: Any) -> bool:
    if _same_number(left, right):
        return True
    try:
        left_f = float(left)
        right_f = float(right)
    except (TypeError, ValueError):
        return False
    if field in {"open", "high", "low", "close"}:
        return abs(left_f - right_f) <= 0.01
    return abs(left_f - right_f) <= max(1.0, 0.01 * max(abs(left_f), abs(right_f)))


def _safe_missing_dates(
    frame: pd.DataFrame,
    missing_dates: set[str],
    current: dict[tuple[str, str], tuple[Any, ...]],
    code: str,
) -> set[str]:
    source_by_date = {str(row.date): row for row in frame.itertuples(index=False)}
    safe: set[str] = set()
    for trade_date in missing_dates:
        before = current.get((code, trade_date))
        row = source_by_date.get(trade_date)
        if before is None or row is None:
            continue
        source = tuple(getattr(row, field) for field in QUOTE_FIELDS)
        if all(
            _within_repair_tolerance(field, left, right)
            for field, left, right in zip(QUOTE_FIELDS, before, source, strict=True)
        ):
            safe.add(trade_date)
    return safe


def _compare_rows(
    frame: pd.DataFrame,
    missing_dates: set[str],
    current: dict[tuple[str, str], tuple[Any, ...]],
    code: str,
) -> dict[str, Any]:
    fields = {
        field: {
            "exact": 0,
            "within_tolerance": 0,
            "material": 0,
            "max_abs_delta": 0.0,
            "max_relative_delta": 0.0,
        }
        for field in QUOTE_FIELDS
    }
    exact_rows = 0
    tolerant_rows = 0
    material_rows = 0
    examples: list[dict[str, Any]] = []
    for row in frame.itertuples(index=False):
        trade_date = str(row.date)
        if trade_date not in missing_dates:
            continue
        before = current.get((code, trade_date))
        if before is None:
            continue
        source = tuple(getattr(row, field) for field in QUOTE_FIELDS)
        row_exact = True
        row_tolerant = True
        row_material = False
        for field, left, right in zip(QUOTE_FIELDS, before, source, strict=True):
            if _same_number(left, right):
                fields[field]["exact"] += 1
                continue
            row_exact = False
            try:
                left_f = float(left)
                right_f = float(right)
                delta = abs(left_f - right_f)
                relative = delta / max(abs(left_f), abs(right_f), 1e-300)
                fields[field]["max_abs_delta"] = max(
                    fields[field]["max_abs_delta"], delta
                )
                fields[field]["max_relative_delta"] = max(
                    fields[field]["max_relative_delta"], relative
                )
                tolerant = _within_repair_tolerance(field, left, right)
            except (TypeError, ValueError):
                tolerant = False
            if tolerant:
                fields[field]["within_tolerance"] += 1
            else:
                fields[field]["material"] += 1
                row_tolerant = False
                row_material = True
                if len(examples) < 4:
                    examples.append(
                        {
                            "code": code,
                            "trade_date": trade_date,
                            "field": field,
                            "database": left,
                            "source_value": right,
                        }
                    )
        exact_rows += int(row_exact)
        tolerant_rows += int(row_tolerant)
        material_rows += int(row_material)
    return {
        "exact_rows": exact_rows,
        "within_tolerance_rows": tolerant_rows,
        "material_rows": material_rows,
        "fields": fields,
        "examples": examples,
    }


def _receipt_payload(
    *,
    run_id: str,
    code: str,
    frame: pd.DataFrame,
    missing_dates: set[str],
    changed_rows: int,
    source: str,
    source_url: str,
) -> dict[str, Any]:
    generated = utc_now()
    coverage_dates = sorted(
        str(value) for value in frame["date"].astype(str) if str(value) in missing_dates
    )
    request_start = trade_date_floor()
    request_end = date.today().isoformat()
    return {
        "code": code,
        "lane": "hist_daily",
        "state": "selected",
        "requested_sources": [source],
        "attempts": [
            {
                "source_id": source,
                "state": "selected",
                "checked_at": generated,
                "rows": int(len(frame)),
                "fields": [str(column) for column in frame.columns],
            }
        ],
        "selected_source": source,
        "fallback_used": False,
        "unresolved": False,
        "coverage": {
            "repair_run_id": run_id,
            "repair_reason": "missing_receipt_authoritative_refetch",
            "source_rows": int(len(frame)),
            "missing_receipt_rows_requested": len(missing_dates),
            "matched_receipt_rows": len(coverage_dates),
            "value_changed_rows": int(changed_rows),
            "fields": [str(column) for column in frame.columns],
        },
        "source_url": source_url,
        "request_start": request_start,
        "request_end": request_end,
        "fetched_at": generated,
        "coverage_start": coverage_dates[0] if coverage_dates else "",
        "coverage_end": coverage_dates[-1] if coverage_dates else "",
    }


def _apply_bucket(
    store: MarketStore,
    *,
    run_id: str,
    instruments: Sequence[tuple[str, str]],
    frames: dict[str, pd.DataFrame],
    missing: dict[str, set[str]],
    current: dict[tuple[str, str], tuple[Any, ...]],
    source: str,
    source_url: str,
) -> tuple[int, int]:
    rows_written = 0
    receipts_written = 0
    with store._transaction() as cursor:
        for code, _kind in instruments:
            frame = frames.get(code)
            missing_dates = missing.get(code, set())
            if frame is None or frame.empty or not missing_dates:
                continue
            missing_dates = _safe_missing_dates(frame, missing_dates, current, code)
            subset = frame[frame["date"].astype(str).isin(missing_dates)].copy()
            if subset.empty:
                continue
            payload = store._quote_payload_from_frame(
                code, subset, source=source, receipt_id=None
            )
            if not payload:
                continue
            changed = _compare_rows(frame, missing_dates, current, code)["material_rows"]
            receipt = _receipt_payload(
                run_id=run_id,
                code=code,
                frame=frame,
                missing_dates=missing_dates,
                changed_rows=changed,
                source=source,
                source_url=source_url,
            )
            store._attach_quote_payload_provenance(receipt, payload)
            receipt_id = store._insert_source_receipt(
                cursor,
                receipt,
                trade_dates=[str(row[0]) for row in payload],
            )
            if source == "tdx":
                written = store._write_quote_payload(
                    [(*row[:-1], receipt_id) for row in payload],
                    cursor=cursor,
                )
            else:
                cursor.executemany(
                    """
                    UPDATE market.quotes_daily
                       SET open=%s, high=%s, low=%s, close=%s, volume=%s, amount=%s,
                           source=%s, receipt_id=%s, fetched_at=CURRENT_TIMESTAMP
                     WHERE trade_date=%s AND code=%s AND receipt_id IS NULL
                    """,
                    [
                        (
                            row[2],
                            row[3],
                            row[4],
                            row[5],
                            row[6],
                            row[7],
                            source,
                            receipt_id,
                            row[0],
                            row[1],
                        )
                        for row in payload
                    ],
                )
                written = max(0, int(cursor.rowcount))
                store._bump_revisions(cursor, "quotes")
            store._record_rows_written(cursor, receipt_id, receipt, written)
            store._bump_revisions(cursor, "source_receipts")
            rows_written += written
            receipts_written += 1
    return rows_written, receipts_written


def _manifest_schema(store: MarketStore) -> None:
    store.conn.raw.execute(
        """
        CREATE TABLE IF NOT EXISTS market.receipt_repair_manifest(
            run_id TEXT PRIMARY KEY,
            backup_table TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            finished_at TIMESTAMPTZ,
            null_rows_before BIGINT NOT NULL DEFAULT 0,
            rows_written BIGINT NOT NULL DEFAULT 0,
            receipts_written BIGINT NOT NULL DEFAULT 0,
            unresolved_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
            details JSONB NOT NULL DEFAULT '{}'::jsonb
        )
        """
    )
    store.conn.raw.commit()


def _create_backup(store: MarketStore, run_id: str) -> tuple[str, int]:
    table = _backup_table(run_id)
    connection = store.conn.raw
    cursor = connection.execute("SELECT to_regclass(%s) AS name", (table,))
    if cursor.fetchone()["name"] is not None:
        raise RuntimeError(f"备份表已存在：{table}")
    connection.execute(
        f"CREATE TABLE {table} AS "
        "SELECT * FROM market.quotes_daily WHERE receipt_id IS NULL"
    )
    count = int(connection.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"])
    connection.execute(
        "INSERT INTO market.receipt_repair_manifest(run_id, backup_table, status, null_rows_before) "
        "VALUES(%s, %s, 'running', %s)",
        (run_id, table, count),
    )
    connection.commit()
    return table, count


def _update_manifest(
    store: MarketStore,
    run_id: str,
    *,
    status: str,
    rows_written: int,
    receipts_written: int,
    unresolved: Sequence[str],
    details: dict[str, Any],
) -> None:
    store.conn.raw.execute(
        """
        UPDATE market.receipt_repair_manifest
           SET status=%s, finished_at=CURRENT_TIMESTAMP, rows_written=%s,
               receipts_written=%s, unresolved_codes=%s::jsonb, details=%s::jsonb
         WHERE run_id=%s
        """,
        (
            status,
            rows_written,
            receipts_written,
            json.dumps(list(unresolved), ensure_ascii=False),
            json.dumps(details, ensure_ascii=False, sort_keys=True),
            run_id,
        ),
    )
    store.conn.raw.commit()


def _iter_buckets(items: Sequence[Any], size: int) -> Iterable[Sequence[Any]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _fetch_frames(
    codes: Sequence[str],
    *,
    instrument_types: dict[str, str],
    source: str,
    bars: int,
    workers: int,
    sina_index_volume_divisor: float = 1.0,
) -> dict[str, pd.DataFrame]:
    if source == "tdx":
        return fetch_daily_many(
            codes,
            bars=bars,
            workers=workers,
            instrument_types=instrument_types,
        )
    if source != "sina":
        raise ValueError(f"不支持的数据源：{source}")
    from src.market.infrastructure.sources import SinaSource

    provider = SinaSource()

    def fetch_one(code: str) -> tuple[str, pd.DataFrame | None]:
        try:
            frame = provider.fetch_daily(
                code, instrument_type=instrument_types.get(code, "STOCK")
            )
            required = ["date", *QUOTE_FIELDS]
            return code, frame.loc[:, [field for field in required if field in frame]]
        except Exception:
            return code, None

    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(codes)))) as pool:
        frames: dict[str, pd.DataFrame] = {}
        for code, frame in pool.map(fetch_one, codes):
            if frame is None or frame.empty:
                continue
            if (
                instrument_types.get(code, "STOCK") == "INDEX"
                and sina_index_volume_divisor != 1.0
            ):
                frame = frame.copy()
                frame["volume"] = frame["volume"] / sina_index_volume_divisor
            frames[code] = frame
        return frames


def run_refetch(args: argparse.Namespace) -> int:
    db_path = Path(market_db())
    store = MarketStore(db_path)
    try:
        if not getattr(store, "_use_postgres", False):
            raise RuntimeError("请在 PostgreSQL 生产容器中运行该工具")
        requested_codes = [
            value.strip() for value in str(args.codes or "").split(",") if value.strip()
        ]
        instruments, missing = _target_rows(
            store,
            codes=requested_codes or None,
            limit=args.limit,
            include_indexes=args.include_indexes,
        )
        if not instruments:
            print("没有待补回执的行情行。")
            return 0
        instrument_types = dict(instruments)
        total_missing = sum(len(dates) for dates in missing.values())
        print(
            f"目标 {len(instruments)} 只，缺回执行 {total_missing} 行；"
            f"{args.source.upper()} 每票请求最近 {args.bars} 根，workers={args.workers}"
        )

        if args.apply:
            _manifest_schema(store)
            existing = store.conn.raw.execute(
                "SELECT status FROM market.receipt_repair_manifest WHERE run_id=%s",
                (args.run_id,),
            ).fetchone()
            store.conn.raw.commit()
            if existing is not None:
                raise RuntimeError(
                    f"run_id 已存在：{args.run_id}（status={existing['status']}）"
                )
            with market_write_lock(db_path, label=f"receipt-repair:{args.run_id}"):
                backup, backed_up = _create_backup(store, args.run_id)
                print(f"事务性备份完成：{backup}（{backed_up} 行）")
                return _run_buckets(
                    args,
                    store,
                    instruments,
                    instrument_types,
                    missing,
                    apply=True,
                )
        return _run_buckets(
            args,
            store,
            instruments,
            instrument_types,
            missing,
            apply=False,
        )
    finally:
        store.close()


def _run_buckets(
    args: argparse.Namespace,
    store: MarketStore,
    instruments: Sequence[tuple[str, str]],
    instrument_types: dict[str, str],
    missing: dict[str, set[str]],
    *,
    apply: bool,
) -> int:
    started = time.monotonic()
    live_receipts = 0
    live_rows = 0
    matched_rows = 0
    exact_rows = 0
    tolerant_rows = 0
    material_rows = 0
    field_stats = {
        field: {
            "exact": 0,
            "within_tolerance": 0,
            "material": 0,
            "max_abs_delta": 0.0,
            "max_relative_delta": 0.0,
        }
        for field in QUOTE_FIELDS
    }
    difference_examples: list[dict[str, Any]] = []
    source_new_dates = 0
    unresolved: list[str] = []
    completed = 0
    for bucket in _iter_buckets(instruments, args.bucket_size):
        codes = [code for code, _kind in bucket]
        frames = _fetch_frames(
            codes,
            instrument_types=instrument_types,
            source=args.source,
            bars=args.bars,
            workers=args.workers,
            sina_index_volume_divisor=args.sina_index_volume_divisor,
        )
        current = _existing_values(store, codes)
        for code, _kind in bucket:
            frame = frames.get(code)
            if frame is None or frame.empty:
                unresolved.append(code)
                continue
            frame = frame.copy()
            frame["date"] = frame["date"].astype(str)
            frame_dates = set(frame["date"])
            missing_dates = missing.get(code, set())
            source_new_dates += len(frame_dates - missing_dates)
            matched = len(frame_dates & missing_dates)
            matched_rows += matched
            comparison = _compare_rows(frame, missing_dates, current, code)
            exact_rows += int(comparison["exact_rows"])
            tolerant_rows += int(comparison["within_tolerance_rows"])
            material_rows += int(comparison["material_rows"])
            for field, values in comparison["fields"].items():
                for state in ("exact", "within_tolerance", "material"):
                    field_stats[field][state] += int(values[state])
                field_stats[field]["max_abs_delta"] = max(
                    field_stats[field]["max_abs_delta"], values["max_abs_delta"]
                )
                field_stats[field]["max_relative_delta"] = max(
                    field_stats[field]["max_relative_delta"],
                    values["max_relative_delta"],
                )
            difference_examples.extend(comparison["examples"])
        if apply:
            rows, receipts = _apply_bucket(
                store,
                run_id=args.run_id,
                instruments=bucket,
                frames=frames,
                missing=missing,
                current=current,
                source=args.source,
                source_url=(
                    "tdx://binary"
                    if args.source == "tdx"
                    else "https://finance.sina.com.cn"
                ),
            )
            live_rows += rows
            live_receipts += receipts
        completed += len(codes)
        elapsed = time.monotonic() - started
        rate = completed / max(elapsed, 1e-9)
        print(
            f"  {completed}/{len(instruments)}  已处理 {len(codes)} 只，"
            f"{rate:.1f} 只/秒"
        )

    details = {
        "bars_requested": args.bars,
        "source": args.source,
        "workers": args.workers,
        "matched_rows": matched_rows,
        "exact_rows": exact_rows,
        "within_tolerance_rows": tolerant_rows,
        "material_change_rows": material_rows,
        "field_differences": field_stats,
        "difference_examples": difference_examples[:20],
        "source_dates_already_receipted": source_new_dates,
        "unresolved_codes": unresolved,
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(details, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    if apply:
        _update_manifest(
            store,
            args.run_id,
            status="applied" if not unresolved else "applied_with_unresolved",
            rows_written=live_rows,
            receipts_written=live_receipts,
            unresolved=unresolved,
            details=details,
        )
    mode = "应用" if apply else "只读预演"
    print(
        f"{mode}完成：匹配缺回执行 {matched_rows}，完全一致 {exact_rows}，"
        f"仅末位误差 {tolerant_rows - exact_rows}，实质差异 {material_rows}，"
        f"未能重取 {len(unresolved)} 只，耗时 {details['elapsed_seconds']:.1f}s"
    )
    if material_rows:
        for field, values in field_stats.items():
            if values["material"]:
                print(
                    f"  {field}: 实质差异 {values['material']} 行，"
                    f"最大绝对差 {values['max_abs_delta']:.8g}，"
                    f"最大相对差 {values['max_relative_delta']:.3g}"
                )
        for example in difference_examples[:5]:
            print(
                f"  样例 {example['code']} {example['trade_date']} {example['field']}: "
                f"库={example['database']} {args.source.upper()}={example['source_value']}"
            )
    if apply:
        print(
            f"实际写入 {live_rows} 行，生成 {live_receipts} 条真实 "
            f"{args.source.upper()} 回执"
        )
    return 1 if unresolved and args.fail_on_unresolved else 0


def run_rollback(args: argparse.Namespace) -> int:
    store = MarketStore(Path(market_db()))
    try:
        if not getattr(store, "_use_postgres", False):
            raise RuntimeError("请在 PostgreSQL 生产容器中运行该工具")
        _manifest_schema(store)
        manifest = store.conn.raw.execute(
            "SELECT backup_table, status FROM market.receipt_repair_manifest WHERE run_id=%s",
            (args.run_id,),
        ).fetchone()
        store.conn.raw.commit()
        if manifest is None:
            raise RuntimeError(f"找不到 run_id：{args.run_id}")
        if manifest["status"] == "rolled_back":
            print("该 run_id 已回滚。")
            return 0
        backup = str(manifest["backup_table"])
        if not re.fullmatch(
            r"market\.(?:quotes_daily_receipt_backup_|qdr_backup_)[a-z0-9_]+",
            backup,
        ):
            raise RuntimeError(f"备份表名不合法：{backup}")
        with market_write_lock(
            Path(market_db()), label=f"receipt-repair-rollback:{args.run_id}"
        ), store._transaction() as cursor:
            cursor.execute(
                f"SELECT b.* FROM {backup} b "
                "JOIN market.quotes_daily q "
                "ON q.code=b.code AND q.trade_date=b.trade_date "
                "JOIN market.source_route_receipts r ON r.receipt_id=q.receipt_id "
                "WHERE r.coverage_json::jsonb->>'repair_run_id'=%s",
                (args.run_id,),
            )
            rows = cursor.fetchall()
            payload = [
                (
                    row["open"],
                    row["high"],
                    row["low"],
                    row["close"],
                    row["volume"],
                    row["amount"],
                    row["outstanding_share"],
                    row["turnover"],
                    row["source"],
                    row["receipt_id"],
                    row["fetched_at"],
                    row["trade_date"],
                    row["code"],
                )
                for row in rows
            ]
            cursor.executemany(
                """
                UPDATE market.quotes_daily
                   SET open=%s, high=%s, low=%s, close=%s, volume=%s, amount=%s,
                       outstanding_share=%s, turnover=%s, source=%s, receipt_id=%s,
                       fetched_at=%s
                 WHERE trade_date=%s AND code=%s
                """,
                payload,
            )
            cursor.execute(
                "DELETE FROM market.source_route_attempts WHERE receipt_id IN "
                "(SELECT receipt_id FROM market.source_route_receipts "
                " WHERE coverage_json::jsonb->>'repair_run_id'=%s)",
                (args.run_id,),
            )
            cursor.execute(
                "DELETE FROM market.source_route_receipts "
                "WHERE coverage_json::jsonb->>'repair_run_id'=%s",
                (args.run_id,),
            )
            store._bump_revisions(cursor, "quotes", "source_receipts")
        _update_manifest(
            store,
            args.run_id,
            status="rolled_back",
            rows_written=len(rows),
            receipts_written=0,
            unresolved=[],
            details={"rollback_rows": len(rows)},
        )
        print(f"回滚完成：恢复 {len(rows)} 行并删除该轮新增回执。")
        return 0
    finally:
        store.close()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="用真实 TDX 取数补齐缺失行情回执")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="只读预演（默认）")
    mode.add_argument("--apply", action="store_true", help="备份后执行修复")
    mode.add_argument("--rollback", action="store_true", help="按 manifest 回滚一次修复")
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--codes", default="", help="逗号分隔的代码，默认全部缺回执证券")
    parser.add_argument("--limit", type=int, default=0, help="只处理前 N 只")
    parser.add_argument(
        "--include-indexes",
        action="store_true",
        help="同时处理指数；默认只修普通股票，避免混淆 TDX 指数量纲",
    )
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--bucket-size", type=int, default=128)
    parser.add_argument("--bars", type=int, default=DEFAULT_BARS)
    parser.add_argument("--source", choices=("tdx", "sina"), default="tdx")
    parser.add_argument(
        "--sina-index-volume-divisor",
        type=float,
        default=1.0,
        help="新浪指数成交量单位归一除数；指数实测百手口径使用 100",
    )
    parser.add_argument("--report", default="", help="把只读对照统计写入 JSON 文件")
    parser.add_argument("--fail-on-unresolved", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.rollback:
        return run_rollback(args)
    if (
        args.workers < 1
        or args.bucket_size < 1
        or args.bars < 1
        or args.sina_index_volume_divisor <= 0
    ):
        raise ValueError("workers、bucket-size、bars、指数成交量除数必须大于 0")
    return run_refetch(args)


if __name__ == "__main__":
    raise SystemExit(main())
