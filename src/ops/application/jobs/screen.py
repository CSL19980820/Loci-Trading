"""screen 任务执行器：选股与候选池落库。"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from src.ops.application.jobs.context import (
    DEFAULT_PALACE_DB,
    JobContext,
    JobError,
    _llm_meta,
)

logger = logging.getLogger(__name__)


def execute_screen(config: dict[str, Any], context: JobContext) -> dict[str, Any]:
    """跑一次选股。结果整体落进执行记录，事后可追溯当天选了什么。

    ``record_candidates=True`` 时同时把入选标的写进账本的候选池——这是
    整个反馈闭环的接头处：

        选股 → 候选池 → T+N 后自动验证 → 知道这套战法准不准

    不写候选池的话，复盘引擎的候选池验证永远没有数据可验，"当初否决的票
    后来涨了多少"这个最有价值的问题就问不出来。
    """
    from src.strategy import screen

    slug = config.get("strategy")
    if not slug:
        raise JobError("screen 任务必须指定 strategy")

    with context.market() as store:
        result = screen(
            store,
            str(slug),
            trade_date=config.get("date"),
            params=config.get("params"),
            codes=config.get("codes"),
            universe=config.get("universe"),
        )
        names = {
            item["code"]: item["name"] for item in store.list_instruments(status="")
        } if config.get("record_candidates") else {}

    # top_n=0 或未设置表示不限制，> 0 则只保留前 N 名。
    # 排名依据 ScreenResult.picks 的原始顺序：各战法自己按 score/信号强度排好了。
    top_n = int(config.get("top_n") or 0)
    use_ai_pick = bool(config.get("use_ai_pick"))
    ai_pick_meta: dict[str, Any] = {}

    if use_ai_pick and top_n > 0 and result.picks:
        provider_name = str(config.get("provider") or "").strip()
        has_provider = bool(provider_name) or (
            context.ops_store is not None
            and context.ops_store.get_default_provider() is not None
        )
        if has_provider:
            ai_result = _ai_pick_codes(
                result.picks,
                top_n=top_n,
                strategy_slug=result.strategy_slug,
                provider_name=provider_name,
                model=str(config.get("model") or ""),
                thinking=str(config.get("thinking") or ""),
                context=context,
            )
            picks = ai_result["picks"]
            ai_pick_meta = {
                "ai_pick": True,
                "ai_provider": ai_result.get("provider", ""),
                "ai_reason": ai_result.get("reason", ""),
                "ai_fallback": ai_result.get("fallback", False),
            }
            if ai_result.get("llm_meta"):
                ai_pick_meta["llm_meta"] = ai_result["llm_meta"]
            if ai_result.get("reason"):
                config = {**config, "decision": "精选", "ai_reason": ai_result["reason"]}
        else:
            picks = result.picks[:top_n]
    elif top_n > 0:
        picks = result.picks[:top_n]
    else:
        picks = result.picks

    reserve_n = int(config.get("reserve_n") or (top_n * 3 if top_n > 0 else 0))

    def _tier(index: int) -> str:
        if top_n <= 0:
            return "core"
        if index < top_n:
            return "core"
        if reserve_n <= 0 or index < top_n + reserve_n:
            return "reserve"
        return "dropped"

    payload = {
        "strategy": result.strategy_slug,
        "trade_date": result.trade_date,
        "universe_size": result.universe_size,
        "entry_timing": result.entry_timing,
        "elapsed_seconds": round(result.elapsed_seconds, 3),
        "pick_count": len(picks),
        "picks": picks,
        "top_n_applied": top_n if top_n > 0 else None,
        "universe": result.universe,
        "universe_funnel": result.universe_funnel,
    }
    if ai_pick_meta:
        payload.update(ai_pick_meta)

    if config.get("record_candidates"):
        import copy
        # _record_candidates gets ALL picks with tier annotation
        tagged_result = copy.copy(result)
        tagged_picks = [
            {**p, "_tier": _tier(i)}
            for i, p in enumerate(result.picks)
        ]
        tagged_result.picks = tagged_picks
        payload["recorded"] = _record_candidates(tagged_result, config, context, names)
    return payload


def _record_candidates(
    result: Any, config: dict[str, Any], context: JobContext, names: dict[str, str]
) -> dict[str, Any]:
    """把选股结果写进候选池。

    pool_id 默认用 "策略slug@日期"：同一天跑多个战法各自成池，复盘时能
    按战法分开统计，而不是混成一锅。同池同标的重复写入会被账本的唯一
    索引覆盖成最新一次，所以重跑任务是幂等的。
    """
    from src.ledger import PalaceError, PalaceStore

    pool_id = str(config.get("pool_id") or f"{result.strategy_slug}@{result.trade_date}")
    decision = str(config.get("decision") or "精选")
    ai_reason = _strip_account_excuses(str(config.get("ai_reason") or ""))
    written, failed = 0, []

    with PalaceStore(context.palace_db or DEFAULT_PALACE_DB) as palace:
        for pick in result.picks:
            code = str(pick["code"])
            try:
                tier = str(pick.pop("_tier", "core"))
                reason = _factor_reason(result.strategy_slug, pick.get("factors") or {})
                if ai_reason and tier == "core":
                    reason = f"{reason}；AI：{ai_reason}"[:500]
                palace.record_candidate(
                    code=code,
                    name=names.get(code, ""),
                    decision=decision,
                    reason=reason,
                    occurred_on=result.trade_date,
                    pool_id=pool_id,
                    timing=result.entry_timing,
                    rule_version=result.strategy_slug,
                    evidence=pick.get("factors") or {},
                    tier=tier,
                    source="job:screen",
                )
                written += 1
            except PalaceError as exc:
                # 单只写失败不该让整批作废——记下来，其余照常入池。
                failed.append({"code": code, "error": str(exc)[:200]})

    return {"pool_id": pool_id, "written": written, "failed": failed}


def _factor_reason(slug: str, factors: dict[str, Any]) -> str:
    """把关键因子压成一句人能读的理由。

    候选记录只留"某战法选中"是没用的——三个月后回看，你需要知道当时是
    哪几个数字让它入选的。
    """
    parts = [
        f"{key}={value:.2f}"
        for key, value in factors.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    ]
    body = "，".join(parts[:6]) or "（无数值因子）"
    return f"{slug} 选中：{body}"[:500]


_ACCOUNT_EXCUSE_RE = re.compile(
    r"账户满仓|仓位已满|没钱|资金不足|没有仓位|无仓位|满仓",
    re.IGNORECASE,
)


def _strip_account_excuses(text: str) -> str:
    """去掉 AI 理由里以账户状态为由的措辞。"""
    if not text:
        return ""
    cleaned = _ACCOUNT_EXCUSE_RE.sub("", text)
    return re.sub(r"\s{2,}", " ", cleaned).strip(" ，；;.")


def _ai_pick_codes(
    candidates: list[dict[str, Any]],
    *,
    top_n: int,
    strategy_slug: str,
    provider_name: str,
    context: "JobContext",
    model: str = "",
    thinking: str = "",
) -> dict[str, Any]:
    """让 LLM 从战法候选里精选 top_n。失败时回退到原始排序前 N。"""
    fallback_picks = candidates[:top_n]

    if context.ops_store is None:
        return {"picks": fallback_picks, "fallback": True, "reason": ""}

    try:
        from src.ai import resolve_config
        from src.ai import ChatMessage, chat

        provider = resolve_config(
            context.ops_store,
            provider_name,
            model=model,
            master_key=context.master_key,
        )
    except Exception as exc:
        logger.warning("AI 精选跳过（供应商不可用）：%s", exc)
        return {"picks": fallback_picks, "fallback": True, "reason": ""}

    lines = []
    for idx, pick in enumerate(candidates, start=1):
        code = str(pick.get("code", ""))
        factors = pick.get("factors") or {}
        factor_text = "，".join(
            f"{k}={v:.2f}" if isinstance(v, (int, float)) and not isinstance(v, bool) else f"{k}={v}"
            for k, v in list(factors.items())[:6]
        )
        lines.append(f"{idx}. {code} {factor_text}".strip())

    system = (
        "你是 A 股量化选股助手。任务是从给定候选列表中按标的质量与战法匹配度"
        f"选出最优的 {top_n} 只。\n"
        "禁止用「账户满仓」「仓位已满」「没钱」等账户状态作为拒绝理由；"
        "只按标的质量与战法匹配度取舍。\n"
        "只返回 JSON：{\"codes\": [\"000001\", ...], \"reason\": \"简短中文理由\"}。"
        "codes 必须来自候选列表，数量不超过要求。"
    )
    user = (
        f"战法：{strategy_slug}\n"
        f"请从以下 {len(candidates)} 只候选中精选 {top_n} 只：\n"
        + "\n".join(lines)
    )

    try:
        response = chat(
            provider,
            [ChatMessage(role="system", content=system), ChatMessage(role="user", content=user)],
            max_tokens=800,
            temperature=0.2,
            thinking=thinking,
        )
        raw = (response.text or "").strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
        data = json.loads(raw)
        chosen = [str(c) for c in data.get("codes", []) if str(c)]
        reason = _strip_account_excuses(str(data.get("reason") or ""))
        valid = {str(p.get("code", "")) for p in candidates}
        chosen = [c for c in chosen if c in valid]
        ordered = [p for p in candidates if str(p.get("code", "")) in chosen][:top_n]
        if not ordered:
            raise ValueError("AI 返回的代码不在候选列表中")
        return {
            "picks": ordered,
            "reason": reason,
            "provider": provider.name,
            "model": provider.model,
            "fallback": False,
            "llm_meta": _llm_meta(provider, thinking),
        }
    except Exception as exc:
        logger.warning("AI 精选失败，回退前 %d 名：%s", top_n, exc)
        return {
            "picks": fallback_picks,
            "fallback": True,
            "reason": "",
            "provider": provider.name,
            "llm_meta": _llm_meta(provider, thinking),
        }
