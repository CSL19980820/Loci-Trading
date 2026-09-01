r"""行情库体检的**阈值与结论载体**：`QualityThresholds` / `Finding` 与四个源
判定常量。

和判据本身（`data_quality.py` 里那一串 `_check_*` 与 `inspect_market_data`）分开，
是因为这两类东西的读者不同：改阈值的人要读满屏「这个数字是怎么标定出来的」，
改判据的人要读 SQL 与分支。它们原先挤在一个 638 行的文件里，谁来都得先翻过
另一半。本模块**只有数据定义，不含任何库访问**。

注释一行没删，按原样搬过来了——包括 `min_last_day_authoritative_ratio` 里那段
标定依据。**取证归属**那段（「开发机 2026-08-26 只读实测 / 同日生产库是健康的 /
别把开发机数字写成生产实测」，根 AGENTS.md §3.5 指着它）仍在
`data_quality.py::_check_last_day_authoritative` 的 docstring 里，没有搬走；这里
只是阈值侧的同一组实测水位。

`data_quality.py` 原样 re-export 本模块全部符号，`from ...data_quality import
QualityThresholds / Finding`（`src/market/__init__.py`、`tests/market/
test_data_quality.py` 都在用）继续成立。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
#: 合成成交额判据的容差。腾讯日 K 的 amount 就是 close*volume，完全相等。
#: 1990 年代单一价格成交日真实值也会相等，所以这条只在**会合成的源**上算。
_SYNTH_EPSILON = 1.0

#: 已知会合成 amount 的源。新增回退源前先确认它给的是不是真实成交额。
FABRICATING_SOURCES: tuple[str, ...] = ("tencent", "tencent_spot")

#: 权威源前缀。占比低于阈值说明主源长期失联、库在靠回退源续命。
AUTHORITATIVE_PREFIX = "tdx"

#: 当日临时行的 source 后缀。盘中 spot 先落一批「还没定稿」的行
#: （``tencent_spot`` / ``tdx_spot``），日终同步再用正式日 K 覆盖它们。
#: 它们既不算「权威源已经写进来了」，也不算「主源失联退到了回退源」，
#: 所以当日源占比判据必须把它们单独归一类，见 ``_check_last_day_authoritative``。
PROVISIONAL_SUFFIX = "_spot"


@dataclass
class QualityThresholds:
    """阈值。默认值是「重同步刚做完」的实测水位留出余量后的结果。"""

    #: 权威源占比下限。重同步后实测 99.2%，跌破 95% 说明有系统性回退。
    min_authoritative_ratio: float = 0.95
    #: 合成成交额行数上限。重同步后实测 335 行（全是通达信不返回的老日期）。
    max_fabricated_rows: int = 2000
    #: 近窗缺回执行数上限。回执是研究输入证据，缺了严格 PIT 会拒绝该输入。
    max_missing_receipts: int = 200
    #: 近窗回看天数。
    lookback_days: int = 90
    #: 最后一个交易日的覆盖率下限，**相对 `instruments` 里的股票数**而非绝对行数。
    #:
    #: 曾写死 `min_last_day_rows = 5000`（注释称「全市场约 5540」）。这是个会随
    #: 时间失效的假设:生产库实测 `instruments` 只有 4932 只股票，当日覆盖 4935 行
    #: 已经是 **100.1%**，却因为够不到 5000 而**天天报警**。判据一旦永远为真，
    #: 人就会开始忽略整张体检表——这正是本模块最想避免的失效模式。
    #: 退市、暂停上市、注册制扩容都会让全市场只数持续漂移，绝对阈值守不住。
    min_last_day_coverage: float = 0.95
    #: 覆盖率判据的兜底:`instruments` 自己空了/没同步时，比率算不出来，
    #: 退回一个「显然不可能是全市场」的绝对地板，避免空库被判成 100% 通过。
    min_last_day_rows_floor: int = 500
    #: 最后一个交易日的权威源占比下限（分母只算**已定稿**的行，见
    #: ``_check_last_day_authoritative``）。
    #:
    #: **为什么要单独有这一条**：``min_authoritative_ratio`` 的分母是全部历史，
    #: 一次全量重灌就能把它顶到 96%，此后每天只新增约 5500 行，「今天主源一行
    #: 没写」被十六年历史稀释到看不见。**开发机**只读实测（2026-08-26，该机
    #: 通达信自 07-28 起被限流）：全库 16,966,403 行里 tdx 占 96.5% 判绿，而最后
    #: 一个交易日的 5542 行里 tdx **0 行**；要把全库压到 95% 以下还得再灌
    #: 271,948 行非权威数据，按每天 5542 行算是 **49 个交易日**——等它开口，
  #: 主源已经断了两个半月。同日生产库是健康的（全库 97.1%、逐日 99.9%~100%），
    #: 盲区靠算术成立，不依赖某一台机器当时是不是真坏了。
    #:
    #: **默认 0.90 的依据**是同一次实测的日水位：2026-01-01~07-27 这 135 个交易
    #: 日里，当日权威源占比稳定在 **97.85% ~ 98.24%**（够不到的那 2% 是通达信
    #: 代码段不支持的票，归 ``watermark_source`` 判据管）。0.90 相对最低水位留了
    #: 8 个百分点、约 430 行/日的余量，吸得住几十只票的临时取数失败；而真退化的
    #: 那一侧是 20.7%（开发机 2026-07-28 起）与 0%，离阈值远得很。
    #:
    #: **不用绝对行数**：这一课已经交过学费——旧的 ``min_last_day_rows = 5000``
    #: 在只有 4932 只票的库上天天误报，当日 4935 行其实已是 100.1%。全市场只数
    #: 会随退市与扩容持续漂移（生产 4932 只、开发机 5544 只，同一天两个数），
    #: 绝对阈值守不住。
    min_last_day_authoritative_ratio: float = 0.90
    #: 最后一个交易日「临时行占比」的上限，超过它就认为当天还没日终定稿。
    #:
    #: 盘中跑体检时当天本来就全是 spot 临时行（占比 1.0），此时去判权威源占比
    #: 等于天天误报；日终同步跑完之后正式日 K 会覆盖掉它们。0.5 落在这两个态
    #: 中间。
    #:
    #: **原先这条的标定是错的，连同订正一起记在这里，免得后来人再照抄**：注释
    #: 曾写「日终同步（15:10）之后正式日 K 会覆盖掉它们，生产实测 2026-08-25
    #: 收盘后残留 1142 / 5542 = 20.6%」。但当时的 ``today_refresh`` 只刷复权因子
    #: 加 ``apply_today_spot``，根本不调 ``sync_quotes``；而 ``quotes_daily`` 的
    #: upsert 是后写覆盖先写，所以 spot 这一趟只要成功，当日就必然 100% 临时行，
    #: 正式日 K 得等第二天早上增量近窗回头重写才落。开发机 2026-08-25 16:10 的
    #: 热库重建快照可以对质：当日 5542 行**全部**是 ``tencent_spot``。那个 20.6%
    #: 是当晚 19:12 手工补跑一次 ``mode=full`` 之后的事后状态，不是流水线终态。
    #: 判据本身没错，错的是流水线缺一步——已由
    #: ``ops/application/jobs/sync.py::_finalize_today_with_authoritative`` 补上。
    max_last_day_provisional_ratio: float = 0.5
    #: 日终定稿窗口（本地时钟小时）。到点之后仍然满屏 spot 就不再豁免。
    #:
    #: 依据：行情日终重刷托管在 15:10，热库重建 16:10，体检自己 16:30。16 点
    #: 既在日终同步之后、又在体检默认点之前。**这道时限不能省**：没有它，
    #: 「日终同步整个失败、当天只剩 spot」会被当成「还没定稿」白白放过，而那
    #: 恰恰是最该当天知道的一天。
    last_day_settle_hour: int = 16
    #: 基准指数收盘价下限。中证系列基点 1000；低于它说明串成了同号个股。
    min_index_close: float = 1000.0
    #: 基准指数代码。
    index_codes: tuple[str, ...] = ("000300", "000905", "000852")


@dataclass
class Finding:
    """一条体检结论。``level`` 只有 ok / warn / block 三档。"""

    key: str
    level: str
    message: str
    observed: dict[str, Any] = field(default_factory=dict)
    remediation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "level": self.level,
            "message": self.message,
            "observed": dict(self.observed),
            "remediation": self.remediation,
        }
