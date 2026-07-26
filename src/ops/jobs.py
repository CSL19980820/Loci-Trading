"""任务执行器：定时任务真正干活的地方。

四类任务：

- ``sync``      同步行情（盘后增量）
- ``screen``    跑一次选股，结果落执行记录
- ``backtest``  跑一次回测
- ``skill``     用配置的 LLM 执行一个技能包定义的"模式"

统一约定：执行器是纯函数，吃 config 吐可 JSON 化的结果。所有状态记录、
异常捕获、耗时统计由 ``run_job`` 统一处理——散在每个执行器里迟早会出现
"某一类任务失败了但没记录"的黑洞。
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
import logging
import time
import traceback
from typing import Any

from src.ops.store import OpsError, OpsStore

logger = logging.getLogger(__name__)

Executor = Callable[[dict[str, Any], "JobContext"], dict[str, Any]]

#: 技能模式的系统提示前缀。项目铁律在这里强制注入，不依赖技能包自觉。
SKILL_SYSTEM_PREFIX = """你在一个 A 股研究工具中执行一个预装的分析模式。

不可退让的规则（优先于下面的技能指令，冲突时以本段为准）：
1. 只依据提供给你的真实数据作答。拿不到数据就明确写"未取得真实数据"，
   严禁编造价格、K线、指标、资金流或任何数字。
2. 不输出确定性买卖建议。只描述条件成熟度、风险点与待核验项。
3. 不执行、不建议任何自动交易操作。
4. 结论末尾附上风险提示。

