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

#: 账本默认路径。PalaceStore 不像 MarketStore 那样接受 None。
DEFAULT_PALACE_DB = str(
    __import__("pathlib").Path(__file__).resolve().parents[2] / ".palace" / "qianlong.db"
)

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
    """跑一次选股。结果整体落进执行记录，事后可追溯当天选了什么。

    ``record_candidates=True`` 时同时把入选标的写进账本的候选池——这是
    整个反馈闭环的接头处：

        选股 → 候选池 → T+N 后自动验证 → 知道这套战法准不准

    不写候选池的话，复盘引擎的候选池验证永远没有数据可验，"当初否决的票
    后来涨了多少"这个最有价值的问题就问不出来。
    """
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
        names = {
            item["code"]: item["name"] for item in store.list_instruments(status="")
        } if config.get("record_candidates") else {}

    payload = {
        "strategy": result.strategy_slug,
        "trade_date": result.trade_date,
        "universe_size": result.universe_size,
        "entry_timing": result.entry_timing,
        "elapsed_seconds": round(result.elapsed_seconds, 3),
        "pick_count": len(result.picks),
        "picks": result.picks,
    }

    if config.get("record_candidates"):
        payload["recorded"] = _record_candidates(result, config, context, names)
    return payload


def _record_candidates(
    result: Any, config: dict[str, Any], context: JobContext, names: dict[str, str]
) -> dict[str, Any]:
    """把选股结果写进候选池。

    pool_id 默认用 "策略slug@日期"：同一天跑多个战法各自成池，复盘时能
    按战法分开统计，而不是混成一锅。同池同标的重复写入会被账本的唯一
    索引覆盖成最新一次，所以重跑任务是幂等的。
    """
    from src.palace import PalaceError, PalaceStore

    pool_id = str(config.get("pool_id") or f"{result.strategy_slug}@{result.trade_date}")
    decision = str(config.get("decision") or "入选")
    written, failed = 0, []

    with PalaceStore(context.palace_db or DEFAULT_PALACE_DB) as palace:
        for pick in result.picks:
            code = str(pick["code"])
            try:
                palace.record_candidate(
                    code=code,
                    name=names.get(code, ""),
                    decision=decision,
                    reason=_factor_reason(result.strategy_slug, pick.get("factors") or {}),
                    occurred_on=result.trade_date,
                    pool_id=pool_id,
                    timing=result.entry_timing,
                    rule_version=result.strategy_slug,
                    evidence=pick.get("factors") or {},
                    source="job:screen",
                )
                written += 1
            except PalaceError as exc:
                # 单只写失败不该让整批作废——记下来，其余照常入池。
                failed.append({"code": code, "error": str(exc)[:200]})

    return {"pool_id": pool_id, "written": written, "failed": failed}


def _factor_reason(slug: str, factors: dict[str, Any]) -> str:
    """把关键因子压成一句人能读的理由。

    候选记录只留"某战法选中"是没用的——三个月后回看，你需要知道当时是
    哪几个数字让它入选的。
    """
    parts = [
        f"{key}={value:.2f}"
        for key, value in factors.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    ]
    body = "，".join(parts[:6]) or "（无数值因子）"
    return f"{slug} 选中：{body}"[:500]


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
    from src.ai import resolve_config
    from src.ai.agent import format_tool_trace, make_mcp_executor, run_agent

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

    # 技能包声明的 tools 用来把工具面收窄：一个 MCP server 可能有 60+ 个
    # 工具，全塞进 system prompt 会占掉大量上下文，而多数技能只用三五个。
    tool_schemas, executor = _resolve_tools(config, skill, context, provider.protocol)

    result = run_agent(
        provider,
        system=SKILL_SYSTEM_PREFIX + "\n" + skill["instructions"],
        user_prompt=user_prompt,
        tool_schemas=tool_schemas,
        tool_executor=executor,
        max_rounds=int(config.get("max_rounds", 8)),
        max_tokens=int(config.get("max_tokens", 4096)),
        temperature=float(config.get("temperature", 0.3)),
    )

    payload = result.to_dict()
    payload.update(
        {
            "skill": skill["slug"],
            "skill_version": skill["version"],
            "provider": provider.name,
            "context_used": sorted(context_blocks),
            "tool_trace": format_tool_trace(result.invocations),
        }
    )
    return payload


