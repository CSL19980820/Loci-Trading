"""人工OHLCV夹具用于语义边界验证，不是行情或收益实测。"""
from decimal import Decimal, ROUND_HALF_UP

import numpy as np
import pandas as pd
import pytest

from src.strategy.application.impulse_pullback import ImpulsePullbackTailV1
from src.strategy.domain.base import StrategyError


FIELDS = ("open", "high", "low", "close", "volume")


def fixture_bars(length=70, distance=3):
    rows = [[9.9, 10.1, 9.8, 10.0, 100.0] for _ in range(length)]
    anchor = length - 1 - distance
    rows[anchor] = [10.0, 11.0, 10.0, 11.0, 1000.0]
    for i in range(anchor + 1, length - 1):
        rows[i] = [10.9, 10.95, 10.55, 10.8, 500.0]
    rows[-2] = [10.75, 10.85, 10.60, 10.70, 400.0]
    rows[-1] = [10.80, 11.05, 10.65, 11.0, 600.0]
    return np.array(rows, dtype=float)


def panels_for(rows, codes=("000001",)):
    index = pd.bdate_range("2026-01-01", periods=len(rows)).strftime("%Y-%m-%d")
    return {field: pd.DataFrame({code: rows[:, k] for code in codes}, index=index)
            for k, field in enumerate(FIELDS)}


def literal_reference(rows, code, params):
    """逐K字面解释，独立查找历史启动、切片、比较；不调用被测函数。"""
    records = [dict(zip(FIELDS, row)) for row in rows if not np.isnan(row).all()]
    starts = []
    result = []
    df, ts, sl, zf = (params[k] for k in ("DF", "TS", "SL", "ZF"))
    for i, row in enumerate(records):
        prev = records[i - 1] if i else None
        if prev is None or not np.isfinite(prev["close"]):
            qd = False
        elif code.startswith("30"):
            qd = row["close"] >= prev["close"] * (1 + df) and row["close"] > row["open"]
        else:
            ztj = float((Decimal(str(prev["close"])) * Decimal("1.10")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP))
            qd = abs(row["close"] - ztj) < .005 and row["close"] == row["high"]
        selected = False
        factors = {}
        if starts:
            anchor = starts[-1]
            t = i - anchor
            start = records[anchor]
            n = max(t - 1, 1)
            window = records[max(0, i - n):i]
            middle = (start["close"] + start["open"]) / 2
            minimum = min((r["close"] for r in window), default=float("nan"))
            factors = {
                "T": t,
                "N": n,
                "BCP": start["close"], "BOP": start["open"], "BVL": start["volume"],
                "MIDP": middle,
                "SJ": 3 <= t <= ts and i + 1 >= 60,
                "YB": start["close"] > start["open"] and start["high"] > start["low"],
                "HL": minimum < start["close"],
                "WH": minimum >= middle and row["low"] >= middle,
                "SX": sum(r["volume"] for r in window) / n <= start["volume"] * sl,
                "WD": i >= 2 and prev["low"] >= records[i - 2]["low"] and row["low"] >= prev["low"],
                "ZQ": row["close"] > row["open"] and row["close"] > prev["high"]
                      and row["volume"] > prev["volume"],
                "WZ": row["close"] <= start["close"] * (1 + zf),
                "DATA_OK": all(np.isfinite(list(r.values())).all()
                               for r in records[max(0, anchor - 1):i + 1]),
            }
            selected = all(factors[k] for k in ("SJ", "YB", "HL", "WH", "SX", "WD", "ZQ", "WZ", "DATA_OK"))
        result.append((selected, factors))
        if qd:
            starts.append(i)
    return result


@pytest.mark.parametrize("distance,expected", [(2, False), (3, True), (10, True), (11, False)])
@pytest.mark.parametrize("code", ["000001", "300001"])
def test_reference_and_window_boundaries(distance, expected, code):
    engine = ImpulsePullbackTailV1()
    rows = fixture_bars(distance=distance)
    actual = engine.compute(panels_for(rows, (code,)))
    reference = literal_reference(rows, code, engine.default_params())
    assert actual.signals[code].tolist() == [item[0] for item in reference]
    assert bool(actual.signals.iloc[-1, 0]) is expected
    for i, (_, factors) in enumerate(reference):
        for name, value in factors.items():
            assert actual.factors[name].iloc[i, 0] == value, (i, name)


