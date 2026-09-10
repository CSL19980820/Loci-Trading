"""写入不许污染已有真值。

行情库是缓存，但缓存被写脏之后没人会发现——换手率、成交额这些数字会一路
流进选股条件和复盘结论里。这一组钉住两条：缺列的源不许把已有值抹成 NULL，
单位错位的残留行不许被"修复"成看着正常的假数字。
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.market.infrastructure.store import MarketStore
from src.market.infrastructure.turnover_math import INSANE_TURNOVER
from src.market.infrastructure.turnover_repair import (
    _infer_shares,
    backfill_missing_turnover,
    load_shares_asof,
)


@pytest.fixture()
def store(tmp_path: Path):
    market = MarketStore(tmp_path / "market.db")
    try:
        yield market
    finally:
        market.close()


def _full_row(**overrides) -> pd.DataFrame:
    row = {
        "date": "2026-08-07",
        "open": 10.0,
        "high": 11.0,
        "low": 9.0,
        "close": 10.5,
        "volume": 2_000_000.0,
        "amount": 21_000_000.0,
        "outstanding_share": 1e9,
        "turnover": 0.002,
    }
    row.update(overrides)
    return pd.DataFrame([row])


def _stored(store: MarketStore, column: str):
    return store.conn.execute(
        f"SELECT {column} FROM quotes_daily WHERE code = '600519'"
    ).fetchone()[0]


class TestUpsertKeepsKnownValues:
    def test_source_without_amount_does_not_erase_the_stored_amount(
        self, store: MarketStore
    ) -> None:
        """成交额是换手率主口径的分子，被抹成 NULL 会让换手整列退化。"""
        store.upsert_quotes("600519", _full_row(), source="sina")

        thin = _full_row()
        store.upsert_quotes("600519", thin.drop(columns=["amount"]), source="tencent")

        assert _stored(store, "amount") == pytest.approx(21_000_000.0)

    def test_source_without_volume_does_not_erase_the_stored_volume(
        self, store: MarketStore
    ) -> None:
        store.upsert_quotes("600519", _full_row(), source="sina")

        thin = _full_row()
        store.upsert_quotes("600519", thin.drop(columns=["volume"]), source="tencent")

        assert _stored(store, "volume") == pytest.approx(2_000_000.0)

    def test_a_real_zero_still_overwrites(self, store: MarketStore) -> None:
        """停牌日的 0 是事实，不能被 COALESCE 当成缺失挡回去。"""
        store.upsert_quotes("600519", _full_row(), source="sina")
        store.upsert_quotes(
            "600519", _full_row(volume=0.0, amount=0.0), source="sina"
        )

        assert _stored(store, "volume") == 0.0
        assert _stored(store, "amount") == 0.0

    def test_corrected_ohlc_still_overwrites(self, store: MarketStore) -> None:
        """量额改成 COALESCE 之后，价格列必须仍然照常被修正值覆盖。"""
        store.upsert_quotes("600519", _full_row(), source="sina")
        store.upsert_quotes(
            "600519",
            _full_row(open=10.2, high=11.5, low=9.5, close=11.0),
            source="sina",
        )

        assert _stored(store, "close") == pytest.approx(11.0)
        assert _stored(store, "high") == pytest.approx(11.5)


class TestShareInferenceRefusesDirtyRows:
    def test_insane_turnover_is_not_used_to_infer_shares(self) -> None:
        """5.0 = 500%，是单位错位的残留；拿它当除数会得到小 100 倍的股本。"""
        assert (
            _infer_shares(2_000_000.0, 5.0, amount=21_000_000.0, close=10.5) is None
        )

    def test_a_sane_turnover_still_infers_shares(self) -> None:
        shares = _infer_shares(2_000_000.0, 0.02, amount=21_000_000.0, close=10.5)
        assert shares == pytest.approx(21_000_000.0 / (10.5 * 0.02))

    def test_dirty_row_does_not_seed_asof_shares(self, store: MarketStore) -> None:
        store.upsert_quotes(
            "600519",
            _full_row(
                date="2026-08-06",
                turnover=INSANE_TURNOVER + 4.5,
                outstanding_share=None,
            ),
            source="eastmoney",
        )

        assert load_shares_asof(store, "2026-08-07") == {}

    def test_dirty_row_does_not_get_laundered_into_a_plausible_turnover(
        self, store: MarketStore
    ) -> None:
        """脏行反推的股本会让另一天算出 ~20% 换手——低于闸门，于是被当合法值落库。"""
        store.upsert_quotes(
            "600519",
            _full_row(
                date="2026-08-06",
                turnover=5.0,
                outstanding_share=None,
                volume=2_000_000.0,
                amount=21_000_000.0,
                close=10.5,
            ),
            source="eastmoney",
        )
        store.upsert_quotes(
            "600519",
            _full_row(date="2026-08-07", turnover=None, outstanding_share=None),
            source="eastmoney",
        )

        backfill_missing_turnover(store, trade_dates=["2026-08-07"])

        row = store.conn.execute(
            "SELECT turnover, outstanding_share FROM quotes_daily"
            " WHERE code = '600519' AND trade_date = '2026-08-07'"
        ).fetchone()
        assert row[0] is None
        assert row[1] is None


def test_upsert_drops_rows_that_violate_ohlc_bounds(store: MarketStore) -> None:
    """四价自相矛盾的 K 线不许落库。

    库里一根 ``high < close`` 的日 K 不会让任何人报错：形态识别、涨跌幅、回测
    都照算，只是答案是错的。这条钉住 ``partition_valid_ohlc_rows`` 的每一条边界，
    包括「一字板四价相等仍然合法」——判据写成严格不等号就会把涨停板整片丢掉。
    """
    frame = pd.DataFrame(
        [
            # 一字板：四价相等，合法
            {"date": "2026-08-03", "open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0},
            {"date": "2026-08-04", "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5},
            # high 低于 close
            {"date": "2026-08-05", "open": 10.0, "high": 10.4, "low": 9.0, "close": 10.5},
            # high 低于 open
            {"date": "2026-08-06", "open": 10.6, "high": 10.4, "low": 9.0, "close": 10.0},
            # low 高于 close
            {"date": "2026-08-07", "open": 10.3, "high": 11.0, "low": 10.2, "close": 10.1},
            # low 高于 open
            {"date": "2026-08-10", "open": 9.9, "high": 11.0, "low": 10.2, "close": 10.5},
            # 非正价
            {"date": "2026-08-11", "open": 10.0, "high": 11.0, "low": 9.0, "close": 0.0},
            # 缺价
            {"date": "2026-08-12", "open": 10.0, "high": 11.0, "low": 9.0, "close": float("nan")},
        ]
    )

    assert store.upsert_quotes("600519", frame, source="test") == 2

    stored = [
        str(row[0])
        for row in store.conn.execute(
            "SELECT trade_date FROM quotes_daily ORDER BY trade_date"
        )
    ]
    assert stored == ["2026-08-03", "2026-08-04"]
