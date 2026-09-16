"""研究回测输入的可校验冻结格式。

该模块只负责把已准备好的 pandas 面板编码为 JSON artifact，并从 artifact
恢复执行所需的最小 context；恢复过程不访问 MarketStore。
"""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import io
import json
from types import SimpleNamespace
from typing import Any, Mapping

import numpy as np
import pandas as pd

from src.backtest import BacktestConfig
from src.strategy import get


#: v2 起：紧凑分隔符（去掉 indent 空白），且 execution 与 signals 面板同源时写 null。
#: 真实行情价格是两位小数，值本身很短，indent 的空白反而占了近一半体积。
CONTRACT_VERSION = "research-frozen-input-v2"


def _scalar(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "item"):
        try:
            return _scalar(value.item())
        except (TypeError, ValueError):
            pass
    return str(value)


def _panel_values(panel: pd.DataFrame) -> list[list[Any]]:
    """面板 → 严格 JSON 的二维列表；NaN 收敛成 None。

    行情面板几乎总是 float64。这条快路径用 ndarray.tolist() 一次性转成 Python
    浮点（C 层），再只对 NaN 那些格回填 None——原来的写法要先 astype(object)
    复制整帧、再 where 复制一次，最后对**每一格**调一次 `_scalar`。
    全市场单面板 185 万格时，两者差着数量级。

    非浮点面板（字符串/混合 dtype）仍走逐格兜底，语义与原实现一致。
    """
    array = panel.to_numpy()
    if array.dtype.kind != "f":
        return [
            [_scalar(value) for value in row]
            for row in panel.astype(object).where(pd.notna(panel), None).values.tolist()
        ]
    rows = array.tolist()
    for i, j in np.argwhere(np.isnan(array)).tolist():
        rows[i][j] = None
    return rows


def _panel_payload(panel: pd.DataFrame) -> dict[str, Any]:
    return {
        "index": [str(value) for value in panel.index],
        "columns": [str(value) for value in panel.columns],
        "values": _panel_values(panel),
    }


def _series_payload(series: pd.Series | None) -> dict[str, Any] | None:
    if series is None:
        return None
    return {
        "index": [str(value) for value in series.index],
        "values": [_scalar(value) if pd.notna(value) else None for value in series.tolist()],
    }


