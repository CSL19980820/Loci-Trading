"""龙头地图日 K / 成分 IO：从 leader_map 拆出，压行数。"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import logging
from typing import Any

import pandas as pd

from src.ops.application.skill_watch import payload as pl

logger = logging.getLogger(__name__)


def member_rows(payload: Any, *, limit: int) -> list[dict[str, Any]]:
    rows = pl.rows_by_code(payload, limit=limit, inherit_keys=())
    output: list[dict[str, Any]] = []
    for code, row in rows.items():
        member = dict(row)
        member["code"] = code
        member["name"] = pl.text_field(row, "name", "stockName", "名称") or code
        output.append(member)
    return output


def normalize_daily_frame(
    frame: Any,
    *,
    end_date: str,
    limit: int = 80,
) -> pd.DataFrame:
    """统一本地仓与 routed adapter 的日 K 形状，不读取 MCP 载荷。"""
    if frame is None:
        return pd.DataFrame()
    try:
        out = frame.copy()
    except AttributeError:
        return pd.DataFrame()
    if not isinstance(out, pd.DataFrame) or out.empty:
        return pd.DataFrame()
    out.columns = [str(column).strip().lower() for column in out.columns]
    if "trade_date" in out.columns and "date" not in out.columns:
        out = out.rename(columns={"trade_date": "date"})
    if "date" not in out.columns:
        return pd.DataFrame()
    out["date"] = out["date"].astype(str).str[:10]
    out = out[out["date"].str.len() == 10]
    if end_date:
        out = out[out["date"] <= end_date]
    if out.empty:
        return pd.DataFrame()
    out = out.sort_values("date").drop_duplicates(subset=["date"], keep="last")
    return out.tail(max(1, limit)).reset_index(drop=True)


def local_daily_frame(
    market_store: Any,
    code: str,
    *,
    trade_date: str,
    limit: int = 80,
) -> pd.DataFrame:
    """从注入的 MarketStore/热读库取不复权日 K；失败交给 routed 回退。"""
    if market_store is None:
        return pd.DataFrame()
    try:
        frame = market_store.history(
            code, end=trade_date, adjust="none", limit=limit
        )
    except TypeError:
        try:
            frame = market_store.history(
                code, end=trade_date, adjust="none"
            )
        except TypeError:
            try:
                # 最旧 fake：无关键字；仍要求调用方不要依赖默认 qfq
                frame = market_store.history(code, adjust="none")  # type: ignore[call-arg]
            except TypeError:
                try:
                    frame = market_store.history(code)
                    logger.warning(
                        "market_store.history(%s) lacks end/limit/adjust; using full series",
                        code,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("local daily frame failed for %s: %s", code, exc)
                    return pd.DataFrame()
            except Exception as exc:  # noqa: BLE001
                logger.warning("local daily frame failed for %s: %s", code, exc)
                return pd.DataFrame()
        except Exception as exc:  # noqa: BLE001
            logger.warning("local daily frame failed for %s: %s", code, exc)
            return pd.DataFrame()
    except Exception as exc:  # noqa: BLE001
        logger.warning("local daily frame failed for %s: %s", code, exc)
        return pd.DataFrame()
    return normalize_daily_frame(frame, end_date=trade_date, limit=limit)


def _code_variants(code: str) -> list[str]:
    """代码的可能写法。

    手写 SQL 没有 store 层的归一，就自己把 sh/sz/bj 前缀与 ``.SH`` 后缀脱掉，
    两种写法都放进 IN 列表，命中哪个都能回刷。
    """
    text = str(code).strip()
    variants = [text]
    bare = text.lower()
    for prefix in ("sh", "sz", "bj"):
        if bare.startswith(prefix):
            bare = bare[len(prefix):]
            break
    bare = bare.split(".")[0]
    if bare and bare != text:
        variants.append(bare)
    return variants


def _conn_daily_batch(
    market_store: Any,
    codes: list[str],
    *,
    trade_date: str,
    limit: int,
) -> dict[str, pd.DataFrame] | None:
    """没有 ``history_many`` 的注入 store：直接一条 ``IN (...)`` 手写 SQL 取回。

    为什么批量：龙头地图一次要 20+ 只成分，逐票回退就是 20+ 次 SQLite
    查询，盘中每轮扫描都要重来一遍；一条窗口函数 SQL 只跑一次。

    与 ``local_daily_frame`` 同口径：直读 ``quotes_daily`` 原值，不复权。
    返回 None = 这条路走不通（无 conn / 表不对），由调用方逐票回退。
    """
    conn = getattr(market_store, "conn", None)
    if conn is None or not codes:
        return None
    aliases: dict[str, str] = {}
    for code in codes:
        for variant in _code_variants(code):
            aliases.setdefault(variant, code)
    if not aliases:
        return None
    placeholders = ",".join("?" for _ in aliases)
    params: list[Any] = list(aliases)
    where = f"code IN ({placeholders})"
    if trade_date:
        where += " AND trade_date <= ?"
        params.append(trade_date)
    # 窗口函数按票倒序编号，一次取出每票最近 limit 根。
    sql = (
        "SELECT * FROM ("
        "SELECT q.*, ROW_NUMBER() OVER ("
        "PARTITION BY code ORDER BY trade_date DESC"
        f") AS rn FROM quotes_daily q WHERE {where}"
        ") AS ranked WHERE rn <= ? ORDER BY code, trade_date"
    )
    params.append(max(1, int(limit)))
    try:
        flat = pd.read_sql_query(sql, conn, params=params)
    except Exception as exc:  # noqa: BLE001
        logger.warning("leader map IN(...) daily batch failed: %s", exc)
        return None
    if flat.empty:
        return {}
    if "rn" in flat.columns:
        flat = flat.drop(columns=["rn"])
    out: dict[str, pd.DataFrame] = {}
    for code, group in flat.groupby("code", sort=False):
        requested = aliases.get(str(code))
        if requested is None:
            continue
        normalized = normalize_daily_frame(
            group.reset_index(drop=True), end_date=trade_date, limit=limit
        )
        if not normalized.empty:
            out[requested] = normalized
    return out


def _local_daily_batch(
    market_store: Any,
    codes: list[str],
    *,
    trade_date: str,
    limit: int = 80,
) -> dict[str, pd.DataFrame]:
    """优先 ``history_many``；无批量接口时走一条 ``IN (...)`` 手写 SQL。"""
    if market_store is None or not codes:
        return {}
    batcher = getattr(market_store, "history_many", None)
    if callable(batcher):
        try:
            raw = batcher(codes, end=trade_date, adjust="none", limit=limit)
        except TypeError:
            try:
                raw = batcher(codes, end=trade_date, adjust="none")
            except Exception as exc:  # noqa: BLE001
                logger.warning("history_many failed: %s", exc)
                raw = None
        except Exception as exc:  # noqa: BLE001
            logger.warning("history_many failed: %s", exc)
            raw = None
        if isinstance(raw, dict):
            out: dict[str, pd.DataFrame] = {}
            for code, frame in raw.items():
                normalized = normalize_daily_frame(
                    frame, end_date=trade_date, limit=limit
                )
                if not normalized.empty:
                    out[str(code)] = normalized
            return out
    # 没有 history_many 就自己拼一条批量 SQL，不再逐票打 N 次查询。
    batched = _conn_daily_batch(
        market_store, codes, trade_date=trade_date, limit=limit
    )
    if batched is not None:
        return batched
    # 连 conn 都没有的注入对象（精简实现/测试 fake）才逐票，保留原降级行为。
    frames: dict[str, pd.DataFrame] = {}
    for code in codes:
        local = local_daily_frame(
            market_store, code, trade_date=trade_date, limit=limit
        )
        if not local.empty:
            frames[code] = local
    return frames


def daily_frames(
    codes: list[str],
    *,
    trade_date: str,
    market_store: Any,
    member_limit: int = 20,
    limit: int = 80,
) -> dict[str, pd.DataFrame]:
    """本地批量日 K 优先；缺票限流走 market 包根公开路由。"""
    del member_limit  # 兼容旧调用方；截断由上游 pending[:member_limit] 负责
    unique = list(dict.fromkeys(str(code) for code in codes if str(code or "").strip()))
    frames = _local_daily_batch(
        market_store, unique, trade_date=trade_date, limit=limit
    )
    missing = [code for code in unique if code not in frames]
    if not missing:
        return frames
    # import 提到循环外：原来每轮循环都要走一次 import 机制。
    try:
        from src.market import enabled_adapter_ids, fetch_daily_routed
    except Exception as exc:  # noqa: BLE001
        logger.warning("routed daily frame unavailable: %s", exc)
        return frames
    try:
        adapter_ids = [
            provider_id
            for provider_id in enabled_adapter_ids("hist_daily")
            if provider_id != "wudao"
        ]
    except Exception as exc:  # noqa: BLE001
        logger.warning("routed adapter ids failed: %s", exc)
        return frames

    def _fetch(code: str) -> Any:
        try:
            routed, _source = fetch_daily_routed(code, adapter_ids=adapter_ids)
        except Exception as exc:  # noqa: BLE001
            logger.warning("routed daily frame failed for %s: %s", code, exc)
            return None
        return routed

    # 缺票 routed 限流：单次扫描最多补 8 只，避免全市场级穿透。
    # 这 8 次是网络 IO，串行等于 8 个 RTT 相加；4 并发把墙钟压到约 1/4。
    targets = missing[:8]
    with ThreadPoolExecutor(max_workers=4) as pool:
        fetched = list(pool.map(_fetch, targets))
    # 并发只用来拉数；归一化与回写仍按原顺序串行，结果与原来一致。
    for code, routed in zip(targets, fetched):
        remote = normalize_daily_frame(routed, end_date=trade_date, limit=limit)
        if not remote.empty:
            frames[code] = remote
    return frames


__all__ = [
    "daily_frames",
    "local_daily_frame",
    "member_rows",
    "normalize_daily_frame",
]