def _resolve_tools(
    config: dict[str, Any], skill: dict[str, Any], context: JobContext, protocol: str
):
    """按配置装配 MCP 工具。没有配置 server 就退化成无工具的单轮对话。"""
    server_names = config.get("mcp_servers")
    if server_names is None:
        return None, None
    if context.ops_store is None:
        return None, None

    try:
        from src.intel.registry import build_client, collect_tools
    except ImportError as exc:
        logger.warning("MCP 依赖缺失（%s），技能将以无工具模式运行", exc.name)
        return None, None

    names = [str(item) for item in server_names] if server_names else None
    allow = config.get("tools") or skill.get("allowed_tools") or None
    tools, routing = collect_tools(context.ops_store, names, allow=allow)
    if not tools:
        logger.warning("未匹配到任何 MCP 工具（server=%s allow=%s）", names, allow)
        return None, None

    clients: dict[str, Any] = {}
    for server in {tool.server for tool in tools}:
        try:
            clients[server] = build_client(
                context.ops_store, server, master_key=context.master_key
            )
        except Exception as exc:
            # 一个 server 连不上不该让整个技能跑不起来，其余工具照常可用。
            logger.warning("MCP server %s 不可用：%s", server, exc)

    schemas = [
        tool.to_anthropic_schema() if protocol == "anthropic" else tool.to_openai_schema()
        for tool in tools
        if tool.server in clients
    ]
    if not schemas:
        return None, None
    return schemas, make_mcp_executor(clients, routing)


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

            with PalaceStore(context.palace_db or DEFAULT_PALACE_DB) as palace:
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



def execute_compare(config: dict[str, Any], context: JobContext) -> dict[str, Any]:
    """横向对比多个战法在同一区间、同一成本口径下的超额。

    单看一个战法的绝对收益意义有限——大盘涨的时候什么都赚。这里统一区间
    与成本，按超额排序，并算出每个战法的"回吐"（MFE 均值 − 净收益均值）。
    回吐大说明浮盈拿不住，问题在退出而不在选股。
    """
    from src.backtest import BacktestConfig, backtest_strategy
    from src.strategies import all_strategies, get

    holds = [int(h) for h in (config.get("holds") or [1, 3])]
    slugs = config.get("strategies")
    engines = [get(str(s)) for s in slugs] if slugs else all_strategies()

    rows: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    with context.market() as store:
        for engine in engines:
            for hold in holds:
                label = f"{engine.slug}/{hold}d"
                try:
                    result = backtest_strategy(
                        store, engine.slug,
                        start=config.get("start"), end=config.get("end"),
                        config=BacktestConfig(
                            hold_days=hold,
                            stop_loss_pct=config.get("stop_loss_pct", -8.0),
                            benchmark=config.get("benchmark", "000300"),
                        ),
                    )
                except Exception as exc:
                    # 一个战法算不出来不该让整批对比作废。
                    failures.append({"label": label, "error": f"{type(exc).__name__}: {exc}"[:200]})
                    continue
                metrics = result.metrics
                if not metrics.get("trades"):
                    continue
                rows.append(
                    {
                        "label": label, "strategy": engine.slug, "hold_days": hold,
                        "trades": metrics["trades"], "win_rate": metrics["win_rate"],
                        "avg_net_return": metrics["avg_net_return"],
                        "avg_mfe": metrics.get("avg_mfe"), "avg_mae": metrics.get("avg_mae"),
                        "avg_alpha": metrics.get("avg_alpha"),
                        "give_back": round(
                            (metrics.get("avg_mfe") or 0) - (metrics.get("avg_net_return") or 0), 4
                        ),
                        "caution": metrics.get("caution", ""),
                    }
                )

    rows.sort(key=lambda item: item.get("avg_alpha") if item.get("avg_alpha") is not None
              else item["avg_net_return"], reverse=True)
    worst = max(rows, key=lambda item: item["give_back"]) if rows else None
    return {
        "rows": rows, "failures": failures,
        "range": {"start": config.get("start"), "end": config.get("end")},
        "worst_give_back": worst,
        "hint": (
            f"回吐最严重的是 {worst['label']}（{worst['give_back']:.2f} 个百分点）。"
            "若多数战法回吐都大，说明问题在退出纪律而不在选股。"
        ) if worst and worst["give_back"] > 4 else "",
    }