def build_frozen_payload(
    context: Mapping[str, Any], *, split: Any = None, research_settings: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """生成稳定 JSON 载荷；不携带 engine/store 等不可序列化对象。"""
    resolved = context["resolved"]
    # execution_panels 常常就是 panels 本身（策略未声明 execution_adjust 时）。
    # 按对象身份缓存，避免把同一批面板原样编码两遍——那是整个冻结流程里最贵的一步。
    encoded: dict[int, dict[str, Any]] = {}

    def encode(panel: pd.DataFrame) -> dict[str, Any]:
        key = id(panel)
        if key not in encoded:
            encoded[key] = _panel_payload(panel)
        return encoded[key]

    panels = {
        name: encode(panel)
        for name, panel in context.get("panels", {}).items()
        if isinstance(panel, pd.DataFrame)
    }
    execution = {
        name: encode(panel)
        for name, panel in context.get("execution_panels", context["panels"]).items()
        if isinstance(panel, pd.DataFrame)
    }
    # 策略未声明 execution_adjust 时执行面板就是信号面板。写 null 而不是把同一批
    # 数字再抄一遍——JSON 没有引用机制，重复的是实打实的几十 MB 文本。
    # 解码侧对空值一律回落到 panels（见 context_from_payload）。
    same_as_panels = execution.keys() == panels.keys() and all(
        execution[name] is panels[name] for name in panels
    )
    benchmark = _series_payload(context.get("benchmark_close"))
    return {
        "contract_version": CONTRACT_VERSION,
        "strategy": str(context["engine"].slug),
        "strategy_revision": str(getattr(context["engine"], "strategy_revision", "")),
        "entry_timing": str(context["engine"].entry_timing),
        "resolved_params": dict(context.get("resolved_params") or {}),
        "config": (
            asdict(context.get("config", BacktestConfig()))
            if hasattr(context.get("config", BacktestConfig()), "__dataclass_fields__")
            else dict(context.get("config") or {})
        ),
        "start": context.get("start"),
        "end": context.get("end"),
        "load_start": context.get("load_start"),
        "load_end": context.get("load_end"),
        "resolved": {
            "codes": [str(code) for code in resolved.codes],
            "spec": dict(resolved.spec),
            "meta": {str(code): dict(value) for code, value in resolved.meta.items()},
            "funnel": resolved.funnel.to_dict(),
        },
        "signals": _panel_payload(context["signals"]),
        "panels": panels,
        "execution_panels": None if same_as_panels else execution,
        "entry_price_panel": _panel_payload(context["entry_price_panel"])
        if isinstance(context.get("entry_price_panel"), pd.DataFrame)
        else None,
        "benchmark_close": benchmark,
        "fields": [str(value) for value in context.get("fields", tuple(panels))],
        "effective_adjust": str(context.get("effective_adjust") or "qfq"),
        "execution_adjust": str(
            context.get("execution_adjust") or context.get("effective_adjust") or "qfq"
        ),
        "universe_control_mask": _panel_payload(context["universe_control_mask"])
        if isinstance(context.get("universe_control_mask"), pd.DataFrame)
        else None,
        "data_snapshot": dict(context.get("data_snapshot") or {}),
        "split": asdict(split) if split is not None else None,
        "research_settings": dict(research_settings or {}),
    }


def payload_bytes(payload: Mapping[str, Any]) -> bytes:
    """冻结产物的**唯一**权威字节形式。

    落盘时必须把这里的返回值直接交给 `write_artifact`，不要把 dict 传进去让它
    再 dump 一遍——那样两份 hash 只是"恰好相等"，而且要为几百 MB 的载荷多付一次
    完整序列化。

    `sort_keys` 保证同一份输入永远得到同一个 hash；紧凑分隔符则是 v2 的体积优化。
    """
    # 直接分块编码UTF-8，避免带中文/非BMP字符的整份Unicode文本及换行复制。
    # json.dump与旧dumps使用相同编码契约，现存artifact的字节/hash保持不变。
    with io.BytesIO() as buffer:
        with io.TextIOWrapper(buffer, encoding="utf-8", newline="\n") as stream:
            json.dump(
                payload, stream, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"), allow_nan=False,
            )
            stream.write("\n")
            stream.flush()
            return buffer.getvalue()


def payload_sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(payload_bytes(payload)).hexdigest()


def _decode_panel(raw: Mapping[str, Any], *, boolean: bool = False) -> pd.DataFrame:
    frame = pd.DataFrame(raw.get("values") or [], index=raw.get("index") or [], columns=raw.get("columns") or [])
    if boolean:
        return frame.fillna(False).astype(bool)
    return frame.apply(pd.to_numeric, errors="coerce")


def _decode_series(raw: Mapping[str, Any] | None) -> pd.Series | None:
    if not raw:
        return None
    return pd.Series(raw.get("values") or [], index=raw.get("index") or [], dtype="float64")


def context_from_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """恢复执行 context；输入缺失/版本错误时明确拒绝。"""
    if payload.get("contract_version") != CONTRACT_VERSION:
        raise ValueError("冻结输入 artifact 版本不受支持")
    strategy = str(payload.get("strategy") or "")
    if not strategy:
        raise ValueError("冻结输入缺少 strategy")
    if strategy == "research-pth252":
        # PTH252 is intentionally not registered as an active strategy.  Its
        # frozen params fully describe the private research engine, so replay
        # can remain deterministic without exposing it in the production
        # catalogue.
        from src.research.application.factor_experiment import (
            pth252_engine_from_frozen_params,
        )

        engine = pth252_engine_from_frozen_params(
            dict(payload.get("resolved_params") or {})
        )
    elif strategy == "impulse-pullback-tail-v1":
        # This strategy is intentionally retired from the active catalogue, but
        # historical research artifacts must remain replayable.  Reconstruct
        # the versioned engine here without making it selectable for new jobs.
        from src.strategy.application.impulse_pullback import ImpulsePullbackTailV1

        engine = ImpulsePullbackTailV1()
    else:
        engine = get(strategy)
    if str(payload.get("strategy_revision") or "") != str(getattr(engine, "strategy_revision", "")):
        raise ValueError("冻结输入的 strategy revision 已漂移，拒绝重放")
    if str(payload.get("entry_timing") or "") != str(engine.entry_timing):
        raise ValueError("冻结输入的 entry_timing 已漂移，拒绝重放")
    resolved_raw = payload.get("resolved")
    if not isinstance(resolved_raw, Mapping):
        raise ValueError("冻结输入缺少股票池快照")
    resolved = SimpleNamespace(
        codes=list(resolved_raw.get("codes") or []),
        spec=dict(resolved_raw.get("spec") or {}),
        meta=dict(resolved_raw.get("meta") or {}),
        funnel=SimpleNamespace(to_dict=lambda: dict(resolved_raw.get("funnel") or {})),
    )
    config = BacktestConfig(**dict(payload.get("config") or {}))
    panels = {name: _decode_panel(raw) for name, raw in dict(payload.get("panels") or {}).items()}
    # execution_panels 为 null/空 = 与 panels 同源（v2 起不再重复写一份）。
    execution = {name: _decode_panel(raw) for name, raw in dict(payload.get("execution_panels") or {}).items()}
    signals = _decode_panel(payload["signals"], boolean=True)
    entry_raw = payload.get("entry_price_panel")
    mask_raw = payload.get("universe_control_mask")
    return {
        "engine": engine,
        "config": config,
        "resolved_params": dict(payload.get("resolved_params") or {}),
        "resolved": resolved,
        "panels": panels,
        "execution_panels": execution or panels,
        "signals": signals,
        "entry_price_panel": _decode_panel(entry_raw) if isinstance(entry_raw, Mapping) else None,
        "benchmark_close": _decode_series(payload.get("benchmark_close")),
        "universe_control_mask": _decode_panel(mask_raw, boolean=True) if isinstance(mask_raw, Mapping) else None,
        "data_snapshot": dict(payload.get("data_snapshot") or {}),
        "fields": tuple(str(value) for value in payload.get("fields") or tuple(panels)),
        "effective_adjust": str(payload.get("effective_adjust") or "qfq"),
        "execution_adjust": str(
            payload.get("execution_adjust") or payload.get("effective_adjust") or "qfq"
        ),
        "start": payload.get("start"),
        "end": payload.get("end"),
        "load_start": payload.get("load_start"),
        "load_end": payload.get("load_end"),
    }


__all__ = ["CONTRACT_VERSION", "build_frozen_payload", "context_from_payload", "payload_bytes", "payload_sha256"]
