"""首板次日：正例、逐条件反例、开盘前视、动态参数与包隔离。"""
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
import yaml

from src.strategy.application.screen_python import ScreenPythonError, build_python_engine
from src.strategy.domain.base import signal_history_bars

ROOT = Path(__file__).resolve().parents[2] / "templates/skills/yixian-auction"


def make_engine():
    return build_python_engine({
        "slug": "yixian-auction", "name": "一线定乾坤·首板次日",
        "manifest": yaml.safe_load((ROOT / "screen.yaml").read_text(encoding="utf-8")),
        "code": (ROOT / "strategy.py").read_text(encoding="utf-8"),
    })


def fixture_panels():
    c = np.linspace(8, 12, 100)
    c[-7:-1] = [11.6, 11.2, 11.0, 11.2, 11.5, 11.7]
    c[-1] = round(c[-2] * 1.1, 2)
    c = np.r_[c, c[-1]]
    dates = pd.bdate_range("2026-01-01", periods=len(c)).strftime("%Y-%m-%d")
    v = np.full(len(c), 1000.)
    v[-5], v[-2] = 500, 2000
    arrays = {"open": c * .995, "high": c + .05, "low": c - .1, "close": c, "volume": v}
    panels = {f: pd.DataFrame({"000001": a}, index=dates) for f, a in arrays.items()}
    panels["high"].iloc[-2] = c[-2]
    return panels


def test_default_positive_and_explanations():
    result = make_engine().compute(fixture_panels())
    assert result.signals.iloc[-1, 0]
    row = {key: frame.iloc[-1, 0] for key, frame in result.factors.items()}
    assert row["SB"] == row["KJ"] == row["TJ"] == 1
    assert row["DL_COUNT"] == 1
    assert row["DIF"] > 0 and row["DEA"] > 0
    assert row["KP"] == pytest.approx(-.5)


@pytest.mark.parametrize("gap,expected", [(-5, True), (.5, True), (-5.001, False), (.501, False)])
def test_inclusive_open_bounds(gap, expected):
    panels = fixture_panels()
    panels["open"].iloc[-1] = panels["close"].iloc[-2, 0] * (1 + gap / 100)
    assert bool(make_engine().compute(panels).signals.iloc[-1, 0]) is expected


@pytest.mark.parametrize("params", [
    {"R": .5}, {"N": 100}, {"JQ": 1}, {"DL_LOOKBACK": 1}, {"DL_COUNT": 2},
    {"VOL_MA": 1}, {"DIF_MIN": 100}, {"DEA_MIN": 100}, {"MIN_BARS": 101},
    {"OPEN_MIN": 0}, {"OPEN_MAX": -1}, {"LIMIT_RATIO": .2},
])
def test_dynamic_thresholds_can_reject(params):
    assert not make_engine().compute(fixture_panels(), params).signals.iloc[-1, 0]


def test_open_only_and_future_cannot_change_signal_or_explanation():
    engine = make_engine()
    panels = fixture_panels()
    baseline = engine.compute(panels)
    for field in ("close", "high", "low", "volume"):
        panels[field].iloc[-1] = np.nan
    partial = engine.compute(panels)
    assert partial.signals.iloc[-1, 0]
    for key in baseline.factors:
        assert partial.factors[key].iloc[-1, 0] == pytest.approx(baseline.factors[key].iloc[-1, 0])
    for frame in panels.values():
        frame.loc["2099-01-01"] = 99999
    assert engine.compute(panels).signals.iloc[-2, 0]


@pytest.mark.parametrize("kind", ["not_limit", "not_high", "consecutive", "no_dry_volume", "no_boost", "bad_history", "zero_open"])
def test_each_original_gate(kind):
    panels = fixture_panels()
    if kind == "not_limit":
        panels["close"].iloc[-2] -= .01
    elif kind == "not_high":
        panels["high"].iloc[-2] += .01
    elif kind == "consecutive":
        panels["close"].iloc[-4] = round(panels["close"].iloc[-3, 0] / 1.1, 2)
        panels["high"].iloc[-3] = panels["close"].iloc[-3, 0]
    elif kind == "no_dry_volume":
        panels["volume"].iloc[-5] = 1000
    elif kind == "no_boost":
        panels["volume"].iloc[-2] = 500
    elif kind == "bad_history":
        panels["volume"].iloc[-4] = np.nan
    elif kind == "zero_open":
        panels["open"].iloc[-1] = 0
    assert not make_engine().compute(panels).signals.iloc[-1, 0]


