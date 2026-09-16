"""研究回测编排的纯支持函数。

这里保留输入遮罩、风险透视输入、JSON 正规化和终态报告等确定性逻辑；
``backtest_run`` 只负责一次运行的阶段编排与存储协调。
"""
from __future__ import annotations

from datetime import date
import hashlib
import json
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from src.backtest import BacktestResult, TrainOOSSplit
from src.research.domain.dag import ResearchWorkflow, StageStatus
from src.research.domain.run_card import ResearchRunCard
from src.research.domain.temporal import MembershipSnapshot
from src.research.infrastructure import ResearchRunCardStore
from src.shared.jsonify import jsonable as json_safe


def validate_research_split(
    *, start: str, end: str, split: TrainOOSSplit | None
) -> TrainOOSSplit:
    """拒绝缺失、无效或越出研究窗口的 train/OOS 声明。"""
    try:
        window_start = date.fromisoformat(str(start))
        window_end = date.fromisoformat(str(end))
    except (TypeError, ValueError) as exc:
        raise ValueError("研究回测日期必须为有效 ISO 日期") from exc
    if window_start > window_end:
        raise ValueError("研究回测必须提供递增的 start/end")
    if split is None:
        raise ValueError("研究回测必须提供完整且不重叠的训练/OOS 区间")
    if not (
        window_start <= date.fromisoformat(split.train_start) <= date.fromisoformat(split.train_end)
        < date.fromisoformat(split.oos_start) <= date.fromisoformat(split.oos_end) <= window_end
    ):
        raise ValueError("训练/OOS 区间必须完全位于回测总区间内")
    return split


