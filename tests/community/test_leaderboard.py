"""榜单用例单测：重算、快照替换、门槛过滤、订阅信号联动。"""

from __future__ import annotations

import pytest

from src.community import CommunityStore
from src.community.application import leaderboard, publishing, subscribe
from src.community.domain.models import Actor, PermissionDeniedError, ValidationError
from src.community.domain.scoring import compute_score
from tests.community.conftest import valid_payload

AS_OF = "2026-08-27"


def _publish(store: CommunityStore, actor: Actor, title: str) -> str:
    result = publishing.publish_strategy(
        store, actor=actor, payload=valid_payload(title=title, slug=title)
    )
    return str(result["strategy"]["publish_id"])


def test_record_metrics_computes_score_server_side(
    store: CommunityStore, author: Actor, published: dict
) -> None:
    """``score`` 由服务端按统一公式现算，调用方递什么都不算数。"""
    publish_id = str(published["strategy"]["publish_id"])
    row = leaderboard.record_metrics(
        store,
        publish_id,
        actor=author,
        as_of=AS_OF,
        sharpe_1y=2.0,
        live_days=182,
        trades=40,
        annual_return=33.0,
    )
    assert row["score"] == compute_score(2.0, 182)
    assert row["as_of_date"] == AS_OF
    assert store.latest_metrics(publish_id)["score"] == row["score"]


def test_record_metrics_requires_ownership(
    store: CommunityStore, reader: Actor, published: dict
) -> None:
    with pytest.raises(PermissionDeniedError):
        leaderboard.record_metrics(
            store, str(published["strategy"]["publish_id"]), actor=reader, sharpe_1y=1.0
        )


def test_rebuild_writes_a_snapshot_and_read_returns_it(
    store: CommunityStore, author: Actor
) -> None:
    strong = _publish(store, author, "strong")
    weak = _publish(store, author, "weak")
    leaderboard.record_metrics(store, strong, as_of=AS_OF, sharpe_1y=2.5, live_days=400, trades=60)
    leaderboard.record_metrics(store, weak, as_of=AS_OF, sharpe_1y=0.6, live_days=400, trades=60)
    result = leaderboard.rebuild_leaderboard(store, as_of=AS_OF, board="overall")
    assert result["written"] == 2
    assert [item["publish_id"] for item in result["entries"]] == [strong, weak]
    board = leaderboard.read_board(store, board="overall")
    assert board["as_of_date"] == AS_OF
    assert [item["rank"] for item in board["entries"]] == [1, 2]
    # 快照带上展示需要的标题，前端不用再挨个查详情
    assert board["entries"][0]["title"] == "strong"
    assert board["entries"][0]["score"] == compute_score(2.5, 400)


def test_rebuild_replaces_rather_than_appends(store: CommunityStore, author: Actor) -> None:
    publish_id = _publish(store, author, "solo")
    leaderboard.record_metrics(
        store, publish_id, as_of=AS_OF, sharpe_1y=1.0, live_days=400, trades=40
    )
    leaderboard.rebuild_leaderboard(store, as_of=AS_OF, board="overall")
    leaderboard.rebuild_leaderboard(store, as_of=AS_OF, board="overall")
    assert store.stats()["leaderboard_snapshots"] == 1


def test_rebuild_defaults_to_latest_metrics_date(store: CommunityStore, author: Actor) -> None:
    """盘后任务凌晨才跑也不该算出一张空榜。"""
    publish_id = _publish(store, author, "solo")
    leaderboard.record_metrics(
        store, publish_id, as_of="2026-08-20", sharpe_1y=1.0, live_days=400, trades=40
    )
    result = leaderboard.rebuild_leaderboard(store)
    assert result["as_of_date"] == "2026-08-20"
    assert result["written"] == 1


def test_thresholds_keep_noise_off_the_board(store: CommunityStore, author: Actor) -> None:
    thin = _publish(store, author, "thin")
    fresh = _publish(store, author, "fresh")
    veteran = _publish(store, author, "veteran")
    leaderboard.record_metrics(store, thin, as_of=AS_OF, sharpe_1y=9.0, live_days=400, trades=5)
    leaderboard.record_metrics(
        store, fresh, as_of=AS_OF, sharpe_1y=3.0, live_days=20, trades=40, annual_return=500.0
    )
    leaderboard.record_metrics(
        store, veteran, as_of=AS_OF, sharpe_1y=1.4, live_days=500, trades=90, annual_return=28.0
    )
    overall = leaderboard.rebuild_leaderboard(store, as_of=AS_OF, board="overall")["entries"]
    assert thin not in [item["publish_id"] for item in overall]
    # 年化榜是唯一看裸收益的榜，门槛最高：跑了 20 天的 +500% 进不去
    annual = leaderboard.rebuild_leaderboard(store, as_of=AS_OF, board="return")["entries"]
    assert [item["publish_id"] for item in annual] == [veteran]
    rookie = leaderboard.rebuild_leaderboard(store, as_of=AS_OF, board="rookie")["entries"]
    assert [item["publish_id"] for item in rookie] == [fresh]


def test_delisted_strategies_drop_off_the_board(store: CommunityStore, author: Actor) -> None:
    publish_id = _publish(store, author, "gone")
    leaderboard.record_metrics(
        store, publish_id, as_of=AS_OF, sharpe_1y=2.0, live_days=400, trades=40
    )
    assert leaderboard.rebuild_leaderboard(store, as_of=AS_OF)["written"] == 1
    publishing.delist_strategy(store, publish_id, actor=author)
    assert leaderboard.rebuild_leaderboard(store, as_of=AS_OF)["written"] == 0


