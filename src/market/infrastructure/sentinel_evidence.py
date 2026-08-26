"""体检 Sprint C：回执 / 证据缺口 / 竞速回退 / 同步 Job 时效。

只读 ``market.db`` 回执表与可选的托管 sync Job 快照；不打外网。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Mapping, Sequence

if TYPE_CHECKING:
    from src.market.infrastructure.sentinel import Finding
    from src.market.infrastructure.store import MarketStore
else:
    Finding = Any
    MarketStore = Any

EVIDENCE_CATALOG: tuple[dict[str, str], ...] = (
    {"id": "ohlc_reject_rate", "label": "坏 OHLC 拒绝比", "group": "回执"},
    {"id": "source_evidence_gap", "label": "来源证据缺口", "group": "回执"},
    {"id": "race_fallback_rate", "label": "竞速回退占比", "group": "回执"},
    {"id": "job_sync_stale", "label": "同步 Job 时效", "group": "运维"},
)

EVIDENCE_THRESHOLDS: dict[str, float] = {
    "max_ohlc_reject_ratio": 0.05,
    "max_evidence_gap_ratio": 0.50,
    "max_fallback_ratio": 0.60,
    "max_sync_job_age_hours": 36.0,
    "receipt_lookback": 200.0,
    # 证据缺口只扫近窗交易日，避免千万行 quotes_daily 全表 COUNT（体检会卡死）。
    "evidence_gap_lookback_days": 20.0,
    # 近窗之外再抽样几个历史交易日：增量同步只重写近 20 日，只看近窗会恒 green。
    "evidence_gap_history_samples": 5.0,
}


def _F(
    check: str,
    severity: str,
    message: str,
    observed: Any = None,
    threshold: Any = None,
) -> Finding:
    from src.market.infrastructure.sentinel import Finding as FindingCls

    return FindingCls(check, severity, message, observed, threshold)


def evidence_remediation(check: str) -> dict[str, str] | None:
    mapping = {
        "ohlc_reject_rate": {
            "action": "sync",
            "label": "换源重同步",
            "hint": "近次回执坏 OHLC 偏高，换数据源或强制重拉",
        },
        "source_evidence_gap": {
            "action": "sync",
            "label": "全量重同步",
            "hint": "大量日 K 无回执/attempts，严格研究不可用；建议强制同步补证据",
        },
        "race_fallback_rate": {
            "action": "open_lanes",
            "label": "检查主源",
            "hint": "竞速常落到后备源，到运维数据源页测速/启主源",
        },
        "job_sync_stale": {
            "action": "open_jobs",
            "label": "去工坊手跑 Job",
            "hint": "日终/盘中同步过久未跑或失败；勿一键全量 bootstrap，到工坊 Job 手跑或查错误",
        },
    }
    return mapping.get(check)


def _parse_coverage(raw: object) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str) and raw.strip():
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}
    return {}


def check_ohlc_reject_rate(
    store: MarketStore,
    *,
    max_ratio: float,
    lookback: int = 200,
) -> Finding:
    """近 N 条回执里 ``rejected_ohlc_rows / (written+rejected)``。"""
    rows = store.conn.execute(
        "SELECT coverage_json FROM source_route_receipts "
        "ORDER BY generated_at DESC, receipt_id DESC LIMIT ?",
        (max(1, int(lookback)),),
    ).fetchall()
    if not rows:
        return _F(
            "ohlc_reject_rate",
            "ok",
            "尚无同步回执，跳过坏 OHLC 比",
            observed={"receipts": 0},
            threshold=max_ratio,
        )
    rejected = 0
    written = 0
    for row in rows:
        cov = _parse_coverage(row["coverage_json"] if "coverage_json" in row.keys() else None)
        rejected += int(cov.get("rejected_ohlc_rows") or 0)
        written += int(cov.get("rows_written") or 0)
    denom = rejected + written
    ratio = (rejected / denom) if denom else 0.0
    observed = {
        "receipts": len(rows),
        "rejected_ohlc_rows": rejected,
        "rows_written": written,
        "ratio": round(ratio, 6),
    }
    if denom == 0:
        return _F(
            "ohlc_reject_rate",
            "ok",
            f"近 {len(rows)} 条回执无写入量统计",
            observed=observed,
            threshold=max_ratio,
        )
    if ratio > max_ratio:
        return _F(
            "ohlc_reject_rate",
            "warn",
            f"近 {len(rows)} 条回执坏 OHLC 拒绝比 {ratio:.1%}（阈值 {max_ratio:.0%}）",
            observed=observed,
            threshold=max_ratio,
        )
    return _F(
        "ohlc_reject_rate",
        "ok",
        f"坏 OHLC 拒绝比 {ratio:.1%}（近 {len(rows)} 条回执）",
        observed=observed,
        threshold=max_ratio,
    )


def _recent_trade_dates(store: MarketStore, *, lookback_days: int) -> list[str]:
    """近窗交易日（新→旧）。日历优先；空日历时回退 quotes 末日。"""
    limit = max(1, int(lookback_days))
    days = [
        str(row[0])
        for row in store.conn.execute(
            "SELECT trade_date FROM trading_calendar"
            " ORDER BY trade_date DESC LIMIT ?",
            (limit,),
        )
    ]
    if days:
        return days
    return [
        str(row[0])
        for row in store.conn.execute(
            "SELECT DISTINCT trade_date FROM quotes_daily"
            " ORDER BY trade_date DESC LIMIT ?",
            (limit,),
        )
    ]


def _historical_probe_dates(
    store: MarketStore, *, recent: Sequence[str], samples: int
) -> list[str]:
    """在近窗之外均匀取若干历史交易日做抽样探针（旧→新）。

    日 K 增量同步只重写最近约 20 个交易日，这恰好就是近窗——近窗回执必然
    齐全，只看近窗的"证据缺口"会退化成恒真断言。历史抽样不做全表 COUNT：
    ``quotes_daily`` 主键是 ``(trade_date, code)``，按日取数走主键前缀。
    """
    if samples <= 0 or not recent:
        return []
    oldest_recent = min(recent)
    days = [
        str(row[0])
        for row in store.conn.execute(
            "SELECT trade_date FROM trading_calendar WHERE trade_date < ?"
            " ORDER BY trade_date",
            (oldest_recent,),
        )
    ]
    if not days:
        return []
    if len(days) <= samples:
        return days
    step = (len(days) - 1) / float(samples - 1) if samples > 1 else 0.0
    picked = {days[min(len(days) - 1, round(index * step))] for index in range(samples)}
    return sorted(picked)


def _receiptless_ratio(store: MarketStore, days: Sequence[str]) -> tuple[int, int]:
    """给定交易日集合内 ``(总行数, 无 receipt_id 行数)``。"""
    if not days:
        return (0, 0)
    placeholders = ",".join("?" * len(days))
    row = store.conn.execute(
        "SELECT COUNT(*) AS n,"
        " SUM(CASE WHEN receipt_id IS NULL OR receipt_id = '' THEN 1 ELSE 0 END)"
        " AS legacy"
        f" FROM quotes_daily WHERE trade_date IN ({placeholders})",
        list(days),
    ).fetchone()
    total = int(row["n"] if row else 0)
    legacy = int(row["legacy"] if row and row["legacy"] is not None else 0)
    return (total, legacy)


#: 孤儿回执抽样条数。写回执坏掉会在最近生成的那批里现形,不需要扫全史
#: (生产库 106 万条,无界 NOT EXISTS 实测 2593 ms)。
ORPHAN_RECEIPT_SAMPLE = 20000


def check_source_evidence_gap(
    store: MarketStore,
    *,
    max_ratio: float,
    lookback_days: int = 20,
    history_samples: int = 5,
) -> Finding:
    """日 K 无 ``receipt_id`` / 回执无 attempt 的比例。

    故意不扫全表：千万行库上 ``COUNT(*) WHERE receipt_id IS NULL`` 可达数秒，
    体检页会一直停在「连接行情仓」。近窗（默认 20 交易日）逐日精确统计，
    近窗之外按主键前缀抽样若干历史交易日——增量同步只重写最近约 20 个交易日，
    只看近窗等于只检查刚被重写的那批行，永远green。历史无回执行对严格研究
    仍由 ``source_evidence(codes, start, end)`` 按实际窗口判定。
    """
    days = _recent_trade_dates(store, lookback_days=lookback_days)
    if not days:
        return _F(
            "source_evidence_gap",
            "ok",
            "仓内无日 K，跳过证据缺口",
            observed={"total_rows": 0, "lookback_days": lookback_days},
            threshold=max_ratio,
        )
    total, legacy = _receiptless_ratio(store, days)
    if total == 0:
        return _F(
            "source_evidence_gap",
            "ok",
            "近窗无日 K，跳过证据缺口",
            observed={
                "total_rows": 0,
                "lookback_days": lookback_days,
                "window_first": days[-1],
                "window_last": days[0],
            },
            threshold=max_ratio,
        )
    # 只看**最近生成**的那批回执,不扫全史。
    #
    # 本函数的 docstring 已经写明「故意不扫全表」,但这条 NOT EXISTS 原先是无界的:
    # 生产库 106 万条回执 × 逐条相关子查询,实测 2593 ms——比这个函数其余部分加起来还贵,
    # 而且和上面近窗抽样的设计自相矛盾。
    #
    # 按 generated_at 倒序取样是对的轴:孤儿回执意味着**写回执的那一步坏了**,
    # 坏了就会在最近生成的那批里现形;远古孤儿既查不动也没法补。
    # 走 idx_source_receipts_recent,O(样本数) 而不是 O(全表)。
    orphan_row = store.conn.execute(
        "SELECT COUNT(*) AS n FROM ("
        "  SELECT receipt_id FROM source_route_receipts"
        "   ORDER BY generated_at DESC, receipt_id DESC LIMIT ?"
        ") r WHERE NOT EXISTS ("
        "  SELECT 1 FROM source_route_attempts a WHERE a.receipt_id = r.receipt_id"
        ")",
        (ORPHAN_RECEIPT_SAMPLE,),
    ).fetchone()
    orphan_receipts = int(orphan_row["n"] if orphan_row else 0)
    ratio = legacy / total
    history_days = _historical_probe_dates(
        store, recent=days, samples=int(history_samples)
    )
    history_total, history_legacy = _receiptless_ratio(store, history_days)
    history_ratio = (history_legacy / history_total) if history_total else None
    observed = {
        "total_rows": total,
        "legacy_rows": legacy,
        "orphan_receipts": orphan_receipts,
        # 抽样口径要跟着结论走,否则「0 条孤儿」会被误读成「全库干净」。
        "orphan_scanned": ORPHAN_RECEIPT_SAMPLE,
        "ratio": round(ratio, 6),
        "lookback_days": lookback_days,
        "window_first": days[-1],
        "window_last": days[0],
        "history_sample_days": history_days,
        "history_sample_rows": history_total,
        "history_legacy_rows": history_legacy,
        "history_ratio": None if history_ratio is None else round(history_ratio, 6),
    }
    parts = []
    if ratio > max_ratio:
        parts.append(f"近窗无回执日 K {ratio:.0%}（{days[-1]}→{days[0]}）")
    if orphan_receipts:
        parts.append(f"{orphan_receipts} 条回执缺 attempts")
    if history_ratio is not None and history_ratio > max_ratio:
        parts.append(
            f"历史抽样 {len(history_days)} 个交易日无回执日 K {history_ratio:.0%}"
        )
    if parts:
        return _F(
            "source_evidence_gap",
            "warn",
            "来源证据缺口：" + "；".join(parts),
            observed=observed,
            threshold=max_ratio,
        )
    scope = f"近窗 {days[-1]}→{days[0]}"
    if history_total:
        scope += f" + 历史抽样 {len(history_days)} 日"
    else:
        scope += "（近窗之外未抽到历史日 K，未覆盖）"
    return _F(
        "source_evidence_gap",
        "ok",
        f"{scope} 回执覆盖 {(1 - ratio):.0%}，attempts 齐全",
        observed=observed,
        threshold=max_ratio,
    )


def check_race_fallback_rate(
    store: MarketStore,
    *,
    max_ratio: float,
    lookback: int = 200,
) -> Finding:
    """近 N 条成功回执中 ``fallback_used`` 占比。"""
    sample = store.conn.execute(
        "SELECT fallback_used FROM source_route_receipts "
        "WHERE TRIM(COALESCE(selected_source, '')) <> '' "
        "ORDER BY generated_at DESC, receipt_id DESC LIMIT ?",
        (max(1, int(lookback)),),
    ).fetchall()
    if not sample:
        return _F(
            "race_fallback_rate",
            "ok",
            "尚无命中源回执，跳过竞速回退比",
            observed={"receipts": 0},
            threshold=max_ratio,
        )
    fallback = sum(1 for row in sample if int(row["fallback_used"] or 0))
    ratio = fallback / len(sample)
    observed = {
        "receipts": len(sample),
        "fallback_used": fallback,
        "ratio": round(ratio, 6),
    }
    if ratio > max_ratio:
        return _F(
            "race_fallback_rate",
            "warn",
            f"竞速回退占比 {ratio:.0%}（近 {len(sample)} 条命中回执，阈值 {max_ratio:.0%}）",
            observed=observed,
            threshold=max_ratio,
        )
    return _F(
        "race_fallback_rate",
        "ok",
        f"竞速回退占比 {ratio:.0%}（近 {len(sample)} 条）",
        observed=observed,
        threshold=max_ratio,
    )


def _parse_job_time(raw: str) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    for candidate in (text, text.replace(" ", "T")):
        try:
            dt = datetime.fromisoformat(candidate)
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def load_managed_sync_jobs() -> list[dict[str, Any]] | None:
    """读 ops 托管行情同步 Job；ops.db 不存在返回 []；异常返回 None（跳过）。"""
    try:
        from src.ops import MANAGED_SYNC_EOD, MANAGED_SYNC_INTRADAY, OpsStore
        from src.shared.paths import ops_db
    except Exception:
        return None
    path = ops_db()
    if not path.exists():
        return []
    try:
        store = OpsStore(path)
    except Exception:
        return None
    try:
        jobs: list[dict[str, Any]] = []
        for name in (MANAGED_SYNC_EOD, MANAGED_SYNC_INTRADAY):
            job = store.get_job_by_name(name)
            if job:
                jobs.append(dict(job))
        return jobs
    except Exception:
        return None
    finally:
        try:
            store.close()
        except Exception:
            pass


def check_job_sync_stale(
    sync_jobs: Sequence[Mapping[str, Any]] | None = None,
    *,
    max_age_hours: float,
    now: datetime | None = None,
) -> Finding:
    """日终/盘中托管 sync 是否失败或过久未跑。"""
    jobs = list(sync_jobs) if sync_jobs is not None else load_managed_sync_jobs()
    if jobs is None:
        return _F(
            "job_sync_stale",
            "ok",
            "无法读取运维 Job（跳过）",
            observed={"skipped": True},
            threshold=max_age_hours,
        )
    if not jobs:
        return _F(
            "job_sync_stale",
            "ok",
            "未配置托管行情同步 Job",
            observed={"jobs": 0},
            threshold=max_age_hours,
        )

    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    ceiling = timedelta(hours=float(max_age_hours))
    issues: list[str] = []
    observed_jobs: list[dict[str, Any]] = []
    enabled_any = False
    for job in jobs:
        name = str(job.get("name") or job.get("id") or "sync")
        enabled = bool(job.get("enabled", True))
        status = str(job.get("last_status") or "")
        last_run = str(job.get("last_run_at") or "")
        observed_jobs.append(
            {
                "name": name,
                "enabled": enabled,
                "last_status": status,
                "last_run_at": last_run,
            }
        )
        if not enabled:
            continue
        enabled_any = True
        if status.lower() in {"failed", "error"}:
            issues.append(f"「{name}」最近失败")
            continue
        when = _parse_job_time(last_run)
        if when is None:
            issues.append(f"「{name}」尚无成功运行记录")
            continue
        age = clock - when
        if age > ceiling:
            hours = age.total_seconds() / 3600.0
            issues.append(f"「{name}」已 {hours:.0f}h 未跑")

    if not enabled_any:
        return _F(
            "job_sync_stale",
            "ok",
            "托管行情同步均已关闭",
            observed={"jobs": observed_jobs},
            threshold=max_age_hours,
        )
    if issues:
        return _F(
            "job_sync_stale",
            "warn",
            "同步 Job：" + "；".join(issues),
            observed={"jobs": observed_jobs, "issues": issues},
            threshold=max_age_hours,
        )
    return _F(
        "job_sync_stale",
        "ok",
        f"托管同步 Job 正常（{len(observed_jobs)} 条）",
        observed={"jobs": observed_jobs},
        threshold=max_age_hours,
    )


def run_evidence_checks(
    store: MarketStore,
    *,
    limits: Mapping[str, float],
    sync_jobs: Sequence[Mapping[str, Any]] | None = None,
) -> list[Finding]:
    lookback = int(limits.get("receipt_lookback", EVIDENCE_THRESHOLDS["receipt_lookback"]))
    return [
        check_ohlc_reject_rate(
            store,
            max_ratio=float(
                limits.get("max_ohlc_reject_ratio", EVIDENCE_THRESHOLDS["max_ohlc_reject_ratio"])
            ),
            lookback=lookback,
        ),
        check_source_evidence_gap(
            store,
            max_ratio=float(
                limits.get(
                    "max_evidence_gap_ratio", EVIDENCE_THRESHOLDS["max_evidence_gap_ratio"]
                )
            ),
            lookback_days=int(
                limits.get(
                    "evidence_gap_lookback_days",
                    EVIDENCE_THRESHOLDS["evidence_gap_lookback_days"],
                )
            ),
            history_samples=int(
                limits.get(
                    "evidence_gap_history_samples",
                    EVIDENCE_THRESHOLDS["evidence_gap_history_samples"],
                )
            ),
        ),
        check_race_fallback_rate(
            store,
            max_ratio=float(
                limits.get("max_fallback_ratio", EVIDENCE_THRESHOLDS["max_fallback_ratio"])
            ),
            lookback=lookback,
        ),
        check_job_sync_stale(
            sync_jobs,
            max_age_hours=float(
                limits.get(
                    "max_sync_job_age_hours", EVIDENCE_THRESHOLDS["max_sync_job_age_hours"]
                )
            ),
        ),
    ]
