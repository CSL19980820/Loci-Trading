"""纸面资金视图单测。

两条最要紧的语义：
- 口径是**名义值**（层→钱的换算），不是可提现余额；系统不记已实现盈亏也不计佣金。
- 满仓只挡开新仓，**不挡减仓/换仓，更不挡任何扫描与预警**。
"""
from __future__ import annotations

import unittest

from src.ops.application.paper_capital import capital_prompt_note, derive_capital_view

_CABIN = {"max_layers": 10.0, "max_positions": 3}


class EmptyBookTests(unittest.TestCase):
    def test_flat_book_has_full_capacity(self) -> None:
        view = derive_capital_view(_CABIN, [], {})

        self.assertEqual(view.used_layers, 0.0)
        self.assertEqual(view.free_layers, 10.0)
        self.assertEqual(view.layer_nominal, 20_000.0)
        self.assertEqual(view.available_cash_nominal, 200_000.0)
        self.assertEqual(view.free_slots, 3)
        self.assertFalse(view.layers_full)
        self.assertFalse(view.slots_full)

    def test_cabin_config_overrides_default_capital(self) -> None:
        view = derive_capital_view(
            {"max_layers": 4.0, "max_positions": 2, "config": {"initial_capital": 80_000}},
            [],
            {},
        )
        self.assertEqual(view.initial_capital, 80_000.0)
        self.assertEqual(view.layer_nominal, 20_000.0)


class HoldingTests(unittest.TestCase):
    def _view(self, layers: float = 2.0, price: float = 11.0):
        positions = [
            {"code": "600001", "name": "测试", "layers": layers, "mark_cost": 10.0}
        ]
        return derive_capital_view(_CABIN, positions, {"600001": {"price": price}})

    def test_layers_translate_to_money(self) -> None:
        view = self._view(layers=2.0, price=10.0)

        self.assertEqual(view.used_layers, 2.0)
        self.assertEqual(view.deployed_nominal, 40_000.0)
        self.assertEqual(view.available_cash_nominal, 160_000.0)
        self.assertEqual(view.position_count, 1)
        self.assertEqual(view.free_slots, 2)

    def test_unrealized_pnl_uses_live_price(self) -> None:
        view = self._view(layers=2.0, price=11.0)

        self.assertAlmostEqual(view.positions[0]["pnl_pct"], 10.0)
        self.assertAlmostEqual(view.market_nominal, 44_000.0)
        self.assertAlmostEqual(view.unrealized_pnl_pct, 10.0)

    def test_missing_quote_falls_back_to_cost(self) -> None:
        """拿不到实时价时按成本记，绝不能凭空造一个价。"""
        view = derive_capital_view(
            _CABIN, [{"code": "600001", "layers": 1.0, "mark_cost": 10.0}], {}
        )
        self.assertEqual(view.positions[0]["price"], 10.0)
        self.assertEqual(view.positions[0]["pnl_pct"], 0.0)

    def test_zero_layer_rows_are_ignored(self) -> None:
        view = derive_capital_view(
            _CABIN, [{"code": "600001", "layers": 0.0, "mark_cost": 10.0}], {}
        )
        self.assertEqual(view.position_count, 0)


class FullBookTests(unittest.TestCase):
    def test_layers_full_is_detected(self) -> None:
        positions = [{"code": "60000%d" % i, "layers": 5.0, "mark_cost": 10.0} for i in range(2)]
        view = derive_capital_view(_CABIN, positions, {})

        self.assertTrue(view.layers_full)
        self.assertEqual(view.available_cash_nominal, 0.0)

    def test_slots_full_is_separate_from_layers_full(self) -> None:
        """3 只各 1 层：只数满了但还有 7 层空间——两种「满」要分开报。"""
        positions = [
            {"code": "60000%d" % i, "layers": 1.0, "mark_cost": 10.0} for i in range(3)
        ]
        view = derive_capital_view(_CABIN, positions, {})

        self.assertTrue(view.slots_full)
        self.assertFalse(view.layers_full)
        self.assertEqual(view.free_slots, 0)
        self.assertEqual(view.free_layers, 7.0)

    def test_prompt_tells_model_full_does_not_mean_idle(self) -> None:
        """满仓最容易让模型「什么都不做」；提示必须点明仍要评估换仓与止损。"""
        positions = [{"code": "60000%d" % i, "layers": 5.0, "mark_cost": 10.0} for i in range(2)]
        note = capital_prompt_note(derive_capital_view(_CABIN, positions, {}))

        self.assertIn("已满仓", note)
        self.assertIn("减仓", note)
        self.assertIn("止盈止损", note)

    def test_prompt_reports_capacity_when_not_full(self) -> None:
        note = capital_prompt_note(derive_capital_view(_CABIN, [], {}))

        self.assertIn("可用约 200000 元", note)
        self.assertNotIn("已满仓", note)


class RobustnessTests(unittest.TestCase):
    def test_garbage_inputs_do_not_explode(self) -> None:
        view = derive_capital_view(
            None, [{"code": "", "layers": "x"}, {"layers": 1.0}], None
        )
        self.assertEqual(view.position_count, 0)
        self.assertEqual(view.used_layers, 0.0)

    def test_view_is_json_serialisable(self) -> None:
        import json

        payload = derive_capital_view(_CABIN, [], {}).as_dict()
        self.assertIn("available_cash_nominal", json.loads(json.dumps(payload)))


if __name__ == "__main__":
    unittest.main()
