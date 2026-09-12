"""相同热库不重复重写；同日旁路修订和回执更新不能被跳过。"""
from collections.abc import Iterator
from pathlib import Path

import pytest

from src.market import MarketStore, mirror_recent_to_hot, mirror_to_hot


@pytest.fixture
def stores(tmp_path: Path) -> Iterator[tuple[MarketStore, MarketStore]]:
    with MarketStore(tmp_path / "full.db") as full, MarketStore(tmp_path / "hot.db", keep_receipt_index=True) as hot:
        full.upsert_instruments([{"code": "000001", "name": "夹具", "market": "SZ", "instrument_type": "STOCK"}])
        full.persist_quote_bar_receipts(
            [{"code": "000001", "lane": "hist_daily", "selected_source": "fixture",
              "attempts": [{"source_id": "fixture", "state": "selected", "rows": 8}]}],
            [{"code": "000001", "date": f"2026-01-{day:02d}", "open": 10., "high": 11.,
              "low": 9., "close": 10.5, "volume": 1000.} for day in range(1, 9)], source="fixture",
        )
        mirror_to_hot(full, hot, window_trading_days=8)
        yield full, hot


def test_unchanged_increment_does_not_rewrite_quotes_or_receipts(stores) -> None:
    full, hot = stores
    changes = hot.conn.total_changes
    result = mirror_recent_to_hot(full, hot, window_trading_days=8)
    assert result["quotes"] == 0
    assert hot.conn.total_changes == changes
    assert hot.conn.execute("SELECT COUNT(*) FROM quotes_daily").fetchone()[0] == 8


@pytest.mark.parametrize("column,value", [("close", 10.75), ("volume", 1234.), ("turnover", .03)])
def test_same_day_direct_update_without_revision_is_mirrored(stores, column: str, value: float) -> None:
    full, hot = stores
    revision = full.market_revision()
    full.conn.execute(f"UPDATE quotes_daily SET {column}=? WHERE trade_date='2026-01-08'", (value,))
    full.conn.commit()
    assert full.market_revision() == revision
    result = mirror_recent_to_hot(full, hot, window_trading_days=8)
    assert result["quotes"] == 7
    assert hot.conn.execute(f"SELECT {column} FROM quotes_daily WHERE trade_date='2026-01-08'").fetchone()[0] == value


def test_receipt_only_change_is_copied_without_rewriting_quotes(stores) -> None:
    full, hot = stores
    full.conn.execute("UPDATE source_route_receipts SET error='revised provenance'")
    full.conn.execute("UPDATE source_route_attempts SET error='revised attempt'")
    full.conn.commit()
    result = mirror_recent_to_hot(full, hot, window_trading_days=8)
    assert result["quotes"] == 0
    assert hot.conn.execute("SELECT error FROM source_route_receipts").fetchone()[0] == "revised provenance"
    assert hot.conn.execute("SELECT error FROM source_route_attempts").fetchone()[0] == "revised attempt"


def test_removed_source_quote_is_removed_from_hot(stores) -> None:
    full, hot = stores
    full.conn.execute("DELETE FROM quotes_daily WHERE trade_date='2026-01-08'")
    full.conn.commit()
    mirror_recent_to_hot(full, hot, window_trading_days=8)
    assert hot.conn.execute("SELECT COUNT(*) FROM quotes_daily WHERE trade_date='2026-01-08'").fetchone()[0] == 0


def test_explicit_rebuild_still_rewrites_full_window(stores) -> None:
    full, hot = stores
    result = mirror_to_hot(full, hot, window_trading_days=8)
    assert result["quotes"] == 8
    assert result["mode"] == "rebuild"
