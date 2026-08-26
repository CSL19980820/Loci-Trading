r"""东财行业板块 -> code→行业名 的映射(取数 / 磁盘缓存 / 失败冷却)。

从 ``sources.py`` 拆出来:那边是「证券列表与回退链」,行业名只是它路上的一步
锦上添花,却带着自己的一整套缓存、TTL、冷却与并发取数,混在一起两头都读不清。

三层保护,都是被真实故障逼出来的:

1. **磁盘缓存 + 7 天 TTL** —— 行业以月为单位变,不值得每次 ``sync_instruments``
   都在关键路径上重跑 ~90 次 akshare。
2. **失败兑现旧缓存** —— 一次网络抖动不能把全市场行业清空。
3. **失败冷却(30 分钟)** —— 上面两层都只在「成功取到过一次」之后才挡得住。
   全新机器 + 端点故障正好两头落空:每次刷新都要为一个已知打不通的端点白等
   19-22 秒(akshare 内部 requests 会重试到超时才放弃)。
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import threading
import time
from typing import Any

from src.shared.clock import utc_now

logger = logging.getLogger(__name__)


def _import_akshare() -> Any:
    """借用 sources 的 akshare 惰性导入,避免两处各写一份代理/重试配置。"""
    from src.market.infrastructure.sources import _import_akshare as _impl

    return _impl()

#: 东财行业图的本地磁盘缓存文件名（落在 ``paths.data_dir()``）。
_EM_INDUSTRY_CACHE_NAME = "em_industry_map.json"
#: 为什么要缓存：这张图要对 ~90 个行业板块各打一次 akshare，且挂在
#: ``fetch_instrument_list`` 的关键路径上，每次 sync_instruments 都重跑一遍。
#: 为什么是 7 天：行业归属（新股入板、板块调整）以「月」为单位变，7 天比它
#: 短一个量级，既跟得上归属变化，又让日常同步一次都不用重拉。
_EM_INDUSTRY_TTL_DAYS = 7.0
#: TTL 覆盖开关（单位：天）。<=0 表示每次都重拉（仍写盘、仍保留失败兜底）。
_EM_INDUSTRY_TTL_ENV = "LOCI_EM_INDUSTRY_TTL_DAYS"
#: 上限：全市场约 5500 只，12000 条留两倍余量。上游异常放大的载荷不写盘也
#: 不进内存，免得一次脏响应把缓存撑成几十 MB。
_EM_INDUSTRY_MAX_CODES = 12000
#: 缓存读写与取数共用一把锁：并发调用退化成单飞，不会两个线程各打 90 次。
_EM_INDUSTRY_LOCK = threading.Lock()


def _em_industry_ttl_seconds() -> float:
    """TTL（秒）。环境变量写坏了就当没写，绝不因此报错。"""
    raw = os.environ.get(_EM_INDUSTRY_TTL_ENV, "").strip()
    days = _EM_INDUSTRY_TTL_DAYS
    if raw:
        try:
            days = float(raw)
        except ValueError:
            logger.warning(
                "%s=%r 不是数字，按默认 %s 天",
                _EM_INDUSTRY_TTL_ENV,
                raw,
                _EM_INDUSTRY_TTL_DAYS,
            )
    return max(0.0, days) * 86400.0


#: 远端连挂之后的重试冷却(秒)。**没有这个冷却,证券列表刷新每次都要为一个
#: 已知打不通的端点白等 22 秒**:akshare 内部 requests 会重试到超时才放弃,
#: 而磁盘缓存只在「取到过一次」之后才挡得住——全新机器 + 端点故障正好两头落空。
_EM_INDUSTRY_FAIL_COOLDOWN_SEC = 1800.0
_EM_INDUSTRY_COOLDOWN_ENV = "LOCI_EM_INDUSTRY_RETRY_COOLDOWN_SEC"

#: 上次远端失败的单调时钟读数;0 = 没失败过。进程内即可,重启本来就该重试一次。
_EM_INDUSTRY_LAST_FAIL = 0.0


def _em_industry_cooldown_seconds() -> float:
    raw = os.environ.get(_EM_INDUSTRY_COOLDOWN_ENV, "").strip()
    if raw:
        try:
            return max(0.0, float(raw))
        except ValueError:
            logger.warning(
                "%s=%r 不是数字,按默认 %s 秒",
                _EM_INDUSTRY_COOLDOWN_ENV,
                raw,
                _EM_INDUSTRY_FAIL_COOLDOWN_SEC,
            )
    return _EM_INDUSTRY_FAIL_COOLDOWN_SEC


def _em_industry_in_cooldown() -> float:
    """还要冷却几秒;0 = 可以再试。"""
    if not _EM_INDUSTRY_LAST_FAIL:
        return 0.0
    left = _em_industry_cooldown_seconds() - (time.monotonic() - _EM_INDUSTRY_LAST_FAIL)
    return left if left > 0 else 0.0


def _note_em_industry_result(*, ok: bool) -> None:
    """记下远端成败,驱动失败冷却。成功立刻解除,不留惩罚期。"""
    global _EM_INDUSTRY_LAST_FAIL
    _EM_INDUSTRY_LAST_FAIL = 0.0 if ok else time.monotonic()


def _em_industry_cache_path() -> Path | None:
    """缓存文件路径；数据目录不可用时返回 None（退化成无缓存的原行为）。"""
    try:
        from src.shared.paths import data_dir

        return data_dir() / _EM_INDUSTRY_CACHE_NAME
    except Exception as exc:
        logger.debug("行业图缓存目录不可用，本次不缓存：%s", exc)
        return None


def _clip_em_industry(mapping: dict[str, str]) -> dict[str, str]:
    """超上限就按代码序截断——缓存可以不全，但不能无界。"""
    if len(mapping) <= _EM_INDUSTRY_MAX_CODES:
        return mapping
    logger.warning(
        "东财行业图 %s 条超过上限 %s，按代码序截断",
        len(mapping),
        _EM_INDUSTRY_MAX_CODES,
    )
    return dict(sorted(mapping.items())[:_EM_INDUSTRY_MAX_CODES])


def _read_em_industry_cache(path: Path | None) -> tuple[dict[str, str], float]:
    """读本地缓存，返回 (映射, 年龄秒)。读不出来一律空表 + inf，不抛错。"""
    if path is None or not path.is_file():
        return {}, float("inf")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        raw = payload.get("map") if isinstance(payload, dict) else None
        if not isinstance(raw, dict):
            return {}, float("inf")
        mapping: dict[str, str] = {}
        for code, name in raw.items():
            plain = str(code).strip().zfill(6)
            label = str(name).strip()
            if label and plain.isdigit() and len(plain) == 6:
                mapping[plain] = label
        if not mapping:
            return {}, float("inf")
        age = max(0.0, time.time() - path.stat().st_mtime)
        return _clip_em_industry(mapping), age
    except Exception as exc:
        logger.warning("行业图缓存读取失败（当作没有）：%s", exc)
        return {}, float("inf")


def _write_em_industry_cache(path: Path | None, mapping: dict[str, str]) -> None:
    """原子落盘。写不进去只记日志——缓存是省流手段，不是数据真相。"""
    if path is None or not mapping:
        return
    tmp = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "fetched_at": utc_now(),
            "count": len(mapping),
            "map": mapping,
        }
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(path)
    except Exception as exc:
        logger.warning("行业图缓存写入失败（不影响本次结果）：%s", exc)
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass


def fetch_em_industry_map() -> dict[str, str]:
    """东财行业板块成分 → code→行业名（如半导体、电力设备）。

    走 ``data_dir()/em_industry_map.json`` 的磁盘缓存，默认 7 天 TTL
    （``LOCI_EM_INDUSTRY_TTL_DAYS`` 可调；``LOCI_SKIP_EM_INDUSTRY`` 仍整体跳过）。
    过期才重拉；重拉失败或拿回空表时**用旧缓存兑现**，绝不让一次网络抖动
    把全市场行业清空。彻底没有可用缓存时才返回空字典（原行为）。
    """
    if os.environ.get("LOCI_SKIP_EM_INDUSTRY", "").strip() in {"1", "true", "yes"}:
        return {}

    path = _em_industry_cache_path()
    ttl = _em_industry_ttl_seconds()
    with _EM_INDUSTRY_LOCK:
        cached, age = _read_em_industry_cache(path)
        if cached and age < ttl:
            logger.info(
                "东财行业映射走本地缓存 %s 只（%.1f 天前）",
                len(cached),
                age / 86400.0,
            )
            return dict(cached)
        cooldown_left = _em_industry_in_cooldown()
        if cooldown_left:
            # 刚失败过就别再等一遍超时。有旧缓存就兑现旧的,没有就空表——
            # 行业名是锦上添花,不该让证券列表刷新为它卡住。
            logger.info(
                "东财行业板块处于失败冷却(还剩 %.0f 秒),本轮跳过远端",
                cooldown_left,
            )
        else:
            fresh = _fetch_em_industry_remote()
            if fresh:
                _note_em_industry_result(ok=True)
                _write_em_industry_cache(path, fresh)
                return fresh
            _note_em_industry_result(ok=False)
        if cached:
            logger.warning(
                "东财行业板块本轮取不到,沿用 %.1f 天前的本地缓存 %s 只",
                age / 86400.0,
                len(cached),
            )
            return dict(cached)
        return {}


def _fetch_em_industry_remote() -> dict[str, str]:
    """真·取数：板块列表 + 每个板块成分（~90 次 akshare）。失败返回空字典。"""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    try:
        ak = _import_akshare()
        boards = ak.stock_board_industry_name_em()
    except Exception as exc:
        logger.warning("取东财行业板块列表失败：%s", exc)
        return {}
    if boards is None or boards.empty:
        return {}
    name_col = "板块名称" if "板块名称" in boards.columns else boards.columns[1]
    names = [str(n).strip() for n in boards[name_col].tolist() if str(n).strip()]
    out: dict[str, str] = {}

    def one(name: str) -> dict[str, str]:
        try:
            cons = ak.stock_board_industry_cons_em(symbol=name)
        except Exception:
            return {}
        if cons is None or cons.empty:
            return {}
        code_col = "代码" if "代码" in cons.columns else None
        if not code_col:
            return {}
        local: dict[str, str] = {}
        for raw in cons[code_col].tolist():
            code = str(raw).strip().zfill(6)
            if code.isdigit() and len(code) == 6:
                local[code] = name
        return local

    workers = min(8, max(2, len(names) // 10 or 2))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(one, name) for name in names]
        for fut in as_completed(futures):
            try:
                out.update(fut.result())
            except Exception as exc:  # pragma: no cover
                logger.debug("行业成分合并失败：%s", exc)
    logger.info("东财行业映射 %s 只（已刷新）", len(out))
    return _clip_em_industry(out)
