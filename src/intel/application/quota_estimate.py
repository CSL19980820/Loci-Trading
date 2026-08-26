"""配额估算：按真实 cron 与真实 Job 配置推算日调用量，超预算给中文告警。

从 ``daily_recipe.py`` 拆出来是体量原因（那边贴着 600 行上限）。

这里只**估**、不发起任何真实调用：喂给 ``build_followup_calls`` 的是
``_synthetic_prior`` 造的「上游给满了」假载荷，估的是扇出上限，当天真返回不了
这么多行只会更少。估算器的轮次必须跟调度器同一个 cron——旧实现写死 20 轮而真实
是 24 轮，数字天生低两成，闸门于是永远卡不住。
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.intel.application.daily_recipe import (
    DEFAULT_INTRADAY_CRON,
    INTRADAY_THEME_TOP_N,
    SKILL_RESERVE,
    STRUCTURED_BUDGET,
    IntelPhase,
    build_followup_calls,
    build_static_calls,
    intraday_runs_from_cron,
)

def _synthetic_prior(*, theme_n: int, stock_n: int) -> dict[str, dict[str, Any]]:
    """给估算器用的「上游给满了」假载荷。

    估的是**扇出上限**（当天真返回不了这么多行就更少），且不发起任何真实调用。
    """
    themes = [{"themeCode": f"T{index:04d}"} for index in range(max(0, int(theme_n)))]
    stocks = [{"code": f"{600000 + index:06d}"} for index in range(max(0, int(stock_n)))]
    return {
        "theme_intraday_capital": {"structured": {"rows": themes}},
        "limit_up_ladder": {"structured": {"rows": stocks}},
    }


def _followup_estimate(
    phase: IntelPhase,
    *,
    theme_top_n: int,
    stock_flow_top_n: int,
    intraday_theme_top_n: int = INTRADAY_THEME_TOP_N,
) -> int:
    """follow-up 扇出上限：直接把 ``build_followup_calls`` 跑一遍数长度。

    以前这里手抄了一份公式，抄漏了盘后档 ``capital_flow`` 的真实分批数（240 只按 20
    一批是 12 批，公式却按 ``min(flow_n, 100)`` 算成 5 批），于是估算天生比实际少一大
    截、闸门永远卡不住。改成复用构造器后，配方怎么改估算都跟得上。
    """
    prior = _synthetic_prior(theme_n=theme_top_n, stock_n=stock_flow_top_n)
    return len(
        build_followup_calls(
            phase,
            prior,
            theme_top_n=theme_top_n,
            stock_flow_top_n=stock_flow_top_n,
            intraday_theme_top_n=intraday_theme_top_n,
        )
    )


#: 每档可单独覆盖的旋钮（``phase_params``）。``runs`` 是该档一天跑几轮。
_PHASE_KNOBS = (
    "theme_top_n",
    "stock_flow_top_n",
    "screener_count",
    "intraday_theme_top_n",
    "runs",
)


def _resolve_knobs(
    phase: IntelPhase,
    *,
    defaults: dict[str, int],
    overrides: Mapping[str, Mapping[str, Any]] | None,
) -> dict[str, int]:
    knobs = dict(defaults)
    row = (overrides or {}).get(phase) or {}
    for key in _PHASE_KNOBS:
        value = row.get(key) if isinstance(row, Mapping) else None
        if value is None:
            continue
        try:
            knobs[key] = int(value)
        except (TypeError, ValueError):
            continue
    return knobs


def estimate_daily_calls(
    *,
    theme_top_n: int = 120,
    stock_flow_top_n: int = 160,
    intraday_runs: int | None = None,
    screener_count: int = 10,
    intraday_theme_top_n: int = INTRADAY_THEME_TOP_N,
    intraday_cron: str | None = None,
    phase_params: Mapping[str, Mapping[str, Any]] | None = None,
    structured_budget: int = STRUCTURED_BUDGET,
    skill_reserve: int = SKILL_RESERVE,
    pool: str = "structured",
) -> dict[str, Any]:
    """三档合计的**上限**估算，供运维核对是否压在预算内。

    ``intraday_runs`` 不再写死：不给就按 ``intraday_cron``（默认镜像托管 cron）数轮次，
    调用方应把 ops.db 里那条任务的真实 cron / 真实配置（``phase_params``）传进来，否则
    估算与调度器两张皮。``phase_params`` 形如
    ``{"close": {"theme_top_n": 200, "runs": 1}}``。
    """
    runs = (
        int(intraday_runs)
        if intraday_runs is not None
        else intraday_runs_from_cron(intraday_cron)
    )
    defaults = {
        "theme_top_n": int(theme_top_n),
        "stock_flow_top_n": int(stock_flow_top_n),
        "screener_count": int(screener_count),
        "intraday_theme_top_n": int(intraday_theme_top_n),
    }
    default_runs = {"open": 1, "intraday": max(0, runs), "close": 1}
    by_phase: dict[str, dict[str, Any]] = {}
    for phase in ("open", "intraday", "close"):
        knobs = _resolve_knobs(phase, defaults=defaults, overrides=phase_params)
        phase_runs = max(0, int(knobs.pop("runs", default_runs[phase])))
        static_n = len(build_static_calls(phase, screener_count=knobs["screener_count"]))
        follow_n = _followup_estimate(
            phase,
            theme_top_n=knobs["theme_top_n"],
            stock_flow_top_n=knobs["stock_flow_top_n"],
            intraday_theme_top_n=knobs["intraday_theme_top_n"],
        )
        per_run = static_n + follow_n
        by_phase[phase] = {
            "static": static_n,
            "followup_max": follow_n,
            "per_run": per_run,
            "runs": phase_runs,
            "daily": per_run * phase_runs,
            "knobs": knobs,
        }
    total = sum(int(row["daily"]) for row in by_phase.values())
    budget = int(structured_budget)
    return {
        "pool": str(pool),
        "open": by_phase["open"]["per_run"],
        "open_static": by_phase["open"]["static"],
        "open_followup_max": by_phase["open"]["followup_max"],
        "intraday_per_run": by_phase["intraday"]["per_run"],
        "intraday_static": by_phase["intraday"]["static"],
        "intraday_followup_max": by_phase["intraday"]["followup_max"],
        "intraday_runs": by_phase["intraday"]["runs"],
        "intraday_cron": str(intraday_cron or DEFAULT_INTRADAY_CRON),
        "close": by_phase["close"]["per_run"],
        "close_static": by_phase["close"]["static"],
        "close_followup_max": by_phase["close"]["followup_max"],
        "by_phase": by_phase,
        "estimated_total": total,
        "structured_budget": budget,
        "skill_reserve": int(skill_reserve),
        "within_budget": total <= budget,
        "over_by": max(0, total - budget),
    }


def structured_budget_alert(estimate: Mapping[str, Any]) -> dict[str, Any] | None:
    """预估超预算就给一条**中文**告警：明说该拧哪个旋钮；没超返回 ``None``。

    只报警、不改配方。静默截断数据会让下游把「只扫了前 N 只」读成「全市场就这些」，
    那比多花几百次配额危险得多——要少拿数据，必须是人显式调旋钮。
    """
    total = int(estimate.get("estimated_total") or 0)
    budget = int(estimate.get("structured_budget") or STRUCTURED_BUDGET)
    if total <= budget:
        return None
    pool = str(estimate.get("pool") or "structured")
    by_phase = estimate.get("by_phase") or dict()
    open_row = by_phase.get("open") or dict()
    intraday = by_phase.get("intraday") or dict()
    close = by_phase.get("close") or dict()
    intraday_knobs = intraday.get("knobs") or dict()
    close_knobs = close.get("knobs") or dict()
    cron = str(estimate.get("intraday_cron") or DEFAULT_INTRADAY_CRON)
    runs = int(intraday.get("runs") or 0)
    per_run = int(intraday.get("per_run") or 0)
    open_daily = int(open_row.get("daily") or 0)
    intraday_daily = int(intraday.get("daily") or 0)
    close_daily = int(close.get("daily") or 0)
    theme_cap = int(intraday_knobs.get("intraday_theme_top_n") or INTRADAY_THEME_TOP_N)
    close_theme = int(close_knobs.get("theme_top_n") or 0)
    close_flow = int(close_knobs.get("stock_flow_top_n") or 0)
    close_screener = int(close_knobs.get("screener_count") or 0)
    close_follow = int(close.get("followup_max") or 0)
    skill_reserve = int(estimate.get("skill_reserve") or SKILL_RESERVE)
    over = total - budget
    knobs = [
        f"把「情报·盘中」的 cron 调稀（当前 {cron}，{runs} 轮/日，每少一轮省 {per_run} 次）",
        f"调小盘中 intraday_theme_top_n（当前 {theme_cap}，每少 10 条题材省 {runs * 10} 次/日）",
        (
            f"调小盘后 theme_top_n / stock_flow_top_n / screener_count"
            f"（当前 {close_theme} / {close_flow} / {close_screener}，"
            f"盘后 follow-up 已占 {close_follow} 次）"
        ),
        f"把盯盘 / tape 类调用留在 skill 池（该池日预算 {skill_reserve} 次，与本池分开计）",
    ]
    message = (
        f"悟道 {pool} 池预估日耗 {total} 次，超出日预算 {budget} 次（超 {over} 次）。"
        f"分档：开盘 {open_daily}、盘中 {per_run}×{runs} 轮={intraday_daily}、盘后 {close_daily}。"
        "本轮照配方跑、不会自动少拿数据；请显式调下面任一旋钮后再重跑："
        + "；".join(knobs)
        + "。"
    )
    return {
        "level": "warning",
        "pool": pool,
        "estimated_total": total,
        "budget": budget,
        "over_by": over,
        "knobs": knobs,
        "message": message,
    }