@pytest.mark.parametrize("length,expected", [(59, False), (60, True)])
def test_barscount_boundary(length, expected):
    result = ImpulsePullbackTailV1().compute(panels_for(fixture_bars(length)))
    assert result.factors["BARSCOUNT"].iloc[-1, 0] == length
    assert bool(result.signals.iloc[-1, 0]) is expected


def test_today_start_keeps_previous_anchor_and_tomorrow_uses_new_start():
    rows = fixture_bars()
    rows[-1] = [10.8, 11.77, 10.65, 11.77, 600]
    result = ImpulsePullbackTailV1().compute(panels_for(rows))
    assert result.factors["QD"].iloc[-1, 0] == 1
    assert result.factors["T"].iloc[-1, 0] == 3
    rows = np.vstack([rows, [11.5, 11.7, 11.4, 11.6, 300]])
    result = ImpulsePullbackTailV1().compute(panels_for(rows))
    assert result.factors["T"].iloc[-1, 0] == 1
    assert result.factors["BCP"].iloc[-1, 0] == 11.77


def test_latest_consecutive_start_overrides_earlier():
    rows = fixture_bars(distance=4)
    rows[-4] = [11.1, 12.1, 11.1, 12.1, 1000]
    result = ImpulsePullbackTailV1().compute(panels_for(rows))
    assert result.factors["T"].iloc[-1, 0] == 3
    assert result.factors["BCP"].iloc[-1, 0] == 12.1


def test_chinext_need_not_close_at_high_and_no_compute_board_filter():
    rows = fixture_bars()
    rows[-4, 1] = 11.2
    result = ImpulsePullbackTailV1().compute(panels_for(rows, ("000001", "300001", "301001")))
    assert result.signals.iloc[-1].tolist() == [False, True, True]
    # 原稿对一切非30前缀都走固定10%，compute不得新增板块/ST排除。
    result = ImpulsePullbackTailV1().compute(panels_for(fixture_bars(), ("688001", "ST0001")))
    assert result.signals.iloc[-1].all()


def test_chinext_strict_gain_and_positive_body():
    rows = fixture_bars()
    for close, open_, expected in [(10.99, 10, 0), (11, 10, 1), (11, 11, 0)]:
        rows[-4, [0, 3]] = [open_, close]
        result = ImpulsePullbackTailV1().compute(panels_for(rows, ("300001",)))
        assert result.factors["QD"].iloc[-4, 0] == expected


def test_full_missing_row_is_not_a_bar_and_partial_row_fails_closed():
    rows = fixture_bars(length=60)
    rows = np.insert(rows, 58, np.nan, axis=0)
    result = ImpulsePullbackTailV1().compute(panels_for(rows))
    assert result.signals.iloc[-1, 0]
    assert not result.signals.iloc[58, 0]
    assert result.factors["T"].iloc[-1, 0] == 3
    assert result.factors["BARSCOUNT"].iloc[-1, 0] == 60
    rows[58] = [10.7, 10.8, np.nan, 10.7, 350]
    result = ImpulsePullbackTailV1().compute(panels_for(rows))
    assert result.factors["T"].iloc[-1, 0] == 4
    assert result.factors["DATA_OK"].iloc[-1, 0] == 0
    assert not result.signals.iloc[-1, 0]


@pytest.mark.parametrize("gate,changes", [
    ("YB", [(-4, 0, 11.0)]),
    ("HL", [(-3, 3, 11.0), (-2, 3, 11.0)]),
    ("WH", [(-2, 3, 10.49)]),
    ("SX", [(-3, 4, 1300.0)]),
    ("WD", [(-1, 2, 10.59)]),
    ("ZQ", [(-1, 4, 400.0)]),
    ("WZ", [(-1, 3, 11.34)]),
])
def test_each_original_gate_rejects(gate, changes):
    rows = fixture_bars()
    for row, column, value in changes:
        rows[row, column] = value
    result = ImpulsePullbackTailV1().compute(panels_for(rows))
    assert result.factors[gate].iloc[-1, 0] == 0
    assert not result.signals.iloc[-1, 0]


