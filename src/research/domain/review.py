"""研究质量和 self-review 门禁。"""
from __future__ import annotations

from src.shared.clock import utc_now as _now
from typing import Callable, Any

from src.research.domain.contract import (
    DimensionResult,
    Quality,
    QualitySnapshot,
    ReviewIssue,
    SourceAttempt,
)


REVIEW_RULE_VERSION = "research-review-v2"
ReviewRule = Callable[
    [list[DimensionResult], set[str], str, dict[str, Any], tuple[SourceAttempt, ...]],
    list[ReviewIssue],
]


def _issue(
    severity: str,
    code: str,
    message: str,
    *,
    dimension: str = "",
    evidence: tuple[str, ...] = (),
    suggested_fix: str = "",
) -> ReviewIssue:
    return ReviewIssue(
        severity=severity,  # type: ignore[arg-type]
        code=code,
        message=message,
        dimension=dimension,
        evidence=evidence,
        suggested_fix=suggested_fix,
        rule_version=REVIEW_RULE_VERSION,
    )


def _presence_rule(
    dimensions: list[DimensionResult],
    required: set[str],
    market_revision: str,
    market_health: dict[str, Any],
    source_attempts: tuple[SourceAttempt, ...],
) -> list[ReviewIssue]:
    del source_attempts
    issues: list[ReviewIssue] = []
    if not market_revision:
        issues.append(
            _issue(
                "critical",
                "market_revision_missing",
                "缺少行情版本锚点",
                suggested_fix="重新读取行情仓并保存 market_revision",
            )
        )
    if bool(market_health.get("blocked")):
        issues.append(
            _issue(
                "critical",
                "market_health_blocked",
                str(market_health.get("reason") or "行情质量门禁未通过"),
                suggested_fix="修复行情质量问题后重新生成研究产物",
            )
        )
    if not dimensions:
        issues.append(
            _issue(
                "critical",
                "dimensions_empty",
                "研究没有产生任何维度",
                suggested_fix="至少生成基础资料和技术走势维度",
            )
        )
    for item in dimensions:
        if item.quality == "error":
            severity = "critical" if item.key in required else "warning"
            issues.append(
                _issue(
                    severity,
                    "dimension_error",
                    item.error or "维度计算失败",
                    dimension=item.key,
                    suggested_fix="修复该维度计算或明确标记为缺失",
                )
            )
        elif item.quality == "missing":
            issues.append(
                _issue(
                    "warning",
                    "dimension_missing",
                    "没有可核验的当前来源",
                    dimension=item.key,
                    suggested_fix="接入可回放来源；未接入前保持 missing",
                )
            )
        elif item.quality == "partial":
            issues.append(
                _issue(
                    "warning",
                    "dimension_partial",
                    "字段或时间范围不完整",
                    dimension=item.key,
                    suggested_fix="补齐字段并保留来源和截止日",
                )
            )
    return issues


def _temporal_rule(
    dimensions: list[DimensionResult],
    required: set[str],
    market_revision: str,
    market_health: dict[str, Any],
    source_attempts: tuple[SourceAttempt, ...],
) -> list[ReviewIssue]:
    del required, market_revision, source_attempts
    cutoff = str(market_health.get("research_cutoff") or "")
    if not cutoff:
        return []
    issues: list[ReviewIssue] = []
    for item in dimensions:
        if item.quality not in {"full", "partial"} or not item.as_of:
            continue
        if str(item.as_of) > cutoff:
            issues.append(
                _issue(
                    "critical",
                    "as_of_after_cutoff",
                    f"维度观察日 {item.as_of} 晚于研究截止日 {cutoff}",
                    dimension=item.key,
                    suggested_fix="截断输入到截止交易日后重新计算",
                )
            )
    return issues


def _evidence_rule(
    dimensions: list[DimensionResult],
    required: set[str],
    market_revision: str,
    market_health: dict[str, Any],
    source_attempts: tuple[SourceAttempt, ...],
) -> list[ReviewIssue]:
    del required, market_revision, market_health
    issues: list[ReviewIssue] = []
    selected = {
        item.source_id
        for item in source_attempts
        if item.state in {"selected", "probed"}
    }
    for item in dimensions:
        if item.quality not in {"full", "partial"}:
            continue
        if not item.evidence:
            issues.append(
                _issue(
                    "warning",
                    "evidence_missing",
                    "结果缺少可回溯证据",
                    dimension=item.key,
                    suggested_fix="绑定 source、as_of 和 payload hash",
                )
            )
            continue
        if selected and item.source and item.source not in selected:
            issues.append(
                _issue(
                    "critical",
                    "source_not_selected",
                    f"维度来源 {item.source} 不在本次实际命中来源中",
                    dimension=item.key,
                    evidence=tuple(ref.payload_sha256 for ref in item.evidence if ref.payload_sha256),
                    suggested_fix="保存实际命中来源后再生成研究结果",
                )
            )
    return issues


REVIEW_RULES: tuple[tuple[str, ReviewRule], ...] = (
    ("presence", _presence_rule),
    ("temporal", _temporal_rule),
    ("evidence", _evidence_rule),
)


def list_review_rules() -> list[str]:
    """返回当前启用的规则名，便于 artifact 记录规则版本。"""
    return [name for name, _ in REVIEW_RULES]


def build_quality_snapshot(
    dimensions: list[DimensionResult],
    *,
    market_revision: str,
    market_health: dict[str, Any],
    generated_at: str | None = None,
    cutoff_as_of: str = "",
    source_attempts: tuple[SourceAttempt, ...] = (),
) -> QualitySnapshot:
    """把维度级质量合并成可展示、可阻断的质量快照。"""
    health = dict(market_health)
    if cutoff_as_of:
        health["research_cutoff"] = cutoff_as_of
    required = {"0_basic", "2_kline"}
    issues: list[ReviewIssue] = []
    for _, rule in REVIEW_RULES:
        issues.extend(rule(dimensions, required, market_revision, health, source_attempts))

    full_count = sum(item.quality == "full" for item in dimensions)
    ratio = round(full_count / len(dimensions), 4) if dimensions else 0.0
    if any(item.quality == "error" for item in dimensions) and not any(
        item.quality in {"full", "partial"} for item in dimensions
    ):
        overall: Quality = "error"
    elif not any(item.quality in {"full", "partial"} for item in dimensions):
        overall = "missing"
    elif all(item.quality == "full" for item in dimensions):
        overall = "full"
    else:
        overall = "partial"

    return QualitySnapshot(
        overall=overall,
        blocked=any(item.severity == "critical" for item in issues),
        completeness_ratio=ratio,
        market_revision=market_revision,
        generated_at=generated_at or _now(),
        findings=tuple(issues),
        market_health=health,
    )
