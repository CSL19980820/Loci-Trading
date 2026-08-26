"""全局助手潜龙候选池工具。"""
from __future__ import annotations

from typing import Any

from src.ai.application.system_tool_result import ToolResult, ok as _ok
from src.ai.domain.assistant import AssistantError, validate_qianlong_decisions


def commit_qianlong_candidates(
    *,
    palace_db: str | None,
    rows: list[dict[str, Any]],
    day: str,
    pool_id: str,
    idempotency_key: str,
) -> list[str]:
    """把整池裁决作为同一账本事务提交。"""
    candidates: list[dict[str, Any]] = []
    for row in rows:
        evidence = dict(row.get("evidence") or {})
        evidence.update(
            {
                "source": "ai_assistant",
                "invalidation": str(row.get("invalidation") or ""),
                "idempotency_key": idempotency_key,
            }
        )
        candidates.append(
            {
                "code": row["code"], "name": str(row.get("name") or ""),
                "decision": row["decision"], "reason": row["reason"],
                "occurred_on": day, "pool_id": pool_id, "score": row.get("score"),
                "timing": str(row.get("timing") or ""), "rule_version": "潜龙",
                "evidence": evidence,
                "tier": {"精选": "selected", "观察": "watch", "落选": "reject"}[row["decision"]],
                "source": "ai_assistant",
            }
        )
    from src.ledger import PalaceStore

    with PalaceStore(palace_db) as store:
        return store.record_candidates(candidates)


def qianlong_pool(owner: Any, args: dict[str, Any]) -> ToolResult:
    from src.ledger import PalaceStore
    with PalaceStore(owner.palace_db) as store:
        rows = store.candidates_payload(args.get("occurred_on"))
    pool_id = str(args.get("pool_id") or "")
    if pool_id:
        rows = [row for row in rows if row.get("pool_id") == pool_id]
    if rows and args.get("occurred_on"):
        pools = {str(row.get("pool_id") or "") for row in rows}
        if len(pools) == 1:
            owner._candidate_pool_snapshots[(str(args["occurred_on"]), pools.pop())] = frozenset(
                str(row.get("code") or "") for row in rows
            )
    owner._artifact("candidate_verdict", "潜龙候选裁决", {"candidates": rows})
    return _ok(rows)

def qianlong_pool_evidence(owner: Any, args: dict[str, Any]) -> ToolResult:
    day = str(args["occurred_on"])
    pool_id = str(args.get("pool_id") or "")
    limit = int(args.get("limit", 10))
    from src.ledger import PalaceStore
    from src.market import MarketStore, normalize_code

    with PalaceStore(owner.palace_db) as palace:
        candidates = palace.candidates_payload(day)
    if pool_id:
        candidates = [row for row in candidates if row.get("pool_id") == pool_id]
    candidates = candidates[:limit]
    if candidates:
        effective_pool = pool_id or str(candidates[0].get("pool_id") or "")
        pools = {str(row.get("pool_id") or "") for row in candidates}
        if len(pools) == 1:
            owner._candidate_pool_evidence[(day, effective_pool)] = frozenset(
                str(row.get("code") or "") for row in candidates
            )
    evidence: list[dict[str, Any]] = []
    codes = [str(candidate.get("code") or "") for candidate in candidates]
    # 与原来 history(code) 内部一致：非法代码照旧抛 MarketError。
    keys = [normalize_code(code) for code in codes]
    with MarketStore(owner.market_db) as market:
        # 为什么批量：原来每只候选一次 history 而且拉全历史再 tail(60)，
        # 10 只候选 = 10 次全量扫描（改 limit 后更多）；history_many 一条
        # IN (...) + 窗口函数 limit=60，一次只取回每票最后 60 根。
        # 复权口径不变：qfq 以截止 day 的最后一根为基准，两边同一天。
        frames = market.history_many(keys, end=day, adjust="qfq", limit=60)
        for candidate, key in zip(candidates, keys):
            frame = frames.get(key)
            # 缺票（本地仓没这只）不会出现在返回 dict 里 = 原来的空表分支。
            rows = (
                frame.to_dict("records")
                if frame is not None and not frame.empty
                else []
            )
            closes = [float(row["close"]) for row in rows if row.get("close") is not None]
            volumes = [float(row["volume"]) for row in rows if row.get("volume") is not None]
            last = closes[-1] if closes else None
            prev = closes[-2] if len(closes) > 1 else None
            # 样本不足就给 None，别把 MA7 贴上 ma20 的标签——新股与长停票必踩。
            ma5 = round(sum(closes[-5:]) / 5, 4) if len(closes) >= 5 else None
            ma20 = round(sum(closes[-20:]) / 20, 4) if len(closes) >= 20 else None
            recent_volume = volumes[-1] if volumes else None
            prior_volumes = volumes[-6:-1] if len(volumes) >= 6 else []
            evidence.append(
                {
                    **candidate,
                    "close": last,
                    "pct_chg": round((last / prev - 1) * 100, 2)
                    if last is not None and prev not in (None, 0) else None,
                    "ma5": ma5,
                    "ma20": ma20,
                    "ma5_gap_pct": round((last / ma5 - 1) * 100, 2)
                    if last is not None and ma5 not in (None, 0) else None,
                    "ma20_gap_pct": round((last / ma20 - 1) * 100, 2)
                    if last is not None and ma20 not in (None, 0) else None,
                    "volume_ratio": round(recent_volume / (sum(prior_volumes) / len(prior_volumes)), 2)
                    if recent_volume is not None and prior_volumes and sum(prior_volumes) else None,
                }
            )
    owner._artifact("candidate_verdict", f"{day} 潜龙候选证据", {"candidates": evidence})
    return _ok({"occurred_on": day, "pool_id": pool_id, "candidates": evidence})

