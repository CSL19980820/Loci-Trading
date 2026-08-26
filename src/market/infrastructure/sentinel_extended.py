"""数据体检扩展项：线路 / 会话 / 依赖 / schema / 库体积 / 可选连通探测。

与 ``sentinel`` 仓内 7 项互补；外网 probe 仅在 ``include_network=True`` 时执行，
避免选股门禁默认打第三方。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Mapping, Sequence

if TYPE_CHECKING:
    from src.market.infrastructure.sentinel import Finding
    from src.market.infrastructure.store import MarketStore
else:
    Finding = Any  # runtime filled via local import
    MarketStore = Any

from src.market.infrastructure.store_schema import SCHEMA_VERSION
from src.market.infrastructure.sentinel_evidence import (
    EVIDENCE_CATALOG,
    EVIDENCE_THRESHOLDS,
    evidence_remediation,
    run_evidence_checks,
)


def _F(
    check: str,
    severity: str,
    message: str,
    observed: Any = None,
    threshold: Any = None,
) -> Finding:
    from src.market.infrastructure.sentinel import Finding as FindingCls

    return FindingCls(check, severity, message, observed, threshold)

#: 选股主路径必需的 lane（关空则无法同步/列表/复权）。
REQUIRED_LANES: tuple[str, ...] = (
    "hist_daily",
    "spot_batch",
    "instruments",
    "adjust_factor",
)

EXTENDED_CATALOG: tuple[dict[str, str], ...] = (
    {"id": "factor_coverage", "label": "复权因子刷新覆盖", "group": "因子"},
    {"id": "lane_required_not_empty", "label": "必需线路未关空", "group": "线路"},
    {"id": "lane_hist_daily_alive", "label": "日 K 源连通", "group": "线路"},
    {"id": "lane_spot_alive", "label": "现价源连通", "group": "线路"},
    {"id": "lane_adjust_factor_alive", "label": "复权因子源连通", "group": "线路"},
    {"id": "lane_instruments_alive", "label": "证券列表源连通", "group": "线路"},
    {"id": "session_backfill", "label": "是否需要补数", "group": "时效"},
    {"id": "capabilities_runtime", "label": "运行时依赖", "group": "运行时"},
    {"id": "schema_version", "label": "库结构版本", "group": "存储"},
    {"id": "db_size_warn", "label": "行情库体积", "group": "存储"},
) + EVIDENCE_CATALOG

EXTENDED_THRESHOLDS: dict[str, float] = {
    # market.db 体积告警（字节）；默认 8 GiB
    "max_db_bytes": float(8 * 1024**3),
    **EVIDENCE_THRESHOLDS,
}

_NETWORK_CHECKS = frozenset(
    {
        "lane_hist_daily_alive",
        "lane_spot_alive",
        "lane_adjust_factor_alive",
        "lane_instruments_alive",
    }
)


def extended_remediation(check: str) -> dict[str, str] | None:
    mapping = {
        "factor_coverage": {
            "action": "sync_factors",
            "label": "刷新复权因子",
            "hint": "部分标的的复权因子长期未刷新，前复权面板会静默失真",
        },
        "lane_required_not_empty": {
            "action": "open_lanes",
            "label": "检查数据源",
            "hint": "必需线路被关空，到运维「数据源」重新启用 provider",
        },
        "lane_hist_daily_alive": {
            "action": "open_lanes",
            "label": "检查日 K 连通",
            "hint": "日 K 源全部探测失败，检查网络或换源",
        },
        "lane_spot_alive": {
            "action": "open_lanes",
            "label": "检查现价连通",
            "hint": "现价源探测失败，盘中实时会空",
        },
        "lane_adjust_factor_alive": {
            "action": "open_lanes",
            "label": "检查复权源连通",
            "hint": "复权因子源探测失败，无法刷新因子表",
        },
        "lane_instruments_alive": {
            "action": "open_lanes",
            "label": "检查证券列表连通",
            "hint": "证券列表源探测失败，无法刷新 instruments",
        },
        "session_backfill": {
            "action": "bootstrap",
            "label": "补齐行情",
            "hint": "库内尖端落后于应覆盖交易日，需增量或 bootstrap 补数",
        },
        "capabilities_runtime": {
            "action": "setup",
            "label": "安装依赖",
            "hint": "运行 setup.ps1 或 pip 安装缺失包",
        },
        "schema_version": {
            "action": "restart",
            "label": "重启应用",
            "hint": "启动时会自动迁移 market schema",
        },
        "db_size_warn": {
            "action": "cleanup",
            "label": "关注磁盘",
            "hint": "行情库体积偏大，注意磁盘空间",
        },
    }
    if check in mapping:
        return mapping[check]
    return evidence_remediation(check)


def _probe_import(module: str) -> bool:
    try:
        __import__(module)
        return True
    except ImportError:
        return False


def check_capabilities_runtime() -> Finding:
    """与 /api/capabilities 同源：关键依赖能否 import。"""
    missing: list[str] = []
    if not _probe_import("pandas"):
        missing.append("pandas")
    if not _probe_import("akshare"):
        missing.append("akshare")
    if missing:
        return _F(
            "capabilities_runtime",
            "block",
            f"运行时缺少依赖：{', '.join(missing)}（同步/选股可能不可用）",
            observed=missing,
        )
    soft: list[str] = []
    if not _probe_import("apscheduler"):
        soft.append("apscheduler")
    if not _probe_import("yaml"):
        soft.append("PyYAML")
    if soft:
        return _F(
            "capabilities_runtime",
            "warn",
            f"可选依赖缺失：{', '.join(soft)}（调度/技能可能不可用）",
            observed=soft,
        )
    return _F("capabilities_runtime", "ok", "运行时依赖齐全")


def check_factor_coverage(store: MarketStore, *, max_age_days: float) -> Finding:
    """有多少标的的复权因子长期没被刷新过。

    ``sentinel._check_factor_age`` 看的是 ``MAX(fetched_at)``：只要有**一只**票
    今天刷过因子，整项就报「0.1 天前更新」，哪怕其余几千只停在两年前。日 K
    增量同步只重写最近约 20 个交易日之后，这种偏科更容易发生。因子过旧不会
    报错，只会让前复权面板静默失真，所以这里按标的口径单独统计一次。
    """
    row = store.conn.execute(
        "SELECT COUNT(*) AS total,"
        " SUM(CASE WHEN newest < ? THEN 1 ELSE 0 END) AS stale FROM ("
        "  SELECT code, MAX(fetched_at) AS newest FROM adjust_factors GROUP BY code"
        ")",
        (
            (
                datetime.now(timezone.utc).replace(tzinfo=None)
                - timedelta(days=max(0.0, float(max_age_days)))
            ).isoformat(sep=" ", timespec="seconds"),
        ),
    ).fetchone()
    total = int(row["total"] or 0) if row else 0
    if not total:
        # 空因子表由 sentinel 的 factor_age 以 block 报出，这里不重复计分。
        return _F(
            "factor_coverage",
            "ok",
            "复权因子表为空，覆盖率由「复权因子时效」单独判定",
            observed={"codes": 0},
            threshold=max_age_days,
        )
    stale = int(row["stale"] or 0) if row else 0
    ratio = stale / total
    observed = {"codes": total, "stale_codes": stale, "ratio": round(ratio, 6)}
    if stale:
        return _F(
            "factor_coverage",
            "warn",
            f"{stale}/{total}（{ratio:.1%}）只标的的复权因子已超过 "
            f"{max_age_days:.0f} 天未刷新；这些标的若期间除权，前复权价会静默失真",
            observed=observed,
            threshold=max_age_days,
        )
    return _F(
        "factor_coverage",
        "ok",
        f"{total} 只标的的复权因子均在 {max_age_days:.0f} 天内刷新过",
        observed=observed,
        threshold=max_age_days,
    )


def check_lane_required_not_empty() -> Finding:
    from src.market.infrastructure.adapters.registry import enabled_adapter_ids

    empty: list[str] = []
    detail: dict[str, list[str]] = {}
    for lane in REQUIRED_LANES:
        ids = enabled_adapter_ids(lane)
        detail[lane] = ids
        if not ids:
            empty.append(lane)
    if empty:
        return _F(
            "lane_required_not_empty",
            "block",
            f"必需线路已关空：{', '.join(empty)}（无法同步/拉列表/复权）",
            observed=detail,
            threshold=list(REQUIRED_LANES),
        )
    return _F(
        "lane_required_not_empty",
        "ok",
        "必需线路均有启用源",
        observed={k: len(v) for k, v in detail.items()},
    )


def check_session_backfill(
    store: MarketStore,
    coverage: dict[str, Any],
    *,
    max_stale_days: int,
) -> Finding:
    from src.market.application.session import build_session_status

    status = build_session_status(
        coverage=coverage,
        trading_days=store.trading_days(),
    )
    lag = int(status.get("lag_trading_days") or 0)
    needs = bool(status.get("needs_backfill"))
    expected = status.get("expected_last_date")
    last = status.get("coverage_last_date") or coverage.get("last_date")
    observed = {
        "needs_backfill": needs,
        "lag_trading_days": lag,
        "expected_last_date": expected,
        "coverage_last_date": last,
    }
    if not needs:
        return _F(
            "session_backfill",
            "ok",
            f"无需补数（尖端 {last or '—'} · 应覆盖 {expected or '—'}）",
            observed=observed,
        )
    if lag > max_stale_days:
        return _F(
            "session_backfill",
            "block",
            f"需补数：落后 {lag} 个交易日（上限 {max_stale_days}），"
            f"尖端 {last or '—'} · 应覆盖 {expected or '—'}",
            observed=observed,
            threshold=max_stale_days,
        )
    return _F(
        "session_backfill",
        "warn",
        f"建议补数：落后 {lag} 个交易日，尖端 {last or '—'} · 应覆盖 {expected or '—'}",
        observed=observed,
        threshold=max_stale_days,
    )


def check_schema_version(store: MarketStore) -> Finding:
    row = store.conn.execute(
        "SELECT value FROM meta WHERE key = 'schema_version'"
    ).fetchone()
    found = str(row["value"]) if row and row["value"] is not None else ""
    expected = str(SCHEMA_VERSION)
    if not found:
        return _F(
            "schema_version",
            "warn",
            f"meta 未写 schema_version（代码期望 {expected}）",
            observed=None,
            threshold=expected,
        )
    if found != expected:
        return _F(
            "schema_version",
            "block",
            f"库结构版本 {found} ≠ 代码期望 {expected}，请重启应用完成迁移",
            observed=found,
            threshold=expected,
        )
    return _F(
        "schema_version",
        "ok",
        f"schema_version={found}",
        observed=found,
        threshold=expected,
    )


def check_db_size_warn(coverage: dict[str, Any], *, max_db_bytes: float) -> Finding:
    size = int(coverage.get("db_bytes") or 0)
    ceiling = int(max_db_bytes)
    gib = size / (1024**3)
    if size > ceiling:
        return _F(
            "db_size_warn",
            "warn",
            f"行情库约 {gib:.2f} GiB，超过告警阈值 {ceiling / (1024**3):.1f} GiB",
            observed=size,
            threshold=ceiling,
        )
    return _F(
        "db_size_warn",
        "ok",
        f"行情库约 {gib:.2f} GiB",
        observed=size,
        threshold=ceiling,
    )


def _check_lane_probe(lane: str, check_id: str, *, label: str) -> Finding:
    from src.market.infrastructure.adapters.router import probe_lane

    results = probe_lane(lane)
    if not results:
        return _F(
            check_id,
            "block" if lane == "hist_daily" else "warn",
            f"{label}：无可用 adapter 可探测（线路可能关空）",
            observed=[],
        )
    ok_ids = [r.adapter_id for r in results if r.ok]
    fail = [
        {"id": r.adapter_id, "error": (r.error or "")}
        for r in results
        if not r.ok
    ]
    observed = {"ok": ok_ids, "failed": fail, "total": len(results)}
    if ok_ids:
        return _F(
            check_id,
            "ok",
            f"{label}：{len(ok_ids)}/{len(results)} 源通（{', '.join(ok_ids)}）",
            observed=observed,
        )
    severity = "block" if lane == "hist_daily" else "warn"
    return _F(
        check_id,
        severity,
        f"{label}：全部 {len(results)} 源探测失败",
        observed=observed,
    )


def run_extended_checks(
    store: MarketStore,
    coverage: dict[str, Any],
    *,
    limits: dict[str, float],
    include_network: bool = False,
    sync_jobs: Sequence[Mapping[str, Any]] | None = None,
) -> list[Finding]:
    """跑扩展检查；网络类仅 ``include_network`` 时加入。"""
    findings: list[Finding] = [
        check_factor_coverage(
            store,
            max_age_days=float(limits.get("max_factor_age_days", 30.0)),
        ),
        check_lane_required_not_empty(),
        check_session_backfill(
            store,
            coverage,
            max_stale_days=int(limits.get("max_stale_days", 3)),
        ),
        check_capabilities_runtime(),
        check_schema_version(store),
        check_db_size_warn(
            coverage,
            max_db_bytes=float(limits.get("max_db_bytes", EXTENDED_THRESHOLDS["max_db_bytes"])),
        ),
    ]
    findings.extend(run_evidence_checks(store, limits=limits, sync_jobs=sync_jobs))
    if include_network:
        findings.extend(
            [
                _check_lane_probe("hist_daily", "lane_hist_daily_alive", label="日 K 源"),
                _check_lane_probe("spot_batch", "lane_spot_alive", label="现价源"),
                _check_lane_probe(
                    "adjust_factor", "lane_adjust_factor_alive", label="复权因子源"
                ),
                _check_lane_probe(
                    "instruments", "lane_instruments_alive", label="证券列表源"
                ),
            ]
        )
    return findings


def is_network_check(check_id: str) -> bool:
    return check_id in _NETWORK_CHECKS
