"""失败结果必须进缓存，缓存 key 必须能跨入口复用。

两条都是花钱的问题：

- 业务错误（「今日无数据」）是**照扣配额**的。失败不落缓存 = 每一次重试都真调
  一次、真扣一次额。
- 同一工具同一交易日被四个入口用四份 limit 各写一行，谁也复用不了谁，等于缓存
  对这个工具没生效。

**本文件不发任何真实 MCP 调用**：client 全部是计数用的假实现，配额记账也只往
列表里追加。配额是花钱的，测试不许碰。
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

from src.intel.application.fetch import call_mcp_tool
from src.intel.infrastructure.intel_cache import (
    _args_hash,
    cache_identity_key,
    coverage_covers,
    read_cached_error,
    read_cached_snapshot,
)
from src.market import MarketStore

TRADE_DATE = "2026-08-07"
TOOL = "theme_intraday_capital"

#: 实测出来的四个入口（扫描报告里的 open80 / intraday60 / close100 / tape20）。
#: 前三个来自 ``intel/application/daily_recipe.py`` 的三档配方，第四个来自
#: ``market/infrastructure/tape/wudao_provider.wudao_tool_arguments``。
ENTRYPOINTS: dict[str, dict[str, Any]] = {
    "open": {"limit": 80, "includeBoomReason": True, "tradeDate": TRADE_DATE},
    "intraday": {"limit": 60, "includeBoomReason": True, "tradeDate": TRADE_DATE},
    "close": {"limit": 100, "includeBoomReason": True, "tradeDate": TRADE_DATE},
    "tape": {
        "limit": 20,
        "tradeDate": TRADE_DATE,
        "format": "json",
        "detailLevel": "standard",
    },
}


class _CountingClient:
    """假 MCP client：只计数、只回预设结果，永远不出网。"""

    def __init__(self, results: list[dict[str, Any]]) -> None:
        self.results = list(results)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def call_tool(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((tool, dict(arguments)))
        if len(self.results) > 1:
            return self.results.pop(0)
        return self.results[0]


@contextmanager
def _wired(client: _CountingClient, charges: list[str]):
    """把 call_mcp_tool 的外部依赖全换成假的。

    ``_settled_at`` 钉成「盘中」：冷却档位和 TTL 都不该跟着测试机的钟点变。
    """
    targets = {
        "src.intel.application.fetch.McpClient": _CountingClient,
        "src.intel.infrastructure.registry.build_client": lambda _server: client,
        "src.intel.application.fetch.is_resident_wudao_server": lambda _server: False,
        "src.intel.application.fetch.acquire_quota": lambda _pool: None,
        "src.intel.application.fetch.record_quota_call": charges.append,
        "src.intel.application.fetch.quota_snapshot": dict,
        "src.intel.application.fetch.trade_date_today": lambda: TRADE_DATE,
        "src.intel.application.fetch._settled_at": lambda *_a, **_k: False,
    }
    stack = [patch(target, value) for target, value in targets.items()]
    for item in stack:
        item.start()
    try:
        yield
    finally:
        for item in reversed(stack):
            item.stop()


def _age_rows(store: MarketStore, minutes: float) -> None:
    """把整表的 fetched_at 往前推，模拟时间流逝（不 sleep）。"""
    stamp = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat(
        timespec="seconds"
    )
    store.conn.execute("UPDATE intel_snapshots SET fetched_at = ?", (stamp,))
    store.conn.commit()


def _call(store: MarketStore, arguments: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return call_mcp_tool(
        TOOL,
        dict(arguments),
        server="other",
        cache=True,
        market_store=store,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# 问题 1：负缓存
# ---------------------------------------------------------------------------


def test_a_business_error_is_cached_so_retries_stop_calling_and_charging(
    tmp_path: Path,
) -> None:
    """失败一次后，冷却期内不再真调、也不再扣额。

    这是本轮要修的主症状：``fetch.py`` 原来只在成功时写缓存，而业务错误是**照扣**
    配额的（服务端真检索过）。于是「今日无数据」这种失败每重试一次就真调一次、
    真扣一次额。
    """
    store = MarketStore(tmp_path / "market.db")
    client = _CountingClient([{"text": "今日无数据", "is_error": True}])
    charges: list[str] = []
    try:
        with _wired(client, charges):
            first = _call(store, ENTRYPOINTS["intraday"])
            second = _call(store, ENTRYPOINTS["intraday"])
            third = _call(store, ENTRYPOINTS["intraday"])
    finally:
        store.close()

    # 第一次：真调、照扣（业务错误在供应商那边真算了一次）。
    assert first["is_error"] is True
    assert first["quota_charged"] is True
    assert first["cached"] is False

    # 之后两次：一次都没再出网，一次额都没再扣。
    assert len(client.calls) == 1, "冷却期内不该再发真实调用"
    assert charges == ["skill"], "冷却期内不该再扣配额"

    # 兑现的仍然是一份失败，不是把错误洗成空数据。
    for payload in (second, third):
        assert payload["is_error"] is True
        assert payload["cached"] is True
        assert payload["error_cached"] is True
        assert payload["quota_charged"] is False
        assert payload["retry_after_minutes"] > 0


def test_the_cooldown_expires_and_the_next_call_goes_out_again(tmp_path: Path) -> None:
    """冷却是冷却，不是永久拉黑：过期后必须回源，否则当天再也拿不到数据。"""
    store = MarketStore(tmp_path / "market.db")
    client = _CountingClient([
        {"text": "今日无数据", "is_error": True},
        {"text": '{"rows": [1, 2]}', "is_error": False},
    ])
    charges: list[str] = []
    try:
        with _wired(client, charges):
            _call(store, ENTRYPOINTS["intraday"])
            _age_rows(store, 6.0)  # 盘中业务错误冷却是 5 分钟
            after = _call(store, ENTRYPOINTS["intraday"])
        still_cooling = read_cached_error(
            store,
            trade_date=TRADE_DATE,
            tool=TOOL,
            arguments=ENTRYPOINTS["intraday"],
        )
    finally:
        store.close()

    assert len(client.calls) == 2, "冷却过期后必须回源"
    assert after["is_error"] is False
    assert still_cooling is None, "成功之后要立刻解除冷却，不留惩罚期"


def test_a_rejected_argument_cools_down_without_ever_charging(tmp_path: Path) -> None:
    """参数被服务端直接拒：本来就不扣额，但同样不该每轮重试都白跑一次建连。

    这一档给的冷却更长（60 分钟）——同一份参数必然再被拒，与「数据还没出来」无关。
    """
    store = MarketStore(tmp_path / "market.db")
    client = _CountingClient([
        {"text": "INVALID_ARGUMENTS: unrecognized key 'foo'", "is_error": True},
    ])
    charges: list[str] = []
    try:
        with _wired(client, charges):
            first = _call(store, ENTRYPOINTS["intraday"])
            second = _call(store, ENTRYPOINTS["intraday"])
        _age_rows(store, 30.0)
        with _wired(client, charges):
            half_hour_later = _call(store, ENTRYPOINTS["intraday"])
    finally:
        store.close()

    assert first["quota_charged"] is False, "没执行的调用不该记账"
    assert charges == [], "参数被拒从头到尾都不扣额"
    assert len(client.calls) == 1
    assert second["error_cached"] is True
    assert half_hour_later["error_cached"] is True, "参数被拒的冷却是 60 分钟"


def test_a_failure_never_evicts_a_still_usable_success(tmp_path: Path) -> None:
    """负缓存走独立 key 命名空间：一次失败不该顶掉上午那份还能用的快照。"""
    store = MarketStore(tmp_path / "market.db")
    client = _CountingClient([
        {"text": '{"rows": [1, 2, 3]}', "is_error": False},
        {"text": "服务端开小差", "is_error": True},
    ])
    charges: list[str] = []
    try:
        with _wired(client, charges):
            good = _call(store, ENTRYPOINTS["intraday"])
            # 把成功那行推到 TTL 之外，逼出一次回源——这次回源失败。
            _age_rows(store, 20.0)
            bad = _call(store, ENTRYPOINTS["intraday"], cache_max_age_minutes=5)
        survivor = read_cached_snapshot(
            store,
            trade_date=TRADE_DATE,
            tool=TOOL,
            arguments=ENTRYPOINTS["intraday"],
        )
        cooling = read_cached_error(
            store,
            trade_date=TRADE_DATE,
            tool=TOOL,
            arguments=ENTRYPOINTS["intraday"],
        )
    finally:
        store.close()

    assert good["is_error"] is False
    assert bad["is_error"] is True
    assert survivor is not None, "成功快照被失败顶掉了"
    assert survivor["is_error"] is False
    assert cooling is not None and cooling["is_error"] is True


def test_cache_false_is_the_escape_hatch(tmp_path: Path) -> None:
    """显式关掉缓存的调用永远重试：别把冷却做成没有逃生口的拉黑。"""
    store = MarketStore(tmp_path / "market.db")
    client = _CountingClient([{"text": "今日无数据", "is_error": True}])
    charges: list[str] = []
    try:
        with _wired(client, charges):
            _call(store, ENTRYPOINTS["intraday"])
            call_mcp_tool(
                TOOL,
                dict(ENTRYPOINTS["intraday"]),
                server="other",
                cache=False,
                market_store=store,
            )
    finally:
        store.close()

    assert len(client.calls) == 2


# ---------------------------------------------------------------------------
# 问题 3：缓存 key 碎片化
# ---------------------------------------------------------------------------


def test_four_entrypoints_of_one_tool_share_one_reuse_key() -> None:
    """同工具、同交易日、不同入口 → 同一个复用 key。

    实测 ``theme_intraday_capital`` 一天产生 4 个互不复用的 key，差异全在
    「回多少行 / 回多细」这类参数上（limit 80/60/100/20、format、detailLevel）。
    这些不改变「这是哪一天哪个工具的什么事实」，所以不进身份 key。
    """
    identities = {
        name: cache_identity_key(TOOL, args) for name, args in ENTRYPOINTS.items()
    }
    assert len(set(identities.values())) == 1, identities

    # 同时钉住「碎片是真实存在的」：存储 key 仍然一变体一行（见 intel_cache
    # 模块头第 2 条——合并存储会让宽窄入口互相顶掉对方的缓存）。
    storage = {name: _args_hash(TOOL, args) for name, args in ENTRYPOINTS.items()}
    assert len(set(storage.values())) == 4, storage


def test_date_alias_and_format_spellings_do_not_fragment_the_key() -> None:
    """同一天写成 ``date=20260807`` 还是 ``tradeDate=2026-08-07`` 都是同一份事实。

    键名归一走 ``wudao_keys`` 那张实测过的表，不在缓存层再抄一份。
    """
    assert cache_identity_key(TOOL, {"date": "20260807"}) == cache_identity_key(
        TOOL, {"tradeDate": TRADE_DATE}
    )
    assert cache_identity_key(TOOL, {"tradeDate": TRADE_DATE, "format": "json"}) == (
        cache_identity_key(TOOL, {"tradeDate": TRADE_DATE})
    )

    # 不同交易日当然不能相等——归一不是把日期抹掉。
    assert cache_identity_key(TOOL, {"tradeDate": TRADE_DATE}) != cache_identity_key(
        TOOL, {"tradeDate": "2026-08-08"}
    )


def test_coverage_not_the_key_decides_whether_a_row_can_be_reused() -> None:
    """key 相同只说明「问的是同一份事实」，能不能兑现还要看条数够不够。

    宁可多回几行，也不能把 limit=60 的半张榜当成 limit=100 的全榜发下去。
    """
    assert coverage_covers(ENTRYPOINTS["open"], ENTRYPOINTS["intraday"]) is True
    assert coverage_covers(ENTRYPOINTS["open"], ENTRYPOINTS["tape"]) is True
    assert coverage_covers(ENTRYPOINTS["intraday"], ENTRYPOINTS["close"]) is False
    assert coverage_covers(ENTRYPOINTS["tape"], ENTRYPOINTS["open"]) is False

    # 可选字段：带了的能覆盖没带的，反过来不行。
    rich = {"limit": 50, "includeBoomReason": True}
    plain = {"limit": 50}
    assert coverage_covers(rich, plain) is True
    assert coverage_covers(plain, rich) is False


def test_a_wider_snapshot_is_reused_by_a_narrower_entrypoint(tmp_path: Path) -> None:
    """端到端：open 抓过 limit=80，intraday 的 limit=60 直接兑现，不再真调。

    这才是省配额的地方——key 相等只是手段。
    """
    store = MarketStore(tmp_path / "market.db")
    client = _CountingClient([{"text": '{"rows": [1, 2]}', "is_error": False}])
    charges: list[str] = []
    try:
        with _wired(client, charges):
            opened = _call(store, ENTRYPOINTS["open"])
            intraday = _call(store, ENTRYPOINTS["intraday"])
            tape = _call(store, ENTRYPOINTS["tape"])
            closed = _call(store, ENTRYPOINTS["close"])
    finally:
        store.close()

    assert opened["cached"] is False
    assert intraday["cached"] is True, "limit=80 的快照完全够 limit=60 用"
    assert tape["cached"] is True, "tape 的 limit=20 更够"
    assert intraday["cache_reused_arguments"]["limit"] == 80

    # 收盘要 100 行，80 行盖不住：必须回源，不能拿半张榜冒充全榜。
    assert closed["cached"] is False
    assert len(client.calls) == 2, "四个入口只该真调两次（80 一次、100 一次）"
    assert charges == ["skill", "skill"]


def test_reuse_still_respects_the_ttl(tmp_path: Path) -> None:
    """跨入口复用不是绕过时效：过期的宽快照照样不给用。"""
    store = MarketStore(tmp_path / "market.db")
    client = _CountingClient([{"text": '{"rows": [1]}', "is_error": False}])
    charges: list[str] = []
    try:
        with _wired(client, charges):
            _call(store, ENTRYPOINTS["open"])
            _age_rows(store, 30.0)  # 盘中 TTL 上限是 10 分钟
            intraday = _call(store, ENTRYPOINTS["intraday"])
    finally:
        store.close()

    assert intraday["cached"] is False
    assert len(client.calls) == 2