def test_inclusive_thresholds_and_strict_breakout():
    rows = fixture_bars()
    rows[-3, 4] = 1200  # (1200 + 400) / 2 == 1000 * .80
    rows[-3:, 2] = 10.5
    rows[-1, 3] = 11 * 1.03
    result = ImpulsePullbackTailV1().compute(panels_for(rows))
    assert result.signals.iloc[-1, 0]
    rows[-1, 3] = rows[-2, 1]
    result = ImpulsePullbackTailV1().compute(panels_for(rows))
    assert result.factors["ZQ"].iloc[-1, 0] == 0


def test_preserves_float_expression_without_epsilon_and_uses_half_up():
    rows = fixture_bars()
    rows[-5, 3] = 10.1
    rows[-4, 3] = rows[-4, 1] = 11.11
    result = ImpulsePullbackTailV1().compute(panels_for(rows, ("300001",)))
    assert result.factors["DZ"].iloc[-4, 0] == float(11.11 >= 10.1 * 1.1)
    rows[-5, 3] = 10.05
    rows[-4, 3] = rows[-4, 1] = 11.06
    result = ImpulsePullbackTailV1().compute(panels_for(rows))
    assert result.factors["ZTJ"].iloc[-4, 0] == 11.06
    assert result.factors["ZT"].iloc[-4, 0] == 1


def test_no_future_dependence():
    rows = fixture_bars()
    engine = ImpulsePullbackTailV1()
    before = engine.compute(panels_for(rows))
    after = engine.compute(panels_for(np.vstack([rows, [30, 40, 20, 35, 9000]])))
    pd.testing.assert_frame_equal(before.signals, after.signals.iloc[:-1])
    for name in before.factors:
        pd.testing.assert_frame_equal(before.factors[name], after.factors[name].iloc[:-1])


@pytest.mark.parametrize("params", [{"TS": 2}, {"TS": 3.1}, {"DF": np.inf}, {"SL": -1}, {"bad": 1}])
def test_invalid_parameters_are_rejected(params):
    with pytest.raises(StrategyError):
        ImpulsePullbackTailV1().compute(panels_for(fixture_bars()), params)


@pytest.mark.parametrize("length,expected", [(59, []), (60, ["000001"]), (70, ["000001"])])
def test_live_precandidates_need_59_prior_bars_only(length, expected):
    panels = panels_for(fixture_bars(length))
    assert ImpulsePullbackTailV1().live_candidate_codes(panels, panels["close"].index[-1]) == expected


def test_live_precandidates_never_read_today_or_future_prices():
    engine = ImpulsePullbackTailV1()
    panels = panels_for(fixture_bars(), ("000001", "300001"))
    day = panels["close"].index[-1]
    expected = engine.live_candidate_codes(panels, day)
    assert expected == ["000001", "300001"]
    for value in (0, 9999, np.nan):
        changed = {k: v.copy() for k, v in panels.items()}
        for field in changed.values():
            field.loc[day] = value
            field.loc["2099-01-01"] = value
        assert engine.live_candidate_codes(changed, day) == expected


def test_true_final_signals_are_always_in_live_precandidates():
    engine = ImpulsePullbackTailV1()
    rng = np.random.default_rng(521)
    # 保留肯定能命中的夹具，同时扰动多列历史与当前值，覆盖预条件边界。
    reference = panels_for(fixture_bars())
    panels = {k: pd.DataFrame(index=v.index) for k, v in reference.items()}
    for j in range(80):
        code = f"{30 if j % 2 else 60}{j:04d}"
        rows = fixture_bars(distance=int(rng.integers(2, 12)))
        if j % 5:
            rows[-3:, 2:4] += rng.uniform(-.3, .3, size=(3, 2))
            rows[-3:, 4] *= rng.uniform(.5, 2, size=3)
        for k, name in enumerate(FIELDS):
            panels[name][code] = rows[:, k]
    day = panels["close"].index[-1]
    pre = set(engine.live_candidate_codes(panels, day))
    final = set(engine.compute(panels).picks_on(day))
    assert final
    assert final <= pre


def test_precandidates_respect_suspension_compression_and_partial_corruption():
    rows = np.insert(fixture_bars(length=60), 58, np.nan, axis=0)
    panels = panels_for(rows)
    engine = ImpulsePullbackTailV1()
    day = panels["close"].index[-1]
    assert engine.live_candidate_codes(panels, day) == ["000001"]
    panels["open"].iloc[58, 0] = 10.5
    assert engine.live_candidate_codes(panels, day) == []
