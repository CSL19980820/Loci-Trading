from __future__ import annotations

from pathlib import Path
import sqlite3

import pandas as pd

from src.market import MarketStore, SourceAttemptRecord, SourceRouteReceipt


def test_data_snapshot_contains_source_coverage_and_unresolved_codes(tmp_path: Path) -> None:
    with MarketStore(tmp_path / "market.db") as store:
        store.upsert_quotes(
            "600519",
            pd.DataFrame(
                {
                    "date": ["2025-01-02", "2025-01-03"],
                    "open": [10.0, 10.2],
                    "high": [10.5, 10.4],
                    "low": [9.8, 10.0],
                    "close": [10.2, 10.1],
                    "volume": [1000, 1200],
                    "amount": [10000, 12000],
                    "turnover": [0.03, None],
                }
            ),
            source="fixture-sina",
        )
        snapshot = store.data_snapshot(
            codes=["600519", "000001"],
            start="2025-01-01",
            end="2025-01-31",
        )

    evidence = snapshot["source_evidence"]
    assert evidence["observed_codes"] == ["600519"]
    assert evidence["unresolved_codes"] == ["000001"]
    assert evidence["sources"][0]["source_id"] == "fixture-sina"
    assert evidence["field_coverage"]["close"]["ratio"] == 1.0
    assert evidence["field_coverage"]["turnover"]["rows"] == 1
    assert evidence["invalid_ohlc_rows"] == 0
    assert evidence["attempts_not_observed"] is True


def test_legacy_market_db_migrates_receipt_tables_idempotently(tmp_path: Path) -> None:
    db = tmp_path / "legacy-market.db"
    connection = sqlite3.connect(db)
    connection.executescript(
        """
        CREATE TABLE quotes_daily (
            trade_date TEXT NOT NULL,
            code TEXT NOT NULL,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume REAL,
            amount REAL,
            outstanding_share REAL,
            turnover REAL,
            source TEXT NOT NULL DEFAULT '',
            fetched_at TEXT NOT NULL,
            PRIMARY KEY (trade_date, code)
        ) WITHOUT ROWID;
        INSERT INTO quotes_daily VALUES(
            '2025-01-02', '600519', 10, 11, 9, 10.5, 1000, 10500, NULL, NULL, 'legacy', '2025-01-02T15:00:00'
        );
        """
    )
    connection.commit()
    connection.close()

    with MarketStore(db) as store:
        columns = {row[1] for row in store.conn.execute("PRAGMA table_info(quotes_daily)")}
        assert "receipt_id" in columns
        assert store.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'source_route_receipts'"
        ).fetchone()
        assert store.source_evidence(codes=["600519"])["attempts_not_observed"] is True

    with MarketStore(db) as store:
        assert store.conn.execute("SELECT COUNT(*) FROM quotes_daily").fetchone()[0] == 1


def test_source_evidence_aggregates_many_receipts_without_quote_detail_fetch(tmp_path: Path) -> None:
    codes = [f"{600000 + index:06d}" for index in range(1001)]
    receipts = [
        {
            "code": code,
            "lane": "hist_daily",
            "selected_source": "fixture",
            "attempts": [{"source_id": "fixture", "state": "selected"}],
        }
        for code in codes
    ]
    bars = [
        {
            "code": code,
            "date": "2025-01-02",
            "open": 10.0,
            "high": 11.0,
            "low": 9.0,
            "close": 10.5,
            "volume": 1000.0,
        }
        for code in codes
    ]
    with MarketStore(tmp_path / "market.db") as store:
        assert store.persist_quote_bar_receipts(receipts, bars, source="fixture") == len(codes)
        statements: list[str] = []
        store.conn.set_trace_callback(statements.append)
        evidence = store.source_evidence(start="2025-01-02", end="2025-01-02")
        store.conn.set_trace_callback(None)

    assert len(evidence["receipts"]) == len(codes)
    source = evidence["sources"][0]
    assert source["source_id"] == "fixture"
    assert source["rows"] == len(codes)
    assert source["codes"] == len(codes)
    assert source["first_date"] == "2025-01-02"
    assert source["last_date"] == "2025-01-02"
    assert source["last_fetched_at"]
    # 优化后：先按 receipt_id 索引取回执，禁止对每条 receipt 做 EXISTS 扫日 K
    assert not any("EXISTS" in statement.upper() for statement in statements)
    assert any("DISTINCT receipt_id FROM quotes_daily" in statement for statement in statements)


