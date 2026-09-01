"""即时选股（异步）HTTP：进度轮询 / 启动 / 取消三个端点。

同步的 `POST /api/strategies/screen` 留在 `router.py`——那是一次请求跑完一天的
选股；本模块这三个端点是**同一批后台任务的三个面**：起（202 受理）、看（轮询
快照）、停（202 受理，协作式取消）。它们共享同一套进度槽语义，改任何一个都要
同时想另外两个，所以放在一起。

**进度槽按「租户 × 战法」分片**（`application/screen_run_state.py`）：一个人可以
同时跑潜龙、三源、杨氏，各有独立进度与取消旗。因此这三个端点都以 `strategy`
为轴：

- `GET /api/screen/run` 不带参 → 聚合快照（顶层兼容老单槽形状 + `runs` 字典）；
带 `?strategy=` → 只要那一个战法的槽。
- `POST /api/screen/run` → 返回**这个战法**的槽快照；被占用时快照里带
`busy_reason`（`same_strategy` / `tenant_limit`）。
- `POST /api/screen/run/cancel?strategy=` → 只停这一个；省略 `strategy` 才停全部
（老客户端语义，那时一个租户最多只有一个在跑）。

`effective_screen_universe` 不在这里：它同时被同步选股消费，拆成两份必然漂移，
已提到同目录 `screen_universe.py`。

本模块**保留** `from __future__ import annotations`。community 的两个 router 刻意
不用它，是因为那边工厂内写了 `Annotated[..., Depends(...)]`，必须在 `def` 求值时
拿到实体对象；strategy 一律用 `_write: None = write_guard` 默认参数风格，与延迟
注解不冲突——照搬即可，不要顺手改成 Annotated。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from src.shared.api_deps import market_store
from src.shared.paths import market_hot_db
from src.strategy.api.schemas import ScreenRequest
from src.strategy.api.screen_universe import effective_screen_universe


def build_screen_run_router(
    *,
    write_dependency,
    market_db: str | None = None,
    ops_db: str | None = None,
    palace_db: str | None = None,
) -> APIRouter:
    router = APIRouter()
    write_guard = Depends(write_dependency)

    def _market():
        return market_store(market_db)

    @router.get("/api/screen/run", tags=["strategy"])
    def screen_run_status(
        strategy: str = Query(
            "",
            max_length=64,
            description="只看这一个战法的槽；省略则返回聚合快照（含 runs 字典）",
        ),
    ) -> dict[str, Any]:
        """即时选股进度（轮询）。

        不带参数返回**聚合**快照：顶层平铺「当前这一个」（老前端照旧能读），
        `runs` 是本租户每个战法各自的槽，`running_strategies` 是正在跑的 slug 列表。
        前端只需要一条轮询就能画出多条并行进度，不必按战法各开一条。
        """
        from src.strategy.application.screen_run import (
            screen_run_snapshot,
            screen_run_snapshot_all,
        )

        slug = str(strategy or "").strip()
        if slug:
            return screen_run_snapshot(slug)
        return screen_run_snapshot_all()

    @router.post("/api/screen/run", tags=["strategy"], status_code=202)
    def screen_run_start(payload: ScreenRequest, _write: None = write_guard) -> dict[str, Any]:
        """后台选股：带阶段进度与日志；默认写入候选池。

        返回**这个战法**的槽快照。占不到槽时快照里带 `busy_reason`：
        `same_strategy`（它自己还在跑，防重复入库）或 `tenant_limit`（本租户并发
        到顶）。别的战法在跑**不**算占用——多槽之后没有「全局单槽」这回事了。
        """
        from src.strategy.application.screen_run import start_screen_run_thread

        opts = payload.model_dump()
        opts["universe"] = effective_screen_universe(
            payload.strategy, payload.universe, ops_db=ops_db
        )
        return start_screen_run_thread(
            opts,
            market_factory=_market,
            palace_db=palace_db,
            hot_db=str(market_hot_db()),
        )

    @router.post("/api/screen/run/cancel", tags=["strategy"], status_code=202)
    def screen_run_cancel(
        strategy: str = Query(
            "",
            max_length=64,
            description="只停这一个战法；省略则停掉本租户全部在跑的选股",
        ),
        _write: None = write_guard,
    ) -> dict[str, Any]:
        """请求停止**本租户**的选股。202 而不是 200：这是受理，不是完成。

        `strategy` 必须点名，否则停的是**全部**在跑的战法——多槽之后这是个真会
        伤人的默认值（用户在潜龙的进度条上点停止，三源、杨氏一起没了）。保留
        「省略 = 全停」只为兼容老客户端：那时一个租户最多只有一个在跑。

        取消是协作式的——选股主体是一段同步的 pandas 面板计算，线程杀不得也
        打不断，只能在交易日循环头的检查点上退出。所以本接口只立旗，终态要
        靠 `GET /api/screen/run` 轮询到 `status='cancelled'` 才算数。

        没有在跑的任务返回 `cancelled: false` 而不是 404：用户连点两次停止，
        第二次什么都不该发生，更不该弹一个红条。
        """
        from src.strategy.application.screen_run import screen_run_request_cancel

        slug = str(strategy or "").strip()
        return screen_run_request_cancel(slug or None)

    return router
