"""纸面量化 Job 共用：日期、舱配置、市场闸门。"""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from typing import Any, Iterator
from zoneinfo import ZoneInfo

from src.ops.application.paper_exec import PaperOrder
from src.ops.application.skill_watch.market_regime import MARKET_SNAPSHOT_TTL_SEC

logger = logging.getLogger(__name__)
_TZ = ZoneInfo("Asia/Shanghai")
DEFAULT_PAPER_LLM_TIMEOUT_SEC = 1800.0
MIN_PAPER_LLM_TIMEOUT_SEC = 120.0
MAX_PAPER_LLM_TIMEOUT_SEC = 1800.0

#: 纸面监测闸门短缓存：与快照 TTL 对齐；force_refresh 须穿透快照层。
_GATE_TTL_SEC = MARKET_SNAPSHOT_TTL_SEC
_GATE_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_LIVE_POOL_SETTING_PREFIX = "paper_live_pool:"


def _live_pool_key(slug: str) -> str:
    return f"{_LIVE_POOL_SETTING_PREFIX}{str(slug or '').strip()}"


def save_live_pool(
    store: Any,
    *,
    slug: str,
    trade_date: str,
    picks: list[dict[str, Any]],
) -> None:
    """兼容旧调用名；实际写入统一监察池。"""
    if store is None:
        return
    from src.ops.application.unified_monitor_pool import replace_candidate_feed

    replace_candidate_feed(
        store,
        slug=slug,
        trade_date=str(trade_date or "").strip(),
        feed=f"skill_watch:{str(slug or '').strip()}",
        candidates=picks,
    )


def load_live_pool(
    store: Any,
    *,
    slug: str,
    trade_date: str,
) -> list[dict[str, Any]] | None:
    """兼容旧读取名；只返回统一池的非持仓投影。"""
    if store is None or not hasattr(store, "get_setting"):
        return None
    raw = store.get_setting(f"unified_monitor_pool:{str(slug).strip()}", None)
    if isinstance(raw, dict) and str(raw.get("trade_date") or "") != str(trade_date):
        return None
    if raw is None:
        legacy = store.get_setting(_live_pool_key(slug), None)
        if not isinstance(legacy, dict) or str(legacy.get("trade_date") or "") != str(trade_date):
            return None
    from src.ops.application.unified_monitor_pool import get_unified_monitor_pool

    snapshot = get_unified_monitor_pool(store, slug=slug, trade_date=str(trade_date))
    if snapshot.get("trade_date") != str(trade_date):
        return None
    return [
        dict(item)
        for item in snapshot.get("items") or []
        if isinstance(item, dict) and item.get("bucket") != "position"
    ]


def clear_market_gate_cache() -> None:
    """测试或强制刷新时清空闸门短缓存。"""
    _GATE_CACHE.clear()


@contextmanager
def market_calendar_store(market: Any | None = None) -> Iterator[Any | None]:
    """共用一只 MarketStore 读交易日历，避免闸门与次日日各开一次。"""
    if market is not None:
        yield market
        return
    store = None
    close_store = False
    try:
        from src.market import MarketStore
        from src.shared.paths import market_db, market_hot_db

        for path in (market_hot_db(), market_db()):
            if path.exists():
                store = MarketStore(path)
                close_store = True
                break
        yield store
    finally:
        if close_store and store is not None:
            try:
                store.close()
            except Exception:  # noqa: BLE001
                pass


def _gate_cache_key(slug: str, day: str, *, stage_on: bool, gate_params: dict[str, Any]) -> str:
    """缓存键含启停与阈值指纹，避免关闸门仍命中旧进攻结果。"""
    bits = [f"{k}={gate_params[k]}" for k in sorted(gate_params)]
    return f"{slug}:{day}:gate={int(stage_on)}:{','.join(bits)}"


def _put_gate_cache(key: str, now: float, gate: dict[str, Any]) -> None:
    expired = [k for k, (ts, _) in _GATE_CACHE.items() if now - ts >= _GATE_TTL_SEC]
    for stale in expired:
        _GATE_CACHE.pop(stale, None)
    _GATE_CACHE[key] = (now, dict(gate))


def _weekend_next(day: date) -> str:
    """无日历时退路：只跳周末。"""
    candidate = day + timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate.isoformat()


