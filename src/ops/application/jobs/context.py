"""Job 执行上下文与公共错误/前缀。"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.ops.infrastructure.store import OpsStore
from src.shared.paths import palace_db as _default_palace_db

#: 账本默认路径。PalaceStore 不像 MarketStore 那样接受 None。
DEFAULT_PALACE_DB = str(_default_palace_db())

Executor = Callable[[dict[str, Any], "JobContext"], dict[str, Any]]

#: 技能模式的系统提示前缀。项目铁律在这里强制注入，不依赖技能包自觉。
SKILL_SYSTEM_PREFIX = """你在一个 A 股研究工具中执行一个预装的分析模式。

不可退让的规则（优先于下面的技能指令，冲突时以本段为准）：
1. 只依据提供给你的真实数据作答。拿不到数据就明确写"未取得真实数据"，
   严禁编造价格、K线、指标、资金流或任何数字。
2. 不输出确定性买卖建议。只描述条件成熟度、风险点与待核验项。
3. 不执行、不建议任何自动交易操作。
4. 结论末尾附上风险提示。
5. 需要外部数据或本地脚本结果时，必须调用已提供的工具；禁止假装已执行 CLI。

以下是本次要执行的技能指令。
"""

#: 显式 ``policy: trading_voice`` 的技能可用：仍禁编造，允许核价后的交易向终稿。
SKILL_SYSTEM_PREFIX_TRADING = """你在一个 A 股研究工具中执行一个预装的交易向分析模式。

不可退让的规则（优先于下面的技能指令，冲突时以本段为准）：
1. 只依据工具返回的真实数据作答。拿不到数据就明确写"未取得真实数据"，
   严禁编造价格、K线、指标、资金流或任何数字。
2. 需要脚本/MCP 数据时必须调用已提供工具；禁止假装已执行 CLI。
3. 仅在 A 级核价通过后，才允许输出明确的标的与买入区间；未核价不得写买入价。
4. 不执行、不建议任何自动下单或券商接口操作；结论仅供人工决策。
5. 若技能要求落盘 journal，须调用 write_journal 工具。

以下是本次要执行的技能指令。
"""


def skill_system_prefix(policy: str = "research") -> str:
    if str(policy or "").lower() in {"trading_voice", "trading", "weipan"}:
        return SKILL_SYSTEM_PREFIX_TRADING
    return SKILL_SYSTEM_PREFIX


class JobError(RuntimeError):
    """任务配置或执行失败。"""


def _llm_meta(provider: Any, thinking: str = "") -> dict[str, str]:
    """LLM 调用元数据，写入 job run result 便于运维页追溯。"""
    return {
        "provider": str(getattr(provider, "name", "") or ""),
        "model": str(getattr(provider, "model", "") or ""),
        "thinking": str(thinking or ""),
    }


class JobContext:
    """执行器需要的外部资源。集中在这里，方便测试时整体替换。"""

    def __init__(
        self,
        *,
        market_db: str | None = None,
        ops_store: OpsStore | None = None,
        skill_root: str | None = None,
        master_key: str | None = None,
        palace_db: str | None = None,
    ) -> None:
        self.market_db = market_db
        self.ops_store = ops_store
        self.skill_root = skill_root
        self.master_key = master_key
        self.palace_db = palace_db

    def market(self):
        from src.market import MarketStore

        return MarketStore(self.market_db)