def membership_mask(
    signals: pd.DataFrame,
    codes: Sequence[str],
    *,
    historical_universe_id: str | None,
    snapshots: Sequence[MembershipSnapshot],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """返回逐日历史股票池遮罩及其 PIT 可用性摘要。"""
    if not historical_universe_id:
        return (
            pd.DataFrame(True, index=signals.index, columns=signals.columns),
            {
                "universe_id": "current_market_universe",
                "pit_membership": False,
                "survivorship_bias": True,
                "degraded": True,
                "missing_reason": "未提供历史股票池快照，使用当前行情仓股票池",
                "snapshot_evidence": [],
                "observed_codes": len(codes),
            },
        )
    by_day: dict[str, MembershipSnapshot] = {}
    missing_days: list[str] = []
    unavailable_days: list[str] = []
    available_at_missing_days: list[str] = []
    degraded_days: list[str] = []
    source_missing_days: list[str] = []
    provenance_missing_days: list[str] = []
    empty_member_days: list[str] = []
    mask = pd.DataFrame(False, index=signals.index, columns=signals.columns)
    for raw_day in signals.index:
        day = str(raw_day)[:10]
        effective = [item for item in snapshots if item.as_of <= day]
        eligible = [
            item for item in effective if item.available_at and item.available_at <= day
        ]
        if not eligible:
            if not effective:
                missing_days.append(day)
            elif any(not item.available_at for item in effective):
                available_at_missing_days.append(day)
            else:
                unavailable_days.append(day)
            continue
        snapshot = max(
            eligible,
            key=lambda item: (item.as_of, item.available_at, item.snapshot_revision),
        )
        by_day[day] = snapshot
        if snapshot.degraded or snapshot.survivorship_bias or not snapshot.pit_membership:
            degraded_days.append(day)
        if not snapshot.source_id or not snapshot.source_url or not snapshot.snapshot_revision:
            source_missing_days.append(day)
        if (
            not snapshot.fetched_at
            or not snapshot.payload_sha256
            or not snapshot.parser_revision
        ):
            provenance_missing_days.append(day)
        if not snapshot.members:
            empty_member_days.append(day)
        allowed = set(snapshot.members)
        mask.loc[raw_day, :] = [str(code) in allowed for code in signals.columns]
    revisions = sorted({item.snapshot_revision for item in by_day.values() if item.snapshot_revision})
    used_snapshots = {
        (item.universe_id, item.as_of, item.snapshot_revision): item for item in by_day.values()
    }
    snapshot_evidence = [
        {
            "as_of": item.as_of,
            "available_at": item.available_at,
            "source_id": item.source_id,
            "source_url": item.source_url,
            "snapshot_revision": item.snapshot_revision,
            "fetched_at": item.fetched_at,
            "payload_sha256": item.payload_sha256,
            "parser_revision": item.parser_revision,
            "member_count": len(item.members),
            "members_sha256": hashlib.sha256(
                json.dumps(list(item.members), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
        }
        for _, item in sorted(used_snapshots.items())
    ]
    reasons: list[str] = []
    if missing_days:
        reasons.append("历史股票池在部分信号日缺失")
    if unavailable_days:
        reasons.append("历史股票池快照在部分信号日尚不可见")
    if available_at_missing_days:
        reasons.append("历史股票池快照缺少 available_at")
    if degraded_days:
        reasons.append("历史股票池快照已标记降级或生存者偏差")
    if source_missing_days:
        reasons.append("历史股票池快照缺少来源、链接或版本")
    if provenance_missing_days:
        reasons.append("历史股票池快照缺少抓取时刻、载荷摘要或解析版本")
    if empty_member_days:
        reasons.append("历史股票池快照为空")
    incomplete_days = (
        set(missing_days)
        | set(unavailable_days)
        | set(available_at_missing_days)
        | set(degraded_days)
        | set(source_missing_days)
        | set(provenance_missing_days)
        | set(empty_member_days)
    )
    return mask, {
        "universe_id": historical_universe_id,
        "pit_membership": bool(by_day) and not incomplete_days,
        "survivorship_bias": bool(incomplete_days),
        "degraded": bool(incomplete_days),
        "missing_reason": "；".join(reasons),
        "snapshot_revisions": revisions,
        "snapshot_days": len(by_day),
        "missing_days": sorted(set(missing_days)),
        "unavailable_days": sorted(set(unavailable_days)),
        "available_at_missing_days": sorted(set(available_at_missing_days)),
        "degraded_days": sorted(set(degraded_days)),
        "source_missing_days": sorted(set(source_missing_days)),
        "provenance_missing_days": sorted(set(provenance_missing_days)),
        "empty_member_days": sorted(set(empty_member_days)),
        "snapshot_evidence": snapshot_evidence,
        "observed_codes": len(codes),
    }


def risk_inputs(context: Mapping[str, Any]) -> dict[str, Any]:
    """从冻结执行面板生成风险归因所需的可复算输入。"""
    execution = context.get("execution_panels", context["panels"])
    close = execution["close"].astype(float)
    opens = execution["open"].astype(float)
    prior_close = close.shift(1)
    # 逐格 .at 取标量在全市场面板上是每格两次调用（370 日 × 5000 只 ≈ 185 万格
    # 即 370 万次），且每格都新建两个字符串键。整体算完再挑有效格，标签只算一遍。
    prior = prior_close.to_numpy(dtype=float)
    opening = opens.to_numpy(dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        gap_pct = (opening / prior - 1.0) * 100.0
    usable = ~np.isnan(prior) & ~np.isnan(opening) & (prior > 0)
    day_labels = [str(day)[:10] for day in close.index]
    code_labels = [str(code) for code in close.columns]
    gaps: dict[tuple[str, str], float] = {
        (code_labels[col], day_labels[row]): round(float(gap_pct[row, col]), 6)
        for row, col in zip(*(axis.tolist() for axis in np.nonzero(usable)))
    }
    returns = close.pct_change().median(axis=1)
    rolling = returns.rolling(20, min_periods=10).mean()
    regimes: dict[str, str] = {}
    for day, value in rolling.items():
        if not pd.notna(value):
            continue
        regimes[str(day)[:10]] = (
            "uptrend" if float(value) > 0.001 else "downtrend" if float(value) < -0.001 else "sideways"
        )
    return {
        "metadata_by_code": {
            str(code): dict(value)
            for code, value in context["resolved"].meta.items()
        },
        "market_regime_by_date": regimes,
        "entry_gap_pct_by_trade": gaps,
    }


def validation_failures(
    *,
    analysis: Mapping[str, Any],
    membership: Mapping[str, Any],
    strict_pit: bool,
    data_snapshot: Mapping[str, Any],
) -> list[str]:
    """返回可公开呈现的证据门禁失败原因。"""
    failures: list[str] = []
    train_oos = analysis.get("train_oos")
    if not isinstance(train_oos, Mapping) or not train_oos.get("oos_is_strict"):
        failures.append("未获得独立执行的严格 train/OOS 结果")
    elif train_oos.get("failures"):
        failures.append("严格 train/OOS 未通过：" + "；".join(map(str, train_oos["failures"])))
    control = analysis.get("random_control")
    if not isinstance(control, Mapping):
        failures.append("未生成同宇宙随机对照")
    else:
        if not control.get("same_universe") or not control.get("same_coverage"):
            failures.append("同宇宙随机对照未满足一致股票池/覆盖率")
        if control.get("failures"):
            failures.append("随机对照未通过：" + "；".join(map(str, control["failures"])))
    failures.extend(
        input_evidence_failures(
            membership=membership,
            strict_pit=strict_pit,
            data_snapshot=data_snapshot,
        )
    )
    return dedupe(failures)


def input_evidence_failures(
    *,
    membership: Mapping[str, Any],
    strict_pit: bool,
    data_snapshot: Mapping[str, Any],
) -> list[str]:
    """验证计算前即可判定的行情与 PIT 输入证据。"""
    failures: list[str] = []
    if strict_pit and (
        membership.get("degraded")
        or membership.get("survivorship_bias")
        or not membership.get("pit_membership")
    ):
        failures.append("严格证据请求缺少完整 PIT 历史股票池快照或存在生存者偏差")
    evidence = data_snapshot.get("source_evidence")
    if isinstance(evidence, Mapping):
        if strict_pit and evidence.get("receipt_details_omitted"):
            failures.append("严格证据请求不能使用未展开逐条回执的来源摘要")
        unresolved = evidence.get("unresolved_codes") or []
        invalid = int(
            evidence.get("invalid_ohlc_rows", evidence.get("invalid_ohlc", 0)) or 0
        )
        rejected = rejected_ohlc_rows(evidence)
        if strict_pit and unresolved:
            failures.append("行情输入存在未解析代码：" + ",".join(map(str, unresolved[:20])))
        if invalid:
            failures.append(f"行情输入存在 {invalid} 条无效 OHLC")
        if strict_pit and rejected:
            failures.append(f"行情来源回执报告 {rejected} 条拒绝 OHLC 行")
        if strict_pit and evidence.get("attempts_not_observed"):
            failures.append("严格证据请求的行情来源 attempt 未观测")
        if strict_pit:
            provenance = market_provenance_failures(evidence)
            if provenance:
                failures.append(
                    "严格证据请求的行情来源 provenance 不完整：" + "；".join(provenance)
                )
        if strict_pit:
            coverage = evidence.get("field_coverage")
            if not isinstance(coverage, Mapping):
                failures.append("严格证据请求缺少 OHLC 字段覆盖率")
            else:
                incomplete = [
                    field for field in ("open", "high", "low", "close")
                    if float(dict(coverage.get(field) or {}).get("ratio") or 0) < 1.0
                ]
                if incomplete:
                    failures.append("严格证据请求 OHLC 覆盖不完整：" + ",".join(incomplete))
    elif strict_pit:
        failures.append("严格证据请求缺少行情来源证据")
    return dedupe(failures)


def market_provenance_failures(evidence: Mapping[str, Any]) -> list[str]:
    """返回严格研究所需的行情来源回执缺口。

    来源名或本机缓存不能证明历史可见性；只有实际选中的 receipt 才能为
    严格 PIT 输入背书。失败/跳过 attempt 由 ``attempts_not_observed`` 和
    未解析代码分别报告，避免把已知失败混同为成功来源的缺失字段。
    """
    receipts = evidence.get("receipts")
    if not isinstance(receipts, list) or not receipts:
        return ["缺少逐代码行情来源回执"]

    selected: list[Mapping[str, Any]] = []
    for receipt in receipts:
        if not isinstance(receipt, Mapping):
            continue
        if str(receipt.get("state") or "") in {"selected", "succeeded", "success"}:
            selected.append(receipt)
    if not selected:
        return ["没有可用的已选行情来源回执"]

    failures: list[str] = []
    hex_digits = set("0123456789abcdef")
    for receipt in selected:
        code = str(receipt.get("code") or "未知代码")
        missing: list[str] = []
        for field in ("selected_source", "source_url", "fetched_at", "as_of", "parser_revision"):
            if not str(receipt.get(field) or "").strip():
                missing.append(field)

        payload_sha256 = str(receipt.get("payload_sha256") or "").lower()
        if len(payload_sha256) != 64 or any(char not in hex_digits for char in payload_sha256):
            missing.append("payload_sha256")

        if str(receipt.get("publication_status") or "") != "observed":
            missing.append("publication_status=observed")
        if not str(receipt.get("published_at") or "").strip():
            missing.append("published_at")
        if str(receipt.get("availability_status") or "") != "observed":
            missing.append("availability_status=observed")
        if not str(receipt.get("available_at") or "").strip():
            missing.append("available_at")

        if missing:
            failures.append(f"{code} 缺少 " + ",".join(missing))
    return failures


def validation_warnings(
    *,
    membership: Mapping[str, Any],
    strict_pit: bool,
    data_snapshot: Mapping[str, Any],
) -> list[str]:
    """返回不阻断探索运行、但必须随结果保留的证据降级原因。"""
    if strict_pit:
        return []

    warnings: list[str] = []
    if (
        membership.get("degraded")
        or membership.get("survivorship_bias")
        or not membership.get("pit_membership")
    ):
        warnings.append("探索运行缺少完整 PIT 历史股票池快照或存在生存者偏差")

    evidence = data_snapshot.get("source_evidence")
    if not isinstance(evidence, Mapping):
        warnings.append("探索运行缺少行情来源证据，不能作为严格证据")
        return dedupe(warnings)
    if evidence.get("attempts_not_observed"):
        warnings.append("探索运行未观测到行情来源 attempts，不能作为严格证据")
    if evidence.get("receipt_details_omitted"):
        warnings.append("本次保留实际报价关联回执，其他历史失败回执仅汇总，不能作为完整严格PIT证据")

    provenance = market_provenance_failures(evidence)
    if provenance:
        warnings.append(
            "探索运行的行情来源 provenance 不完整，不能作为严格证据："
            + "；".join(provenance)
        )

    unresolved = evidence.get("unresolved_codes") or []
    if unresolved:
        warnings.append(
            "探索运行存在未解析代码，已从执行面板排除："
            + ",".join(map(str, unresolved[:20]))
        )
    rejected = rejected_ohlc_rows(evidence)
    if rejected:
        warnings.append(f"探索运行的行情来源回执报告 {rejected} 条拒绝 OHLC 行")

    coverage = evidence.get("field_coverage")
    if not isinstance(coverage, Mapping):
        warnings.append("探索运行缺少 OHLC 字段覆盖率，不能作为严格证据")
    else:
        incomplete = [
            field
            for field in ("open", "high", "low", "close")
            if float(dict(coverage.get(field) or {}).get("ratio") or 0) < 1.0
        ]
        if incomplete:
            warnings.append("探索运行 OHLC 覆盖不完整：" + ",".join(incomplete))
    return dedupe(warnings)


def rejected_ohlc_rows(evidence: Mapping[str, Any]) -> int:
    """汇总来源回执的拒绝 OHLC 行，避免遗漏部分写入的质量事实。"""
    receipts = evidence.get("receipts")
    if not isinstance(receipts, list):
        return 0
    total = 0
    for receipt in receipts:
        if not isinstance(receipt, Mapping):
            continue
        coverage = receipt.get("coverage")
        if not isinstance(coverage, Mapping):
            continue
        value = coverage.get("rejected_ohlc_rows", 0)
        try:
            total += max(0, int(value or 0))
        except (TypeError, ValueError):
            continue
    return total


def backtest_payload(result: BacktestResult | None) -> dict[str, Any] | None:
    """将执行结果转换为 artifact 可持久化的 JSON 投影。"""
    if result is None:
        return None
    return {
        "strategy_slug": result.strategy_slug,
        "config": json_safe(result.config),
        "metrics": json_safe(result.metrics),
        "performance": json_safe(result.performance),
        "skipped": dict(result.skipped),
        "trades": [
            {**item.to_dict(include_factors=bool(result.config.get("economic_returns"))),
             "alpha_pct": item.alpha_pct}
            for item in result.trades
        ],
    }


def write_terminal_artifacts(
    cards: ResearchRunCardStore,
    card: ResearchRunCard,
    workflow: ResearchWorkflow,
) -> None:
    """将最终工作流状态和人类可读摘要追加到 manifest。"""
    cards.write_artifact(
        card.run_id,
        "workflow-final.json",
        workflow.to_dict(),
        artifact_type="workflow_final",
    )
    cards.write_artifact(
        card.run_id,
        "run_card.md",
        report_markdown(card, workflow_status=workflow.status),
        artifact_type="run_card_markdown",
    )


def report_markdown(card: ResearchRunCard, *, workflow_status: str) -> str:
    """生成不含执行权限的研究证据摘要。"""
    metrics = card.to_dict().get("metrics", {})
    validation = card.to_dict().get("validation", {})
    lines = [
        f"# Research Run {card.run_id}",
        "",
        f"- Status: {card.status}",
        f"- Workflow: {workflow_status}",
        f"- Strategy: {card.strategy_slug} ({card.strategy_revision})",
        f"- Requested as-of: {card.requested_as_of}",
        f"- Market revision: {card.market_revision}",
        f"- Input SHA-256: {card.input_sha256}",
        "",
        "## Metrics",
        "",
        f"- Trades: {metrics.get('trades', 0)}",
        f"- Win rate: {metrics.get('win_rate')}",
        f"- Average net return: {metrics.get('avg_net_return')}",
        f"- Profit factor: {metrics.get('profit_factor')}",
        "",
        "## Validation",
        "",
        "```json",
        json.dumps(validation, ensure_ascii=False, indent=2, sort_keys=True, default=str),
        "```",
        "",
        "This artifact is historical research evidence only. It does not change production strategy defaults.",
        "",
    ]
    return "\n".join(lines)


def universe_id(
    *,
    spec: Mapping[str, Any],
    codes: Sequence[str],
    market_revision: str,
    membership: Mapping[str, Any],
) -> str:
    """为同一股票池、行情版本和 PIT 摘要生成稳定标识。"""
    payload = {
        "spec": json_safe(spec),
        "codes": sorted(map(str, codes)),
        "market_revision": market_revision,
        "membership": json_safe(membership),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "universe-" + hashlib.sha256(encoded).hexdigest()[:24]


def workflow_failure_reasons(workflow: ResearchWorkflow) -> list[str]:
    """提取真正失败阶段，避免把下游 blocked 当作根因。"""
    reasons = [
        f"{stage.value}: {state.error or state.failure_code or '阶段失败'}"
        for stage, state in workflow.stages.items()
        if state.status is StageStatus.FAILED
    ]
    return dedupe(reasons) or ["研究工作流未完成"]




def dedupe(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


__all__ = [
    "backtest_payload",
    "dedupe",
    "input_evidence_failures",
    "json_safe",
    "market_provenance_failures",
    "membership_mask",
    "report_markdown",
    "risk_inputs",
    "universe_id",
    "validate_research_split",
    "validation_failures",
    "validation_warnings",
    "workflow_failure_reasons",
    "write_terminal_artifacts",
]