def _next_trade_date(from_day: str | None = None, *, market: Any = None) -> str:
    """下一交易日：优先 market.db 交易日历（含长假）；失败再跳周末。"""
    if from_day:
        day = datetime.strptime(from_day[:10], "%Y-%m-%d").date()
    else:
        day = datetime.now(_TZ).date()
    day_s = day.isoformat()

    store = market
    close_store = False
    try:
        if store is None:
            from src.market import MarketStore
            from src.shared.paths import market_db, market_hot_db

            # 优先热库：全量 market.db 常被盘后同步占写锁，日历只读不应被拖死。
            for path in (market_hot_db(), market_db()):
                if path.exists():
                    store = MarketStore(path)
                    close_store = True
                    break
        if store is not None:
            nxt = store.shift_trading_days(day_s, 1)
            if nxt:
                return str(nxt)
            # from_day 可能是休市日：取严格大于该日的第一个交易日
            after = (day + timedelta(days=1)).isoformat()
            days = store.trading_days(start=after)
            if days:
                return str(days[0])
    except Exception as exc:  # noqa: BLE001 — 日历缺失不得阻断日终/预案
        logger.warning("next_trade_date calendar fallback: %s", exc)
    finally:
        if close_store and store is not None:
            try:
                store.close()
            except Exception:  # noqa: BLE001
                pass
    return _weekend_next(day)


def _today() -> str:
    return datetime.now(_TZ).strftime("%Y-%m-%d")


def resolve_trading_day_gate(
    day: str | None = None,
    *,
    market: Any = None,
) -> dict[str, Any]:
    """判定某日是否 A 股交易日（优先 market.db ``trading_calendar``）。

    - ``is_trading_day``：含周末与法定假日
    - ``buy_execution_allowed``：日历缺失时 fail-closed（仅 weekday 粗判不足以放行买入）
    """
    from src.market.application.session import _resolve_trading_day

    day_s = str(day or _today()).strip()[:10]
    try:
        now_date = datetime.strptime(day_s, "%Y-%m-%d").date()
    except ValueError:
        return {
            "trade_date": day_s,
            "is_trading_day": False,
            "last_trading_day": None,
            "calendar_source": "invalid_date",
            "buy_execution_allowed": False,
            "note": f"无效日期 {day_s}，禁止买入执行",
        }

    store = market
    close_store = False
    calendar_days: list[str] = []
    try:
        if store is None:
            from src.market import MarketStore
            from src.shared.paths import market_db, market_hot_db

            for path in (market_hot_db(), market_db()):
                if path.exists():
                    store = MarketStore(path)
                    close_store = True
                    break
        if store is not None:
            calendar_days = list(store.trading_days() or [])
    except Exception as exc:  # noqa: BLE001
        logger.warning("trading day calendar lookup failed: %s", exc)
    finally:
        if close_store and store is not None:
            try:
                store.close()
            except Exception:  # noqa: BLE001
                pass

    is_trading, last_trading_day = _resolve_trading_day(
        today=day_s,
        days=calendar_days,
        now_date=now_date,
    )

    if calendar_days:
        # 行情库日历只含已入库日；今天不在其中时由交易所公告休市日程判定（见 session）。
        calendar_source = "market_db" if day_s in calendar_days else "exchange_schedule"
        buy_allowed = is_trading
        if is_trading:
            label = "market.db 日历" if day_s in calendar_days else "交易所休市日程"
            note = f"{day_s} 为交易日（{label}）"
        else:
            note = f"{day_s} 非交易日（周末/法定假日），跳过开仓与监测落单"
    else:
        calendar_source = "weekday_fallback"
        buy_allowed = False
        if is_trading:
            note = (
                f"{day_s} 工作日但交易日历缺失：买入 fail-closed；"
                "监测可纠偏但不落买入成交"
            )
        else:
            note = f"{day_s} 非交易日（周末/法定假日），跳过开仓与监测落单"

    return {
        "trade_date": day_s,
        "is_trading_day": is_trading,
        "last_trading_day": last_trading_day,
        "calendar_source": calendar_source,
        "buy_execution_allowed": buy_allowed,
        "note": note,
    }


def _paper_quant_config(cabin_cfg: dict[str, Any]) -> dict[str, Any]:
    raw = cabin_cfg.get("paper_quant") if isinstance(cabin_cfg.get("paper_quant"), dict) else cabin_cfg
    return raw if isinstance(raw, dict) else {}


