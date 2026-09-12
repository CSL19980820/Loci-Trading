"""来源取证单遍聚合：与逐行事实对照，并约束日 K 查询预算。"""
from __future__ import annotations

import sqlite3
from collections import defaultdict

import pytest

from src.market import MarketStore
from src.market.infrastructure import store_provenance_query as query


def _seed(store: MarketStore) -> None:
    for receipt_id, source in (("r1", "alpha"), ("r2", "alpha"), ("empty", ""), ("", "blank-id")):
        store.conn.execute(
            "INSERT INTO source_route_receipts(receipt_id,code,lane,selected_source,state,generated_at) "
            "VALUES (?, '600001', 'hist_daily', ?, 'selected', '2025-01-01')",
            (receipt_id, source),
        )
    for number in range(7):
        store.conn.execute(
            "INSERT INTO source_route_receipts(receipt_id,code,lane,state,generated_at,"
            "request_start,request_end,unresolved) VALUES (?, ?, 'hist_daily', 'failed',"
            "'2025-01-02','2025-01-01','2025-01-31',1)",
            (f"failure-{number}", f"60000{number}"),
        )
        for day, (receipt_id, source) in enumerate(
            [(None, "alpha"), (None, ""), ("r1", "ignored"), ("r2", "other"),
             ("missing", "orphan"), ("empty", "hidden"), ("", "ignored")], 1,
        ):
            store.conn.execute(
                "INSERT INTO quotes_daily(trade_date,code,open,high,low,close,volume,amount,"
                "turnover,outstanding_share,source,receipt_id,fetched_at) "
                "VALUES (?, ?, ?, ?, 9, 10, ?, ?, ?, NULL, ?, ?, ?)",
                (f"2025-01-{day:02d}", f"60000{number}", None if day == 2 else 10,
                 8 if day == 3 else 11, float('inf') if day == 5 else 100,
                 None if day % 2 else 1000, float('nan') if day == 4 else 0.5,
                 source, receipt_id, f"2025-02-{8-day:02d}"),
            )
    store.conn.commit()


def _raw_facts(store: MarketStore, codes: list[str] | None, start: str | None, end: str | None) -> dict:
    rows = [dict(row) for row in store.conn.execute("SELECT * FROM quotes_daily")
            if (not codes or row["code"] in codes)
            and (not start or row["trade_date"] >= start)
            and (not end or row["trade_date"] <= end)]
    receipts = {row["receipt_id"]: row["selected_source"]
                for row in store.conn.execute("SELECT receipt_id,selected_source FROM source_route_receipts")}
    by_source = defaultdict(list)
    for row in rows:
        source = (row["source"] or "unknown") if row["receipt_id"] is None else receipts.get(row["receipt_id"])
        if source:
            by_source[source].append(row)
    sources = []
    for source, group in sorted(by_source.items()):
        item = {"source_id": source, "state": "selected", "rows": len(group),
                "codes": len({row["code"] for row in group}),
                "first_date": min(row["trade_date"] for row in group),
                "last_date": max(row["trade_date"] for row in group),
                "last_fetched_at": max(row["fetched_at"] for row in group)}
        if any(row["receipt_id"] is None for row in group):
            item["attempts_not_observed"] = True
        sources.append(item)
    fields = ("open", "high", "low", "close", "volume", "amount", "turnover", "outstanding_share")
    coverage = {}
    for field in fields:
        count = sum(row[field] is not None for row in rows)
        coverage[field] = {"rows": count, "ratio": round(count / len(rows), 6) if rows else 0.0}
    invalid = sum(all(row[key] is not None for key in fields[:4]) and
                  (row["high"] < max(row["open"], row["close"], row["low"])
                   or row["low"] > min(row["open"], row["close"])
                   or min(row[key] for key in fields[:4]) <= 0) for row in rows)
    return {"sources": sources, "field_coverage": coverage, "invalid_ohlc_rows": invalid,
            "observed_codes": sorted({row["code"] for row in rows})}


@pytest.mark.parametrize("compact", [False, True])
@pytest.mark.parametrize("codes,start,end", [
    (None, None, None),
    (["600006", "600000", "600006", "nonsense", "600003", "600005", "600004"], None, None),
    (["600000", "600001"], "2025-01-02", "2025-01-05"),
    (None, "2025-01-03", None),
    (None, None, "2025-01-02"),
    (None, "2026-01-01", "2026-01-31"),
])
def test_single_scan_matches_raw_rows_and_chunk_budget(tmp_path, monkeypatch, compact, codes, start, end):
    monkeypatch.setattr(query, "_SQL_IN_CHUNK", 3)
    with MarketStore(tmp_path / "market.db") as store:
        _seed(store)
        expected = _raw_facts(store, codes, start, end)
        statements = []
        store.conn.set_trace_callback(statements.append)
        evidence = store.source_evidence(codes=codes, start=start, end=end, include_details=not compact)
        store.conn.set_trace_callback(None)
        for key, value in expected.items():
            assert evidence[key] == value, key
        unique_codes = list(dict.fromkeys(codes or []))
        assert evidence["requested_codes"] == unique_codes
        assert evidence["unparsed_codes"] == (["nonsense"] if "nonsense" in unique_codes else [])
        assert evidence["unresolved_codes"] == sorted(set(unique_codes) - set(expected["observed_codes"]))
        assert sum("FROM quotes_daily" in sql for sql in statements) == max(1, (len(unique_codes) + 2) // 3)
        assert [r["receipt_id"] for r in evidence["receipts"]] == [
            r["receipt_id"] for r in sorted(evidence["receipts"], key=lambda r: (r["generated_at"], r["receipt_id"]))]
        assert not {"missing", ""} & {r["receipt_id"] for r in evidence["receipts"]}
        if compact:
            assert not any(r["state"] == "failed" for r in evidence["receipts"])
            assert evidence["historical_failure_scope"]["detail_rows_materialized"] is False


def test_single_scan_observes_same_and_other_connection_writes(tmp_path):
    """不引入隐式快照缓存；连接内写入和旁路 SQL 修订下一次查询立即可见。"""
    with MarketStore(tmp_path / "market.db") as store:
        _seed(store)
        first = store.source_evidence(codes=["600001"])
        store.conn.execute("UPDATE quotes_daily SET high=7 WHERE code='600001'")
        store.conn.commit()
        second = store.source_evidence(codes=["600001"])
        assert second["invalid_ohlc_rows"] > first["invalid_ohlc_rows"]
        with sqlite3.connect(store.db_path) as other:
            other.execute("UPDATE source_route_receipts SET selected_source='revised' WHERE receipt_id='r1'")
        third = store.source_evidence(codes=["600001"])
        assert "revised" in {source["source_id"] for source in third["sources"]}
        assert "revised" not in {source["source_id"] for source in second["sources"]}
