"""数据线路（Lane）常量与适配器 DTO 约定。

Lane 是「一类数据需求」而不是「一个供应商」：同一 lane 下可以挂多个
adapter，由 router 探测 / 竞速选路。字段转换只写在各 Adapter 代码里，
这里只约定形状，不放映射表。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Lane 常量 —— 字符串 id，便于 API / catalog 直接透传
# ---------------------------------------------------------------------------

LANE_HIST_DAILY = "hist_daily"
LANE_SPOT_BATCH = "spot_batch"
LANE_INSTRUMENTS = "instruments"
LANE_ADJUST_FACTOR = "adjust_factor"
LANE_MINUTE = "minute_bars"
LANE_CAPITAL_FLOW = "capital_flow"
LANE_INTEL_MCP = "intel_mcp"  # 可选类目；有 MCP 情报适配器时再 register，默认空

ALL_LANES: tuple[str, ...] = (
    LANE_HIST_DAILY,
    LANE_SPOT_BATCH,
    LANE_INSTRUMENTS,
    LANE_ADJUST_FACTOR,
    LANE_MINUTE,
    LANE_CAPITAL_FLOW,
    LANE_INTEL_MCP,
)

#: 日线归一列（必选）。Adapter.fetch_daily 必须产出这些列名。
DAILY_REQUIRED_COLUMNS: tuple[str, ...] = (
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
)

#: 日线可选列。turnover 约定为**小数**（0.05 = 5%），与行情仓 / 通达信 COST 一致。
DAILY_OPTIONAL_COLUMNS: tuple[str, ...] = ("turnover", "outstanding_share")


@dataclass(frozen=True)
class AdapterMeta:
    """适配器名片。label 面向用户，用中文。"""

    id: str
    label: str
    lanes: tuple[str, ...]
    description: str = ""
    #: 数据来源站点/接口域名，仅供人核对来源，不参与请求。
    base_url: str = ""


@dataclass
class ProbeResult:
    """单次 lane 探测结果。

    ``ok``：连通且拿到可用小样本（或该 lane 的最小成功条件）。
    ``unsupported``：该 adapter 根本不接这个 lane（不是失败，是能力边界）。
    ``rtt_ms``：往返耗时毫秒；失败时仍可有值（测到报错为止）。
    ``rows``：小样本行数（可选）。
    ``error``：失败/不支持时的说明。
    """

    adapter_id: str
    lane: str
    ok: bool
    rtt_ms: float = 0.0
    rows: int | None = None
    error: str | None = None
    unsupported: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapter_id": self.adapter_id,
            "lane": self.lane,
            "ok": self.ok,
            "rtt_ms": round(self.rtt_ms, 2),
            "rows": self.rows,
            "error": self.error,
            "unsupported": self.unsupported,
            **({"extra": self.extra} if self.extra else {}),
        }


@dataclass
class SpeedTestResult:
    """hist_daily 全量拉取竞速的一条结果。"""

    adapter_id: str
    code: str
    ok: bool
    elapsed_ms: float = 0.0
    rows: int = 0
    bytes_est: int = 0
    mb_per_s: float = 0.0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapter_id": self.adapter_id,
            "code": self.code,
            "ok": self.ok,
            "elapsed_ms": round(self.elapsed_ms, 2),
            "rows": self.rows,
            "bytes_est": self.bytes_est,
            "mb_per_s": round(self.mb_per_s, 4),
            "error": self.error,
        }
