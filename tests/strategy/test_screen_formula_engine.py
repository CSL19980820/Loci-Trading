from __future__ import annotations

import unittest

import pandas as pd

from src.strategy.application.screen_formula import build_formula_engine


def _payload(formula: str) -> dict:
    return {
        "slug": "demo-screen",
        "name": "示例战法",
        "description": "放量站上均线",
        "formula": formula,
        "manifest": {
            "schema_version": 1,
            "entry_timing": "next_open",
            "min_bars": 10,
            "params": {
                "N": {"type": "int", "default": 3, "min": 2, "max": 10, "label": "周期"},
            },
            "output": {"signal": "PICK"},
            "factors": ["BASE"],
        },
    }


def _panels() -> dict[str, pd.DataFrame]:
    index = ["2026-07-24", "2026-07-25", "2026-07-28"]
    return {
        "open": pd.DataFrame({"600001": [10.0, 10.1, 10.3], "600002": [10.0, 10.0, 10.0]}, index=index),
        "high": pd.DataFrame({"600001": [10.1, 10.2, 10.5], "600002": [10.1, 10.0, 10.1]}, index=index),
        "low": pd.DataFrame({"600001": [9.9, 10.0, 10.2], "600002": [9.9, 9.9, 9.9]}, index=index),
        "close": pd.DataFrame({"600001": [10.0, 10.2, 10.6], "600002": [10.0, 10.0, 10.0]}, index=index),
        "volume": pd.DataFrame({"600001": [100.0, 110.0, 180.0], "600002": [100.0, 100.0, 100.0]}, index=index),
        "amount": pd.DataFrame({"600001": [1000.0, 1122.0, 1908.0], "600002": [1000.0, 1000.0, 1000.0]}, index=index),
        "turnover": pd.DataFrame({"600001": [0.01, 0.011, 0.018], "600002": [0.01, 0.01, 0.01]}, index=index),
    }


class ScreenFormulaEngineTests(unittest.TestCase):
    def test_engine_computes_signal_from_new_contract_payload(self) -> None:
        engine = build_formula_engine(
            _payload("BASE:=MA(CLOSE,N);\nPICK: CLOSE>BASE;\n")
        )
        result = engine.compute(_panels())
        self.assertEqual(result.picks_on("2026-07-28"), ["600001"])
        self.assertIn("BASE", result.explain("2026-07-28", "600001"))
        self.assertEqual(engine.required_fields(), ("close",))
        self.assertEqual(engine.min_bars(), 10)

    def test_strategy_revision_is_stable_across_trailing_newline_differences(self) -> None:
        no_newline = build_formula_engine(
            _payload("BASE:=MA(CLOSE,N);\nPICK: CLOSE>BASE;")
        )
        with_newline = build_formula_engine(
            _payload("BASE:=MA(CLOSE,N);\nPICK: CLOSE>BASE;\n")
        )
        self.assertEqual(no_newline.strategy_revision, with_newline.strategy_revision)

    def test_strategy_revision_changes_with_effective_data_selection(self) -> None:
        base = _payload("BASE:=MA(CLOSE,N);\nPICK: CLOSE>BASE;\n")
        base["manifest"]["data"] = {
            "fields": ["close"],
            "adjust": "qfq",
            "universe": {"preset": "default_a_share"},
        }
        changed = _payload("BASE:=MA(CLOSE,N);\nPICK: CLOSE>BASE;\n")
        changed["manifest"]["data"] = {
            "fields": ["close"],
            "adjust": "none",
            "universe": {"preset": "all_a_share"},
        }
        self.assertNotEqual(
            build_formula_engine(base).strategy_revision,
            build_formula_engine(changed).strategy_revision,
        )


if __name__ == "__main__":
    unittest.main()
