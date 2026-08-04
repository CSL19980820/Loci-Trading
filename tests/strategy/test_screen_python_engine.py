from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import pandas as pd

from src.strategy.application.screen_python import (
    ScreenPythonError,
    build_python_engine,
)


def _payload(code: str | None = None) -> dict:
    return {
        "slug": "python-screen",
        "name": "Python 战法",
        "description": "Python 版放量均线",
        "runtime": "python",
        "dialect": "python",
        "entrypoint": "strategy.py:compute",
        "code": code
        or (
            "def compute(panels, params):\n"
            "    close = panels['close']\n"
            "    volume = panels['volume']\n"
            "    base = close.rolling(int(params['N'])).mean()\n"
            "    volr = volume / volume.rolling(3).mean()\n"
            "    return {'signals': (close > base) & (volr >= params['VOL_MULT']), 'factors': {'BASE': base, 'VOLR': volr}}\n"
        ),
        "manifest": {
            "schema_version": 2,
            "entry_timing": "next_open",
            "min_bars": 3,
            "params": {
                "N": {"type": "int", "default": 3, "min": 2, "max": 10, "label": "周期"},
                "VOL_MULT": {"type": "float", "default": 1.2, "min": 0.5, "max": 5.0, "label": "量比"},
            },
            "output": {"signal": "PICK"},
            "factors": ["BASE", "VOLR"],
            "logic": [],
            "references": [],
            "data": {
                "fields": ["close", "volume"],
                "adjust": "qfq",
                "universe": {"codes_include": ["600001"]},
            },
        },
    }


def _panels() -> dict[str, pd.DataFrame]:
    index = ["2026-07-24", "2026-07-25", "2026-07-28"]
    return {
        "close": pd.DataFrame({"600001": [10.0, 10.2, 10.6], "600002": [10.0, 10.0, 10.0]}, index=index),
        "volume": pd.DataFrame({"600001": [100.0, 110.0, 180.0], "600002": [100.0, 100.0, 100.0]}, index=index),
    }


class ScreenPythonEngineTests(unittest.TestCase):
    def test_validate_rejects_syntax_error_without_running_compute(self) -> None:
        engine = build_python_engine(_payload("def compute(panels, params)\n    return {}\n"))

        with self.assertRaises(ScreenPythonError) as caught:
            engine.validate()

        diagnostic = caught.exception.diagnostics[0]
        self.assertEqual(diagnostic.code, "E_PYTHON_SYNTAX")
        self.assertEqual(diagnostic.line, 1)

    def test_engine_computes_signal_from_inline_code(self) -> None:
        engine = build_python_engine(_payload())
        result = engine.compute(_panels())
        self.assertEqual(result.picks_on("2026-07-28"), ["600001"])
        self.assertEqual(engine.required_fields(), ("close", "volume"))
        self.assertEqual(engine.min_bars(), 3)
        self.assertEqual(engine.adjust, "qfq")
        self.assertEqual(engine.default_universe, {"codes_include": ["600001"]})

    def test_engine_loads_local_helper_modules_from_package_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "helpers.py").write_text(
                "def build(close):\n"
                "    return {'signals': close > close.rolling(2).mean(), 'factors': {}}\n",
                encoding="utf-8",
            )
            (root / "strategy.py").write_text(
                "from helpers import build\n\n"
                "def compute(panels, params):\n"
                "    return build(panels['close'])\n",
                encoding="utf-8",
            )
            engine = build_python_engine({**_payload(""), "install_path": str(root), "code": "def compute(*args, **kwargs):\n    raise RuntimeError('unused')\n"})
            result = engine.compute(_panels())
        self.assertEqual(result.picks_on("2026-07-28"), ["600001"])

    def test_engines_isolate_same_named_helpers_and_revision_tracks_helper_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "helpers.py").write_text(
                "def build(close):\n"
                "    return {'signals': close > 0, 'factors': {}}\n",
                encoding="utf-8",
            )
            (root / "strategy.py").write_text(
                "from helpers import build\n\n"
                "def compute(panels, params):\n"
                "    return build(panels['close'])\n",
                encoding="utf-8",
            )
            payload = {
                **_payload("def compute(*args, **kwargs):\n    raise RuntimeError('unused')\n"),
                "install_path": str(root),
            }
            first = build_python_engine(payload)
            first_result = first.compute(_panels())

            (root / "helpers.py").write_text(
                "def build(close):\n"
                "    return {'signals': close < 0, 'factors': {}}\n",
                encoding="utf-8",
            )
            second = build_python_engine(payload)
            second_result = second.compute(_panels())

        self.assertEqual(first_result.picks_on("2026-07-28"), ["600001", "600002"])
        self.assertEqual(second_result.picks_on("2026-07-28"), [])
        self.assertNotEqual(first.strategy_revision, second.strategy_revision)

    def test_engine_rejects_unknown_runtime_params(self) -> None:
        engine = build_python_engine(_payload())
        with self.assertRaises(ScreenPythonError) as caught:
            engine.compute(_panels(), {"UNKNOWN": 1})
        self.assertEqual(caught.exception.diagnostics[0].code, "E_PARAM_UNKNOWN")

    def test_import_failure_exposes_entrypoint_relative_file_and_bounded_trace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bad_helper.py").write_text(
                "raise RuntimeError('boom import')\n",
                encoding="utf-8",
            )
            (root / "strategy.py").write_text(
                "import bad_helper\n\n"
                "def compute(panels, params):\n"
                "    return {'signals': panels['close'] > 0, 'factors': {}}\n",
                encoding="utf-8",
            )
            engine = build_python_engine(
                {
                    **_payload(""),
                    "install_path": str(root),
                    "code": "def compute(*args, **kwargs):\n    raise RuntimeError('unused')\n",
                }
            )
            with self.assertRaises(ScreenPythonError) as caught:
                engine.compute(_panels())
        diagnostic = caught.exception.diagnostics[0]
        self.assertEqual(diagnostic.code, "E_PYTHON_IMPORT")
        self.assertIn("entrypoint=strategy.py:<module>", diagnostic.message)
        self.assertIn("file=strategy.py", diagnostic.message)
        self.assertIn("bad_helper.py", diagnostic.message)
        self.assertIn("boom import", diagnostic.message)
        self.assertLess(len(diagnostic.message), 500)

    def test_compute_failure_exposes_entrypoint_relative_file_and_bounded_trace(self) -> None:
        engine = build_python_engine(
            _payload(
                "def compute(panels, params):\n"
                "    raise RuntimeError('boom compute')\n"
            )
        )
        with self.assertRaises(ScreenPythonError) as caught:
            engine.compute(_panels())
        diagnostic = caught.exception.diagnostics[0]
        self.assertEqual(diagnostic.code, "E_PYTHON_EXEC")
        self.assertIn("entrypoint=strategy.py:compute", diagnostic.message)
        self.assertIn("file=strategy.py", diagnostic.message)
        self.assertIn("boom compute", diagnostic.message)
        self.assertIn("strategy.py", diagnostic.message)
        self.assertLess(len(diagnostic.message), 500)


if __name__ == "__main__":
    unittest.main()
