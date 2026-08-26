"""市场龙头地图：主线题材 + 梯队角色 + 本地日 K 核验。

只回答「现在谁是龙头、谁在走弱」，不给买卖指令。角色由确定性规则算出，
AI 只负责解释证据。龙回头等下游战法直接消费本模块的 leaders，避免各自
从原始涨停池再猜一遍龙头。
"""
from __future__ import annotations

from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
from typing import Any

import pandas as pd

from src.formula import limit_ratio_for
from src.ops.application.skill_watch import payload as pl
from src.ops.application.skill_watch.kline_stats import trend_stats
from src.ops.application.skill_watch.leader_map_frames import (
    daily_frames as _daily_frames,
    member_rows as _member_rows,
)
from src.ops.application.skill_watch.market_regime import (
    disabled_market_gate,
    evaluate_market_gate,
    fetch_market_snapshot,
    today_trade_date,
)
from src.ops.application.skill_watch.defaults import DEFAULT_ROLE_PARAMS
from src.ops.application.skill_watch.roles import LEADER_ROLES, ROLE_LABEL

logger = logging.getLogger(__name__)


def rank_themes(themes: Any, *, limit: int = 3) -> list[dict[str, Any]]:
    """主线题材排行；按强度降序，强度缺失时退回主力净额。"""
    seen: dict[str, dict[str, Any]] = {}
    for mapping in pl.walk_maps(pl.structured(themes)):
        code = pl.text_field(mapping, "themeCode", "theme_code", "板块代码")
        name = pl.text_field(mapping, "themeName", "theme_name", "板块名称", "name")
        if not code and not name:
            continue
        key = code or name
        if key in seen:
            continue
        seen[key] = {
            "theme_code": code,
            "theme_name": name or code,
            "strength": pl.field(mapping, "theme_strength"),
            "main_net_amount": pl.field(mapping, "main_net_amount"),
            "pct_chg": pl.field(mapping, "pct_chg"),
            "boom_reason": pl.text_field(mapping, "boomReason", "boomTitle", "爆发原因"),
        }
    ordered = sorted(
        seen.values(),
        key=lambda row: (
            -(row["strength"] if row["strength"] is not None else -1e18),
            -(row["main_net_amount"] if row["main_net_amount"] is not None else -1e18),
            str(row["theme_name"]),
        ),
    )
    return ordered[:limit]


def classify_role(
    stats: Mapping[str, Any],
    *,
    ladder_level: float | None,
    is_theme_top: bool,
    gain_rank: int,
    params: Mapping[str, Any] | None = None,
) -> tuple[str, str]:
    """返回 (角色, 依据)。判定顺序固定：先看结构是否已破，再看是否最强。"""
    config = {**DEFAULT_ROLE_PARAMS, **dict(params or {})}
    close = float(stats.get("close") or 0)
    ma10 = float(stats.get("ma10") or 0)
    ma20 = float(stats.get("ma20") or 0)
    drawdown = float(stats.get("drawdown_pct") or 0)
    gain_20 = float(stats.get("gain_20_pct") or 0)
    vol_ratio = float(stats.get("vol_ratio") or 0)
    strong_days = int(stats.get("strong_days") or 0)
    level = float(ladder_level or 0)
    was_strong = strong_days >= 1 or gain_20 >= float(config["leader_min_gain_20"])

    if ma20 > 0 and close < ma20 * float(config["failed_ma20_ratio"]) and vol_ratio >= float(
        config["failed_vol_ratio"]
    ):
        return "failed", "放量跌破 MA20，主升结构破坏"
    if was_strong and (
        drawdown >= float(config["weakened_drawdown"]) or (ma10 > 0 and close < ma10)
    ):
        return "weakened", f"曾强但已回撤 {drawdown:.1f}% 或失守 MA10"
    if is_theme_top and level >= float(config["leader_min_level"]):
        return "leader", f"题材内连板最高（{level:.0f} 板）"
    if is_theme_top and level <= 0 and gain_20 >= float(config["leader_min_gain_20"]):
        return "leader", f"题材内 20 日涨幅最高（{gain_20:.1f}%）"
    if level >= float(config["secondary_min_level"]) or gain_rank <= 2:
        return "secondary", "连板或涨幅居前，属中军梯队"
    return "follower", "在主线票池内但未取得高度"


