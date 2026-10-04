"""租户私有的盘后完整样本快照；失败不覆盖上一份完整产物。"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

from src.shared.paths import skill_runs_dir
from src.strategy.domain.base import StrategyError


POOL_FORMAT = 1
MAX_POOL_BYTES = 20 * 1024 * 1024
SELECTION_PARAMS = ("recent_days", "max_recent_gain_pct", "volume_ratio", "position_lookback")


def selection_key(engine, params: dict, universe: dict) -> str:
    """评分和名额不影响盘后样本；形态参数或范围变化必须重新准备。"""
    value = {
        "revision": engine.strategy_revision,
        "params": {key: params[key] for key in SELECTION_PARAMS},
        "universe": universe,
    }
    return _digest(value)


def _bytes(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _digest(value: dict) -> str:
    return hashlib.sha256(_bytes(value)).hexdigest()


def pool_path(slug: str, day: str) -> Path:
    from datetime import date

    if not slug or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789-" for char in slug):
        raise StrategyError("样本策略标识非法")
    if date.fromisoformat(day).isoformat() != day:
        raise StrategyError("样本交易日格式非法")
    # 路径在调用时解析，不缓存 ContextVar 派生的租户目录。
    return skill_runs_dir().parent / "screen_prepared" / slug / f"{day}.json"


def save_prepared_pool(payload: dict) -> dict:
    content = {**payload, "format": POOL_FORMAT}
    envelope = {"sha256": _digest(content), "payload": content}
    raw = _bytes(envelope)
    if len(raw) > MAX_POOL_BYTES:
        raise StrategyError("完整样本快照超过大小限制，未覆盖原有样本")
    target = pool_path(content["strategy_slug"], content["target_trade_date"])
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
    try:
        with staging.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(staging, target)
    finally:
        staging.unlink(missing_ok=True)
    return {"sha256": envelope["sha256"], "bytes": len(raw), "path": str(target)}


def load_prepared_pool(engine, day: str, *, expected_as_of: str, params: dict,
                       universe: dict) -> tuple[dict, str]:
    target = pool_path(engine.slug, day)
    try:
        with target.open("rb") as handle:
            raw = handle.read(MAX_POOL_BYTES + 1)
        if len(raw) > MAX_POOL_BYTES:
            raise ValueError("快照过大")
        envelope = json.loads(raw)
        payload = envelope["payload"]
        digest = _digest(payload)
        if digest != envelope["sha256"]:
            raise ValueError("内容校验失败")
        if (payload.get("format") != POOL_FORMAT or payload.get("strategy_slug") != engine.slug
                or payload.get("target_trade_date") != day
                or payload.get("as_of") != expected_as_of
                or payload.get("selection_key") != selection_key(engine, params, universe)
                or payload.get("status") not in {"prepared", "prepared_empty", "prepared_with_warnings"}):
            raise ValueError("日期、形态参数或策略版本不匹配")
        if not isinstance(payload.get("candidates"), list):
            raise ValueError("样本列表缺失")
        codes = [item["code"] for item in payload["candidates"]]
        if len(codes) != len(set(codes)):
            raise ValueError("样本代码重复")
        if payload.get("candidate_count") != len(codes):
            raise ValueError("样本数量不一致")
    except FileNotFoundError as exc:
        raise StrategyError(f"{day} 的盘后样本尚未准备，请先运行样本准备任务") from exc
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise StrategyError(f"盘后样本不可用（{exc}），请重新准备；不会改用旧日样本") from exc
    return payload, digest
