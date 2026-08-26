"""换手率单位校正：成交额优先，识别手量与多余 ×100。"""
from __future__ import annotations

import unittest

from src.market.infrastructure.turnover_math import (
    compute_turnover,
    normalize_trade_volume,
)


class TurnoverUnitTests(unittest.TestCase):
    def test_normalize_shrinks_hundredfold_inflated_volume(self) -> None:
        # 真实：约 86.9 万股；错写成 8896 万 → amount/(vol*close)≈0.01
        volume = 88_967_500.0
        amount = 49_073_681.0
        close = 56.5
        fixed = normalize_trade_volume(volume, amount=amount, close=close)
        self.assertAlmostEqual(fixed, volume / 100.0)
        self.assertAlmostEqual(amount / (fixed * close), 1.0, delta=0.05)

    def test_normalize_scales_lot_volume_to_shares(self) -> None:
        volume = 10_000.0  # 手
        amount = 10_500_000.0
        close = 10.5
        fixed = normalize_trade_volume(volume, amount=amount, close=close)
        self.assertAlmostEqual(fixed, 1_000_000.0)

    def test_compute_turnover_prefers_amount_over_inflated_volume(self) -> None:
        shares = 89_029_300.0
        turnover = compute_turnover(
            volume=88_967_500.0,
            amount=49_073_681.0,
            close=56.5,
            shares=shares,
            stored=0.999,
        )
        self.assertIsNotNone(turnover)
        assert turnover is not None
        self.assertLess(turnover, 0.02)
        self.assertGreater(turnover, 0.005)


if __name__ == "__main__":
    unittest.main()
