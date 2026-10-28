"""成功取数的回执不能因为后备源未请求就被写成 skipped。

盘中每 5 分钟的增量同步会重写近窗行情与回执；若成功回执被降级成 skipped，
收盘定稿核验就会把前一交易日的证明抹掉（线上 2026-10-21 事故）。
"""
from __future__ import annotations

import pandas as pd

from src.market import MarketStore


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        [{
            "date": "2026-10-20", "open": 1.0, "high": 1.1, "low": 0.9,
            "close": 1.05, "volume": 100.0, "amount": 105.0,
        }]
    )


def _state(store: MarketStore) -> tuple[str, str]:
    row = store.conn.execute(
        "SELECT state, selected_source FROM source_route_receipts WHERE code='000001'"
    ).fetchone()
    return (str(row[0]), str(row[1]))


def test_unrequested_backup_source_does_not_downgrade_success(tmp_path):
    with MarketStore(tmp_path / "market.db") as store:
        store.persist_quote_frame_receipts([(
            {
                "code": "000001",
                "lane": "hist_daily",
                "selected_source": "tdx",
                "unresolved": False,
                "attempts": [
                    {"source_id": "tdx", "state": "attempted"},
                    {"source_id": "tdx", "state": "selected", "rows": 1},
                    {
                        "source_id": "sina",
                        "state": "skipped",
                        "error": "主源命中，本轮未抽中交叉校验，该源未请求",
                    },
                ],
            },
            _frame(),
            "tdx",
        )])
        assert _state(store) == ("selected", "tdx")


def test_watermark_skip_receipt_stays_skipped(tmp_path):
    with MarketStore(tmp_path / "market.db") as store:
        store.persist_source_receipt({
            "code": "000001",
            "lane": "hist_daily",
            "selected_source": "tdx",
            "unresolved": False,
            "attempts": [{"source_id": "watermark", "state": "skipped"}],
        })
        assert _state(store) == ("skipped", "tdx")


def test_failed_fetch_receipt_stays_failed(tmp_path):
    with MarketStore(tmp_path / "market.db") as store:
        store.persist_source_receipt({
            "code": "000001",
            "lane": "hist_daily",
            "selected_source": "",
            "unresolved": True,
            "attempts": [{"source_id": "tdx", "state": "failed", "error": "超时"}],
        })
        assert _state(store) == ("failed", "")
