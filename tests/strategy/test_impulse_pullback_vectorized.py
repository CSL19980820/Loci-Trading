"""优化前逐行算法的冻结对照：逐因子精确比较，不能用近似相等掩盖阈值变化。"""
from typing import Any

import numpy as np
import pandas as pd
import pytest

from src.formula import ZTPRICE
from src.strategy.application.impulse_pullback import (
    ImpulsePullbackTailV1, _FACTORS, _FIELDS, _compute_stock,
)
from tests.strategy.test_impulse_pullback import fixture_bars, panels_for


def _reference_start_flags(bars, cy, df):
    o, h, _, c, _ = bars.T
    previous = np.concatenate(([np.nan], c[:-1]))
    ztj = ZTPRICE(pd.Series(previous), .10).to_numpy()
    zt = (np.abs(c - ztj) < .005) & (c == h)
    dz = (c >= previous * (1 + df)) & (c > o)
    return ztj, zt, dz, dz if cy else zt


def _reference_stock(bars: np.ndarray, cy: bool, p: dict[str, Any]) -> dict[str, np.ndarray]:
    o, h, l, c, v = bars.T
    count = len(c)
    out = {name: np.full(count, np.nan) for name in _FACTORS}
    ztj, zt, dz, qd = _reference_start_flags(bars, cy, p["DF"])
    out.update(CY=np.full(count, float(cy)), ZTJ=ztj, ZT=zt.astype(float),
               DZ=dz.astype(float), QD=qd.astype(float))
    valid = np.isfinite(bars).all(axis=1)
    # BARSCOUNT是从首个有效C到当前的周期数；部分损坏行不得挤掉周期。
    available = np.flatnonzero(np.isfinite(c))
    if available.size:
        out["BARSCOUNT"][available[0]:] = np.arange(1, count - available[0] + 1)
    last = -1
    for i in range(count):
        # 先计算今天的信号，再更新今天的启动，等价REF(QD,1)。
        out["QD_COUNT"][i] = float(qd[max(0, i - p["TS"]):i].sum())
        out["WD"][i] = float(i >= 2 and l[i - 1] >= l[i - 2] and l[i] >= l[i - 1])
        out["ZQ"][i] = float(i >= 1 and c[i] > o[i] and c[i] > h[i - 1] and v[i] > v[i - 1])
        out["XG"][i] = out["DATA_OK"][i] = out["PRE"][i] = 0.0
        if last >= 0:
            t = i - last
            n = max(t - 1, 1)
            bcp, bop, bvl = c[last], o[last], v[last]
            mid = (bcp + bop) / 2
            for name, value in (("T", t), ("N", n), ("BCP", bcp), ("BOP", bop),
                                ("BVL", bvl), ("MIDP", mid)):
                out[name][i] = value
            out["YB"][i] = float(bcp > bop and h[last] > l[last])
            out["SJ"][i] = float(out["QD_COUNT"][i] > 0 and 3 <= t <= p["TS"]
                                  and out["BARSCOUNT"][i] >= 60)
            closes = c[max(0, i - n):i]
            volumes = v[max(0, i - n):i]
            minimum = np.min(closes)
            out["HL"][i] = float(minimum < bcp)
            out["WH"][i] = float(minimum >= mid and l[i] >= mid)
            out["SX"][i] = float(np.sum(volumes) / n <= bvl * p["SL"])
            out["WZ"][i] = float(c[i] <= bcp * (1 + p["ZF"]))
            # 锚点前一日参与QD计算；其后的坏行可能隐藏一次新的启动。
            out["DATA_OK"][i] = float(valid[max(0, last - 1):i + 1].all())
            out["PRE"][i] = float(
                all(out[name][i] == 1 for name in ("SJ", "YB", "HL", "SX"))
                and minimum >= mid and i >= 2 and l[i - 1] >= l[i - 2]
                and valid[max(0, last - 1):i].all()
            )
            gates = ("SJ", "YB", "HL", "WH", "SX", "WD", "ZQ", "WZ", "DATA_OK")
            out["XG"][i] = float(all(out[name][i] == 1 for name in gates))
        if qd[i]:
            last = i
    return out


def _assert_factors(actual, expected):
    assert actual.keys() == expected.keys()
    for name in actual:
        np.testing.assert_array_equal(actual[name], expected[name], err_msg=name, strict=True)


@pytest.mark.parametrize("seed", range(12))
@pytest.mark.parametrize("cy", [False, True])
@pytest.mark.parametrize("order", ["C", "F"])
def test_all_factors_equal_original_with_missing_and_nonfinite_bars(seed, cy, order):
    rng = np.random.default_rng(seed)
    rows = rng.uniform(5, 15, (180, 5))
    rows[:, 4] = rng.lognormal(8, 4, len(rows))
    # 多段连续启动与不同长度整理，避免随机 OHLC 恰好从未命中主板启动。
    for anchor in range(5, 175, 13):
        rows[anchor, 0] = rows[anchor - 1, 3]
        close = np.floor(rows[anchor - 1, 3] * 1.1 * 100 + .5 + 1e-9) / 100
        rows[anchor, [1, 3]] = close
    rows[:3, 3] = np.nan
    rows[31, 2] = np.nan
    rows[54, 3] = np.nan
    rows[80, 4] = np.inf
    rows[93, 4] = -np.inf
    rows[103] = np.nan
    rows = np.array(rows, order=order)
    params = {"DF": [0., .1, .2][seed % 3], "TS": [3, 10, 200][seed % 3],
              "SL": [.0, .8, 1.][seed % 3], "ZF": [.0, .03, .1][seed % 3]}
    with np.errstate(invalid="ignore"):
        _assert_factors(_compute_stock(rows, cy, params), _reference_stock(rows, cy, params))


