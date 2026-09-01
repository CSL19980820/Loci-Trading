"""盘中留存带：采集编排。

只做三件事：**决定今天采什么**、**逐个采集并落盘**、**如实回报每一项的成败**。
具体怎么加密、怎么分目录在 infrastructure；具体怎么取数在各自的 fetcher。

## 为什么每项都必须 fail-soft

一轮采集有六七个上游，任何一个改版/限流都不该让整轮丢掉。所以单项失败只记进
``failures``，其余照常落盘。但**空表不算成功**——上游返回空和「今天真的没有涨停股」
在下游是同一个形状，必须在这里就分开（`AkShare` 的涨停池越界时就是静默返空表）。

## 采什么

按 `docs/research/2026-08-mainstream-quant-benchmark.md` §7.1 的价值/代价排序，
第一梯队是「不存 = 该类策略永久不可回测」的那批。默认清单只放**全市场单次调用**
的接口（一次覆盖全市场，不逐票循环），配额友好。
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from src.market.infrastructure.intraday_archive import (
    IntradayArchiveError,
    describe,
    intraday_root,
    write_snapshot,
)
from src.market.infrastructure.intraday_keyring import KeyMaterial, load_or_create_key

#: 一个采集源：``name`` 决定落盘文件名，``fetch`` 返回上游原始 DataFrame。
Fetcher = Callable[[], Any]


@dataclass(frozen=True)
class CaptureSpec:
    """一条采集定义。``phase`` 只是给调度用的标签，本模块不解释它。"""

    dataset: str
    source: str
    fetch: Fetcher
    phase: str = "close"
    note: str = ""


@dataclass
class CaptureReport:
    trade_date: str
    captured: list[dict[str, Any]] = field(default_factory=list)
    failures: list[dict[str, str]] = field(default_factory=list)
    protection: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.captured) and not self.failures

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "loci-intraday-capture-v1",
            "trade_date": self.trade_date,
            "protection": self.protection,
            "captured": list(self.captured),
            "captured_count": len(self.captured),
            "failures": list(self.failures),
            "failure_count": len(self.failures),
        }


def capture_snapshots(
    data_dir: Path | str,
    specs: list[CaptureSpec],
    *,
    trade_date: str | None = None,
    key: KeyMaterial | None = None,
) -> CaptureReport:
    """按 ``specs`` 逐个采集并落盘。单项失败不影响其余项。"""
    day = trade_date or date.today().isoformat()
    material = key or load_or_create_key(intraday_root(data_dir))
    report = CaptureReport(trade_date=day, protection=material.protection)
    for spec in specs:
        try:
            frame = spec.fetch()
        except Exception as exc:
            report.failures.append(
                {"dataset": spec.dataset, "stage": "fetch", "error": f"{type(exc).__name__}: {exc}"}
            )
            continue
        try:
            record = write_snapshot(
                data_dir,
                trade_date=day,
                dataset=spec.dataset,
                frame=frame,
                source=spec.source,
                key=material,
            )
        except IntradayArchiveError as exc:
            report.failures.append({"dataset": spec.dataset, "stage": "write", "error": str(exc)})
            continue
        report.captured.append(record.to_dict())
    return report


#: 上游抖动重试次数。AkShare 打的是公开网页接口，`RemoteDisconnected` 是常态而不是
#: 异常；不重试会让一整天的快照因为一次 TCP 断开而永久缺失。
FETCH_ATTEMPTS = 3

#: 重试间隔（秒）。递增，不做指数退避——全市场单次调用本来就只有几个。
RETRY_BACKOFF_SEC = 1.5


def _akshare_call(name: str, **kwargs: Any) -> Any:
    """按名字调 AkShare 的全市场接口。名字写死在本模块，不接受外部输入。"""
    import time

    import akshare

    func = getattr(akshare, name, None)
    if func is None:
        raise RuntimeError(f"本机 akshare 没有 {name}（上游删接口不写 changelog，需要核对版本）")
    last: Exception | None = None
    for attempt in range(FETCH_ATTEMPTS):
        try:
            return func(**kwargs)
        except Exception as exc:  # 上游什么都可能抛，这里只负责重试与如实上报
            last = exc
            if attempt + 1 < FETCH_ATTEMPTS:
                time.sleep(RETRY_BACKOFF_SEC * (attempt + 1))
    raise RuntimeError(f"{name} 重试 {FETCH_ATTEMPTS} 次仍失败：{type(last).__name__}: {last}")


def _fetch_spot() -> Any:
    """全市场现价截面：先要东财原表（列最全），失败再退到本仓多源路由。

    东财 `stock_zh_a_spot_em` 的 23 列（量比/涨速/5 分钟涨跌/振幅/换手/双市值）是
    日 K 还原不出来的，所以优先。但它实测会整段 `RemoteDisconnected`，而本仓的
    `fetch_spot_routed` 有 sina/tencent/eastmoney 三源竞速与直连回退——**宁可列少，
    也不要今天这一格是空的**：这份数据明天补不回来。
    """
    try:
        return _akshare_call("stock_zh_a_spot_em")
    except Exception:
        from src.market.infrastructure.adapters.router import fetch_spot_routed
        from src.market.infrastructure.store import MarketStore

        store = MarketStore()
        try:
            codes = [
                str(row[0])
                for row in store.conn.execute(
                    "SELECT code FROM instruments"
                    " WHERE instrument_type = 'STOCK'"
                    " AND COALESCE(status, '') <> 'delisted'"
                    " ORDER BY code"
                )
            ]
        finally:
            store.close()
        if not codes:
            raise
        frame, _source = fetch_spot_routed(codes)
        return frame


def default_specs() -> list[CaptureSpec]:
    """默认采集清单：全部是**全市场单次调用**，不逐票循环。

    排序即价值序（ADR-014 §2）。涨停池那批官方只承诺「近期数据」，越界时上游
    ``data`` 为 ``None`` 而 akshare 静默返回空表——`write_snapshot` 会因空表报错，
 于是它会落进 ``failures`` 而不是伪装成「今天没有涨停股」。
    """
    return [
        CaptureSpec(
            dataset="limit_up_pool",
            source="akshare:stock_zt_pool_em",
            fetch=lambda: _akshare_call("stock_zt_pool_em", date=_ak_date()),
            phase="close",
            note="涨停池：连板梯队与封板资金，日 K 里没有",
        ),
        CaptureSpec(
            dataset="broken_limit_up_pool",
            source="akshare:stock_zt_pool_zbgc_em",
            fetch=lambda: _akshare_call("stock_zt_pool_zbgc_em", date=_ak_date()),
            phase="close",
            note="炸板池：首封时间与炸板次数",
        ),
        CaptureSpec(
            dataset="spot_close",
            source="akshare:stock_zh_a_spot_em|fallback:fetch_spot_routed",
            fetch=_fetch_spot,
            phase="close",
            note="全市场 23 列截面：量比/涨速/振幅/换手/双市值",
        ),
        CaptureSpec(
            dataset="sector_fund_flow_rank",
            source="akshare:stock_sector_fund_flow_rank",
            fetch=lambda: _akshare_call("stock_sector_fund_flow_rank"),
            phase="close",
            note="板块资金流排名：横截面排名只有当下",
        ),
        CaptureSpec(
            dataset="stock_comment",
            source="akshare:stock_comment_em",
            fetch=lambda: _akshare_call("stock_comment_em"),
            phase="close",
            note="千股千评：机构参与度/综合得分/主力成本，东财不提供历史",
        ),
        CaptureSpec(
            dataset="hot_rank",
            source="akshare:stock_hot_rank_em",
            fetch=lambda: _akshare_call("stock_hot_rank_em"),
            phase="close",
            note="人气榜：官方逐字「当前交易日」",
        ),
    ]


def _ak_date() -> str:
    """AkShare 涨停池要 ``YYYYMMDD``。"""
    return date.today().strftime("%Y%m%d")


def intraday_status(data_dir: Path | str) -> dict[str, Any]:
    """留存带现状 + 本机加密能力，供 CLI / 运维页展示。"""
    from src.market.infrastructure.intraday_keyring import dpapi_available

    body = dict(describe(data_dir))
    body["dpapi_available"] = dpapi_available()
    return body


__all__ = [
    "CaptureReport",
    "CaptureSpec",
    "capture_snapshots",
    "default_specs",
    "intraday_status",
]