def qianlong_commit(owner: Any, args: dict[str, Any]) -> ToolResult:
    rows = validate_qianlong_decisions(args.get("decisions"))
    day, pool_id = str(args["occurred_on"]), str(args.get("pool_id") or "")
    from src.ledger import PalaceStore

    with PalaceStore(owner.palace_db) as store:
        existing = store.candidates_payload(day)
        pools = {str(item.get("pool_id") or "") for item in existing}
        if not pool_id:
            if len(pools) != 1:
                raise AssistantError("请明确要精炼的潜龙候选池")
            pool_id = pools.pop()
        existing = [item for item in existing if item.get("pool_id") == pool_id]
        expected = {str(item.get("code") or "") for item in existing}
        submitted = {str(item["code"]) for item in rows}
        if not expected:
            raise AssistantError("候选池为空；请先录入 6-10 只候选再做潜龙精选")
        if submitted != expected:
            missing = sorted(expected - submitted)
            extra = sorted(submitted - expected)
            raise AssistantError(f"提交必须覆盖候选池全部代码；缺少 {missing}，多出 {extra}")
        snapshot_key = (day, pool_id)
        if (
            owner._candidate_pool_snapshots.get(snapshot_key) != frozenset(expected)
            or owner._candidate_pool_evidence.get(snapshot_key) != frozenset(expected)
        ):
            raise AssistantError("提交前必须先读取该候选池及其本机日 K 证据")
    canonical = {"occurred_on": day, "pool_id": pool_id, "decisions": rows}
    key = owner._grant("qianlong.commit_pool", pool_id or "潜龙候选池", canonical)
    ids = commit_qianlong_candidates(
        palace_db=owner.palace_db, rows=rows, day=day, pool_id=pool_id, idempotency_key=key,
    )
    result = {"ids": ids, "pool_size": len(ids), "selected": sum(row["decision"] == "精选" for row in rows)}
    owner._artifact("candidate_verdict", "潜龙候选裁决", {"candidates": rows})
    return _ok(result)





def build_qianlong_tool_specs(owner: Any) -> dict[str, Any]:
    """延迟导入，避免与 SystemToolBus 的 ToolSpec 形成循环。"""
    from src.ai.application.system_toolbus import ToolSpec, _object

    read = False
    write = True
    return {
        "qianlong_candidate_pool": ToolSpec(
            "qianlong_candidate_pool",
            "读取潜龙候选池。",
            _object({"occurred_on": {"type": "string"}, "pool_id": {"type": "string"}}),
            read,
            lambda args: qianlong_pool(owner, args),
        ),
        "qianlong_pool_evidence": ToolSpec(
            "qianlong_pool_evidence",
            "读取潜龙整池的本机日 K 摘要，供从 6-10 只中精选 0-2 只。",
            _object(
                {
                    "occurred_on": {"type": "string"},
                    "pool_id": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 10},
                },
                ["occurred_on"],
            ),
            read,
            lambda args: qianlong_pool_evidence(owner, args),
        ),
        "qianlong_commit": ToolSpec(
            "qianlong_commit",
            "整池提交潜龙 6-10 只、0-2 精选及三档裁决。",
            _object(
                {
                    "occurred_on": {"type": "string"},
                    "pool_id": {"type": "string"},
                    "decisions": {
                        "type": "array",
                        "minItems": 6,
                        "maxItems": 10,
                        "items": {"type": "object"},
                    },
                },
                ["occurred_on", "decisions"],
            ),
            write,
            lambda args: qianlong_commit(owner, args),
        ),
    }
