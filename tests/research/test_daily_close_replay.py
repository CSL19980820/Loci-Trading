"""Integration fixtures use real strategy, execution, portfolio and artifact code.

Only the market adapter/universe resolution is replaced. Fixture prices are
accounting test data, not evidence of strategy profitability or human approval.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from src.backtest import BacktestConfig, BacktestResult, PortfolioResearchConfig, Trade, TrainOOSSplit
from src.backtest import analyze_portfolio, execute_backtest_context
from src.backtest.infrastructure.signal_dataset import (
    canonical_payload,
    import_signal_dataset,
)
from src.market.domain.universe import ResolvedUniverse
from src.research.application import replay as replay_module
from src.research.application.backtest_run import run_research_backtest
from src.research.application.backtest_run_phase import portfolio_market_inputs
from src.research.application.frozen import context_from_payload, payload_sha256
from src.research.application.replay import (
    ResearchReplayError,
    replay_research_backtest,
)
from src.research.infrastructure.run_cards import ResearchRunCardStore
from src.shared.tenancy import tenant_scope
from src.strategy.application.impulse_pullback import ImpulsePullbackTailV1

FIELDS = ("open", "high", "low", "close", "volume")
CODES = ["300001", "300002"]


class _MarketFixture:
    def __init__(self, panels: dict[str, pd.DataFrame], factors: pd.DataFrame) -> None:
        self.panels = panels
        self.factors = factors
        self.blocked = False
        self.calls: list[str] = []

    def _read(self, name: str) -> None:
        if self.blocked:
            raise AssertionError(f"Replay must not read market: {name}")
        self.calls.append(name)

    def trading_days(self) -> list[str]:
        self._read("trading_days")
        return list(self.panels["close"].index)

    def load_panel(self, **kwargs: Any) -> dict[str, pd.DataFrame]:
        self._read(f"load_panel:{kwargs['adjust']}")
        result = {
            field: self.panels[field]
            .loc[kwargs["start"] : kwargs["end"], kwargs["codes"]]
            .copy()
            for field in kwargs["fields"]
        }
        if kwargs["adjust"] == "hfq":
            result["close"] *= self.factors.reindex_like(result["close"])
        return result

    def data_snapshot(self, **_: Any) -> dict[str, Any]:
        self._read("data_snapshot")
        return {"market_revision": "unit-fixture-v1", "quality": "fixture"}


@dataclass
class _Run:
    cards: ResearchRunCardStore
    run_id: str
    store: _MarketFixture
    factors: pd.DataFrame
    dataset_path: Path
    dataset_sha: str
    source_sha: str
    start: str
    end: str

    def artifact_path(self, name: str) -> Path:
        return Path(self.cards.root) / self.run_id / name

    def artifact(self, name: str) -> dict[str, Any]:
        return json.loads(self.artifact_path(name).read_text(encoding="utf8"))


def _inputs() -> tuple[_MarketFixture, dict[str, Any], list[str]]:
    dates = pd.bdate_range("2025-01-02", periods=72).strftime("%Y-%m-%d").tolist()
    arrays = {
        code: np.tile([10.0, 10.05, 9.95, 10.0, 1000.0], (72, 1)) for code in CODES
    }
    for code, anchor in zip(CODES, (60, 67)):
        arrays[code][anchor : anchor + 4] = [
            [10.1, 11.1, 10.1, 11.1, 2000.0],
            [10.9, 11.0, 10.6, 10.9, 700.0],
            [10.85, 10.9, 10.65, 10.8, 500.0],
            [10.8, 11.05, 10.7, 10.75, 1200.0],
        ]
        arrays[code][anchor + 4] = [11.0, 11.3, 10.9, 11.2, 900.0]
    arrays[CODES[0]][65] = [5.6, 5.9, 5.5, 5.8, 1800.0]
    arrays[CODES[0]][66:] = [5.8, 5.85, 5.75, 5.8, 1000.0]
    panels = {
        field: pd.DataFrame({code: arrays[code][:, i] for code in CODES}, index=dates)
        for i, field in enumerate(FIELDS)
    }
    factors = pd.DataFrame(1.0, index=dates, columns=CODES)
    factors.loc[dates[65] :, CODES[0]] = 2.0
    rows = []
    for day in dates[63:]:
        for code in CODES:
            values = [float(panels[field].at[day, code]) for field in FIELDS]
            if (day, code) in {(dates[63], CODES[0]), (dates[70], CODES[1])}:
                values = [10.8, 11.05, 10.7, 11.0, 600.0]
            source_bytes = canonical_payload(
                {"code": code, "date": day, "ohlcv": values}
            )
            rows.append(
                {
                    "code": code,
                    "date": day,
                    "status": "observed",
                    "ohlcv": values,
                    "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
                }
            )
    source_sha = hashlib.sha256(canonical_payload({"rows": rows})).hexdigest()
    payload = {
        "schema": "asof-ohlcv-v1",
        "id": "daily-close-replay-fixture",
        "strategy": "impulse-pullback-tail-v1",
        "params": ImpulsePullbackTailV1().default_params(),
        "coverage": {
            "time": "14:50",
            "volume_unit": "shares",
            "codes": CODES,
            "start": dates[63],
            "end": dates[-1],
        },
        "source_evidence": {"fixture_source_sha256": source_sha},
        "rows": rows,
    }
    return _MarketFixture(panels, factors), payload, dates


def _create_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, daily: bool = True
) -> _Run:
    monkeypatch.setenv("LOCI_DATA_DIR", str(tmp_path / "data"))
    store, payload, dates = _inputs()
    digest = hashlib.sha256(canonical_payload(payload)).hexdigest()
    receipt = import_signal_dataset({"payload": payload, "sha256": digest})
    assert receipt["sha256"] == digest
    monkeypatch.setattr(
        "src.backtest.application.runner.resolve_universe",
        lambda *args, **kwargs: ResolvedUniverse(
            codes=CODES, meta={}, spec={"preset": "fixture"}
        ),
    )
    cards = ResearchRunCardStore(tmp_path / "research_runs")
    config = BacktestConfig(
        hold_days=1,
        stop_loss_pct=None,
        take_profit_pct=None,
        benchmark=None,
        commission_bps=3,
        stamp_duty_bps=10,
        slippage_bps=7,
        signal_dataset=payload["id"],
        economic_returns=True,
        strict_limit_prices=True,
        valuation_end=dates[-1],
    )
    kwargs = {"account_model": "daily_close"} if daily else {}
    outcome = run_research_backtest(
        store,
        strategy=ImpulsePullbackTailV1(),
        start=dates[63],
        end=dates[-1],
        backtest_config=config,
        initial_capital=20_000,
        max_positions=2,
        split=TrainOOSSplit(
            train_start=dates[63],
            train_end=dates[66],
            oos_start=dates[67],
            oos_end=dates[-1],
        ),
        random_repeats=10,
        bootstrap_iterations=20,
        monte_carlo_iterations=20,
        run_card_store=cards,
        **kwargs,
    )
    run = _Run(
        cards,
        outcome.run_card.run_id,
        store,
        store.factors,
        tmp_path / "data" / "backtest_datasets" / f"{payload['id']}.json",
        digest,
        payload["source_evidence"]["fixture_source_sha256"],
        dates[63],
        dates[-1],
    )
    assert run.artifact_path("analysis.json").is_file(), outcome.to_dict()
    assert outcome.run_card.status in {"awaiting_human_review", "rejected"}
    assert not run.artifact_path("human-review.json").exists()
    return run


def _disable_live_inputs(run: _Run, monkeypatch: pytest.MonkeyPatch) -> None:
    run.store.blocked = True
    run.dataset_path.write_text("original dataset no longer readable", encoding="utf8")

    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("Replay must not load the live signal dataset")

    monkeypatch.setattr(
        "src.backtest.application.asof_signals.load_signal_dataset", forbidden
    )
    monkeypatch.setattr(
        "src.backtest.infrastructure.signal_dataset.load_signal_dataset", forbidden
    )


def test_http_replay_projection_keeps_full_artifact_and_uses_staged_file(tmp_path, monkeypatch) -> None:
    with tenant_scope("__primary__"):
        run = _create_run(tmp_path, monkeypatch)
        original = run.cards.write_artifact
        staged = []
        def observed(run_id, path, content, **kwargs):
            if path == "replay-comparison.json":
                assert isinstance(content, Path)
                staged.append(content)
            return original(run_id, path, content, **kwargs)
        monkeypatch.setattr(run.cards, "write_artifact", observed)
        result = replay_research_backtest(run.store, run.run_id, run_card_store=run.cards,
                                         include_execution_details=False)
        assert result["comparison"]["matches_all_recomputed_execution"]
        assert "expected_execution" not in result["comparison"]
        complete = run.artifact("replay-comparison.json")
        assert complete["expected_execution"] == complete["observed_execution"]
        assert complete["control"] == complete["observed_execution"]["random_control_events"]
        assert complete["portfolio_verification"]["matches"]
        assert len(staged) == 1 and not staged[0].exists()


def test_control_payload_shares_only_proven_equal_rows_and_keeps_differences() -> None:
    trade = Trade("300001", "2025-01-02", "2025-01-03", 10.0, "2025-01-06", 11.0,
                  1, 10.0, 9.7, -1.0, 11.0, "hold_expired")
    result = BacktestResult("fixture", {"economic_returns": True},
                            trades=[trade, replace(trade, code="300002")],
                            metrics={"trades": 2}, performance={"net_return": 9.7})
    expected = replay_module.backtest_payload(deepcopy(result))
    result.trades[1].net_return_pct = -3.0
    actual_without_sharing = replay_module.backtest_payload(deepcopy(result))
    observed = replay_module._consume_control_payload(result, expected)
    assert observed == actual_without_sharing
    assert result.trades == []
    assert observed["metrics"] == {"trades": 2}
    assert observed["trades"][0] is expected["trades"][0]
    assert observed["trades"][1] is not expected["trades"][1]
    assert expected["trades"][1]["net_return_pct"] == 9.7
    assert observed["trades"][1]["net_return_pct"] == -3.0


def test_replay_large_inputs_use_bytes_and_match_standard_json(tmp_path, monkeypatch) -> None:
    with tenant_scope("__primary__"):
        run = _create_run(tmp_path, monkeypatch)
        original = replay_module.from_json
        parsed = []
        def checked(raw, **kwargs):
            assert isinstance(raw, bytes), "不得先生成整份Unicode文本"
            assert kwargs.get("allow_partial") is False
            result = original(raw, **kwargs)
            assert result == json.loads(raw.decode("utf-8"))
            parsed.append(len(raw))
            return result
        monkeypatch.setattr(replay_module, "from_json", checked)
        comparison = replay_research_backtest(run.store, run.run_id, run_card_store=run.cards)["comparison"]
        assert comparison["matches_all_recomputed_execution"]
        assert len(parsed) == 1  # 冻结输入走直接bytes；大执行工件走已校验文件流。


def test_daily_close_freezes_asof_sha_factors_and_replays_without_live_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with tenant_scope("__primary__"):
        run = _create_run(tmp_path, monkeypatch)
        frozen = run.artifact("frozen_input.json")
        card = run.cards.require(run.run_id)
        assert frozen["research_settings"]["account_model"] == "daily_close"
        evidence = frozen["data_snapshot"]["signal_dataset"]
        assert evidence["sha256"] == run.dataset_sha
        assert evidence["source_evidence"]["fixture_source_sha256"] == run.source_sha
        assert card.data_snapshot["research_settings"]["account_model"] == "daily_close"
        assert card.data_snapshot["frozen_input_sha256"] == payload_sha256(frozen)
        context = context_from_payload(frozen)
        pd.testing.assert_frame_equal(
            context["execution_panels"]["__adjust_factor"], run.factors
        )
        pd.testing.assert_frame_equal(context["panels"]["close"], run.store.panels["close"])
        pd.testing.assert_frame_equal(
            context["execution_panels"]["close"], run.store.panels["close"]
        )
        assert int(context["signals"].to_numpy().sum()) == 2
        assert (
            not ImpulsePullbackTailV1()
            .compute(run.store.panels)
            .signals.loc[run.start]
            .any()
        )
        analysis = run.artifact("analysis.json")["portfolio"]
        assert analysis["metrics"]["closed_trades"] == 1
        assert analysis["metrics"]["open_positions"] == 1
        assert analysis["metrics"]["final_equity"] == pytest.approx(20_675.45)
        assert analysis["open_allocations"][0]["code"] == CODES[1]
        _disable_live_inputs(run, monkeypatch)
        # Independent public-API recomputation from the frozen context, not a
        # mocked portfolio response or copied analysis artifact.
        execution = execute_backtest_context(run.store, context, use_fast=False)
        recomputed = analyze_portfolio(
            execution.trades,
            strategy_slug=execution.strategy_slug,
            config=PortfolioResearchConfig(
                initial_capital=20_000, max_positions=2, account_model="daily_close"
            ),
            **portfolio_market_inputs(context, "daily_close"),
        ).to_dict()
        assert recomputed == analysis
        before = list(run.store.calls)
        comparison = replay_research_backtest(
            run.store, run.run_id, run_card_store=run.cards
        )["comparison"]
        assert comparison["portfolio_verification"]["status"] == "recomputed"
        assert comparison["portfolio_verification"]["matches"] is True
        assert comparison["matches_all_recomputed_execution"] is True
        assert all(comparison["execution_matches"].values())
        assert run.store.calls == before
        assert comparison["source_signed_manifest_sha256"] is None


@pytest.mark.parametrize("field", ["daily_equity", "open_market_value"])
def test_replay_detects_changed_recomputed_daily_account_even_when_metrics_match(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    with tenant_scope("__primary__"):
        run = _create_run(tmp_path, monkeypatch)
        _disable_live_inputs(run, monkeypatch)
        real_account = replay_module.analyze_portfolio
        calls = []

        def corrupt_after_real_calculation(*args: Any, **kwargs: Any) -> Any:
            result = real_account(*args, **kwargs)
            calls.append(result)
            if field == "daily_equity":
                result.daily[-1] = replace(
                    result.daily[-1], equity=result.daily[-1].equity + 1
                )
            else:
                result.open_allocations[0]["market_value"] += 1
            return result

        monkeypatch.setattr(
            replay_module, "analyze_portfolio", corrupt_after_real_calculation
        )
        comparison = replay_research_backtest(
            run.store, run.run_id, run_card_store=run.cards
        )["comparison"]
        assert len(calls) == 1
        assert comparison["matches_card_metrics"] is True
        assert all(comparison["execution_matches"].values())
        assert (
            comparison["portfolio_verification"]["expected_metrics"]
            == comparison["portfolio_verification"]["observed_metrics"]
        )
        assert comparison["portfolio_verification"]["matches"] is False
        assert comparison["matches_all_recomputed_execution"] is False


@pytest.mark.parametrize(
    "artifact", ["frozen_input.json", "backtest.json", "analysis.json"]
)
def test_replay_rejects_artifact_bytes_changed_outside_the_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    artifact: str,
) -> None:
    with tenant_scope("__primary__"):
        run = _create_run(tmp_path, monkeypatch)
        _disable_live_inputs(run, monkeypatch)
        path = run.artifact_path(artifact)
        path.write_bytes(path.read_bytes() + b"\n ")
        with pytest.raises(ResearchReplayError, match="hash"):
            replay_research_backtest(run.store, run.run_id, run_card_store=run.cards)
        assert not run.artifact_path("replay-comparison.json").exists()


def test_default_legacy_replay_does_not_add_daily_portfolio_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with tenant_scope("__primary__"):
        run = _create_run(tmp_path, monkeypatch, daily=False)
        assert (
            run.artifact("frozen_input.json")["research_settings"]["account_model"]
            == "cost_until_exit"
        )
        _disable_live_inputs(run, monkeypatch)
        comparison = replay_research_backtest(
            run.store, run.run_id, run_card_store=run.cards
        )["comparison"]
        assert "portfolio_verification" not in comparison
        assert comparison["analysis_verification"]["status"] == "not_recomputed"
        assert comparison["matches_all_recomputed_execution"] is True
