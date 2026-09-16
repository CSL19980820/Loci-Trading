from __future__ import annotations

import hashlib
import json

import numpy as np
import pandas as pd
import pytest

from src.backtest.application.asof_signals import compute_asof_signals
from src.backtest.infrastructure.signal_dataset import (
    canonical_payload, dataset_directory, import_signal_dataset, load_signal_dataset, snapshot_rows,
)
from src.shared.tenancy import tenant_scope
from src.strategy.application.impulse_pullback import ImpulsePullbackTailV1
from src.strategy.domain.base import StrategyError


def fixture():
    rows = np.array([[9.9, 10.1, 9.8, 10., 100.]] * 70)
    rows[-4:] = [[10., 11., 10., 11., 1000.], [10.9, 10.95, 10.55, 10.8, 500.],
                  [10.75, 10.85, 10.6, 10.7, 400.], [10.8, 11.05, 10.65, 10.7, 900.]]
    dates = pd.bdate_range("2026-01-01", periods=70).strftime("%Y-%m-%d")
    panels = {f: pd.DataFrame({"300001": rows[:, i]}, index=dates)
              for i, f in enumerate(("open", "high", "low", "close", "volume"))}
    payload = {
        "schema": "asof-ohlcv-v1", "id": "test-asof", "strategy": "impulse-pullback-tail-v1",
        "params": ImpulsePullbackTailV1().default_params(),
        "coverage": {"time": "14:50", "volume_unit": "shares", "codes": ["300001"],
                     "start": dates[-1], "end": dates[-1]},
        "rows": [{"code": "300001", "date": dates[-1], "status": "observed",
                  "source_sha256": "a" * 64, "ohlcv": [10.8, 11.05, 10.65, 11., 600.]}],
    }
    return panels, payload, dates[-1]


def save(payload):
    directory = dataset_directory()
    directory.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(canonical_payload(payload)).hexdigest()
    path = directory / f"{payload['id']}.json"
    path.write_bytes(canonical_payload({"payload": payload, "sha256": digest}))
    return path


