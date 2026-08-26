r"""行情库数据体检：换源之后「数据到底到位没有」要能天天自动答。

背景：把主源换成通达信只改变「以后写进来的数据」。一次性重同步之后没人盯着，
库就会慢慢漂回去——回退源写进来的合成成交额、spot 落的无回执行、退市票的
陈旧水位，都是安静累积的。所以体检必须是**日常任务**，不是一次性脚本。

本模块只读、只判、只出中文告警，**不改库**：修复动作有自己的入口
（``scripts/resync_market_authoritative.py`` / ``repair/turnover``），
体检擅自动手会让「谁改的库」这件事说不清。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: 合成成交额判据的容差。腾讯日 K 的 amount 就是 close*volume，完全相等。
#: 1990 年代单一价格成交日真实值也会相等，所以这条只在**会合成的源**上算。
_SYNTH_EPSILON = 1.0

#: 已知会合成 amount 的源。新增回退源前先确认它给的是不是真实成交额。
FABRICATING_SOURCES: tuple[str, ...] = ("tencent", "tencent_spot")

#: 权威源前缀。占比低于阈值说明主源长期失联、库在靠回退源续命。
AUTHORITATIVE_PREFIX = "tdx"


@dataclass
class QualityThresholds:
    """阈值。默认值是「重同步刚做完」的实测水位留出余量后的结果。"""

    #: 权威源占比下限。重同步后实测 99.2%，跌破 95% 说明有系统性回退。
    min_authoritative_ratio: float = 0.95
    #: 合成成交额行数上限。重同步后实测 335 行（全是通达信不返回的老日期）。
    max_fabricated_rows: int = 2000
    #: 近窗缺回执行数上限。回执是研究输入证据，缺了严格 PIT 会拒绝该输入。
    max_missing_receipts: int = 200
    #: 近窗回看天数。
    lookback_days: int = 90
    #: 最后一个交易日的最少行数。全市场约 5540，少太多说明当日没同步全。
    min_last_day_rows: int = 5000
    #: 基准指数收盘价下限。中证系列基点 1000；低于它说明串成了同号个股。
    min_index_close: float = 1000.0
    #: 基准指数代码。
    index_codes: tuple[str, ...] = ("000300", "000905", "000852")


@dataclass
class Finding:
    """一条体检结论。``level`` 只有 ok / warn / block 三档。"""

    key: str
    level: str
    message: str
    observed: dict[str, Any] = field(default_factory=dict)
    remediation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "level": self.level,
            "message": self.message,
            "observed": dict(self.observed),
            "remediation": self.remediation,
        }


def _scalar(store: Any, sql: str, params: tuple = ()) -> Any:
    row = store.conn.execute(sql, params).fetchone()
    return row[0] if row else None


def _source_mix(store: Any) -> list[tuple[str, int]]:
    rows = store.conn.execute(
        "SELECT source, COUNT(*) FROM quotes_daily GROUP BY 1 ORDER BY 2 DESC"
    ).fetchall()
    return [(str(source or ""), int(count)) for source, count in rows]


def _check_authoritative(mix: list[tuple[str, int]], limits: QualityThresholds) -> Finding:
    total = sum(count for _s, count in mix) or 1
    authoritative = sum(
        count for source, count in mix if source.startswith(AUTHORITATIVE_PREFIX)
    )
    ratio = authoritative / total
    observed = {
        "authoritative_rows": authoritative,
        "total_rows": total,
        "ratio": round(ratio, 4),
        "top_sources": mix[:5],
    }
    if ratio >= limits.min_authoritative_ratio:
        return Finding(
            "authoritative_ratio",
            "ok",
            "权威源（通达信）占比 %.1f%%" % (ratio * 100),
            observed,
        )
    return Finding(
        "authoritative_ratio",
        "block",
        "权威源（通达信）占比只有 %.1f%%，低于 %.0f%% 下限——主源可能长期失联，"
        "库在靠回退源续命，而回退源的成交额是 close×volume 合成的假值。"
        % (ratio * 100, limits.min_authoritative_ratio * 100),
        observed,
        remediation="先查通达信连通性（scripts/check_lane_readiness.py），"
        "恢复后跑 scripts/resync_market_authoritative.py 重写",
    )


def _check_fabricated(store: Any, limits: QualityThresholds) -> Finding:
    """合成成交额只在会合成的源上算——老年代单一价格成交日真实值也相等。"""
    placeholders = ",".join("?" * len(FABRICATING_SOURCES))
    count = int(
        _scalar(
            store,
            "SELECT COUNT(*) FROM quotes_daily WHERE source IN (%s)" % placeholders
            + " AND amount IS NOT NULL AND volume > 0 AND close > 0"
            "   AND ABS(amount - close*volume) < ?",
            tuple(FABRICATING_SOURCES) + (_SYNTH_EPSILON,),
        )
        or 0
    )
    observed = {"rows": count, "limit": limits.max_fabricated_rows}
    if count <= limits.max_fabricated_rows:
        return Finding("fabricated_amount", "ok", "合成成交额 %d 行" % count, observed)
    return Finding(
        "fabricated_amount",
        "warn",
        "合成成交额 %d 行，超过 %d 行上限。这些行的 amount 是 close×volume 算出来的，"
        "不是真实成交额；任何按成交额筛选/排序的策略都会被它带偏。"
        % (count, limits.max_fabricated_rows),
        observed,
        remediation="跑 scripts/resync_market_authoritative.py 用通达信重写",
    )


def _check_receipts(store: Any, limits: QualityThresholds) -> Finding:
    count = int(
        _scalar(
            store,
            "SELECT COUNT(*) FROM quotes_daily"
            " WHERE trade_date >= date('now', ?) AND receipt_id IS NULL",
            ("-%d day" % limits.lookback_days,),
        )
        or 0
    )
    observed = {
        "rows": count,
        "limit": limits.max_missing_receipts,
        "lookback_days": limits.lookback_days,
    }
    if count <= limits.max_missing_receipts:
        return Finding(
            "missing_receipts", "ok", "近 %d 日缺回执 %d 行" % (limits.lookback_days, count), observed
        )
    return Finding(
        "missing_receipts",
        "warn",
        "近 %d 日有 %d 行日 K 没有来源回执，超过 %d 行上限。回执是研究输入证据，"
        "缺回执的行会被严格 PIT 研究直接拒绝。"
        % (limits.lookback_days, count, limits.max_missing_receipts),
        observed,
        remediation="这些多是 spot 落的临时行；等日终同步重写，或跑一次 force 同步补齐",
    )


def _check_last_day(store: Any, limits: QualityThresholds) -> Finding:
    last_day = _scalar(store, "SELECT MAX(trade_date) FROM trading_calendar")
    if not last_day:
        return Finding(
            "last_day_rows", "block", "交易日历为空，无法判断当日覆盖", {}
        )
    count = int(
        _scalar(
            store,
            "SELECT COUNT(*) FROM quotes_daily WHERE trade_date = ?",
            (str(last_day),),
        )
        or 0
    )
    observed = {"trade_date": str(last_day), "rows": count, "limit": limits.min_last_day_rows}
    if count >= limits.min_last_day_rows:
        return Finding(
            "last_day_rows", "ok", "最后交易日 %s 覆盖 %d 只" % (last_day, count), observed
        )
    return Finding(
        "last_day_rows",
        "warn",
        "最后交易日 %s 只覆盖 %d 只，少于 %d 只下限——当日同步可能没跑完。"
        % (last_day, count, limits.min_last_day_rows),
        observed,
        remediation="看运维「执行历史」里当天的行情同步任务是否失败或被跳过",
    )


def _check_index_sanity(store: Any, limits: QualityThresholds) -> Finding:
    """基准指数串成同号个股是真出过的事故：中证 500 该 7717，串回来 8.54。"""
    placeholders = ",".join("?" * len(limits.index_codes))
    rows = store.conn.execute(
        "SELECT code, trade_date, close FROM quotes_daily"
        " WHERE code IN (%s)" % placeholders
        + "   AND trade_date >= (SELECT MIN(trade_date) FROM (SELECT trade_date"
        "       FROM trading_calendar ORDER BY trade_date DESC LIMIT 5))"
        "   AND close < ?",
        tuple(limits.index_codes) + (limits.min_index_close,),
    ).fetchall()
    observed = {"bad_rows": [tuple(r) for r in rows[:10]], "count": len(rows)}
    if not rows:
        return Finding("index_sanity", "ok", "基准指数近 5 日收盘量级正常", observed)
    return Finding(
        "index_sanity",
        "block",
        "基准指数近 5 日有 %d 行收盘价低于 %.0f——几乎肯定是串成了同号个股"
        "（通达信指数要走 get_index_bars，用 get_security_bars 会安静地返回深市同号股票）。"
        "基准一歪，复盘里每一条相对收益都跟着错。"
        % (len(rows), limits.min_index_close),
        observed,
        remediation="用 instrument_type='INDEX' 重同步这三只，并清掉指数发布日之前的残留行",
    )


def _check_watermarks(store: Any) -> Finding:
    """非权威源的水位要能说清原因——退市票取不到是正常的，其它就不是。"""
    rows = store.conn.execute(
        "SELECT w.code, w.source, w.status, w.last_trade_date,"
        "       COALESCE(i.status, '') FROM ingest_watermark w"
        " LEFT JOIN instruments i ON i.code = w.code"
        " WHERE w.source NOT LIKE 'tdx%'"
    ).fetchall()
    unexplained = [
        tuple(row) for row in rows if str(row[4] or "") not in ("delisted", "suspended")
    ]
    observed = {"non_authoritative": len(rows), "unexplained": unexplained[:10]}
    if not unexplained:
        return Finding(
            "watermark_source",
            "ok",
            "非权威源水位 %d 条，全部可解释（退市/停牌）" % len(rows),
            observed,
        )
    return Finding(
        "watermark_source",
        "warn",
        "有 %d 只票的水位来自非权威源且不是退市/停牌——说明通达信取不到它们，"
        "但原因不明。" % len(unexplained),
        observed,
        remediation="逐票用 tdx_daily.fetch_daily_bars 手工试一次，确认是代码段不支持还是别的",
    )


def inspect_market_data(
    store: Any, *, thresholds: QualityThresholds | None = None
) -> dict[str, Any]:
    """跑一遍全部体检项，返回可直接进 job payload 的结构。

    只读；发现问题只报不改。``blocked`` 为真表示有 block 级问题。
    """
    limits = thresholds or QualityThresholds()
    mix = _source_mix(store)
    findings = [
        _check_authoritative(mix, limits),
        _check_fabricated(store, limits),
        _check_receipts(store, limits),
        _check_last_day(store, limits),
        _check_index_sanity(store, limits),
        _check_watermarks(store),
    ]
    blocked = [f for f in findings if f.level == "block"]
    warned = [f for f in findings if f.level == "warn"]
    return {
        "blocked": bool(blocked),
        "block_count": len(blocked),
        "warn_count": len(warned),
        "findings": [f.to_dict() for f in findings],
        "alert": build_alert(findings),
    }


def build_alert(findings: list[Finding]) -> str:
    """中文告警文案。全绿返回空串——没事就别打扰人。"""
    bad = [f for f in findings if f.level in ("block", "warn")]
    if not bad:
        return ""
    lines = ["行情库体检发现 %d 项问题：" % len(bad)]
    for item in bad:
        tag = "【阻断】" if item.level == "block" else "【提醒】"
        lines.append("%s%s" % (tag, item.message))
        if item.remediation:
            lines.append("   处理：%s" % item.remediation)
    return "\n".join(lines)