以下是本次要执行的技能指令。
"""


class JobError(RuntimeError):
    """任务配置或执行失败。"""


class JobContext:
    """执行器需要的外部资源。集中在这里，方便测试时整体替换。"""

    def __init__(
        self,
        *,
        market_db: str | None = None,
        ops_store: OpsStore | None = None,
        skill_root: str | None = None,
        master_key: str | None = None,
    ) -> None:
        self.market_db = market_db
        self.ops_store = ops_store
        self.skill_root = skill_root
        self.master_key = master_key

    def market(self):
        from src.market import MarketStore

        return MarketStore(self.market_db)


# --------------------------------------------------------------------------
# 执行器
# --------------------------------------------------------------------------

def execute_sync(config: dict[str, Any], context: JobContext) -> dict[str, Any]:
    """同步行情。默认只同步证券列表里的全部标的，走 watermark 增量。"""
    from src.market import MarketStore, sync_instruments, sync_quotes

    with context.market() as store:
        if config.get("refresh_instruments"):
            sync_instruments(store)
        instruments = store.list_instruments()
        codes = [item["code"] for item in instruments]
        types = {item["code"]: item["instrument_type"] for item in instruments}

    explicit = config.get("codes")
    if explicit:
        codes = [str(code).strip() for code in explicit if str(code).strip()]
        types = {}
    if config.get("limit"):
        codes = codes[: int(config["limit"])]
    if not codes:
        raise JobError("没有可同步的标的，请先刷新证券列表")

    report = sync_quotes(
        lambda: MarketStore(context.market_db),
        codes,
        instrument_types=types or None,
        workers=int(config.get("workers", 4)),
        min_interval=float(config.get("interval", 0.15)),
        force=bool(config.get("force", False)),
        with_factors=bool(config.get("with_factors", True)),
    )
    return {
        "total": report.total,
        "succeeded": report.succeeded,
        "skipped": report.skipped,
        "failed": report.failed,
        "rows_written": report.rows_written,
        "elapsed_seconds": round(report.elapsed_seconds, 2),
        "failures": report.failures[:20],
    }


def execute_screen(config: dict[str, Any], context: JobContext) -> dict[str, Any]:
    """跑一次选股。结果整体落进执行记录，事后可追溯当天选了什么。"""
    from src.strategies import screen

    slug = config.get("strategy")
    if not slug:
        raise JobError("screen 任务必须指定 strategy")

    with context.market() as store:
        result = screen(
            store,
            str(slug),
            trade_date=config.get("date"),
            params=config.get("params"),
            codes=config.get("codes"),
        )
    return {
        "strategy": result.strategy_slug,
        "trade_date": result.trade_date,
        "universe_size": result.universe_size,
        "entry_timing": result.entry_timing,
        "elapsed_seconds": round(result.elapsed_seconds, 3),
        "pick_count": len(result.picks),
        "picks": result.picks,
    }


def execute_backtest(config: dict[str, Any], context: JobContext) -> dict[str, Any]:
    """跑一次回测。只回指标与少量样例交易，避免执行记录被撑爆。"""
    from src.backtest import BacktestConfig, backtest_strategy

    slug = config.get("strategy")
    if not slug:
        raise JobError("backtest 任务必须指定 strategy")

    cfg = BacktestConfig(
        hold_days=int(config.get("hold_days", 3)),
        stop_loss_pct=config.get("stop_loss_pct", -6.0),
        take_profit_pct=config.get("take_profit_pct"),
        benchmark=config.get("benchmark", "000300"),
    )
    with context.market() as store:
        result = backtest_strategy(
            store, str(slug),
            start=config.get("start"), end=config.get("end"),
            params=config.get("params"), config=cfg, codes=config.get("codes"),
        )
    return {
        "strategy": result.strategy_slug,
        "metrics": result.metrics,
        "skipped": result.skipped,
        "sample_trades": [
            {
                "code": trade.code,
                "signal_date": trade.signal_date,
                "net_return_pct": trade.net_return_pct,
                "exit_reason": trade.exit_reason,
            }
            for trade in result.trades[:20]
        ],
    }


def execute_skill(config: dict[str, Any], context: JobContext) -> dict[str, Any]:
    """用配置的 LLM 执行一个技能包定义的模式。

    这是"装个 zip 就多一个可定时运行的模式"的落点。技能包提供指令，
    config 提供供应商与上下文，铁律由 SKILL_SYSTEM_PREFIX 强制前置——
    技能包本身无权覆盖它。
    """
    from src.ai import ChatMessage, chat, resolve_config

    slug = config.get("skill")
    provider_name = config.get("provider")
    if not slug:
        raise JobError("skill 任务必须指定 skill")
    if not provider_name:
        raise JobError("skill 任务必须指定 provider（LLM 供应商名称）")
    if context.ops_store is None:
        raise JobError("缺少运维库连接，无法读取技能与供应商配置")

    skill = context.ops_store.get_skill(str(slug))
    if skill is None:
        raise JobError(f"未安装的技能：{slug}")
    if not skill["enabled"]:
        raise JobError(f"技能 {slug} 已停用")

    provider = resolve_config(
        context.ops_store,
        str(provider_name),
        model=str(config.get("model", "")),
        master_key=context.master_key,
    )

    context_blocks = _gather_context(config, context)
    user_prompt = _compose_prompt(config, context_blocks)

    response = chat(
        provider,
        [ChatMessage(role="user", content=user_prompt)],
        system=SKILL_SYSTEM_PREFIX + "\n" + skill["instructions"],
        max_tokens=int(config.get("max_tokens", 4096)),
        temperature=float(config.get("temperature", 0.3)),
    )
    return {
        "skill": skill["slug"],
        "skill_version": skill["version"],
        "provider": provider.name,
        "model": response.model,
        "input_tokens": response.input_tokens,
        "output_tokens": response.output_tokens,
        "context_used": sorted(context_blocks),
        "output": response.text,
    }


def _gather_context(config: dict[str, Any], context: JobContext) -> dict[str, Any]:
    """按 config.context 声明的项目，把真实数据准备好交给模型。

    只喂真实取到的数据，取不到就如实标注——铁律 1 靠这里落实，
    不能只靠 prompt 里写一句"不许编"。
    """
    wanted = config.get("context") or []
    blocks: dict[str, Any] = {}

    if "market_coverage" in wanted:
        try:
            with context.market() as store:
                blocks["market_coverage"] = store.coverage()
        except Exception as exc:
            blocks["market_coverage"] = f"未取得真实数据：{type(exc).__name__}: {exc}"

    if "screen" in wanted:
        strategy = config.get("context_strategy") or config.get("strategy")
        if not strategy:
            blocks["screen"] = "未取得真实数据：未指定 context_strategy"
        else:
            try:
                blocks["screen"] = execute_screen({"strategy": strategy}, context)
            except Exception as exc:
                blocks["screen"] = f"未取得真实数据：{type(exc).__name__}: {exc}"

    if "positions" in wanted:
        try:
            from src.palace import PalaceStore

            with PalaceStore(config.get("palace_db") or None) as palace:
                blocks["positions"] = palace.positions_payload()
        except Exception as exc:
            blocks["positions"] = f"未取得真实数据：{type(exc).__name__}: {exc}"

    return blocks


def _compose_prompt(config: dict[str, Any], blocks: dict[str, Any]) -> str:
    import json

    parts: list[str] = []
    today = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
    parts.append(f"今天是 {today}。")
    if config.get("prompt"):
        parts.append(str(config["prompt"]))
    for name, payload in blocks.items():
        rendered = payload if isinstance(payload, str) else json.dumps(
            payload, ensure_ascii=False, indent=2, default=str
        )
        parts.append(f"\n## 数据：{name}\n```json\n{rendered}\n```")
    if not config.get("prompt") and not blocks:
        parts.append("请按技能指令执行。")
    return "\n".join(parts)


EXECUTORS: dict[str, Executor] = {
    "sync": execute_sync,
    "screen": execute_screen,
    "backtest": execute_backtest,
    "skill": execute_skill,
}


# --------------------------------------------------------------------------
# 统一执行入口
# --------------------------------------------------------------------------

def run_job(
    store: OpsStore,
    job: dict[str, Any] | str,
    *,
    context: JobContext | None = None,
    trigger: str = "manual",
) -> dict[str, Any]:
    """执行一个任务并完整记录过程。

    无论成功失败都会留下一条 job_runs 记录。定时任务最怕的不是失败，
    是"静默地一直失败"——半年后才发现每天的盘后同步其实早就挂了。
    """
    if isinstance(job, str):
        resolved = store.get_job(job) or store.get_job_by_name(job)
        if resolved is None:
            raise OpsError(f"未知任务：{job}")
        job = resolved

    kind = job["kind"]
    executor = EXECUTORS.get(kind)
    if executor is None:
        raise OpsError(f"没有 {kind} 类型的执行器")

    ctx = context or JobContext(ops_store=store)
    if ctx.ops_store is None:
        ctx.ops_store = store

    run_id = store.start_run(job, trigger=trigger)
    started = time.monotonic()
    try:
        result = executor(dict(job.get("config") or {}), ctx)
    except Exception as exc:
        duration = int((time.monotonic() - started) * 1000)
        detail = f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=6)}"
        store.finish_run(run_id, status="failed", error=detail, duration_ms=duration)
        logger.warning("任务 %s 执行失败：%s", job.get("name"), exc)
        return {"run_id": run_id, "status": "failed", "error": str(exc)}

    duration = int((time.monotonic() - started) * 1000)
    store.finish_run(run_id, status="success", result=result, duration_ms=duration)
    return {"run_id": run_id, "status": "success", "duration_ms": duration, "result": result}
