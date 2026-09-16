"""研究工作台的两个**进程级线程池**必须带着提交请求那个租户跑。

``_FACTOR_EXECUTOR`` / ``_BACKTEST_EXECUTOR`` 是模块级单例：worker 线程的
Context 停在线程创建那一刻，与提交任务的请求毫无关系。而 ``execute_job`` 里的
run card / workflow / job store 全部挂在 ``research_runs_dir()``（**租户私有**）
下，丢了上下文就是把 B 的实验产物写进管理员目录，B 那边永远只看到 queued。
"""
from __future__ import annotations

import threading
from contextlib import nullcontext
from types import SimpleNamespace
from typing import Any

from src.research.api.backtest_models import ResearchBacktestRequest
from src.research.api.factor_models import Pth252FactorJobRequest
from src.shared.paths import research_runs_dir
from src.shared.tenancy import current_tenant, tenant_scope


def _endpoint(router: Any, path: str) -> Any:
    """从 router 上取出路由函数，直接调用——本组用例验的是线程，不是 HTTP 栈。"""
    for route in router.routes:
        if getattr(route, "path", "") == path:
            return route.endpoint
    raise AssertionError(f"路由未注册：{path}")


def _factor_request() -> Pth252FactorJobRequest:
    return Pth252FactorJobRequest(
        start="2024-01-01",
        end="2024-12-31",
        split={
            "train_start": "2024-01-01",
            "train_end": "2024-06-30",
            "oos_start": "2024-07-01",
            "oos_end": "2024-12-31",
        },
        historical_universe_id="hs300-2024",
    )


def _backtest_request() -> ResearchBacktestRequest:
    return ResearchBacktestRequest(
        strategy="demo",
        start="2024-01-01",
        end="2024-12-31",
        split={
            "train_start": "2024-01-01",
            "train_end": "2024-06-30",
            "oos_start": "2024-07-01",
            "oos_end": "2024-12-31",
        },
    )


def test_factor_job_executor_resolves_paths_for_the_submitting_tenant(monkeypatch) -> None:
    from src.research.api import factor_router as mod

    seen: dict[str, str] = {}
    done = threading.Event()

    def fake_experiment(_store: Any, **_kwargs: Any) -> Any:
        # 只抓「线程内解析出来的租户私有目录」，真实验不跑。
        seen["tenant"] = current_tenant()
        seen["runs_dir"] = str(research_runs_dir())
        done.set()
        return SimpleNamespace(run_card=SimpleNamespace(run_id="run-1"))

    monkeypatch.setattr(mod, "run_pth252_factor_experiment", fake_experiment)
    router = mod.build_research_factor_router(
        write_dependency=lambda: None,
        market_store_factory=lambda _db: nullcontext(None),
    )
    submit = _endpoint(router, "/api/research/factor-jobs")

    with tenant_scope("u_a"):
        submit(request=_factor_request(), _write=None)

    assert done.wait(30), "因子任务没有在池子里跑起来"
    assert seen["tenant"] == "u_a"
    assert "u_a" in seen["runs_dir"], f"线程内解析的研究目录不属于发起租户：{seen}"


def test_backtest_job_executor_resolves_paths_for_the_submitting_tenant(monkeypatch) -> None:
    # 回测端点组 2026-08 拆到了 backtest_router.py；_BACKTEST_EXECUTOR 与
    # run_research_backtest 的查找都在那个模块里，patch 必须打在它身上。
    from src.research.api import backtest_router as mod

    seen: dict[str, str] = {}
    done = threading.Event()

    def fake_backtest(_store: Any, **_kwargs: Any) -> Any:
        seen["tenant"] = current_tenant()
        seen["runs_dir"] = str(research_runs_dir())
        done.set()
        return SimpleNamespace(run_card=SimpleNamespace(run_id="run-1"))

    monkeypatch.setattr(mod, "run_research_backtest", fake_backtest)
    monkeypatch.setattr("src.strategy.get", lambda _slug: SimpleNamespace(backtest_config={}))
    router = mod.build_research_backtest_router(
        write_dependency=lambda: None,
        market_store_factory=lambda _db: nullcontext(None),
    )
    submit = _endpoint(router, "/api/research/backtest-jobs")

    with tenant_scope("u_b"):
        submit(request=_backtest_request(), _write=None)

    assert done.wait(30), "回测任务没有在池子里跑起来"
    assert seen["tenant"] == "u_b"
    assert "u_b" in seen["runs_dir"], f"线程内解析的研究目录不属于发起租户：{seen}"