def test_actual_snapshot_can_signal_when_final_daily_close_does_not(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCI_DATA_DIR", str(tmp_path))
    panels, payload, day = fixture()
    with tenant_scope("__primary__"):
        save(payload)
        engine = ImpulsePullbackTailV1()
        assert not engine.compute(panels).signals.iloc[-1, 0]
        signals, evidence = compute_asof_signals(engine, panels, engine.default_params(),
            dataset_id="test-asof", start=day, end=day)
        assert signals.iloc[-1, 0]
        assert evidence["time"] == "14:50" and evidence["rows"] == 1
        assert panels["close"].iloc[-1, 0] == 10.7
        panels["close"].iloc[-1, 0] = 100.
        again, _ = compute_asof_signals(engine, panels, engine.default_params(),
            dataset_id="test-asof", start=day, end=day)
        pd.testing.assert_frame_equal(signals, again)


def test_previous_days_always_keep_final_daily_values():
    panels, payload, day = fixture()
    engine = ImpulsePullbackTailV1()
    before = {k: v.copy() for k, v in panels.items()}
    engine.compute_asof(panels, snapshot_rows(payload), start=day, end=day)
    for field in panels:
        pd.testing.assert_frame_equal(before[field], panels[field])


def test_missing_required_snapshot_is_not_an_empty_signal():
    panels, _, day = fixture()
    with pytest.raises(StrategyError, match="快照缺失"):
        ImpulsePullbackTailV1().compute_asof(panels, {}, start=day, end=day)
    output = ImpulsePullbackTailV1().compute_asof(
        panels, {(day, "300001"): None}, start=day, end=day)
    assert not output.signals.to_numpy().any()


def test_checksum_params_dates_and_tenant_isolation(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCI_DATA_DIR", str(tmp_path))
    panels, payload, day = fixture()
    engine = ImpulsePullbackTailV1()
    with tenant_scope("__primary__"):
        path = save(payload)
        with pytest.raises(ValueError, match="参数不匹配"):
            compute_asof_signals(engine, panels, {**engine.default_params(), "TS": 11},
                dataset_id="test-asof", start=day, end=day)
        with pytest.raises(ValueError, match="覆盖区间"):
            compute_asof_signals(engine, panels, engine.default_params(),
                dataset_id="test-asof", start="2025-01-01", end=day)
    with tenant_scope("other-user"):
        with pytest.raises(ValueError, match="当前租户没有"):
            load_signal_dataset("test-asof")
        alternate = json.loads(json.dumps(payload))
        alternate["rows"][0]["ohlcv"][-1] = 700.
        save(alternate)
        assert snapshot_rows(load_signal_dataset("test-asof")[0])[(day, "300001")][-1] == 700.
    with tenant_scope("__primary__"):
        assert snapshot_rows(load_signal_dataset("test-asof")[0])[(day, "300001")][-1] == 600.
        body = json.loads(path.read_text(encoding="utf-8"))
        body["payload"]["rows"][0]["ohlcv"][-1] = 999.
        path.write_text(json.dumps(body), encoding="utf-8")
        with pytest.raises(ValueError, match="内容校验失败"):
            load_signal_dataset("test-asof")


@pytest.mark.parametrize("bad_id", ["../other", "a/b", "a\\b", "x" * 97])
def test_ids_cannot_escape_tenant_dataset_directory(bad_id):
    with pytest.raises(ValueError, match="ID无效"):
        load_signal_dataset(bad_id)


def test_bad_values_duplicates_and_unproved_suspension_rejected():
    _, payload, _ = fixture()
    payload["rows"][0]["ohlcv"][4] = -1
    with pytest.raises(ValueError, match="数值无效"):
        snapshot_rows(payload)
    payload["rows"][0]["ohlcv"][4] = 1
    payload["rows"].append(dict(payload["rows"][0]))
    with pytest.raises(ValueError, match="重复"):
        snapshot_rows(payload)
    payload["rows"] = [dict(payload["rows"][0], status="confirmed_suspension")]
    with pytest.raises(ValueError, match="独立证据"):
        snapshot_rows(payload)


def test_import_is_validated_idempotent_and_never_overwrites(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCI_DATA_DIR", str(tmp_path))
    _, payload, _ = fixture()
    body = {"payload": payload, "sha256": hashlib.sha256(canonical_payload(payload)).hexdigest()}
    first = import_signal_dataset(body)
    assert first["created"]
    assert not import_signal_dataset(body)["created"]
    payload["rows"][0]["ohlcv"][4] = 601.
    body["sha256"] = hashlib.sha256(canonical_payload(payload)).hexdigest()
    with pytest.raises(ValueError, match="禁止覆盖"):
        import_signal_dataset(body)
    assert not list(dataset_directory().glob(".snapshot-*"))


def test_runner_uses_dataset_and_freezes_economic_prices(tmp_path, monkeypatch):
    from src.backtest import BacktestConfig, prepare_backtest_context
    from src.market.domain.universe import ResolvedUniverse

    monkeypatch.setenv("LOCI_DATA_DIR", str(tmp_path))
    panels, payload, day = fixture()
    save(payload)

    class Store:
        calls = []

        def trading_days(self):
            return list(panels["close"].index)

        def load_panel(self, **kwargs):
            self.calls.append(kwargs)
            result = {key: value.copy() for key, value in panels.items()}
            if kwargs["adjust"] == "hfq":
                result["close"] *= 2
            return result

        def data_snapshot(self, **kwargs):
            return {"market_revision": "fixture-only"}

    monkeypatch.setattr("src.backtest.application.runner.resolve_universe", lambda *args, **kwargs:
        ResolvedUniverse(codes=["300001"], meta={}, spec={"preset": "fixture"}))
    context = prepare_backtest_context(Store(), ImpulsePullbackTailV1(), start=day, end=day,
        config=BacktestConfig(signal_dataset="test-asof", economic_returns=True, benchmark=None))
    assert context["signals"].iloc[-1, 0]
    assert context["execution_panels"]["close"].iloc[-1, 0] == 10.7
    assert context["execution_panels"]["__adjust_factor"].iloc[-1, 0] == 2
    assert context["data_snapshot"]["signal_dataset"]["id"] == "test-asof"
    assert context["config"].valuation_end == day
    assert all(call["end"] <= day for call in Store.calls)


def test_backend_template_preserves_explicit_overrides_and_legacy_defaults():
    from src.backtest import BacktestConfig, resolve_backtest_config

    engine = ImpulsePullbackTailV1()
    cfg = resolve_backtest_config(engine)
    assert cfg.hold_days == 9 and cfg.stop_loss_pct is None
    assert cfg.signal_dataset and cfg.economic_returns and cfg.strict_limit_prices
    assert cfg.valuation_end is None  # 实际请求end决定截止日，不能锁住模板的旧日期。
    assert cfg.round_trip_cost_pct() == pytest.approx(.3)
    overridden = resolve_backtest_config(engine, {"hold_days": 7, "slippage_bps": 22})
    assert overridden.hold_days == 7 and overridden.round_trip_cost_pct() == pytest.approx(.6)
    assert cfg.hold_days == 9

    class Legacy:
        backtest_config = {"hold_days": 15}

    assert resolve_backtest_config(Legacy()).to_dict() == BacktestConfig().to_dict()


def test_snapshot_template_cannot_silently_fall_back_to_eod():
    from src.backtest import BacktestConfig, prepare_backtest_context

    with pytest.raises(StrategyError, match="不能回退"):
        prepare_backtest_context(None, ImpulsePullbackTailV1(), config=BacktestConfig())


def test_snapshot_internal_type_error_never_retries_without_scope():
    from src.backtest.application.runner import _data_snapshot

    class Store:
        calls = []
        def data_snapshot(self, **kwargs):
            self.calls.append(kwargs)
            raise TypeError("internal unexpected keyword failure")
    with pytest.raises(TypeError):
        _data_snapshot(Store(), codes=["300001"], start="2025-01-01", end="2025-01-02",
                       include_source_details=False)
    assert Store.calls == [{"codes": ["300001"], "start": "2025-01-01", "end": "2025-01-02", "include_source_details": False}]