def apply_auction_stances(
    entries: list[dict[str, Any]],
    stances: list[dict[str, Any]],
) -> None:
    """竞价放弃/降级会**就地改写角色**，避免下游拿着过期的龙头继续找买点。"""
    by_code = {str(row.get("code")): row for row in stances if row.get("code")}
    for entry in entries:
        stance = by_code.get(str(entry.get("code")))
        if stance is None:
            continue
        entry["auction_stance"] = stance["stance"]
        entry["auction_gap_pct"] = stance.get("gap_pct")
        entry["auction_reason"] = stance.get("reason")
        if stance["stance"] == "abandoned":
            entry["role"] = "failed"
            entry["role_label"] = ROLE_LABEL["failed"]
            entry["role_basis"] = str(stance.get("reason") or "竞价放弃")
        elif stance["stance"] == "pending":
            # 竞价未就绪：标记阻塞，下游 paper_eligibility 统一 fail-closed
            entry["open_blocked"] = True
            entry["role_basis"] = str(stance.get("reason") or "竞价待定")
        elif stance["stance"] == "downgraded" and entry.get("role") == "leader":
            entry["role"] = "secondary"
            entry["role_label"] = ROLE_LABEL["secondary"]
            entry["role_basis"] = str(stance.get("reason") or "竞价降级")


