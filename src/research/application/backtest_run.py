"""可审计的研究回测运行用例。

普通 ``/api/backtest`` 保持轻量、兼容的单次指标接口。本模块专门处理需要
证据链的研究运行：固定输入后分别执行 train/OOS，建立同宇宙随机基线，并
把结果、失败门禁和可读报告写进不可变 run card。
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any, Mapping

from src.backtest import (
    BacktestConfig,
    PortfolioResearchConfig,
    TrainOOSSplit,
    analyze_backtest_research,
    build_universe_control,
    execute_backtest_context,
)
from src.research.application.backtest_run_phase import (
    ResearchBacktestError,
    assert_execution_alignment,
    prepare_research_backtest_context,
    slice_research_backtest_phase,
)
from src.research.application.backtest_support import (
    backtest_payload as _backtest_payload,
    input_evidence_failures as _input_evidence_failures,
    json_safe as _json_safe,
    report_markdown as _report_markdown,
    risk_inputs as _risk_inputs,
    universe_id as _universe_id,
    validate_research_split as _validate_research_split,
    validation_failures as _validation_failures,
    validation_warnings as _validation_warnings,
    workflow_failure_reasons as _workflow_failure_reasons,
    write_terminal_artifacts as _write_terminal_artifacts,
)
from src.research.application.frozen import (
    CONTRACT_VERSION,
    build_frozen_payload,
    context_from_payload,
    payload_bytes,
)
from src.research.application.workflow import StageOutcome, execute_research_workflow
from src.research.domain.dag import ResearchStage, ResearchWorkflow
from src.research.domain.run_card import ResearchRunCard
from src.research.infrastructure import MembershipSnapshotStore, ResearchRunCardStore, ResearchWorkflowStore
from src.strategy import StrategyEngine

# 兼容旧导入路径（replay / 外部用例）
_assert_execution_alignment = assert_execution_alignment
_prepare_context = prepare_research_backtest_context


@dataclass(frozen=True, slots=True)
class ResearchBacktestOutcome:
    """一次研究回测的对外投影，不将全量交易明细塞进 HTTP 主响应。"""
    run_card: ResearchRunCard
    workflow: ResearchWorkflow

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_card": self.run_card.to_dict(),
            "workflow": self.workflow.to_dict(),
        }
def run_research_backtest(
    store: Any,
    *,
    strategy: str | StrategyEngine,
    start: str,
    end: str,
    params: Mapping[str, Any] | None = None,
    backtest_config: BacktestConfig | None = None,
    universe: Mapping[str, Any] | None = None,
    split: TrainOOSSplit | None = None,
    hypothesis_id: str | None = None,
    initial_capital: float = 200_000.0,
    max_positions: int = 2,
    lot_size: int = 100,
    seed: int = 0,
    random_repeats: int = 500,
    bootstrap_iterations: int = 500,
    monte_carlo_iterations: int = 500,
    historical_universe_id: str | None = None,
    strict_pit: bool = False,
    hypothesis_revision: int | None = None,
    membership_store: MembershipSnapshotStore | None = None,
    run_card_store: ResearchRunCardStore | None = None,
    workflow_store: ResearchWorkflowStore | None = None,
) -> ResearchBacktestOutcome:
    """执行一次不可变研究回测，不改变策略默认参数或任一业务数据库。

    ``strict_pit`` 只在传入历史股票池注册表时允许得到严格时点结论；未接入
    历史成分的普通 A 股研究仍可运行，但会在 card 中明确标为 degraded，不能
    被误读为无生存者偏差的验证。
    """
    try:
        split = _validate_research_split(start=start, end=end, split=split)
    except ValueError as exc:
        raise ResearchBacktestError(str(exc)) from exc
    if random_repeats <= 0:
        raise ResearchBacktestError("random_repeats 必须为正整数")
    cfg = backtest_config or BacktestConfig()
    cards = run_card_store or ResearchRunCardStore()
    workflows = workflow_store or ResearchWorkflowStore(cards.root)
    memberships = membership_store or MembershipSnapshotStore()
    membership_rows = (
        memberships.list(universe_id=historical_universe_id)
        if historical_universe_id
        else []
    )
    historical_codes = sorted(
        {
            member
            for snapshot in membership_rows
            for member in snapshot.members
        }
    )
    try:
        context, membership_summary = _prepare_context(
            store,
            strategy=strategy,
            start=start,
            end=end,
            params=params,
            config=cfg,
            universe=universe,
            historical_universe_id=historical_universe_id,
            membership_rows=membership_rows,
            historical_codes=historical_codes,
        )
        _assert_execution_alignment(context)
    except Exception as exc:
        raise ResearchBacktestError(str(exc)) from exc
    engine = context["engine"]
    resolved = context["resolved"]
    data_snapshot = dict(context["data_snapshot"])
    # 不能只把选中的 PIT 股票池写在可变 run card；冻结输入也必须携带其
    # 实际来源、载荷摘要和解析版本，重放时才不会重新解析今天的名单。
    data_snapshot["temporal_membership"] = dict(membership_summary)
    research_settings = {
        "seed": seed,
        "random_repeats": random_repeats,
        "bootstrap_iterations": bootstrap_iterations,
        "monte_carlo_iterations": monte_carlo_iterations,
        "initial_capital": initial_capital,
        "max_positions": max_positions,
        "lot_size": lot_size,
    }
    frozen_payload = build_frozen_payload(
        context, split=split, research_settings=research_settings
    )
    # 只序列化一次：这份字节既用来算 hash，也原样落盘（见 payload_bytes 的说明）。
    frozen_bytes = payload_bytes(frozen_payload)
    frozen_sha256 = hashlib.sha256(frozen_bytes).hexdigest()
    frozen_context = context_from_payload(frozen_payload)
    _assert_execution_alignment(frozen_context)
    data_snapshot["frozen_input_sha256"] = frozen_sha256
    data_snapshot["frozen_input_contract"] = CONTRACT_VERSION
    data_snapshot["frozen_input_path"] = "frozen_input.json"
    data_snapshot["hypothesis_revision"] = hypothesis_revision
    data_snapshot["research_settings"] = research_settings
    source_evidence = data_snapshot.get("source_evidence")
    universe_id = _universe_id(
        spec=resolved.spec,
        codes=resolved.codes,
        market_revision=str(data_snapshot.get("market_revision") or ""),
        membership=membership_summary,
    )
    card = cards.create(
        strategy_slug=str(engine.slug),
        strategy_revision=str(getattr(engine, "strategy_revision", "")),
        version=str(getattr(engine, "version", "")),
        hypothesis_id=hypothesis_id,
        hypothesis_revision=hypothesis_revision,
        requested_as_of=end,
        actual_as_of=end,
        market_revision=str(data_snapshot.get("market_revision") or ""),
        universe={**dict(resolved.spec), "universe_id": universe_id},
        universe_funnel={
            **resolved.funnel.to_dict(),
            "panel_columns": int(context["panels"]["close"].shape[1]),
            "temporal_membership": membership_summary,
        },
        params=dict(context["resolved_params"]),
        backtest_config=cfg,
        data_snapshot=data_snapshot,
        source_evidence=(source_evidence,) if isinstance(source_evidence, Mapping) else (),
        metrics={},
        validation={"status": "pending", "universe_id": universe_id},
        risk_xray={},
        conclusion={"status": "running", "default_parameters_changed": False},
        status="running",
    )
    workflow = ResearchWorkflow.create(card.run_id, max_retries=0)
    workflows.create(workflow)
    current_card = card
    state: dict[str, Any] = {
        "context": frozen_context,
        "membership_summary": membership_summary,
        "universe_id": universe_id,
        "result": None,
        "control": None,
        "analysis": None,
        "validation_failures": [],
        "validation_warnings": [],
    }
    def save_workflow(next_workflow: ResearchWorkflow) -> None:
        previous = workflows.load(next_workflow.run_id)
        workflows.save(
            next_workflow,
            expected_event_count=len(previous.events) if previous is not None else 0,
        )
    def capture_input(_: ResearchStage, __: ResearchWorkflow) -> StageOutcome:
        payload = {
            "run_card_input": current_card.input_payload(),
            "parameter_commitment": {
                "params": dict(context["resolved_params"]),
                "committed_before_oos_execution": True,
            },
            "temporal_membership": membership_summary,
        }
        entry = cards.write_artifact(
            current_card.run_id,
            "input.json",
            payload,
            artifact_type="research_input",
        )
        frozen_entry = cards.write_artifact(
            current_card.run_id,
            "frozen_input.json",
            frozen_bytes,
            artifact_type="frozen_research_input",
            metadata={"input_sha256": frozen_sha256},
        )
        if frozen_entry.sha256 != frozen_sha256:
            return StageOutcome.failed("冻结输入 artifact hash 不一致", retryable=False)
        return StageOutcome.succeeded(artifact_sha256=entry.sha256)
    def calculate(_: ResearchStage, __: ResearchWorkflow) -> StageOutcome:
        nonlocal current_card
        if strict_pit:
            failures = _input_evidence_failures(
                membership=membership_summary,
                strict_pit=True,
                data_snapshot=data_snapshot,
            )
            if failures:
                state["validation_failures"] = failures
                entry = cards.write_artifact(
                    current_card.run_id,
                    "validation.json",
                    {"status": "rejected", "strict_pit": True, "failures": failures,
                     "warnings": [], "universe_id": universe_id},
                    artifact_type="validation",
                )
                return StageOutcome.validation_failed("；".join(failures))
        result = execute_backtest_context(store, frozen_context, use_fast=False)
        control = build_universe_control(store, frozen_context, use_fast=False)
        isolated_train = execute_backtest_context(
            store,
            slice_research_backtest_phase(
                frozen_context, split.train_start, split.train_end
            ),
            use_fast=False,
        )
        isolated_oos = execute_backtest_context(
            store,
            slice_research_backtest_phase(
                frozen_context, split.oos_start, split.oos_end
            ),
            use_fast=False,
        )
        risk_inputs = _risk_inputs(frozen_context)
        analysis = analyze_backtest_research(
            result,
            strategy_slug=result.strategy_slug,
            portfolio_config=PortfolioResearchConfig(
                initial_capital=initial_capital,
                max_positions=max_positions,
                lot_size=lot_size,
            ),
            trading_dates=[str(day) for day in frozen_context["panels"]["close"].index],
            split=split,
            parameters=dict(context["resolved_params"]),
            isolated_train=isolated_train,
            isolated_oos=isolated_oos,
            universe_trades=control.trades,
            universe_id=universe_id,
            selected_universe_id=universe_id,
            metadata_by_code=risk_inputs["metadata_by_code"],
            market_regime_by_date=risk_inputs["market_regime_by_date"],
            entry_timing=str(engine.entry_timing),
            entry_gap_pct_by_trade=risk_inputs["entry_gap_pct_by_trade"],
            seed=seed,
            random_repeats=random_repeats,
            bootstrap_iterations=bootstrap_iterations,
            monte_carlo_iterations=monte_carlo_iterations,
        )
        state.update(
            {
                "result": result,
                "control": control,
                "analysis": analysis,
                "isolated_train": isolated_train,
                "isolated_oos": isolated_oos,
            }
        )
        entry = cards.write_artifact(
            current_card.run_id,
            "backtest.json",
            {
                "result": _backtest_payload(result),
                "random_control_events": _backtest_payload(control),
                "isolated_train": _backtest_payload(isolated_train),
                "isolated_oos": _backtest_payload(isolated_oos),
            },
            artifact_type="backtest_execution",
        )
        cards.write_artifact(
            current_card.run_id,
            "analysis.json",
            analysis.to_dict(),
            artifact_type="research_analysis",
        )
        # write_artifact 会追加 manifest；重新读取后再写结果，避免用内存中
        # 的旧 card 覆盖已经登记的 artifact 条目。
        current_card = cards.require(current_card.run_id)
        current_card = cards.save(
            current_card.with_updates(
                metrics=_json_safe(result.metrics),
                validation={"status": "pending", "universe_id": universe_id},
                risk_xray=_json_safe(analysis.risk_xray.to_dict()),
                conclusion={
                    "status": "calculated",
                    "default_parameters_changed": False,
                },
            )
        )
        return StageOutcome.succeeded(artifact_sha256=entry.sha256)
    def validate(_: ResearchStage, __: ResearchWorkflow) -> StageOutcome:
        analysis = state["analysis"]
        if analysis is None:
            return StageOutcome.failed("calculate 阶段没有生成分析产物", retryable=False)
        failures = _validation_failures(
            analysis=analysis.to_dict(),
            membership=membership_summary,
            strict_pit=strict_pit,
            data_snapshot=data_snapshot,
        )
        warnings = _validation_warnings(
            membership=membership_summary,
            strict_pit=strict_pit,
            data_snapshot=data_snapshot,
        )
        state["validation_failures"] = failures
        state["validation_warnings"] = warnings
        entry = cards.write_artifact(
            current_card.run_id,
            "validation.json",
            {
                "status": "rejected" if failures else "degraded" if warnings else "passed",
                "strict_pit": strict_pit,
                "failures": failures,
                "warnings": warnings,
                "universe_id": universe_id,
            },
            artifact_type="validation",
        )
        if failures:
            return StageOutcome.validation_failed("；".join(failures))
        return StageOutcome.succeeded(artifact_sha256=entry.sha256)
    def render(_: ResearchStage, __: ResearchWorkflow) -> StageOutcome:
        nonlocal current_card
        result = state["result"]
        analysis = state["analysis"]
        if result is None or analysis is None:
            return StageOutcome.failed("缺少计算产物", retryable=False)
        current_card = cards.require(current_card.run_id)
        warnings = list(state["validation_warnings"])
        exploratory_degraded = bool(warnings)
        current_card = cards.save(
            current_card.with_updates(
                metrics=_json_safe(result.metrics),
                validation={
                    "status": "degraded" if exploratory_degraded else "passed",
                    "evidence_level": "exploratory" if exploratory_degraded else "strict",
                    "warnings": warnings,
                    "universe_id": universe_id,
                    "train_oos": analysis.train_oos.to_dict() if analysis.train_oos else {},
                    "random_control": (
                        analysis.random_control.to_dict()
                        if analysis.random_control
                        else {}
                    ),
                },
                risk_xray=_json_safe(analysis.risk_xray.to_dict()),
                conclusion={
                    "status": "awaiting_human_review",
                    "evidence_level": "exploratory" if exploratory_degraded else "strict",
                    "default_parameters_changed": False,
                    "next_step": "等待人工签署发布；未签署不得作为已通过证据",
                },
            )
        )
        entry = cards.write_artifact(
            current_card.run_id,
            "report.md",
            _report_markdown(current_card, workflow_status="awaiting human review"),
            artifact_type="human_readable_report",
        )
        return StageOutcome.succeeded(artifact_sha256=entry.sha256)

    handlers = {
        ResearchStage.CAPTURE_INPUT: capture_input,
        ResearchStage.CALCULATE: calculate,
        ResearchStage.VALIDATE: validate,
        ResearchStage.RENDER: render,
    }
    try:
        workflow = execute_research_workflow(
            workflow,
            handlers,
            on_update=save_workflow,
            stop_before_human_review=True,
        )
        if workflow.status == "awaiting_human_review":
            current_card = cards.require(current_card.run_id)
            current_card = cards.save(current_card.with_status("awaiting_human_review"))
        elif workflow.status != "completed":
            current_card = cards.require(current_card.run_id)
            validation_failed = any(
                stage.failure_code == "validation_failed" for stage in workflow.stages.values()
            )
            if validation_failed:
                reasons = list(state["validation_failures"]) or _workflow_failure_reasons(workflow)
                current_card = cards.save(
                    current_card.with_updates(
                        validation={
                            "status": "rejected",
                            "universe_id": universe_id,
                            "failures": reasons,
                        },
                        conclusion={
                            "status": "rejected",
                            "reasons": reasons,
                            "default_parameters_changed": False,
                        },
                    ).with_status("rejected")
                )
            else:
                reasons = _workflow_failure_reasons(workflow)
                error = "；".join(reasons)
                current_card = cards.save(
                    current_card.with_updates(
                        validation={
                            "status": "failed",
                            "universe_id": universe_id,
                            "failures": reasons,
                        },
                        conclusion={
                            "status": "failed",
                            "reasons": reasons,
                            "default_parameters_changed": False,
                        },
                    ).with_status("failed", error=error)
                )
            _write_terminal_artifacts(cards, current_card, workflow)
            current_card = cards.require(current_card.run_id)
        else:
            current_card = cards.require(current_card.run_id)
            _write_terminal_artifacts(cards, current_card, workflow)
            current_card = cards.require(current_card.run_id)
        return ResearchBacktestOutcome(run_card=current_card, workflow=workflow)
    except Exception as exc:
        try:
            current_card = cards.require(current_card.run_id)
            current_card = cards.save(
                current_card.with_updates(
                    conclusion={
                        "status": "failed",
                        "reason": f"{type(exc).__name__}: {exc}",
                        "default_parameters_changed": False,
                    },
                ).with_status("failed", error=f"{type(exc).__name__}: {exc}")
            )
            failed = workflows.load(current_card.run_id) or workflow
            _write_terminal_artifacts(cards, current_card, failed)
        except Exception:
            pass
        raise ResearchBacktestError(f"研究回测失败：{type(exc).__name__}: {exc}") from exc


__all__ = [
    "ResearchBacktestError",
    "ResearchBacktestOutcome",
    "run_research_backtest",
    "slice_research_backtest_phase",
]
