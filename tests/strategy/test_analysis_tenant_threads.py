"""即时分析（横向对比 / 退出扫描）的后台线程必须写**发起租户**的运维库。

run 行是在请求线程里用发起用户的 ops.db 建的；worker 若掉回主租户，收口写入会
落进管理员的 ``job_runs``，发起人那边只看到一条永远停在 running 的 run。
"""
from __future__ import annotations

import threading
from typing import Any

from src.shared.paths import ops_db
from src.shared.tenancy import current_tenant, tenant_scope
from src.strategy.api.router import build_strategy_router
from src.strategy.api.schemas import AnalysisRequest


def _endpoint(router: Any, path: str) -> Any:
    for route in router.routes:
        if getattr(route, "path", "") == path:
            return route.endpoint
    raise AssertionError(f"路由未注册：{path}")


def test_instant_analysis_thread_writes_the_caller_tenant_ops_db(monkeypatch) -> None:
    import src.ops as ops_pkg

    seen: dict[str, str] = {}
    done = threading.Event()

    def fake_run_job(store: Any, _job: Any, **_kwargs: Any) -> dict[str, Any]:
        seen["tenant"] = current_tenant()
        seen["ops_db"] = str(ops_db())
        seen["store_db"] = str(store.db_path)
        done.set()
        return {"status": "ok"}

    monkeypatch.setattr(ops_pkg, "run_job", fake_run_job)

    router = build_strategy_router(
        write_dependency=lambda: None,
        market_db=None,
        ops_db=None,
        palace_db=None,
    )
    start = _endpoint(router, "/api/analysis/{kind}")

    with tenant_scope("u_b"):
        start(kind="compare", payload=AnalysisRequest(), _write=None)

    assert done.wait(30), "后台分析没有跑起来"
    assert seen["tenant"] == "u_b"
    assert "u_b" in seen["ops_db"], f"线程内解析的 ops.db 不属于发起租户：{seen}"
    assert "u_b" in seen["store_db"], f"worker 自建的连接开在别人的库上：{seen}"
