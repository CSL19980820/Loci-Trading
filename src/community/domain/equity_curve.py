"""净值曲线的正式契约与归一函数。

**契约**（唯一真相，README 里同步写了一份给前端）::

    metrics_json.equity_curve = [{"d": "YYYY-MM-DD", "v": 1.0234}, ...]

- ``v`` 是**归一化净值**（起点 1.0），不是金额：金额会泄露本金规模，也没法让
  两条曲线叠在一张图上比。
- 点数建议 ``<= MAX_EQUITY_POINTS``（750，约三年日频），超过就等距降采样——
  曲线是给人看形状的，不是对账凭据，万点曲线只会把广场接口撑成几 MB。

**为什么要有归一函数**：这个契约是后定的。历史数据里曲线躺在 ``equity`` /
``nav`` / ``curve`` 三个别名下，点本身还有 ``{"date","value"}`` 与
``["2024-01-02", 1.02]`` 两种写法，前端曾经为此在四个键上挨个猜。归一收敛在这里
一次做完，**认不出来一律返回空列表，绝不抛异常**：历史形状不可控，不该因为某条
老记录里躺着脏数据就让整个广场列表 500。

本模块拆出来而不是写在 ``models.py``，只是因为那个文件已经贴着 600 行上限；
它仍是域模型的一部分，``from src.community.domain.models import EquityPoint``
照常可用（models 在末尾 re-export）。纯标准库，无 IO，不认识 sqlite3 / FastAPI。
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping

#: 契约里曲线的落库键名。**写入只写这一个**，别名只在读的时候认。
EQUITY_CURVE_KEY = "equity_curve"

#: 曲线点数上限（三年日频约 730 个交易日）。
MAX_EQUITY_POINTS = 750

#: 历史别名，按优先级从左到右取第一个「长得像列表」的。
EQUITY_CURVE_ALIASES: tuple[str, ...] = ("equity_curve", "equity", "nav", "curve")

_DATE_KEYS = ("d", "date", "dt", "day", "trade_date", "t")
_VALUE_KEYS = ("v", "value", "nav", "equity", "close", "y")
_DATE_RE = re.compile(r"^(\d{4})-?(\d{2})-?(\d{2})")

__all__ = [
    "EQUITY_CURVE_ALIASES",
    "EQUITY_CURVE_KEY",
    "MAX_EQUITY_POINTS",
    "EquityPoint",
    "normalize_equity_curve",
]


@dataclass(frozen=True, slots=True)
class EquityPoint:
    """净值曲线上的一个点。``v`` 已归一到起点 1.0，多条曲线可直接叠图比较。"""

    d: str
    v: float

    def to_dict(self) -> dict[str, Any]:
        return {"d": self.d, "v": self.v}


def normalize_equity_curve(raw: Any, *, limit: int = MAX_EQUITY_POINTS) -> list[EquityPoint]:
    """把任意历史形状的净值曲线归一成契约形状。

    接受：契约形状本身、``{"equity"|"nav"|"curve": [...]}`` 三个别名容器、
    ``{"date","value"}`` 之类的近义键、``[date, value]`` 二元组、金额序列（按首点归一）。
    返回：按日期升序、起点 1.0 的 ``EquityPoint`` 列表；**任何认不出来的输入返回 []**。
    """
    try:
        points = _extract(raw)
        if not points:
            return []
        return _downsample(points, max(2, int(limit)))
    except Exception:  # 形状不可控：宁可空曲线，也不让脏数据炸掉调用方
        return []


def _extract(raw: Any) -> list[EquityPoint]:
    source = _unwrap(raw)
    if not isinstance(source, (list, tuple)):
        return []
    merged: dict[str, float] = dict()
    for item in source:
        pair = _pair(item)
        if pair is not None:
            merged[pair[0]] = pair[1]  # 同一天重复出现：后写的那条赢
    if not merged:
        return []
    ordered = sorted(merged.items())
    base = ordered[0][1]
    if base == 0.0:
        # 起点 0 没法归一（多半喂进来的是收益率序列而不是净值），整条丢掉。
        return []
    return [EquityPoint(d=day, v=round(value / base, 6)) for day, value in ordered]


def _unwrap(raw: Any) -> Any:
    """容器形状：``{"equity_curve": [...]}`` / ``{"nav": [...]}`` …；裸列表原样返回。"""
    if not isinstance(raw, Mapping):
        return raw
    for key in EQUITY_CURVE_ALIASES:
        value = raw.get(key)
        if isinstance(value, (list, tuple)):
            return value
    return None


def _pair(item: Any) -> tuple[str, float] | None:
    """单点形状：``{"d","v"}`` / ``{"date","value"}`` / ``["2024-01-02", 1.02]``。"""
    if isinstance(item, Mapping):
        day = next((item[key] for key in _DATE_KEYS if key in item), "")
        value = next((item[key] for key in _VALUE_KEYS if key in item), None)
    elif isinstance(item, (list, tuple)) and len(item) == 2:
        day, value = item[0], item[1]
    else:
        return None
    date = _date(day)
    if not date or value is None or isinstance(value, bool):
        return None
    number = _number(value)
    return None if number is None else (date, number)


def _date(raw: Any) -> str:
    """认 ``2024-01-02`` 与 ``20240102``；认不出来返回空串（该点被丢弃）。"""
    match = _DATE_RE.match(str(raw or "").strip())
    return f"{match.group(1)}-{match.group(2)}-{match.group(3)}" if match else ""


def _number(raw: Any) -> float | None:
    """NaN / inf / 非数值一律判为缺失——它们进了曲线就是一条断掉的线。"""
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return value


def _downsample(points: list[EquityPoint], limit: int) -> list[EquityPoint]:
    """等距抽稀，首尾必留：抽掉的是密度，不是区间。"""
    if len(points) <= limit:
        return points
    step = len(points) / float(limit - 1)
    picked = {int(index * step) for index in range(limit - 1)}
    picked.add(len(points) - 1)
    return [points[index] for index in sorted(picked)]