def paper_llm_timeout_sec(config: dict[str, Any]) -> float:
    """纸面决策模型允许慢推理；默认给足 30 分钟单次调用预算。"""
    try:
        value = float(config.get("llm_timeout_sec") or DEFAULT_PAPER_LLM_TIMEOUT_SEC)
    except (TypeError, ValueError):
        return DEFAULT_PAPER_LLM_TIMEOUT_SEC
    if value <= 0:
        return DEFAULT_PAPER_LLM_TIMEOUT_SEC
    return max(MIN_PAPER_LLM_TIMEOUT_SEC, min(value, MAX_PAPER_LLM_TIMEOUT_SEC))


def _resolve_market_gate(
    slug: str,
    config: dict[str, Any],
    *,
    store: Any = None,
    force_refresh: bool = False,
) -> dict[str, Any] | None:
    """龙王套件纸面舱监测取闸门；短 TTL 复用，避免与扫描器重复扣配额。

    阈值与启停复用该战法的监测调参（`watch_tuning:{slug}`），避免同一个闸门
    在扫描器和纸面舱里得出两套结论。市场数据经 market tape 公开入口，与扫描器同路由。
    """
    from src.ops.application.skill_watch.engine_registry import engine_spec

    spec = engine_spec(slug)
    if not ((spec and spec.uses_market_gate) or config.get("market_gate")):
        return None
    day = datetime.now(_TZ).date().isoformat()
    now = time.monotonic()
    cache_key: str | None = None
    try:
        from src.market import legacy_call_tool
        from src.ops.application.skill_watch.market_regime import (
            disabled_market_gate,
            scan_market_gate,
        )
        from src.ops.application.skill_watch.tuning import load_tuning, section, stage_enabled

        tuning = load_tuning(store, slug)
        stage_on = stage_enabled(tuning, "market_gate")
        gate_params = dict(section(tuning, "gate"))
        cache_key = _gate_cache_key(slug, day, stage_on=stage_on, gate_params=gate_params)
        if not force_refresh:
            cached = _GATE_CACHE.get(cache_key)
            if cached and (now - cached[0]) < _GATE_TTL_SEC:
                gate = dict(cached[1])
                gate["from_cache"] = True
                return gate
        if not stage_on:
            gate = {**disabled_market_gate(day), "from_cache": False}
            _put_gate_cache(cache_key, now, gate)
            return gate
        gate = scan_market_gate(
            legacy_call_tool,
            params=gate_params,
            force_refresh=force_refresh,
        )
        if isinstance(gate, dict):
            gate = {**gate, "from_cache": False}
            _put_gate_cache(cache_key, now, gate)
        return gate
    except Exception as exc:  # noqa: BLE001 — 闸门失败必须按空仓处理
        logger.warning("market gate failed for %s: %s", slug, exc)
        # 失败结果用独立键，避免污染 stage_on+空 params 的成功键空间
        fail_key = f"{slug}:{day}:gate_error"
        gate = {
            "state": "empty",
            "mode": "空",
            "label": "空仓窗口",
            "entry_allowed": False,
            "data_status": "degraded",
            "reason": f"市场闸门未取得：{type(exc).__name__}",
            "quality_warnings": ["market_gate_unavailable"],
            "from_cache": False,
        }
        _put_gate_cache(fail_key if cache_key is None else cache_key, now, gate)
        return gate


def _apply_market_gate(
    orders: list[PaperOrder],
    market_gate: dict[str, Any] | None,
    *,
    entry_exempt_codes: set[str] | frozenset[str] | None = None,
) -> tuple[list[PaperOrder], list[dict[str, Any]]]:
    if not market_gate or market_gate.get("entry_allowed"):
        return orders, []
    exempt = {str(code) for code in (entry_exempt_codes or set())}
    kept: list[PaperOrder] = []
    rejects: list[dict[str, Any]] = []
    for order in orders:
        if (
            str(order.action).lower() in {"open", "add", "buy_dip"}
            and str(order.code) not in exempt
        ):
            rejects.append(
                {
                    "code": order.code,
                    "action": order.action,
                    "reason": f"龙空龙闸门拦截：{market_gate.get('reason') or '当前不在进攻窗口'}",
                }
            )
        else:
            kept.append(order)
    return kept, rejects