def test_prefilter_uses_yesterday_and_dynamic_history():
    engine = make_engine()
    panels = fixture_panels()
    day = panels["open"].index[-1]
    assert engine.live_candidate_codes(panels, day, engine.default_params()) == ["000001"]
    assert engine.strict_live_ohlcv
    assert signal_history_bars(engine, params={"N": 900}) > 900
    assert signal_history_bars(engine, params={"MACD_SLOW": 100}) > signal_history_bars(engine)
    assert engine.default_universe["boards"] == ["main"]
    assert not engine.default_universe["exclude_st"]


@pytest.mark.parametrize("params", [{"N": 0}, {"N": 1.5}, {"N": True}, {"R": float("nan")},
    {"OPEN_MIN": 2, "OPEN_MAX": 1}, {"MACD_FAST": 26}, {"DL_COUNT": 6}, {"TYPO": 1}])
def test_invalid_params_fail(params):
    with pytest.raises(ScreenPythonError):
        make_engine().compute(fixture_panels(), params)


def test_real_screen_overlay_keeps_zero_volume_valid_open():
    from datetime import date
    from src.market.domain.universe import ResolvedUniverse
    from src.strategy.application.screener import screen

    panels = fixture_panels()
    today = date.today().isoformat()
    old = panels["open"].index[-1]
    panels = {key: frame.rename(index={old: today}) for key, frame in panels.items()}
    class Store:
        def trading_days(self, **kwargs):
            return panels["open"].index.tolist()
        def data_snapshot(self, **kwargs):
            return {"revision": "fixture"}
        def load_panel(self, **kwargs):
            return {key: frame.copy() for key, frame in panels.items()}
    opening = panels["close"].iloc[-2, 0] * .995
    quote = {"000001": {"open": opening, "close": opening, "high": opening,
                          "low": opening, "volume": 0}}
    universe = ResolvedUniverse(codes=["000001"], meta={}, spec={})
    with patch("src.strategy.application.screener.resolve_universe", return_value=universe), \
         patch("src.market.fetch_live_spot_bars", return_value=quote):
        result = screen(Store(), make_engine(), codes=["000001"], live_overlay=True)
    assert [row["code"] for row in result.picks] == ["000001"]
    assert result.data_snapshot["live_ohlcv"] == quote
    assert result.data_snapshot["live_overlay_codes"] == 1


def test_saved_defaults_are_dynamic_and_tenant_private():
    from src.ops import save_screen_package
    from src.shared.tenancy import tenant_scope
    from src.strategy import get
    from src.strategy.application.screen_skills import refresh_screen_strategy_catalog
    from src.strategy.domain.base import StrategyError

    files = {name: (ROOT / name).read_text(encoding="utf-8")
             for name in ("SKILL.md", "screen.yaml", "strategy.py")}
    with tenant_scope("yixian_a"):
        save_screen_package("yixian-auction", files)
        assert not refresh_screen_strategy_catalog()["rejected"]
        assert get("yixian-auction").compute(fixture_panels()).signals.iloc[-1, 0]
        manifest = yaml.safe_load(files["screen.yaml"])
        manifest["params"]["OPEN_MAX"]["default"] = -1.0
        files["screen.yaml"] = yaml.safe_dump(manifest, allow_unicode=True)
        save_screen_package("yixian-auction", files)
        refresh_screen_strategy_catalog()
        assert not get("yixian-auction").compute(fixture_panels()).signals.iloc[-1, 0]
        assert get("yixian-auction").default_params()["OPEN_MAX"] == -1.0
    with tenant_scope("yixian_b"):
        with pytest.raises(StrategyError, match="未注册"):
            get("yixian-auction")
