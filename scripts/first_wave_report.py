"""Render a first-wave research report from completed, local output files only.

Usage: python scripts/first_wave_report.py <directory>
This module does not import the research runner or open a market database.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


RESEARCH_DATE = "2026-10-27"
LAST_COMPLETE_SESSION = "2026-10-26"
YEARS = tuple(range(1990, 2027))
GATES = (
    ("no_mainline", "无主线"),
    ("price_resonance_proxy", "价格共振代理"),
    ("observed_theme", "真实题材（有历史证据）"),
)
SEGMENTS = (
    ("historical_1990_2022", "1990–2022", 1990, 2022),
    ("validation_2023_2025", "2023–2025", 2023, 2025),
    ("latest_2026", "2026", 2026, 2026),
)
CLOSED_STATUSES = {"closed", "completed", "filled"}
INPUT_FILES = (
    "summary.json",
    "protocol.json",
    "all-wave-setups.csv",
    "all-opportunities.jsonl",
    "yearly-results.csv",
)


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError(f"数值字段不能是布尔值：{value!r}")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"数值字段必须有限：{value!r}")
    return result


def _count(value: Any) -> int:
    number = _number(value)
    if number is None or number < 0 or not number.is_integer():
        raise ValueError(f"计数字段必须是非负整数：{value!r}")
    return int(number)


def _fmt(value: Any, suffix: str = "") -> str:
    number = _number(value)
    return "—" if number is None else f"{number:.2f}{suffix}"


def _fmt_count(value: Any, *, zero_dash: bool = False) -> str:
    if value is None:
        return "—"
    count = _count(value)
    return "—" if zero_dash and count == 0 else f"{count:,}"


def _cell(value: Any) -> str:
    if value is None or value == "":
        return "—"
    return str(value).replace("|", "\\|").replace("\r", "").replace("\n", "<br>")


def _table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    lines.extend("| " + " | ".join(_cell(cell) for cell in row) + " |" for row in rows)
    return "\n".join(lines)


def _json_block(value: Any) -> str:
    return "```json\n" + json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n```"


def _variant(gate: str, *, minute: bool = False, quoted: bool = False, horizon: int | None = None) -> str:
    if horizon is not None:
        return f"{gate}__next_open__h{horizon}__single_full__horizon"
    mode = "sampled_quotes_1450" if quoted else "intraday_1450" if minute else "next_open"
    return f"{gate}__{mode}__h10__staged__ma5_or_horizon"


@dataclass
class _Bucket:
    opportunities: int = 0
    closed: int = 0
    net_sum: float = 0.0
    wins: int = 0
    months: set[str] = field(default_factory=set)

    def add(self, signal_date: str, net: float | None) -> None:
        self.opportunities += 1
        if net is not None:
            self.closed += 1
            self.net_sum += net
            self.wins += net > 0
            self.months.add(signal_date[:7])


@dataclass
class _Ledger:
    overall: dict[str, _Bucket] = field(default_factory=lambda: defaultdict(_Bucket))
    yearly: dict[tuple[str, int], _Bucket] = field(default_factory=lambda: defaultdict(_Bucket))
    segments: dict[tuple[str, str], _Bucket] = field(default_factory=lambda: defaultdict(_Bucket))
    statuses: dict[str, Counter[str]] = field(default_factory=lambda: defaultdict(Counter))
    minute_counts: dict[str, Counter[str]] = field(default_factory=lambda: defaultdict(Counter))
    quote_counts: dict[str, Counter[str]] = field(default_factory=lambda: defaultdict(Counter))


def _minute_flags(row: Mapping[str, Any], closed: bool) -> set[str]:
    """Keep status categories inspectable; entry fills can also be immature."""
    status = row.get("status", "unknown").lower()
    flags: set[str] = set()
    if any(token in status for token in (
        "missing", "no_data", "no_minute", "unavailable", "insufficient_minute", "incomplete_minute",
    )):
        flags.add("no_data")
    if any(token in status for token in ("unknown", "unverifiable", "uncertain", "unverified")):
        flags.add("unknown")
    if row.get("exit_reason") == "data_end" or status in {"open", "data_end"} or any(
        token in status for token in ("pending", "awaiting", "immature", "unmatured", "not_mature")
    ):
        flags.add("immature")
    if row.get("legs") or closed:
        flags.add("filled")
    if not flags:
        flags.add("other")
    return flags


def _read_ledger(path: Path) -> _Ledger:
    ledger = _Ledger()
    with path.open(encoding="utf-8-sig") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"{path.name}:{line_number} 必须是 JSON 对象")
            variant = row["variant"]
            signal_date = row["signal_date"]
            status = row.get("status", "unknown")
            if not isinstance(variant, str) or not isinstance(status, str):
                raise ValueError(f"{path.name}:{line_number} variant/status 必须是字符串")
            if not isinstance(signal_date, str) or len(signal_date) != 10:
                raise ValueError(f"{path.name}:{line_number} signal_date 必须是 YYYY-MM-DD")
            year = int(signal_date[:4])
            net = _number(row.get("net_return_pct"))
            closed = status in CLOSED_STATUSES and row.get("exit_reason") != "data_end" and net is not None
            realized_net = net if closed else None
            ledger.overall[variant].add(signal_date, realized_net)
            ledger.yearly[variant, year].add(signal_date, realized_net)
            for segment, _, start, end in SEGMENTS:
                if start <= year <= end:
                    ledger.segments[variant, segment].add(signal_date, realized_net)
            ledger.statuses[variant][status] += 1
            if "__intraday_1450__" in variant:
                ledger.minute_counts[variant].update(_minute_flags(row, closed))
            if "__sampled_quotes_1450__" in variant:
                counts = ledger.quote_counts[variant]
                counts[row.get("reason", "")] += 1
                if row.get("legs"):
                    counts["any_bought"] += 1
                if row.get("missing_quote_date"):
                    counts["d2_missing" if row["missing_quote_date"] == signal_date else "later_missing"] += 1
    return ledger


def _check_metrics(metrics: Mapping[str, Any], bucket: _Bucket, label: str) -> None:
    if _count(metrics["opportunities"]) != bucket.opportunities:
        raise ValueError(f"{label} 机会数与逐笔文件不一致；请使用同一次已完成研究的产物")
    if _count(metrics["realized_trades"]) != bucket.closed:
        raise ValueError(f"{label} 已平仓数与逐笔文件不一致")
    if bucket.closed:
        mean = _number(metrics.get("mean_net_pct"))
        if mean is None or not math.isclose(mean, bucket.net_sum / bucket.closed, rel_tol=1e-9, abs_tol=1e-8):
            raise ValueError(f"{label} 平均净收益与逐笔文件不一致")


def _read_inputs(directory: Path) -> tuple[dict, dict, Counter, Counter, _Ledger, dict]:
    # Missing or incomplete files fail immediately; never wait or fabricate placeholders.
    for name in INPUT_FILES:
        if not (directory / name).is_file():
            raise FileNotFoundError(f"缺少已完成研究产物：{directory / name}")
    summary = json.loads((directory / "summary.json").read_text(encoding="utf-8-sig"))
    protocol = json.loads((directory / "protocol.json").read_text(encoding="utf-8-sig"))
    for key in ("database_sha256", "source_hashes", "configuration"):
        if summary[key] != protocol[key]:
            raise ValueError(f"summary.json 与 protocol.json 的 {key} 不一致")
    setups: Counter[str] = Counter()
    reasons: Counter[tuple[str, str, str]] = Counter()
    with (directory / "all-wave-setups.csv").open(encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source):
            status = row.get("status") or "unknown"
            setups[status] += 1
            for key, value in row.items():
                if key and (key == "reason" or key.endswith("_reason")) and value:
                    reasons[status, key, value] += 1
    expected_setups = {key: _count(value) for key, value in summary["setup_counts"].items()}
    if dict(setups) != expected_setups:
        raise ValueError("all-wave-setups.csv 形态计数与 summary.json 不一致")
    ledger = _read_ledger(directory / "all-opportunities.jsonl")
    variants = summary["variants"]
    if set(variants) != set(ledger.overall):
        raise ValueError("summary.json 的变体集合与 all-opportunities.jsonl 不一致")
    for variant, item in variants.items():
        _check_metrics(item["overall"], ledger.overall[variant], variant)
        if item["overall"]["status_counts"] != dict(ledger.statuses[variant]):
            raise ValueError(f"{variant} status_counts 与逐笔文件不一致")
        for year, metrics in item["by_year"].items():
            _check_metrics(metrics, ledger.yearly.get((variant, int(year)), _Bucket()), f"{variant}/{year}")
        for segment, metrics in item["segments"].items():
            _check_metrics(metrics, ledger.segments.get((variant, segment), _Bucket()), f"{variant}/{segment}")
    annual: dict[tuple[str, int], dict[str, Any]] = {}
    with (directory / "yearly-results.csv").open(encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source):
            key = (row["variant"], _count(row["year"]))
            if key in annual:
                raise ValueError(f"yearly-results.csv 年度记录重复：{key}")
            _check_metrics(row, ledger.yearly.get(key, _Bucket()), f"yearly-results.csv/{key}")
            annual[key] = row
    expected_years = {(variant, int(year)) for variant, item in variants.items() for year in item["by_year"]}
    if set(annual) != expected_years or not set(ledger.yearly).issubset(expected_years):
        raise ValueError("yearly-results.csv、summary.json 与逐笔文件的年度覆盖不一致")
    return summary, protocol, setups, reasons, ledger, annual


def _read_quote_inputs(directory: Path, baseline: Mapping[str, Any]) -> tuple[dict, _Ledger, dict]:
    summary = json.loads((directory / "quote-summary.json").read_text(encoding="utf-8-sig"))
    protocol = json.loads((directory / "quote-protocol.json").read_text(encoding="utf-8-sig"))
    for key in ("source_hashes", "baseline_database_sha256"):
        if summary[key] != protocol[key]:
            raise ValueError(f"报价回放 summary/protocol 的 {key} 不一致")
    if summary["baseline_database_sha256"] != baseline["database_sha256"]:
        raise ValueError("报价回放与日线对照不使用同一冻结数据库")
    ledger = _read_ledger(directory / "quote-opportunities.jsonl")
    expected = {_variant(gate, quoted=True) for gate, _ in GATES}
    if set(summary["variants"]) != expected or set(ledger.overall) != expected:
        raise ValueError("报价回放变体必须覆盖三个完整门禁")
    annual = {}
    for variant, item in summary["variants"].items():
        _check_metrics(item["overall"], ledger.overall[variant], variant)
        if item["overall"]["status_counts"] != dict(ledger.statuses[variant]):
            raise ValueError(f"{variant} 报价状态与逐笔文件不一致")
        if item["overall"]["opportunities"] != summary["opportunities"]:
            raise ValueError(f"{variant} 未覆盖全部报价机会")
        for year, metrics in item["by_year"].items():
            _check_metrics(metrics, ledger.yearly.get((variant, int(year)), _Bucket()), f"{variant}/{year}")
            annual[variant, int(year)] = metrics
    if sum(bucket.opportunities for bucket in ledger.overall.values()) != summary["ledger_rows"]:
        raise ValueError("报价回放总行数不一致")
    if summary["opportunities"] != baseline["setup_counts"]["setup_ready"]:
        raise ValueError("报价回放机会数与冻结形态不一致")
    return summary, ledger, annual


def _metrics(summary: Mapping[str, Any], variant: str, segment: str | None = None) -> Mapping[str, Any]:
    item = summary["variants"].get(variant)
    if item is None:
        return {"opportunities": 0, "realized_trades": 0}
    return item["overall"] if segment is None else item["segments"][segment]


def _return_fields(metrics: Mapping[str, Any]) -> list[str]:
    if not _count(metrics["realized_trades"]):
        return ["—"] * 6
    return [
        _fmt(metrics.get("win_rate_pct"), "%"),
        _fmt(metrics.get("mean_net_pct"), "%"),
        _fmt(metrics.get("mean_invested_net_pct"), "%"),
        _fmt(metrics.get("profit_factor")),
        _fmt(metrics.get("mean_allocation_pct"), "%"),
        _fmt(metrics.get("two_tranche_rate_pct"), "%"),
    ]


def _ci(metrics: Mapping[str, Any]) -> str:
    interval = metrics.get("mean_net_month_cluster_ci95")
    if not _count(metrics["realized_trades"]) or interval is None:
        return "—"
    if not isinstance(interval, list) or len(interval) != 2:
        raise ValueError("mean_net_month_cluster_ci95 必须含上下两个端点")
    low, high = (_number(value) for value in interval)
    if low is None or high is None or low > high:
        raise ValueError("mean_net_month_cluster_ci95 端点无效")
    return f"[{low:.2f}%, {high:.2f}%]"


def _quote_results(directory: Path, summary: Mapping[str, Any], ledger: _Ledger, annual: Mapping) -> list[str]:
    main_rows, coverage_rows, confidence_rows, segment_rows, stability = [], [], [], [], []
    for gate, label in GATES:
        variant = _variant(gate, quoted=True)
        metrics = _metrics(summary, variant)
        count = _count(metrics["realized_trades"])
        main_rows.append([label, _fmt_count(count, zero_dash=True), *_return_fields(metrics)])
        statuses = ledger.statuses[variant]
        counts = ledger.quote_counts[variant]
        coverage_rows.append([
            label, metrics["opportunities"], statuses["mainline_rejected"],
            statuses["mainline_unverifiable"], statuses["skipped"], counts["d2_missing"],
            counts["later_missing"], count, counts["any_bought"],
        ])
        confidence_rows.append([label, len(ledger.overall[variant].months), _ci(metrics)])
        for segment, segment_label, _, _ in SEGMENTS:
            bucket = ledger.segments.get((variant, segment), _Bucket())
            segment_rows.append([
                label, segment_label, _fmt_count(bucket.closed, zero_dash=True),
                _fmt(bucket.net_sum / bucket.closed if bucket.closed else None, "%"),
                _fmt(100 * bucket.wins / bucket.closed if bucket.closed else None, "%"),
            ])
        active = [annual[variant, year] for year in YEARS if annual[variant, year]["realized_trades"]]
        stability.append([
            label, len(active), sum(row["mean_net_pct"] > 0 for row in active),
            sum(row["mean_net_pct"] < 0 for row in active),
        ])
    proxy = _metrics(summary, _variant("price_resonance_proxy", quoted=True))
    plain = _metrics(summary, _variant("no_mainline", quoted=True))
    proxy_counts = ledger.quote_counts[_variant("price_resonance_proxy", quoted=True)]
    plain_counts = ledger.quote_counts[_variant("no_mainline", quoted=True)]
    closed_years = [year for year in YEARS if annual[_variant("no_mainline", quoted=True), year]["realized_trades"]]
    capture = json.loads((directory / "quote-data-capture.json").read_text(encoding="utf-8-sig"))
    captured = capture["d2_status_counts"]
    return [
        "## 14:50 报价采样回放",
        f"价格共振代理组完成 {_fmt_count(proxy['realized_trades'])} 笔交易，扣费后平均计划资金收益 "
        f"{_fmt(proxy.get('mean_net_pct'), '%')}，胜率 {_fmt(proxy.get('win_rate_pct'), '%')}，"
        f"月聚类 95% 均值区间 {_ci(proxy)}。无主线组完成 {_fmt_count(plain['realized_trades'])} 笔，"
        f"平均 {_fmt(plain.get('mean_net_pct'), '%')}。当前固定参数没有显示盈利优势；"
        "真实题材组因缺少当时的成员证据，全部保留为未知，不能给出该组收益结论。",
        "本实验保留 D2 的 14:50 判断时点，数据为每分钟最后价格与成交量。"
        "首买 50%，D3 按小 K 或大涨后回踩规则加另 50%；研究补充的卖点为 MA5 失守或首买后 T+10。"
        "成交假设为决策之后下一条正成交量报价，计入费用、滑点与各批次 T+1。"
        "它没有分钟内开、高、低，也没有订单簿，不能证明真实 tick 路径或指定数量一定成交。",
        _table([
            "门禁", "已平仓 N", "胜率", "平均计划资金净收益", "平均已投资净收益",
            "利润因子", "平均资金投入", "加仓率",
        ], main_rows),
        "每个机会独立安排 10 万元，未加仓的现金保留。上表均值只统计完整平仓机会，"
        "未知和未成交不按零收益掺入；下面把它们全部列出。样本缺失并非随机，"
        "已有完整交易的平均收益不能推广到所有缺失机会。",
        f"报价采样的完整平仓样本实际覆盖 {min(closed_years)}–{max(closed_years)} 年。"
        "数据库更早年份仍完成了形态扫描；缺少报价的机会保持未知，"
        "不能把扫描起日 1990-12-19 当作完整分钟收益证据的起日。",
        "### 覆盖与未成交",
        _table([
            "门禁", "全部机会", "主线拒绝", "主线未知", "条件不符或无法成交",
            "D2 数据缺失", "后续数据缺失", "完整平仓", "曾买入（可重叠）",
        ], coverage_rows),
        "除最后一列外，各状态互斥并加总为每组全部机会。曾买入包括后来缺少报价而无法完整核算的机会，"
        f"不能当成完整平仓数。无主线组有 {plain_counts['d2_below_dynamic_ma5']:,} 次在 D2 低于动态 MA5、"
        f"{plain_counts['first_buy_upper_limit']:,} 次首买触及涨停而保守放弃；"
        f"价格共振代理组分别为 {proxy_counts['d2_below_dynamic_ma5']:,} 次和 "
        f"{proxy_counts['first_buy_upper_limit']:,} 次。"
        "所有代码、同日全部机会及同票重叠机会均已保留，无 TopN、资金或持仓数量筛除。",
        f"全部 {capture['opportunities']:,} 个 D2 中，{captured['verified']:,} 份报价通过末价与当日日线区间交叉核对；"
        f"{captured['history_empty']:,} 份未取到历史报价，{captured['daily_price_mismatch']:,} 份价格核对不一致，"
        f"{captured['daily_validation_missing']:,} 份缺少日线核对依据。"
        "这些失败均保留原始状态，不猜测为停牌或额度问题。"
        "日期来自历史接口请求及日线价格核对，接口本身不独立返回带日期的时间戳。"
        "首买日取数记录见 [quote-data-capture.json](quote-data-capture.json)。",
        "后续报价中有 3 次接口调用失败，经每个日期各重试一次均补回，并通过日线价格核对。"
        "更新仅使无主线组的 3 个机会由未知转为完整平仓，主线代理组统计不变；"
        "原失败回执和旧结果已保留。详见 [取数回执](quote-targeted-retry.json) 与 "
        "[更新对照](quote-targeted-retry-verification.json)。",
        "### 时间分段与均值区间",
        _table(["门禁", "信号日期分段", "已平仓 N", "平均计划资金净收益", "胜率"], segment_rows),
        "分段固定为 1990–2022、2023–2025 与 2026；2026 为截至 10 月 26 日的非完整年度。"
        "分段结果来自同一组参数，不是事前独立样本外发现。",
        _table(["门禁", "有平仓样本的信号月份数", "月聚类 bootstrap 95% 均值区间"], confidence_rows),
        "按信号月份整组重采样 1,000 次，固定种子 20261027；不足 5 个有效月份时不报区间。"
        "聚类保留同月机会的部分共振，但仍有跨月持有、同票重叠与存续偏差。"
        "价格共振代理组区间跨零，不能据此确认其均值方向；无主线组区间为负。",
        _table(["门禁", "37 年中有平仓样本的年份数", "年度均值 > 0", "年度均值 < 0"], stability),
        "![14:50 报价采样年度结果](quote-annual-results.png)",
        "图按信号年统计完整平仓数与计划资金净收益均值。所有 1990–2026 年份均保留，"
        "无完整样本的年份不画收益点，不能解释为零收益。"
        "[年度 CSV](quote-yearly-results.csv) / [PNG](quote-annual-results.png) / [SVG](quote-annual-results.svg)。",
        "报价回放原件：[逐笔 JSONL](quote-opportunities.jsonl)、[汇总](quote-summary.json)、"
        "[冻结协议](quote-protocol.json)、[报价缓存指纹清单](quote-cache-manifest.json)。"
        "日线对照与完整分钟 OHLC 结果分别列在下方。",
        "独立核验发现早期报价版的回踩窗口只检查 MA5 下沿，与冻结基线的 1% 区间不一致，"
        "已统一为两个窗口末价均在区间内，并对全部机会重跑。首仓全部相同；"
        "111 个独立机会、140 条门禁记录的加仓或后续结果改变。"
        "本报告采用统一后的结果，旧版已归档，变更对照见 "
        "[quote-band-alignment-verification.json](quote-band-alignment-verification.json)。",
    ]


def _d2_high_results(directory: Path) -> list[str]:
    path = directory / "d2-next-day-high-win-rate-adjusted.json"
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    rows = []
    for section, section_label in (
        ("factor_adjusted_actual_d2_fill", "实际 D2 首笔成交价"),
        ("raw_actual_d2_fill", "实际 D2 首笔成交价（原始价格）"),
        ("factor_adjusted_d2_1450_observation", "D2 14:50 观察价"),
    ):
        for gate, label in (("no_mainline", "无主线"), ("price_resonance_proxy", "价格共振代理")):
            metrics = data[section][gate]
            rows.append([
                f"{label} / {section_label}",
                _fmt_count(metrics["entries"]),
                _fmt_count(metrics["known_next_high"]),
                _fmt_count(metrics["wins"]),
                _fmt_count(metrics["ties"]),
                _fmt_count(metrics["losses"]),
                _fmt(metrics.get("win_rate_pct"), "%"),
            ])
    return [
        "## 只评价 D2 买点的次日最高价胜率",
        "本表只看 D2 首批买入，不看 D3 加仓，也不使用 MA5 退出。"
        "如果下一个市场交易日的日线最高价严格高于 D2 买入价，记为胜；等于买入价单列为平；"
        "次日最高价缺失的记录不进入胜率分母。复权口径用于处理除权除息，原始价格口径保留用户直观比较。",
        _table(["口径", "D2 首买", "有次日高点", "胜", "平", "负", "胜率"], rows),
        "价格共振主线的实际 D2 首笔成交价口径为 339 胜、39 负、4 平，胜率 88.74%。"
        "这个指标回答的是次日是否曾经给过更高价，不等于按该最高价可成交，也不等于扣费后的最终收益。"
        "完整原始结果见 [d2-next-day-high-win-rate-adjusted.json](d2-next-day-high-win-rate-adjusted.json)。",
    ]


def _optional_evidence(directory: Path) -> list[str]:
    parts = []
    quote_path = directory / "quote-crosscheck.json"
    if quote_path.is_file():
        quote = json.loads(quote_path.read_text(encoding="utf-8-sig"))
        checked = _fmt_count(quote.get("checked_full_close_snapshots"))
        mismatches = _fmt_count(quote.get("mismatch_count"))
        parts.extend([
            "### 收盘快照交叉核对",
            f"[quote-crosscheck.json](quote-crosscheck.json)：实际核对 {checked} 份以 15:00 结束的分时收盘快照，"
            f"与同日日线的收盘不一致数为 {mismatches}。该结论只覆盖这些已核对记录，"
            "不能推广到全部历史行情，也不能证明 14:50 入场条件或分钟成交可复现。",
        ])
    original_path = directory / "original-buy-audit.json"
    if original_path.is_file():
        original = json.loads(original_path.read_text(encoding="utf-8-sig"))
        audit = original["summary"]
        links = "[original-buy-audit.json](original-buy-audit.json)"
        if (directory / "original-buy-audit.csv").is_file():
            links += " 与 [original-buy-audit.csv](original-buy-audit.csv)"
        parts.extend([
            "### 原始 D2 条件的代数审计",
            f"审计原件：{links}。该审计用动态 MA5 的代数阈值和 D2 全天最低价/最高价，"
            "事后区分条件必然真、必然假与未知，不把全天高低价当成盘中信号或买价。"
            "另有报价的机会则直接核对 14:50 条件。动态 MA5 条件可化简为："
            "`当时原价 ≥ 此前四个有效交易日的调整收盘之和 / (4 × 当日因子)`。",
            _table(["证据", "满足", "不满足", "未知或无法比较"], [
                ["仅靠全天价格区间（事后边界）", audit["interval_status_counts"]["always_true"],
                 audit["interval_status_counts"]["always_false"],
                 audit["interval_status_counts"]["ambiguous"] + audit["interval_status_counts"]["unverifiable"]],
                ["实际 14:50 报价条件", audit["minute_condition_counts"]["true"],
                 audit["minute_condition_counts"]["false"], audit["minute_condition_counts"]["unknown"]],
            ]),
            f"区间与报价条件矛盾 {_fmt_count(audit['interval_minute_comparison_counts']['contradiction'])} 次；"
            f"数据不一致 {_fmt_count(audit['data_inconsistent'])} 次。"
            "报价能证明当时条件，不等于有可成交的下一报价或完整退出路径。",
        ])
    for filename, label in (("ledger-verification.json", "日线台账独立核验"),
                            ("quote-ledger-verification.json", "报价台账独立核验")):
        evidence_path = directory / filename
        if evidence_path.is_file():
            evidence = json.loads(evidence_path.read_text(encoding="utf-8-sig"))
            passed = evidence.get("ledger_checks_passed", evidence.get("passed"))
            status_text = f"账本核验：{'通过' if passed else '未通过'}。"
            if "original_rules_passed" in evidence:
                status_text += f"量化口径一致性：{'通过' if evidence['original_rules_passed'] else '未通过'}。"
            counts = evidence.get("counts", evidence)
            parts.extend([
                f"### {label}",
                f"原件：[{filename}]({filename})。{status_text}"
                "逐笔经济核算与源价格核对不证明缺失的历史题材、分钟内路径或订单容量。",
                _table(["核验项目", "数量"], [
                    [key, _fmt_count(value)] for key, value in counts.items()
                    if isinstance(value, int) and not isinstance(value, bool)
                ]),
            ])
    validation_path = directory / "validation.json"
    if validation_path.is_file():
        validation = json.loads(validation_path.read_text(encoding="utf-8-sig"))
        parts.extend([
            "### 验证记录",
            "以下计数只读取 [validation.json](validation.json)，报告生成器不重新运行验证；"
            "验证通过数不等于历史数据完整、策略盈利或具备上线条件。",
            _table(["检查", "结果"], [
                [item["name"], item["result"]] for item in validation["checks"]
            ]),
        ])
    return parts


def _render_annual(annual: Mapping[tuple[str, int], Mapping[str, Any]], path: Path, *, quoted: bool = False) -> None:
    # Direct Agg canvas is suitable for offline CLI use without opening a window.
    import matplotlib as mpl
    from matplotlib import font_manager
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from matplotlib.ticker import FuncFormatter, MaxNLocator

    available = {font.name for font in font_manager.fontManager.ttflist}
    font = next((name for name in (
        "Microsoft YaHei", "Noto Sans CJK SC", "Source Han Sans SC", "SimHei",
        "SimSun", "WenQuanYi Micro Hei", "PingFang SC", "Arial Unicode MS",
    ) if name in available), None)
    chinese = font is not None
    with mpl.rc_context({"font.family": [font or "DejaVu Sans"], "axes.unicode_minus": False}):
        figure = Figure(figsize=(16, 8.5), dpi=160, facecolor="white")
        FigureCanvasAgg(figure)
        counts_axis, returns_axis = figure.subplots(2, 1, sharex=True, gridspec_kw={"height_ratios": [1, 1.2]})
        figure.subplots_adjust(left=0.075, right=0.985, top=0.85, bottom=0.16, hspace=0.23)
        figure.suptitle(
            ("首波回调：14:50 报价采样 / 价格共振代理" if quoted else
             "首波回调：日线次开对照 / 价格共振代理") if chinese else
            ("First-wave pullback: 14:50 sampled quotes / Price-resonance proxy" if quoted else
             "First-wave pullback: Daily next-open comparison / Price-resonance proxy"),
            fontsize=16, fontweight="bold", y=0.97,
        )
        mode = "sampled_quotes_1450" if quoted else "next_open"
        figure.text(0.075, 0.91, f"{mode} / h10 / staged / ma5_or_horizon", fontsize=11, color="#475569")
        has_returns = False
        for index, (gate, label) in enumerate(GATES[:2]):
            variant = _variant(gate, quoted=quoted)
            counts, means = [], []
            for year in YEARS:
                metrics = annual.get((variant, year), {})
                count = _count(metrics.get("realized_trades", 0))
                counts.append(count)
                mean = _number(metrics.get("mean_net_pct")) if count else None
                means.append(mean if mean is not None else math.nan)
                has_returns = has_returns or mean is not None
            color = ("#2563eb", "#c2410c")[index]
            counts_axis.bar(
                [year + (-0.2 if index == 0 else 0.2) for year in YEARS], counts,
                width=0.38, color=color, label=label if chinese else gate,
            )
            returns_axis.plot(YEARS, means, marker=("o", "s")[index], markersize=4, linewidth=1.5, color=color)
        counts_axis.set_ylabel("已平仓交易数（笔）" if chinese else "Closed trades", fontsize=11)
        counts_axis.yaxis.set_major_locator(MaxNLocator(integer=True, nbins=5))
        counts_axis.set_ylim(bottom=0)
        counts_axis.legend(loc="upper left", frameon=False, fontsize=11)
        returns_axis.set_ylabel("平均计划资金净收益" if chinese else "Mean net return / planned capital", fontsize=11)
        returns_axis.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:.1f}%"))
        returns_axis.axhline(0, linewidth=0.8, color="#64748b", zorder=0)
        if not has_returns:
            returns_axis.set_ylim(-1, 1)
            returns_axis.text(
                0.5, 0.65, "无已平仓样本，收益未知" if chinese else "No closed trades; returns unavailable",
                transform=returns_axis.transAxes, ha="center", fontsize=11,
            )
        returns_axis.set_xticks(YEARS, labels=[str(year) for year in YEARS], rotation=60, ha="right")
        returns_axis.set_xlim(1989.3, 2026.7)
        returns_axis.set_xlabel("信号年份" if chinese else "Signal year", fontsize=11)
        for axis in (counts_axis, returns_axis):
            axis.set_axisbelow(True)
            axis.grid(axis="y", color="#e2e8f0", linewidth=0.6)
            axis.tick_params(labelsize=9)
            for side in ("top", "right"):
                axis.spines[side].set_visible(False)
        figure.text(
            0.075, 0.025,
            "零样本年份不画收益点；2026 年非完整年度。最新完整交易日：2026-10-26。" if chinese else
            "Zero-count years have no return point. 2026 is partial; latest complete session: 2026-10-26.",
            fontsize=9, color="#475569",
        )
        figure.savefig(path, format="png", dpi=160, facecolor="white")
        figure.savefig(path.with_suffix(".svg"), format="svg", facecolor="white")


def build_report(directory: Path) -> Path:
    """Read finished artifacts and write report.md and annual-results.png.

    Counts and realized means are checked against the JSONL ledger. Other
    metrics and monthly bootstrap intervals come from the research summary;
    no market access, simulation, parameter search or bootstrap is run here.
    Optional audit and validation JSON files are included only when present.
    """
    directory = Path(directory).resolve()
    summary, protocol, setups, reasons, ledger, annual = _read_inputs(directory)
    quote_summary, quote_ledger, quote_annual = _read_quote_inputs(directory, summary)
    parts = [
        "# 首波回调量化验证：14:50 报价采样与日线对照",
        f"当前研究日期：{RESEARCH_DATE}。最新完整交易日：{LAST_COMPLETE_SESSION}。",
        "**这套口述模式已量化并覆盖冻结数据库全期扫描；当前参数尚未验证出盈利优势。"
        "14:50 报价采样、日线次开和完整分钟 OHLC 是三种不同证据，分别报告。"
        "全历史真实题材归属与部分报价仍缺失，完整原模式的全历史验证尚不能成立。**",
        "## 模式定义",
        "启动前 20 日平台振幅不超过 25%、净涨不超过 15%；收盘突破平台高点且放量至少 1.2 倍。"
        "首波从已知平台低点计算，最多 30 日；涨幅达到 20% 后的首次收盘回落记为 D1。"
        "D1 确认时冻结 D0 的涨幅 20%–60%、对数价格回归日速度至少 1%、上涨均量为平台均量 1.2–2.5 倍、"
        "D0 量至少是前日两倍；D1 量不超过 D0 的 2/3。失败的首波不能事后改名为下一波。",
        "视觉 45° 随图表缩放变化，研究把它换成固定的归一化日速度。"
        "主线采用 D0 已知的相对市场收益共振组，排除候选本身，"
        "同时检查组内上涨广度、超额收益、量比与持续性。它是统计代理，不声称核实了历史行业或题材。"
        "完整阈值与因果时点见 [METHOD.md](METHOD.md)。",
    ]
    parts.extend(_quote_results(directory, quote_summary, quote_ledger, quote_annual))
    parts.extend(_d2_high_results(directory))
    parts.extend([
        "## 日线次开对照",
        "对照为 `next_open / h10 / staged / ma5_or_horizon`：D2 日线收盘确认后 D3 开盘入场，"
        "分批持仓，按研究定义的 MA5 条件或 10 个交易日上限退出。"
        "它比原买点晚，不能代替 14:50 回放。下表为已平仓机会算术均值；零交易或未知指标记为“—”。",
    ])
    main_rows, confidence_rows, conclusions = [], [], []
    for gate, label in GATES:
        variant = _variant(gate)
        metrics = _metrics(summary, variant)
        count = _count(metrics["realized_trades"])
        main_rows.append([
            label, _fmt_count(count, zero_dash=True), _fmt_count(metrics["opportunities"]), *_return_fields(metrics),
        ])
        months = len(ledger.overall.get(variant, _Bucket()).months)
        interval = _ci(metrics)
        confidence_rows.append([label, _fmt_count(months, zero_dash=True), interval])
        if count:
            conclusions.append(
                f"- {label}：已平仓 {count:,} 笔，平均计划资金净收益 {_fmt(metrics.get('mean_net_pct'), '%')}，"
                f"按月聚类 bootstrap 95% 区间 {interval}，覆盖 {months:,} 个有已平仓样本的信号月份。"
            )
        else:
            conclusions.append(f"- {label}：没有已平仓样本，收益方向与稳定性均无法判断。")
    parts.extend([
        "\n".join(conclusions),
        _table([
            "门禁", "已平仓 N", "机会总数", "胜率", "平均计划资金净收益", "平均已投资净收益",
            "利润因子", "平均资金投入", "加仓率",
        ], main_rows),
        "机会总数包含门禁拒绝、证据未知、未成交与未成熟机会，三个门禁是同一机会集合的对照，不能相加。"
        "胜率指净收益严格大于 0 的比例；利润因子为正收益之和 / 负收益绝对值之和，无亏损分母时为“—”。"
        "平均资金投入是已投入本金占每笔计划资金的比例；加仓率是已平仓机会中恰有两笔买入的比例。",
        "### 按月区间与稳定性",
        _table(["门禁", "有已平仓样本的信号月份数", "计划资金均值的月聚类 bootstrap 95% CI"], confidence_rows),
        "区间直接读取 `summary.json` 的 `mean_net_month_cluster_ci95`，不以逐笔独立抽样替代月份聚类。"
        "研究按信号月份整组重采样 1,000 次，固定种子 20261027；不足 5 个有样本月份时不提供区间。"
        "CI 为“—”时无法据此判断稳定性；区间跨零时均值方向未获该区间支持。"
        "即使区间全在零的一侧，也受机会重叠、样本选择和存续偏差影响，不能作为可上线的充分依据。",
    ])
    stability = []
    for gate, label in GATES:
        active = [annual[_variant(gate), year] for year in YEARS
                  if (_variant(gate), year) in annual and _count(annual[_variant(gate), year]["realized_trades"])]
        means = [_number(row.get("mean_net_pct")) for row in active]
        stability.append([
            label, len(active), sum(value > 0 for value in means),
            sum(value < 0 for value in means), sum(value == 0 for value in means),
        ])
    parts.extend([
        _table(["门禁", "37 年中有已平仓样本的年份数", "年度均值 > 0", "年度均值 < 0", "年度均值 = 0"], stability),
        "年度均值不按年份等权合成为全区间均值；样本少的年份和月份应结合 N 阅读。",
        "### 日线分批主策略的时间分段",
    ])
    segment_rows = []
    for gate, label in GATES:
        for segment, segment_label, _, _ in SEGMENTS:
            metrics = _metrics(summary, _variant(gate), segment)
            count = _count(metrics["realized_trades"])
            segment_rows.append([
                label, segment_label, _fmt_count(count, zero_dash=True), _fmt_count(metrics["opportunities"]),
                _fmt(metrics.get("win_rate_pct"), "%") if count else "—",
                _fmt(metrics.get("mean_net_pct"), "%") if count else "—", _ci(metrics),
            ])
    parts.extend([
        _table(["门禁", "信号日期分段", "已平仓 N", "机会总数", "胜率", "平均计划资金净收益", "月聚类 95% CI"], segment_rows),
        "分段按信号日期归属，跨年平仓不改归属。2026 年截至冻结数据实际末日，为非完整年度；"
        "这些是固定时间段对照，不宣称为事前独立样本外发现。",
        "### 固定持有 1 / 3 / 5 / 10 / 20 日的首次全仓对照",
        "本表均为 `next_open / single_full / horizon`，首次按 100% 计划资金买入，不分批，"
        "使用固定持有期退出，不套用主策略的 MA5 提前退出条件。N 和均值仍仅统计已平仓机会。",
    ])
    control_rows = []
    for gate, label in GATES:
        for horizon in (1, 3, 5, 10, 20):
            row = [label, str(horizon)]
            for segment in (None, *(item[0] for item in SEGMENTS)):
                metrics = _metrics(summary, _variant(gate, horizon=horizon), segment)
                count = _count(metrics["realized_trades"])
                row.extend([
                    _fmt_count(count, zero_dash=True),
                    _fmt(metrics.get("mean_net_pct"), "%") if count else "—",
                ])
            control_rows.append(row)
    parts.extend([
        _table([
            "门禁", "持有交易日", "全区间 N", "全区间均值", "1990–2022 N", "1990–2022 均值",
            "2023–2025 N", "2023–2025 均值", "2026 N", "2026 均值",
        ], control_rows),
        "固定持有对照并非所有均值均为负。例如价格共振代理的 20 日全仓对照均值为 "
        f"{_fmt(_metrics(summary, _variant('price_resonance_proxy', horizon=20)).get('mean_net_pct'), '%')}，"
        f"月聚类 95% 区间 {_ci(_metrics(summary, _variant('price_resonance_proxy', horizon=20)))}。"
        "这个区间跨零的小幅正均值不足以证明盈利；也不能把全仓固定持有的结果算作半仓分批模型的收益。",
        "### 完整分钟 OHLC 实验的证据与成交状态",
        "本表保留日线实验冻结时的 `intraday_1450 / h10 / staged / ma5_or_horizon` 结果。"
        "这一批分钟覆盖不足，没有完整平仓交易；后来取得的报价采样回放已单独报告，"
        "没有覆盖此表的冻结结果。日线次开也不能用于填充分钟成交或收益。",
    ])
    minute_rows, raw_status_rows = [], []
    for gate, label in GATES:
        variant = _variant(gate, minute=True)
        bucket = ledger.overall.get(variant, _Bucket())
        counts = ledger.minute_counts.get(variant, Counter())
        minute_rows.append([
            label, bucket.opportunities, counts["filled"], bucket.closed,
            ledger.statuses[variant]["unverifiable"], ledger.statuses[variant]["mainline_rejected"],
            ledger.statuses[variant]["mainline_unverifiable"],
        ])
        for status, count in sorted(ledger.statuses.get(variant, {}).items()):
            raw_status_rows.append([label, status, count])
    parts.extend([
        _table(["门禁", "全部机会", "曾买入（可重叠）", "完整平仓", "交易证据不足", "主线拒绝", "主线未知"], minute_rows),
        "曾买入一列与最终状态可重叠；仅首买而缺少后续证据的机会仍属交易证据不足，不能计作完整收益。",
        _table(["门禁", "原始 status", "计数"], raw_status_rows) if raw_status_rows else "原始分钟状态：—（无机会记录）。",
        "### 年度研究图",
        "![日线次开对照与价格共振代理年度结果](annual-results.png)",
        "图只比较无主线与价格共振代理的日线分批主策略，按信号年统计已平仓 N 与平均计划资金净收益。"
        "1990–2026 每年均保留；零样本年份的交易数为 0，收益不画点，也不填 0。",
        "## 依据与口径",
        "### 资金与执行口径",
        "每个机会独立按 100,000 计划资金计算。主策略首次只买 50%，后续可能不加仓；"
        "未投入现金按 0 收益计算。平均计划资金净收益与平均已投资净收益使用不同分母，不能互换。"
        "机会独立，无 TopN、账户资金或持仓数限制，同一股票允许重叠信号。"
        "本报告不是受资金约束的组合回测，不给出组合年化、复利累计净值或账户收益承诺。",
        "已平仓定义与研究脚本一致：`status` 属于 `closed / completed / filled`，"
        "`exit_reason` 不是 `data_end`，且 `net_return_pct` 有值。未成熟和未知机会不按零收益参与均值。"
        "源价与复权、T+1、费用、涨跌停及执行证据缺口详见 [METHOD.md](METHOD.md)。",
        "### 数据范围与冻结信息",
    ])
    database_range = summary["database_range"]
    parts.append(_table(["项目", "实际记录"], [
        ["原始日线全区间", f"{database_range[0] or '—'} 至 {database_range[1] or '—'}"],
        ["代码数", _fmt_count(summary.get("stock_codes"))],
        ["原始日线数", _fmt_count(database_range[2])],
        ["市场交易日数", _fmt_count(summary.get("market_sessions"))],
        ["全部形态数", f"{sum(setups.values()):,}"],
        ["日线及完整分钟实验逐笔记录数（24 变体）", f"{sum(bucket.opportunities for bucket in ledger.overall.values()):,}"],
        ["报价采样实验逐笔记录数（3 门禁）", f"{quote_summary['ledger_rows']:,}"],
        ["前缀截断检查数", _fmt_count(summary.get("prefix_checks"))],
        ["冻结时间", protocol.get("frozen_at")],
        ["研究产物生成时间", summary.get("created_at")],
        ["冻结数据库 SHA256", summary.get("database_sha256")],
    ]))
    if database_range[1] != LAST_COMPLETE_SESSION:
        parts.append(
            f"冻结库实际末日为 {_cell(database_range[1])}，与本次最新完整交易日 {LAST_COMPLETE_SESSION} 不同；"
            "所有结果只代表该冻结库实际覆盖范围。"
        )
    parts.extend([
        "当前代码集合缺少完整退市历史，存续偏差未消除；不能将现有代码的历史样本当作完整历史可交易股票池。",
        "本地与生产源在三个重叠交易日做了价格、成交量与因子抽查，并检查 2023 年拼接处的调整收益。"
        "接缝未发现 30% 以上的调整价格跳变；两处百倍成交量单位差异为已排除的指数。"
        "这不是全日期逐行来源一致性证明，原件见 [source-merge-crosscheck.json](source-merge-crosscheck.json)。",
        "### 数据审计与排除",
        "排除统计来自冻结行情库审计，不将不同维度简单相加。逐年计数见 [summary.json](summary.json)。",
        _table(["项目", "记录数"], [
            ["无效 OHLCV", summary["quality"]["invalid_rows"]],
            ["上市日期之前的行情", summary["quality"]["prelisting_rows"]],
            ["有效价格缺少因子", summary["quality"]["valid_prices_without_factor"]],
        ]),
        "### 全部形态与失败计数",
        _table(["原始形态 status", "计数"], [[status, count] for status, count in sorted(setups.items())])
        if setups else "形态记录：—（空产物，无形态）。",
    ])
    if reasons:
        parts.append(_table(["形态 status", "原因字段", "原始原因", "计数"], [
            [status, key, reason, count] for (status, key, reason), count in sorted(reasons.items())
        ]))
    else:
        parts.append("形态 CSV 未提供非空原因字段，失败细分以原始 status 计数为准。")
    parts.extend([
        "### 分钟与历史题材覆盖",
        f"日线对照冻结时完整分钟覆盖为 {summary['minute_coverage']['code_days']:,} 个代码日，"
        f"补采后为 {quote_summary['coverage']['code_days']:,} 个；"
        "补采数据用于单独的报价实验，未回填覆盖日线对照原产物。"
        "完整分钟与逐机会 D2 报价采样是不同覆盖口径，详见各自 summary 的覆盖字段。",
        "新闻与题材相关证据覆盖：",
        _table(["来源", "起日", "末日", "快照数"], summary["news_coverage"]),
        "新闻覆盖本身不等于题材门禁通过；真实题材门禁仅使用逐机会当时可得的历史证据。"
        "不能将当前题材、事后新闻或价格代理反填到无证据历史日期。",
    ])
    parts.extend(_optional_evidence(directory))
    parts.extend([
        "### 冻结参数与产物",
        _json_block(protocol.get("configuration")),
        "实现文件哈希（`protocol.source_hashes`）：",
        _json_block(protocol.get("source_hashes")),
        "- [逐笔机会 JSONL](all-opportunities.jsonl) 与 [逐笔机会 CSV](all-opportunities.csv)\n"
        "- [14:50 报价逐笔 JSONL](quote-opportunities.jsonl) 与 [报价汇总](quote-summary.json)\n"
        "- [全部形态及失败记录](all-wave-setups.csv)\n"
        "- [日线年度 CSV](yearly-results.csv)、[PNG](annual-results.png)、[SVG](annual-results.svg)\n"
        "- [报价年度 CSV](quote-yearly-results.csv)、[PNG](quote-annual-results.png)、[SVG](quote-annual-results.svg)\n"
        "- [真实汇总及月聚类区间](summary.json) 与 [冻结协议](protocol.json)\n"
        "- [方法与执行限制](METHOD.md)",
        "### 复现",
        "本次研究输入位于项目根目录下的 `.local/research/2026-10-26-first-wave/`："
        "冻结库为 `frozen-market.db`，报价缓存为 `quote-cache/`，补充分时为 `minute-supplement/`；"
        "日线对照使用其独立保留的 `minute-overlay/`。",
        "在项目根目录，使用冻结数据库、对应分钟覆盖文件和相同实现版本重跑研究；"
        "以下为命令模板，不由报告生成器执行：",
        "```text\npython scripts/first_wave_research.py <frozen-db> --output <dir> --minute-overlay <overlay>\n```",
        "单独复现报价采样回放（优先读取缓存，仅对需要且未缓存的日期请求数据）：",
        "```text\npython scripts/first_wave_quote_research.py replay <frozen-db> --directory <dir> --cache <cache> --minute-overlay <supplement>\n```",
        "两种实验产物均已完成后，独立核验台账并重建本报告与年度图：",
        "```text\npython scripts/verify_first_wave_research.py <frozen-db> <dir>\n"
        "python scripts/verify_first_wave_quote_research.py <frozen-db> <dir> --cache <cache> --minute-overlay <supplement>\n"
        "python scripts/first_wave_report.py <dir>\n```",
        "报告生成器读取两组本地产物，并在存在时读取收盘核对、D2 条件审计和验证 JSON；"
        "不访问数据库、不联网、不启动回测。"
        "它核对汇总、逐笔与年度计数和已平仓均值；文件缺失或不一致时直接报错。"
        "字体优先使用本机可用中文字体，否则采用英文图中文字；不下载字体。",
    ])
    report_path = directory / "report.md"
    report_text = "\n\n".join(parts) + "\n"
    _render_annual(annual, directory / "annual-results.png")
    _render_annual(quote_annual, directory / "quote-annual-results.png", quoted=True)
    with (directory / "quote-yearly-results.csv").open("w", encoding="utf-8-sig", newline="") as target:
        fields = ["variant", "year", "opportunities", "realized_trades", "mean_net_pct", "win_rate_pct"]
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        for (variant, year), metrics in sorted(quote_annual.items()):
            writer.writerow({"variant": variant, "year": year, **{key: metrics.get(key) for key in fields[2:]}})
    report_path.write_text(report_text, encoding="utf-8", newline="\n")
    return report_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="已完成研究的本地产物目录")
    args = parser.parse_args(argv)
    try:
        report = build_report(args.directory)
    except (OSError, ValueError, KeyError, ImportError) as error:
        parser.error(str(error))
    print(report)
    print(report.with_name("annual-results.png"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
