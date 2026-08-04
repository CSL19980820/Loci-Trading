"""前视偏差审计：拦下"用收盘后才知道的信息做当日决策"的策略。

## 为什么必须自动查

前视偏差是量化里最贵的错误，因为它**只让回测变好看，不让代码报错**。
本项目手工回测阶段就吃过：用当日盘中数据做当日决策，收益虚高。

而现在多了一个新风险源——AI 生成的策略。模型不理解"9:25 竞价时收盘价
还不存在"，它只会照着形态条件写公式。所以生成即注册这条链上必须有一道
自动审计，否则第一个被写坏的策略会安静地产出一份漂亮的回测报告。

## 两层检查

1. **静态（AST）**：``entry_timing='open'`` 的策略不得引用当日 ``close`` /
   ``high`` / ``low`` / ``volume`` / ``turnover``。这些在集合竞价结束时都还没
   发生。引用 ``REF(close, 1)`` 是合法的——那是昨天的收盘价。
2. **动态（截断重跑）**：把面板砍到信号日为止再跑一次，信号应当完全一致。
   若不一致，说明策略读到了信号日之后的数据（比如 ``.iloc[-1]`` 之类的
   绝对定位，或对整列做了 ``max()``）。这类问题 AST 查不出来。

静态检查靠"当日字段是否被裸用"，会有误报（比如策略确实只用它算了个不
参与信号的展示因子）。所以静态结论按 ``warn`` 报，动态不一致才是 ``block``——
后者是行为证据，不会误判。
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
import inspect
from typing import Any

import pandas as pd

#: 当日不可用字段。集合竞价结束（9:25）时，这些都还没产生。
#: ``open`` 不在其中：竞价结束时开盘价已确定。
INTRADAY_FIELDS = ("close", "high", "low", "volume", "turnover", "amount")

#: 把当日字段"变回合法"的包装函数。出现在这些调用里的字段引用不算违规。
LAGGING_CALLS = ("REF", "MA", "EMA", "SMA", "WMA", "HHV", "LLV", "SUM", "STD",
                 "AVEDEV", "COUNT", "BARSLAST", "BARSSINCE", "DMA")


@dataclass
class AuditFinding:
    check: str
    severity: str      # "block" | "warn"
    message: str
    detail: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "check": self.check,
            "severity": self.severity,
            "message": self.message,
            "detail": self.detail,
        }


@dataclass
class AuditReport:
    strategy: str
    entry_timing: str
    findings: list[AuditFinding] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return any(item.severity == "block" for item in self.findings)

    def reason(self) -> str:
        blockers = [item.message for item in self.findings if item.severity == "block"]
        if blockers:
            return "；".join(blockers)
        warns = [item.message for item in self.findings if item.severity == "warn"]
        return "；".join(warns) if warns else "未发现前视偏差"

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "entry_timing": self.entry_timing,
            "failed": self.failed,
            "reason": self.reason(),
            "findings": [item.to_dict() for item in self.findings],
        }


class LookAheadError(RuntimeError):
    def __init__(self, report: AuditReport) -> None:
        super().__init__(report.reason())
        self.report = report


# --------------------------------------------------------------------------
# 静态检查
# --------------------------------------------------------------------------

class _IntradayVisitor(ast.NodeVisitor):
    """找出裸用当日盘中字段的地方。

    判定方式：``panels["close"]`` 这类下标取值，若它**不在** REF/MA 等滞后
    函数的实参位置上，就记为一次裸用。这不是精确的数据流分析——精确分析
    需要完整的符号执行，成本远超收益。宁可误报（报 warn 让人看一眼），
    也不要漏报。
    """

    def __init__(self) -> None:
        self.bare_uses: list[tuple[str, int]] = []
        # 记录当前是否位于滞后函数的实参里。用栈支持嵌套：MA(REF(close,1), 5)。
        self._lagging_depth = 0

    def visit_Call(self, node: ast.Call) -> None:
        name = ""
        if isinstance(node.func, ast.Name):
            name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            name = node.func.attr

        is_lagging = name in LAGGING_CALLS
        # REF(x, 0) 是"当日"，不构成滞后。
        if name == "REF" and len(node.args) >= 2:
            second = node.args[1]
            if isinstance(second, ast.Constant) and second.value == 0:
                is_lagging = False

        if is_lagging:
            self._lagging_depth += 1
        self.generic_visit(node)
        if is_lagging:
            self._lagging_depth -= 1

    def visit_Subscript(self, node: ast.Subscript) -> None:
        key = node.slice
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            field_name = key.value
            if field_name in INTRADAY_FIELDS and self._lagging_depth == 0:
                self.bare_uses.append((field_name, node.lineno))
        self.generic_visit(node)


def audit_source(code: str, *, entry_timing: str, strategy: str = "") -> AuditReport:
    """对策略源码做静态前视偏差检查。"""
    report = AuditReport(strategy=strategy, entry_timing=entry_timing)
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        report.findings.append(
            AuditFinding("syntax", "block", f"源码无法解析：{exc.msg}（第 {exc.lineno} 行）")
        )
        return report

    if entry_timing != "open":
        # next_open / next_dip / close 用当日数据是合法的，静态层无话可说。
        return report

    visitor = _IntradayVisitor()
    visitor.visit(tree)
    if visitor.bare_uses:
        detail = [{"field": name, "line": line} for name, line in visitor.bare_uses]
        fields = sorted({name for name, _ in visitor.bare_uses})
        report.findings.append(
            AuditFinding(
                "intraday_field",
                "warn",
                f"入场时点为 open（9:25 竞价）但直接使用了当日 {', '.join(fields)}——"
                "集合竞价结束时这些数据尚未产生。若确实需要，应改用 "
                "REF(字段, 1) 取昨日值，或把 entry_timing 改成 next_open/next_dip",
                detail=detail,
            )
        )
    return report


def audit_engine_source(engine: Any) -> AuditReport:
    """对已注册的策略对象做静态检查，源码由 inspect 取。"""
    try:
        code = inspect.getsource(type(engine))
    except (OSError, TypeError):
        report = AuditReport(strategy=getattr(engine, "slug", ""),
                             entry_timing=getattr(engine, "entry_timing", ""))
        report.findings.append(
            AuditFinding("source", "warn", "取不到策略源码，跳过静态检查")
        )
        return report
    return audit_source(
        code,
        entry_timing=str(getattr(engine, "entry_timing", "next_open")),
        strategy=str(getattr(engine, "slug", "")),
    )


# --------------------------------------------------------------------------
# 动态检查：截断重跑
# --------------------------------------------------------------------------

def audit_truncation(
    engine: Any,
    panels: dict[str, pd.DataFrame],
    *,
    params: dict[str, Any] | None = None,
    probe_dates: int = 3,
) -> AuditReport:
    """把面板截断到某一天再跑，信号应与全量一致。

    这是行为层的证据：如果策略偷看了信号日之后的数据，截断后信号必然变化。
    静态检查抓不到的绝对定位（``.iloc[-1]``、对整列 ``max()``）都会在这里露出来。

    probe_dates: 从尾部往前取几个交易日做探针。取 3 个而不是 1 个，是因为
                 单点可能恰好没有信号，比不出差异。
    """
    slug = str(getattr(engine, "slug", ""))
    timing = str(getattr(engine, "entry_timing", "next_open"))
    report = AuditReport(strategy=slug, entry_timing=timing)

    reference = next((frame for frame in panels.values() if not frame.empty), None)
    if reference is None or len(reference.index) < 2:
        report.findings.append(
            AuditFinding("truncation", "warn", "面板数据不足，无法做截断一致性检查")
        )
        return report

    full = engine.compute(panels, params)
    dates = list(reference.index)
    # 留出足够的历史给指标窗口；探针只在尾部取。
    min_bars = int(getattr(engine, "min_bars", lambda: 30)())
    usable = [day for day in dates[min_bars:] if day in full.signals.index]
    if not usable:
        report.findings.append(
            AuditFinding("truncation", "warn",
                         f"可用交易日不足（需要超过 min_bars={min_bars} 根），跳过截断检查")
        )
        return report

    mismatches: list[dict[str, Any]] = []
    for cutoff in usable[-probe_dates:]:
        truncated = {
            name: frame.loc[:cutoff] for name, frame in panels.items() if not frame.empty
        }
        partial = engine.compute(truncated, params)
        if cutoff not in partial.signals.index:
            mismatches.append({"date": cutoff, "issue": "截断后该日信号消失"})
            continue

        expected = set(full.picks_on(cutoff))
        actual = set(partial.picks_on(cutoff))
        if expected != actual:
            mismatches.append(
                {
                    "date": cutoff,
                    "only_in_full": sorted(expected - actual)[:10],
                    "only_in_truncated": sorted(actual - expected)[:10],
                }
            )

    if mismatches:
        report.findings.append(
            AuditFinding(
                "truncation",
                "block",
                f"截断重跑后信号不一致（{len(mismatches)}/{min(probe_dates, len(usable))} 个探针日不符）"
                "：策略读取了信号日之后的数据，回测结论不可信",
                detail=mismatches,
            )
        )
    return report


def audit_strategy(
    engine: Any,
    panels: dict[str, pd.DataFrame] | None = None,
    *,
    params: dict[str, Any] | None = None,
    probe_dates: int = 3,
) -> AuditReport:
    """静态 + 动态一起跑，合并成一份报告。"""
    report = audit_engine_source(engine)
    if panels:
        dynamic = audit_truncation(engine, panels, params=params, probe_dates=probe_dates)
        report.findings.extend(dynamic.findings)
    return report


def guard_strategy(
    engine: Any,
    panels: dict[str, pd.DataFrame] | None = None,
    *,
    params: dict[str, Any] | None = None,
) -> AuditReport:
    """审计并在发现 block 级问题时抛 ``LookAheadError``。"""
    report = audit_strategy(engine, panels, params=params)
    if report.failed:
        raise LookAheadError(report)
    return report
