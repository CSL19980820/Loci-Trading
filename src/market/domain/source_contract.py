"""行情源出口契约（唯一真相）。

每个 lane 声明目标列、候选源列、是否数值化、单位换算。
字段映射与单位口径只活在这里；fetcher 只负责拿原始表。

纯标准库：领域层不依赖 pandas / fastapi / sqlite。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from src.market.domain.column_glossary import CN_TO_EN


class Unit(str, Enum):
    """源侧单位 → 仓内口径。"""

    NONE = "none"
    LOTS_TO_SHARES = "lots_to_shares"  # 手 → 股（×100）
    PERCENT_TO_RATIO = "percent_to_ratio"  # 百分数 → 小数（÷100）
    #: 小数 → 百分数（×100）。为什么需要：同一个目标列会被两家源填，而两家
    #: 的口径正好相反——东财 `涨跌幅` / `主力净流入-净占比` 给的是百分数
    #: （2.45 表示 2.45%），新浪 `changeratio` / `ratioamount` / `r0_ratio`
    #: 给的是小数（0.0245）。仓内 `pct_chg` / `*_net_pct` 只认百分数一种口径，
    #: 否则同一张表里东财的行是 2.45、新浪的行是 0.0245，阈值判断（「主力净
    #: 占比 > 5」）会在换源那天静默失效。差 100 倍的错不会报错，只会算错。
    RATIO_TO_PERCENT = "ratio_to_percent"  # 小数 → 百分数（×100）


@dataclass(frozen=True)
class FieldSpec:
    """单列映射。

    ``sources`` 按优先级匹配原始列名；命中后写入 ``target``。
    ``unit_by_source``：仅当命中该源列名时才换算（已是仓内口径的英文列不二次换算）。
    """

    target: str
    sources: tuple[str, ...]
    numeric: bool = True
    required: bool = True
    unit: Unit = Unit.NONE
    unit_by_source: tuple[tuple[str, Unit], ...] = ()

    def unit_for(self, source_column: str) -> Unit:
        for name, unit in self.unit_by_source:
            if name == source_column:
                return unit
        return self.unit


@dataclass(frozen=True)
class LaneContract:
    """一条 lane 的出口契约。"""

    lane: str
    fields: tuple[FieldSpec, ...]
    keep_unmapped: bool = False

    def required_columns(self) -> tuple[str, ...]:
        return tuple(field.target for field in self.fields if field.required)

    def optional_columns(self) -> tuple[str, ...]:
        return tuple(field.target for field in self.fields if not field.required)

    def output_columns(self) -> tuple[str, ...]:
        return tuple(field.target for field in self.fields)


def _cn(*names: str) -> tuple[str, ...]:
    missing = [name for name in names if name not in CN_TO_EN]
    if missing:
        raise KeyError(f"列名未登记在 CN_TO_EN：{missing}")
    return names


DAILY_CONTRACT = LaneContract(
    lane="hist_daily",
    fields=(
        FieldSpec("date", _cn("日期") + ("date",), numeric=False),
        FieldSpec("open", _cn("开盘") + ("open",)),
        FieldSpec("high", _cn("最高") + ("high",)),
        FieldSpec("low", _cn("最低") + ("low",)),
        FieldSpec("close", _cn("收盘") + ("close",)),
        FieldSpec(
            "volume",
            _cn("成交量") + ("volume",),
            unit_by_source=(("成交量", Unit.LOTS_TO_SHARES),),
        ),
        FieldSpec("amount", _cn("成交额") + ("amount",)),
        FieldSpec(
            "turnover",
            _cn("换手率") + ("turn", "turnover"),
            required=False,
            unit_by_source=(
                ("换手率", Unit.PERCENT_TO_RATIO),
                ("turn", Unit.PERCENT_TO_RATIO),
            ),
        ),
        FieldSpec(
            "outstanding_share",
            _cn("流通股本") + ("outstanding_share",),
            required=False,
        ),
    ),
)

SPOT_CONTRACT = LaneContract(
    lane="spot_batch",
    fields=(
        FieldSpec("code", _cn("代码") + ("code",), numeric=False),
        FieldSpec("date", ("date",), numeric=False, required=False),
        FieldSpec("open", _cn("今开", "开盘") + ("open",)),
        FieldSpec("high", _cn("最高") + ("high",)),
        FieldSpec("low", _cn("最低") + ("low",)),
        FieldSpec("close", _cn("最新价", "收盘") + ("close",)),
        FieldSpec(
            "volume",
            _cn("成交量") + ("volume",),
            unit_by_source=(("成交量", Unit.LOTS_TO_SHARES),),
        ),
        FieldSpec("amount", _cn("成交额") + ("amount",)),
    ),
)

LIVE_CONTRACT = LaneContract(
    lane="spot_batch_live",
    fields=(
        FieldSpec("code", _cn("代码") + ("code",), numeric=False),
        FieldSpec("name", _cn("名称") + ("name",), numeric=False, required=False),
        FieldSpec("open", _cn("今开", "开盘") + ("open",)),
        FieldSpec("high", _cn("最高") + ("high",)),
        FieldSpec("low", _cn("最低") + ("low",)),
        FieldSpec("close", _cn("最新价", "收盘") + ("close", "price")),
        FieldSpec(
            "volume",
            _cn("成交量") + ("volume",),
            unit_by_source=(("成交量", Unit.LOTS_TO_SHARES),),
        ),
        FieldSpec("amount", _cn("成交额") + ("amount",)),
        FieldSpec("prev_close", _cn("昨收") + ("prev_close",), required=False),
        FieldSpec("pct", _cn("涨跌幅") + ("pct",), required=False),
        FieldSpec("change", _cn("涨跌额") + ("change",), required=False),
    ),
    keep_unmapped=True,
)

MINUTE_CONTRACT = LaneContract(
    lane="minute_bars",
    fields=(
        FieldSpec("datetime", _cn("时间") + ("datetime",), numeric=False),
        FieldSpec("open", _cn("开盘") + ("open",), required=False),
        FieldSpec("high", _cn("最高") + ("high",), required=False),
        FieldSpec("low", _cn("最低") + ("low",), required=False),
        FieldSpec("close", _cn("收盘") + ("close",)),
        FieldSpec("volume", _cn("成交量") + ("volume",)),
        FieldSpec("amount", _cn("成交额") + ("amount",), required=False),
        FieldSpec("avg_price", _cn("均价") + ("avg_price",), required=False),
    ),
)

CAPITAL_FLOW_CONTRACT = LaneContract(
    lane="capital_flow",
    #: 两家源：东财（akshare `stock_individual_fund_flow`，中文列名、百分数口径）
    #: 与新浪（`MoneyFlow.ssl_qsfx_zjlrqs`，英文原始键、小数口径）。新浪只给
    #: 主力（`netamount` / `ratioamount`）与超大单（`r0_net` / `r0_ratio`）两组，
    #: **没有大单 / 中单 / 小单拆分**——那六列在新浪回退时就是缺列，不编造，
    #: 也不用「主力减超大单」去凑一个假的大单。
    fields=(
        FieldSpec("date", _cn("日期") + ("date", "opendate"), numeric=False),
        FieldSpec(
            "close", _cn("收盘价", "收盘") + ("close", "trade"), required=False
        ),
        # 资金流历史归一名是 pct_chg，与现价表 pct 撞同一个中文名，必须显式覆盖。
        FieldSpec(
            "pct_chg",
            ("涨跌幅", "pct_chg", "changeratio"),
            required=False,
            unit_by_source=(("changeratio", Unit.RATIO_TO_PERCENT),),
        ),
        FieldSpec(
            "main_net_inflow",
            _cn("主力净流入-净额") + ("main_net_inflow", "netamount"),
            required=False,
        ),
        FieldSpec(
            "main_net_pct",
            _cn("主力净流入-净占比") + ("main_net_pct", "ratioamount"),
            required=False,
            unit_by_source=(("ratioamount", Unit.RATIO_TO_PERCENT),),
        ),
        FieldSpec(
            "super_large_net_inflow",
            _cn("超大单净流入-净额") + ("super_large_net_inflow", "r0_net"),
            required=False,
        ),
        FieldSpec(
            "super_large_net_pct",
            _cn("超大单净流入-净占比") + ("super_large_net_pct", "r0_ratio"),
            required=False,
            unit_by_source=(("r0_ratio", Unit.RATIO_TO_PERCENT),),
        ),
        # 以下六列只有东财有；新浪回退时它们整列缺席（required=False，不补空列）。
        FieldSpec(
            "large_net_inflow",
            _cn("大单净流入-净额") + ("large_net_inflow",),
            required=False,
        ),
        FieldSpec(
            "large_net_pct",
            _cn("大单净流入-净占比") + ("large_net_pct",),
            required=False,
        ),
        FieldSpec(
            "medium_net_inflow",
            _cn("中单净流入-净额") + ("medium_net_inflow",),
            required=False,
        ),
        FieldSpec(
            "medium_net_pct",
            _cn("中单净流入-净占比") + ("medium_net_pct",),
            required=False,
        ),
        FieldSpec(
            "small_net_inflow",
            _cn("小单净流入-净额") + ("small_net_inflow",),
            required=False,
        ),
        FieldSpec(
            "small_net_pct",
            _cn("小单净流入-净占比") + ("small_net_pct",),
            required=False,
        ),
    ),
    keep_unmapped=True,
)

INSTRUMENTS_SH_CONTRACT = LaneContract(
    lane="instruments_sh",
    fields=(
        FieldSpec("code", _cn("证券代码") + ("code",), numeric=False),
        FieldSpec("name", _cn("证券简称") + ("name",), numeric=False, required=False),
        FieldSpec(
            "list_date", _cn("上市日期") + ("list_date",), numeric=False, required=False
        ),
    ),
)

INSTRUMENTS_SZ_CONTRACT = LaneContract(
    lane="instruments_sz",
    fields=(
        FieldSpec("code", _cn("A股代码") + ("code",), numeric=False),
        FieldSpec("name", _cn("A股简称") + ("name",), numeric=False, required=False),
        FieldSpec(
            "list_date",
            _cn("A股上市日期") + ("list_date",),
            numeric=False,
            required=False,
        ),
        FieldSpec("board", _cn("板块") + ("board",), numeric=False, required=False),
        FieldSpec(
            "industry", _cn("所属行业") + ("industry",), numeric=False, required=False
        ),
    ),
)

INSTRUMENTS_BJ_CONTRACT = LaneContract(
    lane="instruments_bj",
    fields=(
        FieldSpec("code", _cn("证券代码") + ("code",), numeric=False),
        FieldSpec("name", _cn("证券简称") + ("name",), numeric=False, required=False),
        FieldSpec(
            "list_date", _cn("上市日期") + ("list_date",), numeric=False, required=False
        ),
    ),
)


def _preferred_chinese_rename(contract: LaneContract) -> dict[str, str]:
    """每个目标列取第一个中文候选源列，供对照测试 / 目录展示。"""
    mapping: dict[str, str] = {}
    for field in contract.fields:
        for source in field.sources:
            if source == field.target:
                continue
            if any("\u4e00" <= char <= "\u9fff" for char in source):
                mapping[source] = field.target
                break
    return mapping


# 由契约派生；勿再手写第二份中英表。
EASTMONEY_DAILY_RENAME = _preferred_chinese_rename(DAILY_CONTRACT)
#: 现价对照含 live 富字段（name/pct…），由 LIVE_CONTRACT 派生。
EASTMONEY_LIVE_RENAME = _preferred_chinese_rename(LIVE_CONTRACT)
EASTMONEY_SPOT_RENAME = EASTMONEY_LIVE_RENAME  # 兼容旧名
EASTMONEY_MINUTE_RENAME = _preferred_chinese_rename(MINUTE_CONTRACT)
EASTMONEY_CAPITAL_FLOW_RENAME = _preferred_chinese_rename(CAPITAL_FLOW_CONTRACT)
