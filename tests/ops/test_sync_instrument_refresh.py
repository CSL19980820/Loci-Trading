"""托管行情任务每天先刷新一次证券目录。"""
from __future__ import annotations

from datetime import date, timedelta
import unittest
from unittest.mock import patch

from src.ops.application.jobs import JobContext, execute_sync


class DailyInstrumentRefreshTests(unittest.TestCase):
    def test_stale_snapshot_is_refreshed_before_sync_codes_are_selected(self) -> None:
        instruments = [
            {"code": "600611", "instrument_type": "STOCK"},
            {"code": "920305", "instrument_type": "STOCK"},
        ]
        sync_calls = 0
        spot_codes: list[str] = []

        class FakeStore:
            def __init__(self, path: str | None = None) -> None:
                self.db_path = path or ":memory:"

            def __enter__(self) -> "FakeStore":
                return self

            def __exit__(self, *_args: object) -> bool:
                return False

            def close(self) -> None:
                return None

            def instrument_snapshot_date(self) -> str:
                return (date.today() - timedelta(days=1)).isoformat()

            def list_instruments(self) -> list[dict[str, str]]:
                return list(instruments)

        def refresh(_store: FakeStore) -> int:
            nonlocal sync_calls
            sync_calls += 1
            instruments[:] = [row for row in instruments if row["code"] != "920305"]
            return len(instruments)

        def spot(_store: FakeStore, codes: list[str], **_kwargs: object) -> int:
            spot_codes.extend(codes)
            return 0

        context = JobContext(market_db=":memory:", market_hot_db=":memory:")
        with (
            patch("src.market.MarketStore", FakeStore),
            patch("src.market.open_market_hot", FakeStore),
            patch("src.market.sync_instruments", refresh),
            patch("src.market.apply_today_spot", spot),
            patch("src.market.backfill_missing_turnover", lambda *_a, **_k: {}),
            patch(
                "src.market.mirror_recent_to_hot",
                lambda *_a, **_k: {"mode": "skip", "quotes": 0, "end": ""},
            ),
        ):
            result = execute_sync(
                {
                    "mode": "today_refresh",
                    "with_factors": False,
                    "refresh_instruments_daily": True,
                },
                context,
            )

        self.assertEqual(sync_calls, 1)
        self.assertEqual(spot_codes, ["600611"])
        self.assertEqual(result["instrument_refresh"]["status"], "refreshed")


if __name__ == "__main__":
    unittest.main()
