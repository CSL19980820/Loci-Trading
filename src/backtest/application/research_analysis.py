"""P1 回测研究分析的组合入口。

该入口只做编排，具体口径在 ``research_portfolio``、``research_validation``
和 ``research_risk`` 中实现。所有子结果都有 ``to_dict``，可直接放进 run
card；缺少严格切分或同宇宙候选时返回显式 failure，而不是假装验证通过。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from src.backtest.application.engine import BacktestResult, Trade
from src.backtest.application.research_portfolio import (
    PortfolioResearchConfig,
    PortfolioResearchResult,
    analyze_portfolio,
)
from src.backtest.application.research_oos import evaluate_isolated_train_oos
from src.backtest.application.research_risk import RiskXrayResult, risk_xray
from src.backtest.application.research_validation import (
    RandomControlResult,
    TrainOOSResult,
    TrainOOSSplit,
    UncertaintyResult,
    bootstrap_uncertainty,
    evaluate_train_oos,
    monte_carlo_uncertainty,
    strict_random_control,
)


@dataclass
class BacktestResearchAnalysis:
    """组合、切分、随机对照、风险与不确定性的统一 artifact。"""

    strategy_slug: str
    sample_size: int
    time_range: dict[str, str | None]
    seed: int
    portfolio: PortfolioResearchResult
    risk_xray: RiskXrayResult
    train_oos: TrainOOSResult | None
    random_control: RandomControlResult | None
    bootstrap: UncertaintyResult
    monte_carlo: UncertaintyResult
    failures: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "backtest-research-analysis-v1",
            "strategy_slug": self.strategy_slug,
            "sample_size": self.sample_size,
            "time_range": dict(self.time_range),
            "seed": self.seed,
            "portfolio": self.portfolio.to_dict(),
            "risk_xray": self.risk_xray.to_dict(),
            "train_oos": self.train_oos.to_dict() if self.train_oos else {
                "oos_is_strict": False,
                "failures": ["未预声明 train/OOS 切分，不能输出 OOS 结论"],
            },
            "random_control": self.random_control.to_dict() if self.random_control else {
                "is_oos": False,
                "failures": ["未提供同宇宙候选，不能建立严格随机对照"],
            },
            "bootstrap": self.bootstrap.to_dict(),
            "monte_carlo": self.monte_carlo.to_dict(),
            "failures": list(self.failures),
        }


def analyze_backtest_research(
    result: BacktestResult | Iterable[Trade],
    *,
    strategy_slug: str = "",
    portfolio_config: PortfolioResearchConfig | None = None,
    trading_dates: Sequence[str] | None = None,
    split: TrainOOSSplit | None = None,
    parameters: dict[str, Any] | None = None,
    isolated_train: BacktestResult | None = None,
    isolated_oos: BacktestResult | None = None,
    universe_trades: Sequence[Trade] | None = None,
    universe_id: str | None = None,
    selected_universe_id: str | None = None,
    metadata_by_code: dict[str, dict[str, Any]] | None = None,
    market_regime_by_date: dict[str, str] | None = None,
    entry_timing: str = "",
    entry_gap_pct_by_trade: dict[tuple[str, str], float] | None = None,
    seed: int = 0,
    random_repeats: int = 500,
    bootstrap_iterations: int = 500,
    monte_carlo_iterations: int = 500,
) -> BacktestResearchAnalysis:
    """生成确定性的 P1 研究 artifact。

    ``universe_trades`` 必须是同日同宇宙的全部可比较事件，不是仅仅把
    strategy trades 自己复制一份；缺失时随机对照保持 blocked。``split``
    和 ``parameters`` 都是可选的，省略时结果会保留失败原因而不产出 OOS
    结论，便于上游 run card 做门禁。
    """
    trades = list(result.trades) if isinstance(result, BacktestResult) else list(result)
    slug = strategy_slug or (result.strategy_slug if isinstance(result, BacktestResult) else "")
    portfolio = analyze_portfolio(
        trades,
        config=portfolio_config,
        trading_dates=trading_dates,
        strategy_slug=slug,
    )
    risk = risk_xray(
        trades,
        metadata_by_code=metadata_by_code,
        market_regime_by_date=market_regime_by_date,
        entry_timing=entry_timing,
        entry_gap_pct_by_trade=entry_gap_pct_by_trade,
    )
    if split is not None and isolated_train is not None and isolated_oos is not None:
        train_oos = evaluate_isolated_train_oos(
            isolated_train,
            isolated_oos,
            split=split,
            parameters=parameters or {},
        )
    elif split is not None:
        train_oos = evaluate_train_oos(trades, split=split, parameters=parameters)
    else:
        train_oos = None
    random_control = (
        strict_random_control(
            trades,
            universe_trades,
            repeats=random_repeats,
            seed=seed,
            universe_id=universe_id,
            selected_universe_id=selected_universe_id,
        )
        if universe_trades is not None
        else None
    )
    bootstrap = bootstrap_uncertainty(
        trades,
        iterations=bootstrap_iterations,
        seed=seed + 1,
    )
    monte_carlo = monte_carlo_uncertainty(
        trades,
        iterations=monte_carlo_iterations,
        seed=seed + 2,
    )
    failures = list(portfolio.failures) + list(risk.failures)
    if train_oos is None:
        failures.append("未预声明 train/OOS 切分")
    else:
        failures.extend(train_oos.failures)
    if random_control is None:
        failures.append("未提供同宇宙候选")
    else:
        failures.extend(random_control.failures)
    failures.extend(bootstrap.failures)
    failures.extend(monte_carlo.failures)
    return BacktestResearchAnalysis(
        strategy_slug=slug,
        sample_size=len(trades),
        time_range=portfolio.time_range,
        seed=int(seed),
        portfolio=portfolio,
        risk_xray=risk,
        train_oos=train_oos,
        random_control=random_control,
        bootstrap=bootstrap,
        monte_carlo=monte_carlo,
        failures=_dedupe(failures),
    )


def _dedupe(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