def test_rebuild_all_covers_every_board(store: CommunityStore, author: Actor) -> None:
    publish_id = _publish(store, author, "solo")
    leaderboard.record_metrics(
        store, publish_id, as_of=AS_OF, sharpe_1y=1.2, live_days=400, trades=40
    )
    boards = {item["board"] for item in leaderboard.rebuild_all(store, as_of=AS_OF)}
    assert boards == {"overall", "sharpe", "return", "rookie"}
    assert leaderboard.read_board(store, board="sharpe")["entries"]


def test_unknown_board_is_rejected(store: CommunityStore) -> None:
    with pytest.raises(ValidationError):
        leaderboard.rebuild_leaderboard(store, board="收益榜")
    with pytest.raises(ValidationError):
        leaderboard.read_board(store, board="收益榜")


def test_empty_board_reads_as_empty(store: CommunityStore) -> None:
    assert leaderboard.read_board(store, board="overall")["entries"] == []


def test_board_catalog_explains_the_gates() -> None:
    catalog = {item["board"]: item for item in leaderboard.board_catalog()}
    assert catalog["return"]["min_live_days"] == 365
    assert catalog["rookie"]["max_live_days"] == 365
    assert leaderboard.preview_score(2.0, 365)["score"] == 2.0


def test_snapshots_keep_the_sort_key(store: CommunityStore, author: Actor) -> None:
    """副榜的排序键值要落库：``sort_value`` 缺了，前端只能从 metrics 里反推名次怎么来的。"""
    strong = _publish(store, author, "sharp")
    weak = _publish(store, author, "blunt")
    leaderboard.record_metrics(
        store, strong, as_of=AS_OF, sharpe_1y=2.4, annual_return=30.0, live_days=400, trades=60
    )
    leaderboard.record_metrics(
        store, weak, as_of=AS_OF, sharpe_1y=0.9, annual_return=12.0, live_days=400, trades=60
    )
    leaderboard.rebuild_all(store, as_of=AS_OF)
    sharpe = store.read_leaderboard(board="sharpe", as_of_date=AS_OF)
    assert [row["publish_id"] for row in sharpe] == [strong, weak]
    assert sharpe[0]["sort_value"] == pytest.approx(2.4)  # 夏普榜排的是夏普
    annual = store.read_leaderboard(board="return", as_of_date=AS_OF)
    assert annual[0]["sort_value"] == pytest.approx(30.0)  # 年化榜排的是年化
    overall = store.read_leaderboard(board="overall", as_of_date=AS_OF)
    assert overall[0]["sort_value"] == pytest.approx(overall[0]["score"])  # 主榜两者同值


def test_schema_migration_is_idempotent(store: CommunityStore, author: Actor) -> None:
    """迁移每次连接都无条件重跑：跑第二遍不能炸，也不能把数据冲掉。"""
    from src.community.infrastructure.schema import apply_schema

    publish_id = _publish(store, author, "solo")
    leaderboard.record_metrics(
        store, publish_id, as_of=AS_OF, sharpe_1y=1.0, live_days=400, trades=40
    )
    leaderboard.rebuild_leaderboard(store, as_of=AS_OF)
    apply_schema(store.conn)
    apply_schema(store.conn)
    assert store.stats()["leaderboard_snapshots"] == 1
    assert store.read_leaderboard(board="overall", as_of_date=AS_OF)[0]["sort_value"] is not None


def test_metrics_write_normalizes_the_equity_curve(
    store: CommunityStore, author: Actor, published: dict
) -> None:
    """净值曲线契约：落库只有 ``equity_curve``，起点归一到 1.0。"""
    publish_id = str(published["strategy"]["publish_id"])
    row = leaderboard.record_metrics(
        store,
        publish_id,
        actor=author,
        as_of=AS_OF,
        sharpe_1y=1.0,
        live_days=400,
        trades=40,
        metrics={"curve": [{"date": "2024-01-02", "value": 50000}, ["20240103", 55000]]},
    )
    assert row["metrics"]["equity_curve"] == [
        {"d": "2024-01-02", "v": 1.0},
        {"d": "2024-01-03", "v": 1.1},
    ]
    assert "curve" not in row["metrics"]
def test_subscribers_pull_the_authors_daily_signals(
    store: CommunityStore, author: Actor, reader: Actor, published: dict
) -> None:
    """跟单只走「拉信号」这一条路：社区不下单、不写订阅者的账本。"""
    publish_id = str(published["strategy"]["publish_id"])
    sub = subscribe.subscribe(store, publish_id, actor=reader)
    assert sub["mode"] == "signal_only"
    assert sub["notice"] == "只推信号，不自动下单"
    subscribe.publish_signals(
        store,
        publish_id,
        actor=author,
        trade_date=AS_OF,
        payload={"codes": ["600519"], "note": "尾盘扫"},
    )
    pulled = subscribe.pull_signals(store, actor=reader)
    assert pulled["subscriptions"] == 1
    assert pulled["items"][0]["payload"]["codes"] == ["600519"]
    assert pulled["items"][0]["payload"]["entry_timing"] == "next_open"
    assert "不自动下单" in pulled["notice"]
    # 只有作者能发信号
    with pytest.raises(PermissionDeniedError):
        subscribe.publish_signals(store, publish_id, actor=reader, payload={"codes": []})
    assert subscribe.unsubscribe(store, publish_id, actor=reader)["changed"] is True
    assert subscribe.pull_signals(store, actor=reader)["items"] == []