def execute_optimize(config: dict[str, Any], context: JobContext) -> dict[str, Any]:
    """扫描退出规则：固定选股信号，只改持有期 / 止盈 / 止损。

    参数扫描天生会生产漂亮数字。结果里必须带上过拟合提示，并建议换区间
    重跑——不加这句，它就只是个自我欺骗的工具。
    """
    from src.backtest import BacktestConfig, backtest_strategy

    slug = config.get("strategy")
    if not slug:
        raise JobError("optimize 任务必须指定 strategy")

    holds = [int(x) for x in (config.get("holds") or [1, 2, 3, 5])]
    targets = [None if not x else float(x) for x in (config.get("targets") or [0, 3, 5, 8])]
    stops = [None if not x else float(x) for x in (config.get("stops") or [0, -5, -8])]

    rows: list[dict[str, Any]] = []
    with context.market() as store:
        for hold in holds:
            for target in targets:
                for stop in stops:
                    try:
                        result = backtest_strategy(
                            store, str(slug),
                            start=config.get("start"), end=config.get("end"),
                            config=BacktestConfig(
                                hold_days=hold, take_profit_pct=target, stop_loss_pct=stop,
                                benchmark=config.get("benchmark", "000300"),
                            ),
                        )
                    except Exception:
                        continue
                    metrics = result.metrics
                    if not metrics.get("trades"):
                        continue
                    rows.append(
                        {
                            "hold_days": hold, "take_profit_pct": target, "stop_loss_pct": stop,
                            "trades": metrics["trades"], "win_rate": metrics["win_rate"],
                            "avg_net_return": metrics["avg_net_return"],
                            "avg_alpha": metrics.get("avg_alpha"),
                            "exit_reasons": metrics.get("exit_reasons", {}),
                            "caution": metrics.get("caution", ""),
                        }
                    )

    if not rows:
        return {"rows": [], "note": "没有产生任何可评估的交易"}

    rows.sort(key=lambda item: item.get("avg_alpha") if item.get("avg_alpha") is not None
              else item["avg_net_return"], reverse=True)
    best = rows[0]
    baseline = next(
        (r for r in rows if r["take_profit_pct"] is None and r["stop_loss_pct"] is None), None
    )
    key = "avg_alpha" if best.get("avg_alpha") is not None else "avg_net_return"
    return {
        "strategy": slug, "rows": rows, "best": best, "baseline": baseline,
        "improvement": round((best.get(key) or 0) - (baseline.get(key) or 0), 4)
        if baseline else None,
        "warning": (
            "这是在同一段历史上反复试参数，天然存在过拟合风险。"
            "换一段区间重跑一次，若最优组合完全不同，说明它只拟合了噪声。"
        ),
    }


def execute_prune(config: dict[str, Any], context: JobContext) -> dict[str, Any]:
    """清理历史执行记录。

    定时任务是每天跑的，job_runs 不清理会无限增长，最终把几百 KB 的运维库
    撑到几百 MB。按任务保留最近 N 条即可——更早的记录除了占地方没有用处，
    真要追溯久远的问题，那时也早该看行情仓和账本了。
    """
    if context.ops_store is None:
        raise JobError("缺少运维库连接")
    keep = int(config.get("keep_per_job", 200))
    removed = context.ops_store.prune_runs(keep_per_job=keep)
    return {"removed": removed, "keep_per_job": keep}


EXECUTORS: dict[str, Executor] = {
    "sync": execute_sync,
    "screen": execute_screen,
    "backtest": execute_backtest,
    "compare": execute_compare,
    "optimize": execute_optimize,
    "prune": execute_prune,
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