def test_source_evidence_chunks_large_code_lists(tmp_path: Path) -> None:
    codes = [f"{600000 + index:06d}" for index in range(1200)]
    receipts = [
        {
            "code": code,
            "lane": "hist_daily",
            "selected_source": "fixture",
            "attempts": [{"source_id": "fixture", "state": "selected"}],
        }
        for code in codes
    ]
    bars = [
        {
            "code": code,
            "date": "2025-01-02",
            "open": 10.0,
            "high": 11.0,
            "low": 9.0,
            "close": 10.5,
            "volume": 1000.0,
        }
        for code in codes
    ]
    with MarketStore(tmp_path / "market.db") as store:
        assert store.persist_quote_bar_receipts(receipts, bars, source="fixture") == len(codes)
        evidence = store.source_evidence(codes=codes, start="2025-01-02", end="2025-01-02")

    assert len(evidence["observed_codes"]) == len(codes)
    assert len(evidence["receipts"]) == len(codes)


def test_source_route_receipt_contract_preserves_scope_and_failure() -> None:
    receipt = SourceRouteReceipt(
        code="600519",
        lane="hist_daily",
        attempts=(SourceAttemptRecord(source_id="fixture", state="failed", error="timeout"),),
        unresolved=True,
        state="failed",
        request_start="2025-01-01",
        request_end="2025-01-31",
        error="timeout",
    ).to_dict()

    assert receipt["state"] == "failed"
    assert receipt["request_end"] == "2025-01-31"
    assert receipt["attempts"][0]["state"] == "failed"


def test_quote_receipt_round_trips_complete_pit_provenance(tmp_path: Path) -> None:
    receipt = {
        "code": "600519",
        "lane": "hist_daily",
        "requested_sources": ["fixture-a", "fixture-b"],
        "selected_source": "fixture-b",
        "fallback_used": True,
        "attempts": [
            {"source_id": "fixture-a", "state": "failed", "error": "timeout"},
            {"source_id": "fixture-b", "state": "selected", "rows": 2},
        ],
        "state": "selected",
        "source_url": "https://example.test",
        "published_at": "2025-01-02T09:00:00",
        "publication_status": "observed",
        "fetched_at": "2025-01-02T09:00:00",
        "as_of": "2025-01-02",
        "request_start": "2025-01-01",
        "request_end": "2025-01-31",
    }
    bars = [
        {
            "code": "600519",
            "date": "2025-01-02",
            "open": 10.0,
            "high": 11.0,
            "low": 9.0,
            "close": 10.5,
            "volume": 1000.0,
        }
    ]
    with MarketStore(tmp_path / "market.db") as store:
        written = store.persist_quote_bar_receipts([receipt], bars, source="fixture-b")
        assert written == 1
        evidence = store.source_evidence(codes=["600519"], start="2025-01-02", end="2025-01-02")

    assert evidence["observed_codes"] == ["600519"]
    assert evidence["unresolved_codes"] == []
    assert evidence["sources"][0]["source_id"] == "fixture-b"
    detail = evidence["receipts"][0]
    assert detail["fallback_used"] is True
    assert detail["payload_sha256"]
    assert detail["selected_source"] == "fixture-b"
    assert detail["source_url"] == "https://example.test"
    assert detail["publication_status"] == "observed"
    assert detail["published_at"] == "2025-01-02T09:00:00"
    assert len(detail["attempts"]) == 2


def test_failed_receipt_outside_range_is_excluded(tmp_path: Path) -> None:
    with MarketStore(tmp_path / "market.db") as store:
        store.persist_source_receipt(
            {
                "code": "600519",
                "lane": "hist_daily",
                "state": "failed",
                "unresolved": True,
                "attempts": [{"source_id": "fixture", "state": "failed", "error": "x"}],
                "request_start": "2024-01-01",
                "request_end": "2024-12-31",
                "coverage_start": "2024-01-01",
                "coverage_end": "2024-12-31",
            }
        )
        evidence = store.source_evidence(codes=["600519"], start="2025-01-01", end="2025-01-31")

    assert evidence["receipts"] == []
    assert evidence["unresolved_receipt_codes"] == []


def test_global_query_keeps_unlinked_failed_receipt(tmp_path: Path) -> None:
    with MarketStore(tmp_path / "market.db") as store:
        store.persist_source_receipt(
            {
                "code": "600519",
                "lane": "hist_daily",
                "state": "failed",
                "unresolved": True,
                "attempts": [{"source_id": "fixture", "state": "failed", "error": "x"}],
                "request_start": "2025-02-01",
                "request_end": "2025-02-28",
                "coverage_start": "2025-02-01",
                "coverage_end": "2025-02-28",
            }
        )
        evidence = store.source_evidence(start="2025-02-01", end="2025-02-28")

    assert len(evidence["receipts"]) == 1
    assert evidence["receipts"][0]["state"] == "failed"
    # 无 requested_codes 时 unresolved_codes 为空；未解析回执从 receipts 侧暴露
    assert evidence["unresolved_receipt_codes"] == ["600519"]