"""开盘啦区间强度软过滤：叠在盘中题材截面之上，不替换闸门 strength。

悟道 ``sector_analysis``（默认 strengthPeriod=5）给出四象限：
持续强势 / 低位启动 / 高位走弱 / 弱势。龙王选题材时用软加权偏好「持续」，
走弱只出预警信号，fail-open（调用失败则退回盘中强度排序），但必须留下可观测状态。

**两个题材池不是一个集合**（2026-08 实测）：闸门与盘中排序用的
``theme_intraday_capital`` 默认 ``universe=featured``，是 271 个精选大类板
（芯片 / 医药 / 并购重组…，带 strength）；``sector_analysis`` 的四象限出自 247 个
细分概念（HBM存储 / 光刻机概念…，无 strength），且服务端固定每象限只回 5 行。
两边按各自口径取前 N，名字交集长期为空——只靠名字打标，这段等于没生效。
所以细分主线改走**名额注入**：从四象限的持续强势 / 低位启动里挑 ``interval_slots``
个题材，用同池的 ``universe=concept`` 截面补上盘中涨幅与主力净额后并入主线池。
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from src.ops.application.skill_watch import payload as pl

QUADRANT_LABEL: dict[str, str] = {
    "continuingStrong": "持续强势",
    "emerging": "低位启动",
    "weakening": "高位走弱",
    "weak": "弱势",
}

#: 相对盘中 strength 的软倍率；不硬剔除，只改变入选优先级。
_QUADRANT_MULT: dict[str, float] = {
    "continuingStrong": 1.2,
    "emerging": 1.05,
    "weakening": 0.75,
    "weak": 0.55,
}

_TOP_LIST_KEYS = ("continuingStrong", "emerging", "weakening", "weak")

#: 允许被注入主线池的象限，越靠前越优先。
_INJECT_QUADRANTS = ("continuingStrong", "emerging")

#: 命中率低于此阈值记 partial/unmatched，避免静默失效。
_MATCH_PARTIAL = 0.34


def _norm_name(value: Any) -> str:
    return str(value or "").strip().casefold().replace(" ", "")


def parse_sector_quadrants(payload: Any) -> dict[str, dict[str, Any]]:
    """把 sector_analysis 压成「题材名 → 象限字段」；同名后写覆盖前写。"""
    structured = pl.structured(payload)
    if not isinstance(structured, Mapping):
        return {}
    top_lists = structured.get("topLists") or structured.get("top_lists") or {}
    if not isinstance(top_lists, Mapping):
        top_lists = structured if any(k in structured for k in _TOP_LIST_KEYS) else {}
    out: dict[str, dict[str, Any]] = {}
    for quadrant in _TOP_LIST_KEYS:
        rows = top_lists.get(quadrant) if isinstance(top_lists, Mapping) else None
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            name = pl.text_field(row, "name", "themeName", "theme_name", "板块名称")
            key_name = _norm_name(name)
            if not key_name:
                continue
            out[key_name] = {
                "interval_quadrant": quadrant,
                "interval_label": QUADRANT_LABEL[quadrant],
                # 榜上原名：细分池缺行时仍要能按 themeName 下钻
                "interval_name": name,
                "interval_recent_change": pl.number(row.get("recentChange")),
                "interval_period_change": pl.number(row.get("periodChange")),
                "interval_today_change": pl.number(row.get("todayChange")),
                "interval_position": pl.number(row.get("positionInRange")),
            }
    return out


def _theme_sort_key(row: Mapping[str, Any]) -> tuple[bool, float, bool, float, str]:
    """强度缺失排后；有值时乘象限软倍率，再比主力净额与名称。"""
    strength = pl.number(row.get("strength"))
    missing_strength = strength is None
    score = 0.0 if missing_strength else float(strength)
    if not missing_strength:
        quadrant = str(row.get("interval_quadrant") or "")
        score *= float(_QUADRANT_MULT.get(quadrant, 1.0))
    net = pl.number(row.get("main_net_amount"))
    return (
        missing_strength,
        -score,
        net is None,
        -(net or 0.0),
        str(row.get("theme_name") or ""),
    )


def index_concept_board(payload: Any) -> dict[str, dict[str, Any]]:
    """把 ``universe=concept`` 的盘中截面压成「题材名 → 盘中行」。

    这一池与四象限同源，代价是没有 strength，只有涨幅与主力净额。
    """
    rows: dict[str, dict[str, Any]] = {}
    if payload is None or pl.tool_failed(payload):
        return rows
    for mapping in pl.walk_maps(pl.structured(payload)):
        name = pl.text_field(mapping, "themeName", "theme_name", "板块名称", "name")
        key = _norm_name(name)
        if not key or key in rows:
            continue
        rows[key] = {
            "theme_name": name,
            "pct_chg": pl.field(mapping, "pct_chg"),
            "main_net_amount": pl.field(mapping, "main_net_amount"),
        }
    return rows


def _interval_candidates(
    quadrants: Mapping[str, Mapping[str, Any]],
    concept_rows: Mapping[str, Mapping[str, Any]],
    *,
    exclude: set[str],
    slots: int,
    pool_rows: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """挑区间强势题材当主线候选：先持续强势后低位启动，同象限比近窗涨幅。

    题材本就在盘中池里（只是排不进前几席）时复用那一行——它带 strength 和
    可下钻的 themeCode，比细分池的行更完整。
    """
    ranked: list[tuple[tuple[int, float, str], dict[str, Any]]] = []
    for key, fields in quadrants.items():
        quadrant = str(fields.get("interval_quadrant") or "")
        if quadrant not in _INJECT_QUADRANTS or key in exclude:
            continue
        kept = (pool_rows or {}).get(key)
        board = concept_rows.get(key)
        if kept is not None:
            row = {**dict(kept), "theme_source": "interval"}
        else:
            # 细分池按主力净额截断，强势小板可能不在其中；缺行只丢盘中数值，
            # 不影响按 themeName 下钻，所以照样占名额。
            name = str((board or {}).get("theme_name") or fields.get("interval_name") or "")
            if not name:
                continue
            row = {
                # concept:74 这类代码 theme_stocks 不认，留空强制走 themeName 下钻
                "theme_code": "",
                "theme_name": name,
                "strength": None,
                "main_net_amount": (board or {}).get("main_net_amount"),
                "pct_chg": (board or {}).get("pct_chg"),
                "boom_reason": "",
                "theme_source": "interval",
                **dict(fields),
            }
        recent = fields.get("interval_recent_change")
        sort_key = (
            _INJECT_QUADRANTS.index(quadrant),
            -float(recent or 0.0),
            str(row.get("theme_name") or ""),
        )
        ranked.append((sort_key, row))
    ranked.sort(key=lambda item: item[0])
    return [row for _key, row in ranked[:slots]]


def _degraded_signal(status: str, *, detail: str) -> dict[str, Any]:
    labels = {
        "unavailable": "区间强度不可用",
        "unmatched": "区间强度未命中",
        "partial": "区间强度部分命中",
        "concept_unavailable": "区间强度成分池不可用",
    }
    # reason 给人看：避免「四象限 / 软过滤」术语直接进企微
    human = {
        "unavailable": "主线区间强度服务暂不可用，已按盘中强度排序",
        "unmatched": "题材名称与区间强度榜对不上，已按盘中强度排序",
        "partial": "仅部分题材对上区间强度榜，其余仍按盘中强度",
        "concept_unavailable": "区间强势题材的盘中数据暂不可用，本轮只按盘中强度排序",
    }.get(status, detail)
    return {
        "type": "theme_interval_degraded",
        "code": "theme",
        "name": labels.get(status, "区间强度降级"),
        "role": status,
        "role_label": labels.get(status, status),
        "reason": human or detail,
        "detail": detail,
        "validation": "unverified",
    }


def apply_theme_interval(
    themes: Sequence[Mapping[str, Any]],
    sector_payload: Any,
    *,
    keep: int,
    concept_payload: Any = None,
    interval_slots: int = 0,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """软重排题材并截断；返回 (入选题材, 信号, 状态元数据)。

    ``sector_payload`` 为空/失败时保持原序截断（fail-open），并标记 status。
    ``interval_slots`` > 0 时从四象限强势侧另留名额给细分主线，需要
    ``concept_payload``（同池盘中截面）补齐涨幅与主力净额。
    """
    pool = [dict(row) for row in themes if isinstance(row, Mapping)]
    meta: dict[str, Any] = {
        "status": "ok",
        "pool_size": len(pool),
        "matched": 0,
        "match_rate": 0.0,
        "keep": max(0, keep),
        "quadrant_rows": 0,
        "slots": max(0, int(interval_slots)),
        "injected": 0,
        "concept_status": "skipped",
    }
    if keep < 1 or not pool:
        meta["status"] = "empty_pool"
        return [], [], meta

    if sector_payload is None or pl.tool_failed(sector_payload):
        meta["status"] = "unavailable"
        signal = _degraded_signal(
            "unavailable",
            detail="区间强度调用失败或载荷无效，已退回盘中 strength 排序",
        )
        return pool[:keep], [signal], meta

    quadrants = parse_sector_quadrants(sector_payload)
    meta["quadrant_rows"] = len(quadrants)
    if not quadrants:
        meta["status"] = "unavailable"
        signal = _degraded_signal(
            "unavailable",
            detail="区间强度四象限为空，已退回盘中 strength 排序",
        )
        return pool[:keep], [signal], meta

    matched = 0
    for row in pool:
        hit = quadrants.get(_norm_name(row.get("theme_name")))
        if hit is None:
            continue
        matched += 1
        row.update(hit)
    meta["matched"] = matched
    meta["match_rate"] = matched / len(pool) if pool else 0.0

    signals: list[dict[str, Any]] = []
    ranked = sorted(pool, key=_theme_sort_key)
    # 名额封顶：盘中最强题材至少留一席，区间强势不能整锅端走主线池
    slots = max(0, min(meta["slots"], keep - 1))
    injected: list[dict[str, Any]] = []
    if slots:
        concept_rows = index_concept_board(concept_payload)
        if not concept_rows:
            meta["concept_status"] = "unavailable"
            signals.append(
                _degraded_signal(
                    "concept_unavailable",
                    detail="区间强势题材缺少同池盘中截面，本轮未注入主线",
                )
            )
        else:
            meta["concept_status"] = "ok"
            injected = _interval_candidates(
                quadrants,
                concept_rows,
                exclude={_norm_name(row.get("theme_name")) for row in ranked[: keep - slots]},
                slots=slots,
                pool_rows={_norm_name(row.get("theme_name")): row for row in ranked},
            )
    meta["injected"] = len(injected)

    if injected:
        selected = [*ranked[: keep - len(injected)], *injected]
    else:
        selected = ranked[:keep]
    if slots:
        # 名额机制在跑：名字对不上属常态（两池本就不同源），只记状态不推送
        if not injected and meta["concept_status"] == "ok":
            meta["status"] = "no_candidate"
    elif matched == 0:
        meta["status"] = "unmatched"
        signals.append(
            _degraded_signal(
                "unmatched",
                detail=f"题材名与四象限未对齐（0/{len(pool)}），软过滤未生效",
            )
        )
    elif meta["match_rate"] < _MATCH_PARTIAL:
        meta["status"] = "partial"
        signals.append(
            _degraded_signal(
                "partial",
                detail=(
                    f"题材名仅部分对齐（{matched}/{len(pool)}），"
                    "未命中票按盘中 strength 中性倍率"
                ),
            )
        )

    for row in selected:
        quadrant = str(row.get("interval_quadrant") or "")
        if quadrant not in {"weakening", "weak"}:
            continue
        label = str(row.get("interval_label") or QUADRANT_LABEL.get(quadrant) or "走弱")
        name = str(row.get("theme_name") or row.get("theme_code") or "题材")
        recent = row.get("interval_recent_change")
        recent_s = f"，近窗 {float(recent):+.1f}%" if recent is not None else ""
        signals.append(
            {
                "type": "theme_interval_weak",
                "code": str(row.get("theme_code") or "theme"),
                "name": name,
                "theme": name,
                "role": quadrant,
                "role_label": label,
                "reason": f"区间强度{label}{recent_s}：主线持续性存疑，慎扩仓",
                "validation": "unverified",
            }
        )
    return selected, signals, meta


def fetch_sector_analysis(
    call_tool: Any,
    *,
    strength_period: int = 5,
    period: int = 60,
) -> Any:
    """拉一次开盘啦四象限；调用方负责 fail-open。"""
    return call_tool(
        "sector_analysis",
        {
            "source": "kpl",
            "strengthPeriod": strength_period,
            "period": period,
            "format": "json",
            "detailLevel": "standard",
        },
    )


def fetch_concept_board(call_tool: Any, *, limit: int = 100) -> Any:
    """拉四象限同池（``universe=concept``）的盘中截面；调用方负责 fail-open。

    走独立 lane，避免与闸门用的精选大类截面互相覆盖缓存。
    """
    return call_tool(
        "theme_concept_board",
        {
            "universe": "concept",
            "sortBy": "mainNetAmount",
            "limit": limit,
            "format": "json",
            "detailLevel": "standard",
        },
    )


__all__ = [
    "QUADRANT_LABEL",
    "apply_theme_interval",
    "fetch_concept_board",
    "fetch_sector_analysis",
    "index_concept_board",
    "parse_sector_quadrants",
]