def build_leader_map(
    *,
    gate: Mapping[str, Any],
    themes: list[dict[str, Any]],
    ladder_rows: Mapping[str, Mapping[str, Any]],
    members: Mapping[str, list[dict[str, Any]]],
    frames: Mapping[str, pd.DataFrame],
    params: Mapping[str, Any] | None = None,
    auction: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """纯函数：把题材、梯队与日 K 合成龙头地图。便于不打 MCP 直接测。"""
    entries: list[dict[str, Any]] = []
    for theme in themes:
        theme_key = theme.get("theme_code") or theme.get("theme_name")
        scored: list[dict[str, Any]] = []
        for member in members.get(str(theme_key), []):
            code = pl.clean_code(member.get("code"))
            frame = frames.get(code)
            if not code or frame is None or frame.empty:
                continue
            name = str(member.get("name") or code)
            stats = trend_stats(frame, code=code, name=name)
            if stats is None:
                continue
            ladder_row = ladder_rows.get(code) or {}
            live_pct = pl.field(member, "pct_chg")
            is_limit_up = bool(
                member.get("isLimitUp")
                or member.get("is_limit_up")
                or ladder_row
            )
            # 日 K 末根涨跌在盘中可能滞后；梯队/成分涨停标记优先，避免「涨停却显示 -x%」
            today_pct = float(stats["today_pct"])
            if live_pct is not None:
                today_pct = float(live_pct)
            elif is_limit_up and today_pct < 5:
                # 已在涨停梯队或成分标涨停，但 K 线末根仍像昨收 → 不沿用滞后涨跌
                today_pct = float(limit_ratio_for(code, name) * 100.0)
            scored.append(
                {
                    "code": code,
                    "name": name,
                    "theme_code": theme.get("theme_code"),
                    "theme_name": theme.get("theme_name"),
                    "ladder_level": pl.field(ladder_row, "ladder_level"),
                    "in_ladder": bool(ladder_row),
                    "is_limit_up": is_limit_up,
                    "bar_date": str(stats.get("bar_date") or ""),
                    **{k: v for k, v in stats.items() if k != "today_pct"},
                    "today_pct": round(today_pct, 2),
                }
            )
        if not scored:
            continue

        best_level = max(float(row["ladder_level"] or 0) for row in scored)
        best_gain = max(float(row["gain_20_pct"]) for row in scored)
        by_gain = sorted(scored, key=lambda row: -float(row["gain_20_pct"]))
        gain_rank = {row["code"]: index + 1 for index, row in enumerate(by_gain)}

        for row in scored:
            level = float(row["ladder_level"] or 0)
            is_top = (
                (best_level > 0 and level >= best_level)
                if best_level > 0
                else float(row["gain_20_pct"]) >= best_gain
            )
            role, basis = classify_role(
                row,
                ladder_level=row["ladder_level"],
                is_theme_top=is_top,
                gain_rank=gain_rank[row["code"]],
                params=params,
            )
            row["role"] = role
            row["role_label"] = ROLE_LABEL[role]
            row["role_basis"] = basis
        entries.extend(scored)

    if auction and auction.get("stances"):
        apply_auction_stances(entries, list(auction["stances"]))

    return finalize_leader_entries(
        entries,
        gate=gate,
        themes=themes,
        auction=auction,
    )


def finalize_leader_entries(
    entries: list[dict[str, Any]],
    *,
    gate: Mapping[str, Any],
    themes: list[dict[str, Any]],
    auction: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """竞价改写角色后重排并重建 leaders/signals（不重跑日 K）。"""
    order = {role: index for index, role in enumerate(LEADER_ROLES)}
    entries.sort(
        key=lambda row: (
            order.get(str(row["role"]), 99),
            -float(row["ladder_level"] or 0),
            -float(row["gain_20_pct"]),
            str(row["code"]),
        )
    )
    leaders = [row for row in entries if row["role"] == "leader"]
    weakened = [row for row in entries if row["role"] in {"weakened", "failed"}]

    signals: list[dict[str, Any]] = []
    if not gate.get("entry_allowed"):
        signals.append(
            {
                "type": "gate_empty" if gate.get("state") == "empty" else "watch_only",
                "code": "market",
                "reason": str(gate.get("reason") or "市场未进入进攻窗口"),
                "validation": "unverified",
            }
        )
    signals.extend(
        {
            "type": "leader_watch",
            "code": row["code"],
            "name": row.get("name") or "",
            "role": row.get("role") or "",
            "role_label": row.get("role_label") or "",
            "theme": row["theme_name"],
            "reason": f"{row['role_label']}：{row['role_basis']}",
            "validation": "unverified",
        }
        for row in leaders[:3]
    )
    signals.extend(
        {
            "type": "leader_weak",
            "code": row["code"],
            "name": row.get("name") or "",
            "role": row.get("role") or "",
            "role_label": row.get("role_label") or "",
            "theme": row["theme_name"],
            "reason": f"{row['role_label']}：{row['role_basis']}",
            "validation": "unverified",
        }
        for row in weakened[:3]
    )
    if not signals:
        signals.append(
            {
                "type": "watch_only",
                "code": "market",
                "reason": "主线票池暂无可判定角色的标的",
                "validation": "unverified",
            }
        )

    return {
        "trade_date": gate.get("trade_date") or "",
        "market_gate": dict(gate),
        "themes": themes,
        "leaders": leaders,
        "weakened": weakened,
        "entries": entries,
        "signals": signals,
        "auction": dict(auction or {"active": False, "reason": "未启用竞价确认", "stances": []}),
        "validation": "unverified",
        "validation_label": "未经过前向验证",
        "pool_size": len(entries),
    }


def scan_leader_map(
    call_tool: Any,
    *,
    trade_date: str | None = None,
    skip_when_empty: bool = False,
    tuning: Mapping[str, Any] | None = None,
    market_store: Any | None = None,
) -> dict[str, Any]:
    """扫一次市场龙头地图。K 线按题材批量取，避免逐股打满配额。

    ``skip_when_empty``：空仓窗口下直接收工。龙头地图本身在退潮日仍有价值
    （谁破位、谁走弱），所以默认继续扫；只有下游开仓型战法才提前止损配额。
    """
    from src.ops.application.skill_watch.auction_confirm import confirm_leaders
    from src.ops.application.skill_watch.tuning import section, stage_enabled

    day = trade_date or today_trade_date()
    scan_cfg = section(tuning, "scan")
    theme_limit = int(scan_cfg["theme_limit"])
    member_limit = int(scan_cfg["member_limit"])

    emotion, ladder, themes_payload = fetch_market_snapshot(call_tool, trade_date=day)
    if stage_enabled(tuning, "market_gate"):
        gate = evaluate_market_gate(
            emotion, ladder, themes_payload, trade_date=day, params=section(tuning, "gate")
        )
    else:
        gate = disabled_market_gate(day)
    if skip_when_empty and gate["state"] == "empty":
        return build_leader_map(gate=gate, themes=[], ladder_rows={}, members={}, frames={})

    # 先取更宽盘中池，再用区间强度软重排截到 theme_limit（失败则退回强度序）。
    pool_limit = max(theme_limit * 3, theme_limit)
    themes = rank_themes(themes_payload, limit=pool_limit)
    interval_signals: list[dict[str, Any]] = []
    interval_meta: dict[str, Any] = {"status": "disabled", "pool_size": len(themes)}
    if themes and stage_enabled(tuning, "theme_interval"):
        from src.ops.application.skill_watch.theme_interval import (
            apply_theme_interval,
            fetch_concept_board,
            fetch_sector_analysis,
        )

        interval_slots = int(scan_cfg["interval_theme_slots"])
        try:
            sector_payload = fetch_sector_analysis(call_tool)
        except Exception as exc:  # noqa: BLE001 — 区间强度 fail-open，但要留下日志
            logger.warning("theme_interval sector_analysis failed: %s", exc)
            sector_payload = None
        concept_payload = None
        if interval_slots > 0 and sector_payload is not None:
            try:
                concept_payload = fetch_concept_board(call_tool)
            except Exception as exc:  # noqa: BLE001 — 同上，缺了只是不注入细分主线
                logger.warning("theme_interval concept board failed: %s", exc)
        themes, interval_signals, interval_meta = apply_theme_interval(
            themes,
            sector_payload,
            keep=theme_limit,
            concept_payload=concept_payload,
            interval_slots=interval_slots,
        )
    else:
        themes = themes[:theme_limit]
    if not themes:
        return build_leader_map(gate=gate, themes=[], ladder_rows={}, members={}, frames={})

    ladder_rows = pl.rows_by_code(ladder, limit=80)
    members: dict[str, list[dict[str, Any]]] = {}
    frames: dict[str, pd.DataFrame] = {}
    owned_market_store = market_store
    close_market_store = False
    if owned_market_store is None:
        try:
            from src.market import open_market_hot

            owned_market_store = open_market_hot()
            close_market_store = True
        except Exception:
            owned_market_store = None
            logger.warning("leader_map open_market_hot failed; frames may be empty", exc_info=True)
    try:
        theme_jobs: list[tuple[str, dict[str, Any]]] = []
        for theme in themes:
            key = str(theme.get("theme_code") or theme.get("theme_name"))
            args: dict[str, Any] = {"limit": member_limit}
            if theme.get("theme_code"):
                args["themeCode"] = theme["theme_code"]
            else:
                args["themeName"] = theme.get("theme_name")
            theme_jobs.append((key, {**args, "format": "json", "detailLevel": "standard"}))

        def _fetch_theme(job: tuple[str, dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
            # 方案 B：工作线程不透传主线程 MarketStore，走 owned 独立连接。
            key, tool_args = job
            try:
                payload = call_tool(
                    "theme_stocks",
                    tool_args,
                    allow_injected_store=False,
                )
            except TypeError:
                payload = call_tool("theme_stocks", tool_args)
            rows = _member_rows(payload, limit=member_limit)
            return key, rows

        def _ingest(key: str, rows: list[dict[str, Any]]) -> None:
            members[key] = rows
            pending = [row["code"] for row in rows if row["code"] not in frames]
            if pending:
                frames.update(
                    _daily_frames(
                        pending[:member_limit],
                        trade_date=day,
                        market_store=owned_market_store,
                        member_limit=member_limit,
                    )
                )

        # 题材成分互不依赖：先并行压 MCP 延迟；失败 job 单独串行重试。
        # 并行全空且无异常（本地非线程安全 store）→ 整批串行兜底。
        fetched: list[tuple[str, list[dict[str, Any]]]] = []
        retry_jobs: list[tuple[str, dict[str, Any]]] = []
        workers = max(1, min(4, len(theme_jobs)))
        if len(theme_jobs) <= 1:
            for job in theme_jobs:
                try:
                    fetched.append(_fetch_theme(job))
                except Exception as exc:  # noqa: BLE001
                    logger.warning("theme_stocks fetch failed: %s", exc)
                    retry_jobs.append(job)
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                future_map = {pool.submit(_fetch_theme, job): job for job in theme_jobs}
                for fut in as_completed(future_map):
                    job = future_map[fut]
                    try:
                        fetched.append(fut.result())
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("theme_stocks fetch failed: %s", exc)
                        retry_jobs.append(job)
            if theme_jobs and not any(rows for _key, rows in fetched) and not retry_jobs:
                fetched = []
                retry_jobs = list(theme_jobs)
        for job in retry_jobs:
            try:
                fetched.append(_fetch_theme(job))
            except Exception as exc:  # noqa: BLE001
                logger.warning("theme_stocks serial retry failed: %s", exc)
        for key, rows in fetched:
            _ingest(key, rows)
    finally:
        if close_market_store and owned_market_store is not None:
            try:
                owned_market_store.close()
            except Exception as exc:  # noqa: BLE001
                logger.debug("market_store close failed: %s", exc)

    def _with_interval(result: dict[str, Any]) -> dict[str, Any]:
        out = {**result, "theme_interval": dict(interval_meta)}
        if not interval_signals:
            return out
        signals = list(result.get("signals") or [])
        # 区间走弱/降级插在龙头观察信号之前，便于监测正文先看到主线风险
        insert_at = 0
        for index, signal in enumerate(signals):
            if str(signal.get("type") or "") in {"leader_watch", "leader_weak"}:
                insert_at = index
                break
            insert_at = index + 1
        merged = signals[:insert_at] + list(interval_signals) + signals[insert_at:]
        return {
            **out,
            "signals": merged,
            "theme_interval_warnings": list(interval_signals),
        }

    draft = _with_interval(
        build_leader_map(
            gate=gate,
            themes=themes,
            ladder_rows=ladder_rows,
            members=members,
            frames=frames,
            params=section(tuning, "roles"),
        )
    )
    if not stage_enabled(tuning, "auction_confirm"):
        return draft

    # 龙头 + 中军都复核：secondary 也可进可买，竞价砸盘须同样 fail-closed
    auction_targets = [
        row
        for row in (draft.get("entries") or [])
        if isinstance(row, dict) and str(row.get("role") or "") in {"leader", "secondary"}
    ]
    auction = confirm_leaders(
        call_tool,
        auction_targets,
        trade_date=day,
        params=section(tuning, "auction"),
    )
    if not auction.get("active"):
        return {**draft, "auction": auction}

    # 竞价可能把龙头打成 failed：就地改写后重排，禁止二次拉日 K / classify
    entries = [dict(row) for row in (draft.get("entries") or []) if isinstance(row, dict)]
    apply_auction_stances(entries, list(auction.get("stances") or []))
    return _with_interval(
        finalize_leader_entries(
            entries,
            gate=gate,
            themes=themes,
            auction=auction,
        )
    )


__all__ = [
    "DEFAULT_ROLE_PARAMS",
    "LEADER_ROLES",
    "ROLE_LABEL",
    "apply_auction_stances",
    "build_leader_map",
    "classify_role",
    "finalize_leader_entries",
    "rank_themes",
    "scan_leader_map",
]
