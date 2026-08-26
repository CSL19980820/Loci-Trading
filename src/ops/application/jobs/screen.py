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
    from src.strategy import get, screen

    slug = config.get("strategy")
    if not slug:
        raise JobError("screen 任务必须指定 strategy")

    # 选股要的是「今日日 K 可用」：覆盖已达标则跳过 spot，避免与盘后同步抢写。
    spot_rows = 0
    spot_requested = 0
    spot_refresh_meta: dict[str, Any] = {
        "enabled": bool(config.get("refresh_spot", True)),
        "status": "disabled",
        "message": "",
    }
    if bool(config.get("refresh_spot", True)):
        from src.market.application.screen_spot import (
            ScreenSpotError,
            ensure_today_quotes_for_screen,
        )

        try:
            with context.market() as store:
                instruments = store.list_instruments()
                spot_codes = [item["code"] for item in instruments]
                spot_types = {
                    item["code"]: item["instrument_type"] for item in instruments
                }
                spot_requested = len(spot_codes)
                ensured = ensure_today_quotes_for_screen(
                    store,
                    spot_codes,
                    instrument_types=spot_types or None,
                    force_refresh=bool(config.get("force_spot_refresh", False)),
                )
            spot_rows = int(ensured.get("written") or 0)
            spot_refresh_meta = {
                "enabled": True,
                "status": str(ensured.get("status") or ""),
                "requested": spot_requested,
                "written": spot_rows,
                "message": str(ensured.get("message") or ""),
                "coverage": ensured.get("coverage") or {},
            }
        except ScreenSpotError as exc:
            raise JobError(str(exc)) from exc
        except Exception as exc:
            raise JobError(
                f"选股前准备当日行情失败，已阻断选股：{exc}"
            ) from exc

    # 策略声明 requires_full_history 时跳过热库镜像，直接读全量库。
    # 否则尽量镜像后读热库；镜像失败或热库落后于全量时回退全量库选股
    # （与 screen_run 一致，不假装哨兵会修）。
    try:
        needs_full = bool(getattr(get(str(slug)), "requires_full_history", False))
    except Exception:
        needs_full = False

    use_hot = False
    if not needs_full:
        # refresh_spot=False 时也补一次窗口，保证热库与全量库一致。
        try:
            with context.market() as full, context.market_hot() as hot:
                from src.market import hot_unusable_reason, mirror_recent_to_hot

                mirror_recent_to_hot(full, hot)
                reason = hot_unusable_reason(full, hot)
                if reason:
                    logger.warning("%s，回退全量库选股", reason)
                else:
                    use_hot = True
        except Exception as exc:
            logger.warning("镜像热库失败，回退全量库选股：%s", exc)

    with (context.market_hot() if use_hot else context.market()) as store:
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

    try:
        strategy_name = str(get(result.strategy_slug).name)
    except Exception:
        strategy_name = str(result.strategy_slug)

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
        "strategy_name": strategy_name,
        "strategy_revision": getattr(result, "strategy_revision", ""),
        "trade_date": result.trade_date,
        "universe_size": result.universe_size,
        "entry_timing": result.entry_timing,
        "elapsed_seconds": round(result.elapsed_seconds, 3),
        "params": getattr(result, "params", {}),
        "effective_params": getattr(result, "effective_params", getattr(result, "params", {})),
        "pick_count": len(picks),
        "picks": picks,
        "watch_count": len(getattr(result, "watch_picks", None) or []),
        "watch_picks": list(getattr(result, "watch_picks", None) or []),
        "top_n_applied": top_n if top_n > 0 else None,
        "universe": result.universe,
        "universe_funnel": result.universe_funnel,
        "data_snapshot": result.data_snapshot,
        "spot_refresh": spot_refresh_meta,
    }
    if ai_pick_meta:
        payload.update(ai_pick_meta)

    if config.get("record_candidates"):
        from src.strategy.application.persist import persist_screen_candidates

        # tier → 裁决：core 才进「精选」胜率样本；reserve 挂观察、
        # dropped 记落选，否则低置信票会污染「精选候选」口径。
        _TIER_DECISION = {"core": "精选", "reserve": "观察", "dropped": "落选"}

        class _Bag:
            strategy_slug = result.strategy_slug
            strategy_revision = getattr(result, "strategy_revision", "")
            trade_date = result.trade_date
            entry_timing = result.entry_timing
            params = getattr(result, "params", {})
            effective_params = getattr(result, "effective_params", getattr(result, "params", {}))
            picks = [
                {**p, "_tier": _tier(i), "_decision": _TIER_DECISION[_tier(i)]}
                for i, p in enumerate(result.picks)
            ]
            watch_picks = [
                {**p, "_tier": "watch", "_decision": "观察"}
                for p in list(getattr(result, "watch_picks", None) or [])
            ]

        payload["recorded"] = persist_screen_candidates(
            _Bag(),
            palace_db=context.palace_db or DEFAULT_PALACE_DB,
            names=names,
            pool_id=str(config.get("pool_id") or "") or None,
            decision=str(config.get("decision") or "精选"),
            source="job:screen",
            top_n=0,
        )
    return payload


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