@pytest.mark.parametrize("distance", [1, 2, 3, 10, 11, 60, 100])
@pytest.mark.parametrize("direction", [-np.inf, 0., np.inf])
def test_volume_threshold_and_long_window_keep_original_reduction(distance, direction):
    rows = fixture_bars(length=180, distance=distance)
    anchor = len(rows) - distance - 1
    rng = np.random.default_rng(distance)
    # 大小数量级混合会放大前缀和减法和求和次序的舍入差。
    rows[anchor + 1:-1, 4] = rng.lognormal(8, 15, distance - 1)
    width = max(distance - 1, 1)
    volume_mean = np.sum(rows[-1 - width:-1, 4]) / width
    rows[anchor, 4] = volume_mean if direction == 0 else np.nextafter(volume_mean, direction)
    params = {"DF": .1, "TS": 180, "SL": 1., "ZF": .03}
    _assert_factors(_compute_stock(rows, False, params), _reference_stock(rows, False, params))


def test_panel_factors_preserve_suspensions_partial_rows_and_column_order():
    rows = fixture_bars(length=80)
    panels = panels_for(rows, ("300123", "000001", "688123", "empty"))
    for field in panels.values():
        field.loc[:, "empty"] = np.nan
        field.iloc[5:8, 0] = np.nan
        field.iloc[35, 1] = np.nan
    panels["low"].iloc[76, 2] = np.nan
    panels["close"].iloc[:2, 1] = np.nan
    engine = ImpulsePullbackTailV1()
    actual = engine.compute(panels)
    for column, code in enumerate(actual.signals.columns):
        raw = np.column_stack([panels[name].iloc[:, column].to_numpy(float) for name in _FIELDS])
        positions = np.flatnonzero(~np.isnan(raw).all(axis=1))
        expected = {name: np.full(len(rows), np.nan) for name in _FACTORS}
        expected["XG"].fill(0)
        expected["DATA_OK"].fill(0)
        if positions.size:
            computed = _reference_stock(raw[positions], code.startswith("30"), engine.default_params())
            for name, values in computed.items():
                expected[name][positions] = values
        _assert_factors({name: value.iloc[:, column].to_numpy() for name, value in actual.factors.items()}, expected)
        np.testing.assert_array_equal(actual.signals.iloc[:, column], expected["XG"] == 1)
    assert actual.signals.iloc[-1, :2].all()
    assert not actual.signals.iloc[-1, 2:].any()


@pytest.mark.parametrize("shape", [(0, 2), (4, 0)])
def test_empty_panel_shapes_remain_supported(shape):
    panels = {name: pd.DataFrame(np.empty(shape)) for name in _FIELDS}
    result = ImpulsePullbackTailV1().compute(panels)
    assert result.signals.shape == shape
    assert all(frame.shape == shape for frame in result.factors.values())


@pytest.mark.parametrize("seed", [45, 88])
def test_batch_boundaries_preserve_each_stock_history_and_all_factors(seed):
    rng = np.random.default_rng(seed)
    count, length = 259, 180
    cube = np.stack([fixture_bars(length=length, distance=int(rng.integers(2, 120)))
                     for _ in range(count)], axis=1)
    cube[:, :, 4] *= rng.lognormal(0, 8, size=(length, count))
    # 整列缺失、不同上市长度/停牌位置、部分坏行都必须按本股票独立压缩。
    cube[rng.random((length, count)) < .05] = np.nan
    cube[:, 128] = np.nan
    cube[:35, 127] = np.nan
    cube[76, 256, 2] = np.nan
    cube[60, 129, 4] = np.inf
    codes = [f"{30 if i % 2 else 60}{i:04}" for i in range(count)]
    panels = {field: pd.DataFrame(cube[:, :, k], columns=codes)
              for k, field in enumerate(_FIELDS)}
    actual = ImpulsePullbackTailV1().compute(panels)
    for column, code in enumerate(codes):
        bars = cube[:, column]
        positions = np.flatnonzero(~np.isnan(bars).all(axis=1))
        expected = {name: np.full(length, np.nan) for name in _FACTORS}
        expected["XG"].fill(0)
        expected["DATA_OK"].fill(0)
        if positions.size:
            values = _reference_stock(bars[positions], code.startswith("30"),
                                      ImpulsePullbackTailV1().default_params())
            for name, array in values.items():
                expected[name][positions] = array
        _assert_factors({name: frame.iloc[:, column].to_numpy() for name, frame in actual.factors.items()}, expected)
        np.testing.assert_array_equal(actual.signals.iloc[:, column], expected["XG"] == 1)
