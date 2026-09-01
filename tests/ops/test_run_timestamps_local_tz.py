"""运维库时间戳统一到本地时区后的行为锁定（``store_helpers._now()`` 口径）。

背景：``job_runs`` 的写入原先走 SQLite ``datetime('now')``——UTC、秒级。运维页
不做任何时区换算（``JobRecentRunsPanel.vue`` 只把 ``T`` 换成空格再切 19 位），
于是北京时间 15:30 跑的任务在页面上显示 07:30。

但这批时间戳**不只是给人看的**：僵尸任务回收拿 ``heartbeat_at``/``started_at``
跟 ``datetime('now', '-N seconds')`` 比。只把写入改成本地而比较仍用 UTC 基准，
回收窗就凭空多出 8 小时（真死的任务 8 小时没人收尸）；反过来把基准改成本地而
行仍是 UTC，则**刚启动的任务立刻被判死**。所以这里两侧都要有用例压着。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.ops.application.eod_catchup import last_run_covers_slot, slot_for_day
from src.ops.infrastructure.store import OpsStore
from src.ops.infrastructure.store_helpers import _now
from src.ops.infrastructure.store_runs import (
    RUN_CLOCK_SQL,
    RUN_ORDER_SQL,
    RUN_STALE_SQL,
    STALE_RUN_SECONDS_BY_KIND,
)

#: 生产库里 2026-08-25 之前的行长这样：UTC、秒级、空格分隔、无偏移。
LEGACY_FMT = "%Y-%m-%d %H:%M:%S"


def _legacy_utc(moment: datetime) -> str:
    """把一个绝对时刻写成改造前 ``datetime('now')`` 会写出的样子。"""
    return moment.astimezone(timezone.utc).strftime(LEGACY_FMT)


@pytest.fixture()
def store(tmp_path: Path):
    with OpsStore(tmp_path / "ops.db") as opened:
        yield opened


def _job(store: OpsStore, *, name: str = "同步", kind: str = "sync") -> dict:
    return store.get_job(store.create_job(name=name, kind=kind))


# --------------------------------------------------------------------------
# 1. 写入口径：页面上的执行时间必须就是本地（北京）时间
# --------------------------------------------------------------------------


def test_start_run_writes_local_wall_clock(store: OpsStore) -> None:
    """``started_at`` 与本机墙上时间的差必须以分钟计。
    
    修复前：写的是 UTC，东八区下这个差恒为 8 小时（28800s），本条必红。
    """
    run_id = store.start_run(_job(store))
    started = datetime.fromisoformat(store.get_run(run_id)["started_at"])
    assert started.tzinfo is not None, "时间戳必须带偏移，否则读的人只能靠猜"
    drift = abs((started - datetime.now().astimezone()).total_seconds())
    assert drift < 300, f"started_at 与本地时钟相差 {drift:.0f}s：{started}"


def test_run_lifecycle_timestamps_share_one_clock(store: OpsStore) -> None:
    """start / heartbeat / finish / jobs.last_run_at 必须同一口径。
    
    任何一处留在 UTC，跨字段的时间差都会凭空差出 8 小时（``duration_ms`` 是
    另算的，它掩盖不了这个错）。
    """
    job = _job(store)
    run_id = store.start_run(job)
    assert store.heartbeat_run(run_id) is True
    store.finish_run(run_id, status="success", duration_ms=7)
    row = store.get_run(run_id)
    stamps = {
        "started_at": datetime.fromisoformat(row["started_at"]),
        "heartbeat_at": datetime.fromisoformat(row["heartbeat_at"]),
        "finished_at": datetime.fromisoformat(row["finished_at"]),
        "last_run_at": datetime.fromisoformat(store.get_job(job["id"])["last_run_at"]),
    }
    for field, value in stamps.items():
        assert value.tzinfo is not None, f"{field} 没有偏移"
    spread = max(stamps.values()) - min(stamps.values())
    assert spread < timedelta(seconds=60), f"同一次运行的时间戳散开了 {spread}：{stamps}"
    assert stamps["finished_at"] >= stamps["started_at"]


def test_heartbeat_writer_thread_uses_the_same_clock(store: OpsStore, tmp_path: Path) -> None:
    """后台心跳线程走的是另一条连接、另一段 SQL，口径同样不能漂。"""
    run_id = store.start_run(_job(store))
    writer = store.run_heartbeat_writer()
    try:
        assert writer.beat(run_id) is True
    finally:
        writer.close()
    beat = datetime.fromisoformat(store.get_run(run_id)["heartbeat_at"])
    assert abs((beat - datetime.now().astimezone()).total_seconds()) < 300


def test_now_is_parseable_by_sqlite(store: OpsStore) -> None:
    """``julianday(_now())`` 必须解析得出且贴着当前时刻。
    
    整套「新旧格式同轴比较」都架在这上面：一旦 ``_now()`` 写出 SQLite 认不出的
    串（例如带秒的时区偏移），回收判据会退化成 NULL，僵尸任务再也收不掉。
    """
    row = store.conn.execute(
        "SELECT julianday(?) AS ours, julianday('now') AS ref", (_now(),)
    ).fetchone()
    assert row["ours"] is not None, "SQLite 解析不了 _now() 写出的时间戳"
    assert abs(row["ours"] - row["ref"]) * 86400 < 60


# --------------------------------------------------------------------------
# 2. 回收：真超时的收得掉，刚启动的绝不能被误收
# --------------------------------------------------------------------------


def _backdate(store: OpsStore, run_id: str, stamp: str) -> None:
    with store._transaction() as cursor:
        cursor.execute(
            "UPDATE job_runs SET started_at = ?, heartbeat_at = '' WHERE id = ?",
            (stamp, run_id),
        )


def test_reclaims_run_stale_in_new_local_format(store: OpsStore) -> None:
    """本地格式写下的、真的超了 45 分钟的 sync，必须被回收。"""
    job = _job(store)
    run_id = store.start_run(job)
    _backdate(store, run_id, (datetime.now().astimezone() - timedelta(hours=3)).isoformat())
    assert store.reclaim_stale_runs() >= 1
    assert store.get_run(run_id)["status"] == "failed"


def test_reclaims_legacy_utc_run_that_is_truly_stale(store: OpsStore) -> None:
    """历史 UTC 行照样要收：不重写旧数据，不等于放着不管。"""
    job = _job(store)
    run_id = store.start_run(job)
    _backdate(store, run_id, _legacy_utc(datetime.now(timezone.utc) - timedelta(hours=3)))
    assert store.reclaim_stale_runs() >= 1
    assert store.get_run(run_id)["status"] == "failed"


def test_never_reclaims_a_just_started_run(store: OpsStore) -> None:
    """刚启动的 run 绝不能被判死——本次改动最大的风险就在这里。
    
    ``sync`` 的回收窗只有 45 分钟，而 UTC 与本地差 8 小时：一旦比较的两侧口径
    对不上，这条会当场变红（生产表现是任务刚起来就被写成「运行超时，已按中断
    回收」，而进程还在跑）。
    """
    job = _job(store)
    run_id = store.start_run(job)
    assert store.reclaim_stale_runs() == 0
    assert store.get_run(run_id)["status"] == "running"
    # claim_run 里另有一条按 job_id 的回收 SQL，也得放它过去
    again, claimed = store.claim_run(job)
    assert claimed is False and again == run_id
    assert store.get_run(run_id)["status"] == "running"


def test_never_reclaims_a_fresh_legacy_utc_run(store: OpsStore) -> None:
    """刚写下的**旧格式** UTC 行同样不能被收。
    
    这是上一条的镜像：如果把比较基准整个换成本地时间而不做折算，UTC 行看起来
    就「早了 8 小时」，历史行与升级瞬间正在跑的行会被批量错杀。
    """
    job = _job(store)
    run_id = store.start_run(job)
    _backdate(store, run_id, _legacy_utc(datetime.now(timezone.utc)))
    assert store.reclaim_stale_runs() == 0
    assert store.get_run(run_id)["status"] == "running"


def test_stale_window_boundary_holds_for_both_formats(store: OpsStore) -> None:
    """直接压回收判据本身：窗内不收、窗外收，与写法无关。"""
    window = STALE_RUN_SECONDS_BY_KIND["sync"]
    now_local = datetime.now().astimezone()
    cases = {
        "新格式-窗内": ((now_local - timedelta(seconds=window - 120)).isoformat(), False),
        "新格式-窗外": ((now_local - timedelta(seconds=window + 120)).isoformat(), True),
        "旧UTC-窗内": (_legacy_utc(now_local - timedelta(seconds=window - 120)), False),
        "旧UTC-窗外": (_legacy_utc(now_local - timedelta(seconds=window + 120)), True),
    }
    sql = f"SELECT {RUN_STALE_SQL} AS stale"
    for label, (stamp, expected) in cases.items():
        row = store.conn.execute(
            sql.replace(RUN_CLOCK_SQL, "?"), (stamp, f"-{window} seconds")
        ).fetchone()
        assert bool(row["stale"]) is expected, f"{label} 判定错了：{stamp}"


#: 东八区（或任何东侧时区）才谈得上「UTC 与本地差出几个小时」。偏移为 0 的机器上
#: 这两个陷阱退化成不存在，用例没有意义，直接跳过。
_EAST_OF_UTC = (datetime.now().astimezone().utcoffset() or timedelta(0)) >= timedelta(hours=1)


@pytest.mark.skipif(not _EAST_OF_UTC, reason="需要东时区才能复现 UTC/本地混用的时差")
def test_string_comparison_would_miss_a_dead_run(store: OpsStore) -> None:
    """锁死「为什么必须用 julianday」之一：字符串比较会漏收真死掉的任务。
    
    写入换成本地而比较仍用 UTC 基准时，本地串看着永远更晚（连 ``'T' > ' '`` 都在
    帮倒忙），一个已经死了 3 小时的 sync 会被判成「还活着」。谁把 ``RUN_STALE_SQL``
    改回 ``clock < datetime('now', ?)``，这里立刻变红。
    """
    dead = (datetime.now().astimezone() - timedelta(hours=3)).isoformat()
    window = STALE_RUN_SECONDS_BY_KIND["sync"]
    naive = store.conn.execute(
        "SELECT ? < datetime('now', ?) AS stale", (dead, f"-{window} seconds")
    ).fetchone()["stale"]
    assert bool(naive) is False, "字符串比较居然收得掉——这条用例的前提变了，请重写"
    safe = store.conn.execute(
        f"SELECT {RUN_STALE_SQL.replace(RUN_CLOCK_SQL, '?')} AS stale",
        (dead, f"-{window} seconds"),
    ).fetchone()["stale"]
    assert bool(safe) is True, "死了 3 小时的 sync 必须进回收窗"


@pytest.mark.skipif(not _EAST_OF_UTC, reason="需要东时区才能复现 UTC/本地混用的时差")
def test_local_baseline_would_kill_fresh_legacy_rows(store: OpsStore) -> None:
    """镜像陷阱：把基准换成本地钟去比历史 UTC 行，会把刚起来的任务当场判死。
    
    这正是「只改写入不改比较」的反方向事故；两边都得有用例压着。
    """
    fresh_legacy = _legacy_utc(datetime.now(timezone.utc))
    window = STALE_RUN_SECONDS_BY_KIND["sync"]
    wrong = store.conn.execute(
        "SELECT ? < datetime('now', 'localtime', ?) AS stale",
        (fresh_legacy, f"-{window} seconds"),
    ).fetchone()["stale"]
    assert bool(wrong) is True, "本地基准对 UTC 行本应显得超前 8 小时"
    safe = store.conn.execute(
        f"SELECT {RUN_STALE_SQL.replace(RUN_CLOCK_SQL, '?')} AS stale",
        (fresh_legacy, f"-{window} seconds"),
    ).fetchone()["stale"]
    assert bool(safe) is False, "刚写下的历史格式行不能被回收"


def test_legacy_no_pid_row_with_unparseable_clock_is_reclaimed(store: OpsStore) -> None:
    """脏时间戳 + 无 owner_pid 的旧行不能永久占槽。
    
    julianday() 对脏值返回 NULL，时间窗谓词整体为 NULL（既不真也不假），
    这一支专门兜住它们——否则那个任务的槽位会永远显示「正在执行」。
    """
    job = _job(store)
    run_id = store.start_run(job)
    with store._transaction() as cursor:
        cursor.execute(
            "UPDATE job_runs SET owner_pid = 0, started_at = 'not-a-time',"
            " heartbeat_at = '' WHERE id = ?",
            (run_id,),
        )
    assert store.reclaim_stale_runs() >= 1
    assert store.get_run(run_id)["status"] == "failed"
    assert "无进程号" in store.get_run(run_id)["error_text"]


# --------------------------------------------------------------------------
# 3. 新旧混存的排序
# --------------------------------------------------------------------------


def _insert_finished(store: OpsStore, job: dict, *, run_id: str, started: str) -> None:
    with store._transaction() as cursor:
        cursor.execute(
            "INSERT INTO job_runs(id, job_id, job_name, kind, trigger, status,"
            " started_at, owner_pid, idempotency_key, cancel_requested, heartbeat_at)"
            " VALUES(?, ?, ?, ?, 'manual', 'success', ?, 0, '', 0, '')",
            (run_id, job["id"], job["name"], job["kind"], started),
        )


def test_list_runs_orders_mixed_formats_by_real_time(store: OpsStore) -> None:
    """旧 UTC 行与新本地行混在一起时，必须按**绝对时刻**倒序。
    
    按字符串排会错：'T' > ' '，同一天的新行会无条件排到旧行前面。这里的旧行
    （06:00 UTC = 14:00 北京）其实比新行（13:00 北京）更晚，必须排在前面。
    """
    job = _job(store, name="混存")
    _insert_finished(store, job, run_id="RUN-legacy", started="2026-08-26 06:00:00")
    _insert_finished(store, job, run_id="RUN-local", started="2026-08-26T13:00:00.000000+08:00")
    ordered = [run["id"] for run in store.list_runs(job_id=job["id"], limit=10)]
    assert ordered == ["RUN-legacy", "RUN-local"], ordered


def test_claim_picks_the_latest_running_across_formats(store: OpsStore) -> None:
    """认领时返回的「当前在跑的那条」也走同一条时间轴。"""
    job = _job(store, name="混存认领", kind="backtest")
    with store._transaction() as cursor:
        for run_id, started in (
            ("RUN-old-utc", "2026-08-26 06:00:00"),
            ("RUN-new-local", "2026-08-26T13:00:00.000000+08:00"),
        ):
            cursor.execute(
                "INSERT INTO job_runs(id, job_id, job_name, kind, trigger, status,"
                " started_at, owner_pid, idempotency_key, cancel_requested, heartbeat_at)"
                " VALUES(?, ?, ?, ?, 'manual', 'running', ?, ?, '', 0, '')",
                (run_id, job["id"], job["name"], job["kind"], started, 0),
            )
    row = store.conn.execute(
        f"SELECT id FROM job_runs WHERE job_id = ? AND status = 'running'"
        f" ORDER BY {RUN_ORDER_SQL} LIMIT 1",
        (job["id"],),
    ).fetchone()
    assert row["id"] == "RUN-old-utc"


def test_prune_keeps_the_absolutely_newest_run(store: OpsStore) -> None:
    """保留窗按真实先后裁剪——排错了就是把最新一次执行记录删掉。"""
    job = _job(store, name="混存清理", kind="prune")
    _insert_finished(store, job, run_id="RUN-keep", started="2026-08-26 06:00:00")
    _insert_finished(store, job, run_id="RUN-drop", started="2026-08-26T13:00:00.000000+08:00")
    store.prune_runs(keep_per_job=1)
    left = [run["id"] for run in store.list_runs(job_id=job["id"], limit=10)]
    assert left == ["RUN-keep"], left


# --------------------------------------------------------------------------
# 4. 下游：启动补跑的「已跑过」判定
# --------------------------------------------------------------------------


def test_eod_catchup_reads_both_formats(store: OpsStore) -> None:
    """``last_run_at`` 改成带偏移之后，补跑判定走精确分支；旧行仍靠双解释兜底。"""
    slot = slot_for_day("2026-08-03", 15, 30)
    assert last_run_covers_slot("2026-08-03T15:31:00.000000+08:00", slot) is True
    assert last_run_covers_slot("2026-08-03T15:29:00.000000+08:00", slot) is False
    # 旧行：15:31 上海 = 07:31 UTC，无偏移，仍要认出来（否则每次启动都重复补跑）
    assert last_run_covers_slot("2026-08-03 07:31:14", slot) is True


def test_finished_run_is_recognised_as_today_by_catchup(store: OpsStore) -> None:
    """新写的 ``finished_at`` 要能被 ``shanghai_date_of_timestamp`` 换回今天。"""
    from src.ops.application.wecom_push_mark import shanghai_date_of_timestamp

    job = _job(store, name="补跑日历", kind="screen")
    run_id = store.start_run(job)
    store.finish_run(run_id, status="success")
    finished = store.get_run(run_id)["finished_at"]
    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    assert shanghai_date_of_timestamp(finished) == today
