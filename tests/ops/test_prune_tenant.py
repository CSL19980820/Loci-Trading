"""租户段清理（``prune_tenant``）：子租户的 ops.db 终于有人清了。

守的是六条会**静默**出错的线：

1. 子租户真的被清 —— 老 ``prune`` 在 ``SYSTEM_JOB_KINDS`` 里，子租户一条都不
   装载，于是它们的 ``job_runs`` / ``ai_*`` 从建库那天起没人动过。
2. ``job_runs`` 三参数双闸门 —— 单参数 ``keep_per_job=200`` 对 ``*/5`` 任务只有
   2.8 天、对日更任务是 10 个月；保底条数、硬上限、时间闸三者必须同时生效。
3. 分批删除 —— CPython 的 sqlite3 没开 ``DELETE...LIMIT`` 编译选项，必须走
   ``rowid IN (SELECT ... LIMIT n)`` 循环，且一轮要把该删的全删干净。
4. 单段失败不带走整轮 —— 一张表炸了，其余表照清，错误只进 payload。
5. ``storage_mb`` 激进模式 —— 超限后保留期减半再清一轮，且**不拒绝写入**。
6. cron 错峰的**确定性** —— 同一个租户每次算出的时点必须一样，否则每次启动
   都在改用户的 cron。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import itertools
from pathlib import Path
from typing import Any

import pytest

from src.ops.application.ensure_managed_jobs import ensure_tenant_jobs
from src.ops.application.ensure_prune_tenant_job import (
    DEFAULT_PRUNE_TENANT_CONFIG,
    MANAGED_PRUNE_TENANT,
    ensure_prune_tenant_job,
    prune_tenant_cron,
)
from src.ops.application.jobs import JobContext
from src.ops.application.jobs.prune_tenant import execute_prune_tenant
from src.ops.application.tenant_storage import tenant_storage_usage
from src.ops.infrastructure.store import OpsStore
from src.ops.infrastructure.store_helpers import JOB_KINDS
from src.ops.application.jobs.registry import EXECUTORS
from src.ops.application.tenant_jobs import SYSTEM_JOB_KINDS, tenant_job_rows
from src.shared.paths import data_dir, skill_runs_dir
from src.shared.tenancy import ensure_tenant_root, tenant_scope


def _iso(days_ago: float) -> str:
    """本地带偏移的 ISO 时间戳（与 ``store_helpers._now()`` 同格式）。"""
    moment = datetime.now().astimezone() - timedelta(days=days_ago)
    return moment.isoformat(timespec="microseconds")


def _utc_naive(days_ago: float) -> str:
    """UTC 裸串（历史行的格式，``datetime('now')`` 落下的那种）。"""
    moment = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return moment.strftime("%Y-%m-%d %H:%M:%S")


_SEQ = itertools.count()


def _add_run(store: OpsStore, job_id: str, *, started_at: str, status: str = "success") -> str:
    """直接插一行执行历史。走 SQL 是为了能自由指定 ``started_at``。"""
    run_id = f"RUN-{next(_SEQ):06d}"
    store.conn.execute(
        "INSERT INTO job_runs(id, job_id, job_name, kind, trigger, status, started_at)"
        " VALUES(?,?,?,?,?,?,?)",
        (run_id, job_id, "t", "sync", "manual", status, started_at),
    )
    store.conn.commit()
    return run_id


def _count(store: OpsStore, table: str) -> int:
    return int(store.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


# --------------------------------------------------------------------------
# 1. 注册与装载：新 kind 必须两张名单都在，且**不**是系统级
# --------------------------------------------------------------------------


def test_kind_is_registered_and_is_not_system_level() -> None:
    """JOB_KINDS 管建、EXECUTORS 管跑；进了 SYSTEM_JOB_KINDS 就等于没改。"""
    assert "prune_tenant" in JOB_KINDS
    assert "prune_tenant" in EXECUTORS
    # 这一条是整个改动的要害：一旦被塞进系统级集合，子租户又回到一条都不清。
    assert "prune_tenant" not in SYSTEM_JOB_KINDS


def test_sub_tenant_gets_the_job_and_it_survives_the_system_filter(tmp_path: Path) -> None:
    """子租户经 ``ensure_tenant_jobs`` 拿到清理任务，且装载层不会把它滤掉。"""
    ensure_tenant_root(data_dir(), "alice")
    with tenant_scope("alice"):
        with OpsStore(None) as store:
            ensure_tenant_jobs(store)
            job = store.get_job_by_name(MANAGED_PRUNE_TENANT)
        assert job is not None
        assert job["kind"] == "prune_tenant"
        kinds = {row["kind"] for row in tenant_job_rows("alice")}
    assert "prune_tenant" in kinds, "被 SYSTEM_JOB_KINDS 滤掉了，等于没挂"


def test_ensure_is_idempotent_and_keeps_user_switches(tmp_path: Path) -> None:
    """再次 ensure 只补缺失键，不还原用户关掉的开关 / 改过的 cron。"""
    with OpsStore(str(tmp_path / "ops.db")) as store:
        first = ensure_prune_tenant_job(store)
        assert first["created"] == 1
        job = store.get_job_by_name(MANAGED_PRUNE_TENANT)
        assert job is not None
        store.update_job(
            job["id"], enabled=False, cron="15 4 * * *", config={"keep_days": 30}
        )

        ensure_prune_tenant_job(store)

        after = store.get_job_by_name(MANAGED_PRUNE_TENANT)
        assert after is not None
        assert after["enabled"] is False
        assert after["cron"] == "15 4 * * *"
        assert after["config"]["keep_days"] == 30
        # 缺的键靠 {**DEFAULT, **prev} 补齐，不用写迁移。
        assert after["config"]["run_keep_min"] == DEFAULT_PRUNE_TENANT_CONFIG["run_keep_min"]
        assert after["config"]["ai_session_keep"] == 500


# --------------------------------------------------------------------------
# 2. cron 错峰：确定性 + 落在 02:30-03:29
# --------------------------------------------------------------------------


def test_cron_is_deterministic_and_spread_over_one_hour() -> None:
    assert prune_tenant_cron(None) == "30 2 * * *"
    for tenant in ("alice", "bob", "u-7f3a", "carol"):
        cron = prune_tenant_cron(tenant)
        assert cron == prune_tenant_cron(tenant), "同一租户两次算出不同时点"
        minute, hour = int(cron.split()[0]), int(cron.split()[1])
        total = hour * 60 + minute
        assert 150 <= total <= 209, f"{cron} 不在 02:30-03:29"


def test_cron_actually_spreads_tenants() -> None:
    """20 个租户至少落进 5 个不同的分钟槽，否则错峰是假的。"""
    slots = {prune_tenant_cron(f"tenant-{i}") for i in range(20)}
    assert len(slots) >= 5


# --------------------------------------------------------------------------
# 3. job_runs 三参数双闸门
# --------------------------------------------------------------------------


def test_dual_gate_keeps_min_deletes_over_max_and_ages_the_middle(tmp_path: Path) -> None:
    """保底 / 硬上限 / 时间闸三者必须同时成立。"""
    with OpsStore(str(tmp_path / "ops.db")) as store:
        job_id = store.create_job(name="高频", kind="sync", cron="*/5 9-14 * * mon-fri")
        # 3 条很老的（老到跨过时间闸），外加 12 条很新的。
        for i in range(3):
            _add_run(store, job_id, started_at=_iso(400 + i))
        for i in range(12):
            _add_run(store, job_id, started_at=_iso(i * 0.01))
        assert _count(store, "job_runs") == 15

        # keep_min=5 保底，keep_max=10 硬上限，keep_days=15 管中间地带。
        result = store.prune_runs_windowed(keep_min=5, keep_max=10, keep_days=15)

        # 15 条里排名 11-15 的一律删（超硬上限）；剩下 10 条里 6-10 名若够老也删。
        # 这里 1-12 名都是新的，所以只掉 11、12 两条 + 三条老的（13-15 名）。
        assert result["deleted"] == 5
        assert _count(store, "job_runs") == 10


def test_keep_min_wins_over_the_age_gate(tmp_path: Path) -> None:
    """全部记录都超龄时，仍要留下 ``keep_min`` 条——否则连"上次跑没跑过"都查不到。"""
    with OpsStore(str(tmp_path / "ops.db")) as store:
        job_id = store.create_job(name="日更", kind="outcome", cron="45 15 * * mon-fri")
        for i in range(9):
            _add_run(store, job_id, started_at=_iso(100 + i))

        store.prune_runs_windowed(keep_min=5, keep_max=200, keep_days=15)

        assert _count(store, "job_runs") == 5


def test_dual_gate_compares_mixed_timestamp_formats_on_one_axis(tmp_path: Path) -> None:
    """新旧两种时间戳并存时，判定必须一致——字符串比会差 8 小时且排序也错。

    历史行是 UTC 裸串 ``"YYYY-MM-DD HH:MM:SS"``，新行是本地带偏移的
    ``"...T...+08:00"``。两条**同样只有 1 天龄**的记录，一条不能因为格式不同
    就被 15 天的闸门砍掉。
    """
    with OpsStore(str(tmp_path / "ops.db")) as store:
        job_id = store.create_job(name="混格式", kind="sync")
        fresh_legacy = _add_run(store, job_id, started_at=_utc_naive(1))
        fresh_modern = _add_run(store, job_id, started_at=_iso(1))
        old_legacy = _add_run(store, job_id, started_at=_utc_naive(90))
        old_modern = _add_run(store, job_id, started_at=_iso(90))

        store.prune_runs_windowed(keep_min=1, keep_max=200, keep_days=15)

        alive = {row[0] for row in store.conn.execute("SELECT id FROM job_runs")}
        assert fresh_legacy in alive and fresh_modern in alive
        assert old_legacy not in alive and old_modern not in alive


def test_running_slot_is_never_pruned(tmp_path: Path) -> None:
    """删掉执行中的运行槽 = ``finish_run`` 当场报「任务运行不存在」。"""
    with OpsStore(str(tmp_path / "ops.db")) as store:
        job_id = store.create_job(name="在跑", kind="sync")
        running = _add_run(store, job_id, started_at=_iso(900), status="running")
        for i in range(20):
            _add_run(store, job_id, started_at=_iso(500 + i))

        store.prune_runs_windowed(keep_min=1, keep_max=2, keep_days=1)

        alive = {row[0] for row in store.conn.execute("SELECT id FROM job_runs")}
        assert running in alive


def test_deletion_is_batched_and_still_completes(tmp_path: Path) -> None:
    """批大小远小于待删量时，一轮也要把该删的删干净（循环，不是删一批就走）。"""
    with OpsStore(str(tmp_path / "ops.db")) as store:
        job_id = store.create_job(name="海量", kind="sync")
        for i in range(120):
            _add_run(store, job_id, started_at=_iso(300 + i))

        result = store.prune_runs_windowed(keep_min=1, keep_max=10, keep_days=15, batch=7)

        assert result["deleted"] == 119
        assert _count(store, "job_runs") == 1


def test_batching_does_not_hold_one_giant_transaction(tmp_path: Path) -> None:
    """每批一条独立的 DELETE + 提交，而不是一条巨型语句独占写锁跑到底。

    数 DELETE 的条数（``set_trace_callback``）而不是数提交次数：
    ``sqlite3.Connection.commit`` 是只读属性，打桩不上。
    """
    with OpsStore(str(tmp_path / "ops.db")) as store:
        job_id = store.create_job(name="计批", kind="sync")
        for i in range(50):
            _add_run(store, job_id, started_at=_iso(300 + i))
        seen: list[str] = []
        store.conn.set_trace_callback(lambda sql: seen.append(sql))
        try:
            store.prune_runs_windowed(keep_min=1, keep_max=1, keep_days=15, batch=10)
        finally:
            store.conn.set_trace_callback(None)

        deletes = [sql for sql in seen if sql.lstrip().upper().startswith("DELETE FROM JOB_RUNS")]
        # 49 条待删 / 每批 10 → 5 批（最后一批不满，循环收口）。
        assert len(deletes) == 5, deletes
        assert _count(store, "job_runs") == 1


# --------------------------------------------------------------------------
# 4. 执行器：真的清、单段失败不带走整轮、payload 口径
# --------------------------------------------------------------------------


def _seed_dirty_tenant_db(store: OpsStore) -> None:
    """种一批「够老」的行，覆盖三类截断都会碰到的表。"""
    job_id = store.create_job(name="脏活", kind="sync")
    for i in range(30):
        _add_run(store, job_id, started_at=_iso(200 + i))
    store.conn.execute(
        "INSERT INTO monitor_runs(id, slug, status, started_at) VALUES(?,?,?,?)",
        ("MR-old", "s", "success", _iso(90)),
    )
    store.conn.execute(
        "INSERT INTO monitor_runs(id, slug, status, started_at) VALUES(?,?,?,?)",
        ("MR-new", "s", "success", _iso(1)),
    )
    store.conn.execute(
        "INSERT INTO leader_role_snapshots"
        "(id, slug, trade_date, observed_at, code, role, created_at) VALUES(?,?,?,?,?,?,?)",
        ("LR-old", "s", "2020-01-01", _iso(900), "600000", "leader", _iso(900)),
    )
    store.conn.execute(
        "INSERT INTO mcp_quota(trade_date, pool, call_count, updated_at) VALUES(?,?,?,?)",
        ("2020-01-01", "structured", 3, _iso(900)),
    )
    store.conn.execute(
        "INSERT INTO ai_decisions(id, slug, created_at) VALUES(?,?,?)",
        ("AID-old", "s", _iso(90)),
    )
    store.conn.commit()


def test_executor_cleans_a_sub_tenant_ops_db(tmp_path: Path) -> None:
    """这就是审计里那条 580 MB/年/人 的盲区：子租户的库终于被清了。"""
    ensure_tenant_root(data_dir(), "alice")
    with tenant_scope("alice"):
        with OpsStore(None) as store:
            _seed_dirty_tenant_db(store)
            payload = execute_prune_tenant(
                dict(DEFAULT_PRUNE_TENANT_CONFIG), JobContext(ops_store=store)
            )

            assert payload["tenant"] == "alice"
            tables = payload["tables"]
            assert tables["job_runs"]["deleted"] > 0
            assert tables["monitor_runs"]["deleted"] == 1
            assert tables["leader_role_snapshots"]["deleted"] == 1
            assert tables["mcp_quota"]["deleted"] == 1
            assert tables["ai_decisions"]["deleted"] == 1
            # 没超龄的那条盯盘记录必须还在。
            alive = {r[0] for r in store.conn.execute("SELECT id FROM monitor_runs")}
            assert alive == {"MR-new"}


def test_payload_reports_per_table_numbers_and_byte_sizes(tmp_path: Path) -> None:
    """删行不会让文件变小，所以「删了多少」和「现在多大」必须同时报。"""
    with OpsStore(str(tmp_path / "ops.db")) as store:
        _seed_dirty_tenant_db(store)
        payload = execute_prune_tenant(
            dict(DEFAULT_PRUNE_TENANT_CONFIG), JobContext(ops_store=store)
        )

    for key in ("bytes_before", "bytes_after", "over_quota", "storage_mb"):
        assert key in payload
    for name, entry in payload["tables"].items():
        assert "deleted" in entry, name
        assert "ms" in entry, name
    # VACUUM 明确不在本任务里做（要重写整个库 + 独占写锁）。
    assert payload["vacuum"] == "not_run"


def test_one_failing_table_does_not_take_down_the_round(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``job_runs`` 那段炸掉，其余表照清，错误只进 payload。"""
    with OpsStore(str(tmp_path / "ops.db")) as store:
        _seed_dirty_tenant_db(store)

        def boom(**_kwargs: Any) -> dict[str, Any]:
            raise RuntimeError("database is locked")

        monkeypatch.setattr(store, "prune_runs_windowed", boom)
        payload = execute_prune_tenant(
            dict(DEFAULT_PRUNE_TENANT_CONFIG), JobContext(ops_store=store)
        )

        assert "database is locked" in payload["tables"]["job_runs"]["error"]
        # 后面那些表一张都不能被带走。
        assert payload["tables"]["monitor_runs"]["deleted"] == 1
        assert payload["tables"]["ai_decisions"]["deleted"] == 1


def test_keep_days_zero_deletes_nothing(tmp_path: Path) -> None:
    """0 在配置里最可能是「忘了填」，绝不能解释成「全部删光」。"""
    with OpsStore(str(tmp_path / "ops.db")) as store:
        _seed_dirty_tenant_db(store)
        config = {**DEFAULT_PRUNE_TENANT_CONFIG, "keep_days": 0, "ai_session_keep": 0}

        payload = execute_prune_tenant(config, JobContext(ops_store=store))

        assert payload["tables"]["monitor_runs"]["deleted"] == 0
        assert payload["tables"]["ai_decisions"]["deleted"] == 0
        assert _count(store, "monitor_runs") == 2


def test_missing_ops_store_is_a_job_error(tmp_path: Path) -> None:
    from src.ops.application.jobs.context import JobError

    with pytest.raises(JobError):
        execute_prune_tenant({}, JobContext())


# --------------------------------------------------------------------------
# 5. 磁盘产物与 storage_mb 激进模式
# --------------------------------------------------------------------------


def _touch_skill_run(run_id: str, *, age_days: float) -> Path:
    import os
    import time

    root = skill_runs_dir()
    root.mkdir(parents=True, exist_ok=True)
    state = root / f"{run_id}.json"
    events = root / f"{run_id}.events.jsonl"
    state.write_text("{}", encoding="utf-8")
    events.write_text("\n" * 50, encoding="utf-8")
    stamp = time.time() - age_days * 86400
    os.utime(state, (stamp, stamp))
    os.utime(events, (stamp, stamp))
    return state


def test_stale_skill_runs_are_removed_with_their_event_files(tmp_path: Path) -> None:
    with OpsStore(str(tmp_path / "ops.db")) as store:
        old = _touch_skill_run("SR-old", age_days=90)
        fresh = _touch_skill_run("SR-new", age_days=1)

        payload = execute_prune_tenant(
            dict(DEFAULT_PRUNE_TENANT_CONFIG), JobContext(ops_store=store)
        )

        assert payload["artifacts"]["skill_runs"]["deleted"] == 1
        assert not old.exists()
        assert not old.with_suffix(".events.jsonl").exists()
        assert fresh.exists()


def test_research_run_state_files_are_never_touched(tmp_path: Path) -> None:
    """``RR-*/`` 之外的 json 是长期状态存档，按 mtime 删会抹掉研究域的假设库。"""
    import os
    import time

    from src.shared.paths import research_runs_dir

    root = research_runs_dir()
    root.mkdir(parents=True, exist_ok=True)
    run_dir = root / "RR-abcdef123456"
    run_dir.mkdir()
    (run_dir / "run.json").write_text("{}", encoding="utf-8")
    state = root / "hypotheses.json"
    state.write_text("[]", encoding="utf-8")
    stamp = time.time() - 400 * 86400
    for path in (run_dir / "run.json", run_dir, state):
        os.utime(path, (stamp, stamp))

    with OpsStore(str(tmp_path / "ops.db")) as store:
        payload = execute_prune_tenant(
            dict(DEFAULT_PRUNE_TENANT_CONFIG), JobContext(ops_store=store)
        )

    assert payload["artifacts"]["research_runs"]["deleted"] == 1
    assert not run_dir.exists()
    assert state.exists(), "hypotheses.json 不是 run 产物，绝不能删"


def test_storage_usage_reports_itemised_breakdown() -> None:
    """只报总数的话，用户看到「你超了 2 GB」也不知道该删什么。"""
    _touch_skill_run("SR-usage", age_days=0)
    usage = tenant_storage_usage(None)

    assert set(usage["items"]) == {
        "palace_db",
        "ops_db",
        "skills",
        "skill_runs",
        "research_runs",
    }
    assert usage["items"]["skill_runs"] > 0
    assert usage["bytes"] == sum(usage["items"].values())


def test_over_quota_triggers_aggressive_pass_without_blocking_writes(
    tmp_path: Path,
) -> None:
    """超 ``storage_mb`` 后保留期减半再清一轮；**永远不拒绝写入**。"""
    ensure_tenant_root(data_dir(), "bob")
    with tenant_scope("bob"):
        with OpsStore(None) as store:
            job_id = store.create_job(name="超限", kind="sync")
            # 10 天龄：常规 15 天闸门放过，减半后的 7 天闸门砍掉。
            for i in range(40):
                _add_run(store, job_id, started_at=_iso(10))
            store.conn.execute(
                "INSERT INTO monitor_runs(id, slug, status, started_at) VALUES(?,?,?,?)",
                ("MR-10d", "s", "success", _iso(10)),
            )
            store.conn.commit()
            # storage_mb=1 保证任何非空库都超限（配置值优先于身份库）。
            config = {**DEFAULT_PRUNE_TENANT_CONFIG, "storage_mb": 1}

            payload = execute_prune_tenant(config, JobContext(ops_store=store))

            assert payload["over_quota"] is True
            assert payload["storage_mb"] == 1
            assert payload["aggressive"]["keep_days"] == 7
            assert payload["aggressive"]["writes_blocked"] is False
            assert payload["aggressive"]["tables"]["monitor_runs"]["deleted"] == 1
            # 前后体积都要报，否则「删了但库还是 5 GB」会被当成清理没生效。
            assert payload["bytes_before"] > 0
            assert "bytes_after" in payload["aggressive"]


def test_under_quota_stays_in_normal_mode(tmp_path: Path) -> None:
    with OpsStore(str(tmp_path / "ops.db")) as store:
        _seed_dirty_tenant_db(store)
        config = {**DEFAULT_PRUNE_TENANT_CONFIG, "storage_mb": 1_000_000}

        payload = execute_prune_tenant(config, JobContext(ops_store=store))

        assert payload["over_quota"] is False
        assert "aggressive" not in payload


def test_negative_storage_mb_means_unlimited(tmp_path: Path) -> None:
    with OpsStore(str(tmp_path / "ops.db")) as store:
        _seed_dirty_tenant_db(store)
        config = {**DEFAULT_PRUNE_TENANT_CONFIG, "storage_mb": -1}

        payload = execute_prune_tenant(config, JobContext(ops_store=store))

        assert payload["over_quota"] is False


# --------------------------------------------------------------------------
# 6. 系统段（prune）新增的两块：identity 死代码接上、community 三表
# --------------------------------------------------------------------------


def test_system_prune_calls_identity_purge_expired(tmp_path: Path) -> None:
  """``IdentityStore.purge_expired()`` 此前是**全仓零调用点的死代码**。

  payload 分三段报（``expired`` / ``notifications`` / ``usage_counters``）而不是
  合成一个 ``removed``：合起来只剩一个数时，「会话清了 0 条」与「通知清了 0 条」
  长得一模一样，出问题没法从留痕里判断是哪一段哑了。
  """
  from src.identity import IdentityStore
  from src.ops.application.jobs.prune import execute_prune
  from src.shared.paths import identity_db

  old = _utc_naive(40)
  old_day = old[:10]
  with IdentityStore(identity_db()) as identity:
    identity.conn.execute(
      "INSERT INTO oauth_states(state, provider, status, created_at, updated_at, expires_at)"
      " VALUES(?,?,?,?,?,?)",
      ("s-stale", "wechat", "pending", _utc_naive(9), _utc_naive(9), _utc_naive(8)),
    )
    identity.conn.execute(
      "INSERT INTO notifications(id, user_id, kind, title, body, link, created_at, read_at)"
      " VALUES(?,?,?,?,?,?,?,?)",
      ("n-old", "u_x", "system", "旧通知", "", "", old, old),
    )
    identity.conn.executemany(
      "INSERT INTO usage_counters(user_id, period, metric, value, updated_at)"
      " VALUES(?,?,?,?,?)",
      [
        ("u_x", old_day, "llm_calls", 3, old),
        ("u_x", old_day[:7], "llm_tokens", 100, old),
      ],
    )
    identity.conn.commit()

  with OpsStore(str(tmp_path / "ops.db")) as store:
    payload = execute_prune({"keep_per_job": 200, "intraday_keep_days": 0}, store_ctx(store))

  assert payload["identity"]["expired"] == 1
  assert payload["identity"]["notifications"] == 1
  assert payload["identity"]["usage_counters"] == 1
  with IdentityStore(identity_db()) as identity:
    left = identity.conn.execute("SELECT COUNT(*) FROM oauth_states").fetchone()[0]
    notes = identity.conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0]
    # 月计数必须活着：它是 llm_monthly_tokens 的判定依据，删了当月配额凭空复位
    months = identity.conn.execute(
      "SELECT COUNT(*) FROM usage_counters WHERE length(period) = 7"
    ).fetchone()[0]
  assert (left, notes, months) == (0, 0, 1)


def test_system_prune_never_creates_the_global_dbs(tmp_path: Path) -> None:
    """顺手把空 identity.db / community.db 建出来会改变「这台机器启没启用账号体系」。"""
    from src.ops.application.jobs.prune import execute_prune
    from src.shared.paths import community_db, identity_db

    assert not identity_db().exists()
    assert not community_db().exists()

    with OpsStore(str(tmp_path / "ops.db")) as store:
        payload = execute_prune({"intraday_keep_days": 0}, store_ctx(store))

    assert not identity_db().exists()
    assert not community_db().exists()
    assert "不存在" in payload["identity"]["skipped"]
    assert "不存在" in payload["community"]["skipped"]


def test_system_prune_cleans_community_feed(tmp_path: Path) -> None:
    from src.community import CommunityStore
    from src.ops.application.jobs.prune import execute_prune
    from src.shared.paths import community_db

    with CommunityStore(community_db()) as community:
        community.conn.execute(
            "INSERT INTO activity_feed(id, actor_id, verb, created_at) VALUES(?,?,?,?)",
            ("F-old", "u-1", "published", _iso(90)),
        )
        community.conn.commit()

    with OpsStore(str(tmp_path / "ops.db")) as store:
        payload = execute_prune({"intraday_keep_days": 0}, store_ctx(store))

    assert payload["community"]["tables"]["activity_feed"]["deleted"] == 1


def test_system_prune_survives_a_broken_global_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """跨上下文那两段炸掉，只进 payload，不把整条运维清理刷红。"""
    from src.ops.application.jobs import prune as prune_module

    monkeypatch.setattr(
        prune_module, "_purge_identity", lambda: {"error": "RuntimeError: boom"}
    )
    with OpsStore(str(tmp_path / "ops.db")) as store:
        payload = execute_prune_system(store)

    assert payload["identity"]["error"] == "RuntimeError: boom"
    assert "removed" in payload


def store_ctx(store: OpsStore) -> JobContext:
    return JobContext(ops_store=store)


def execute_prune_system(store: OpsStore) -> dict[str, Any]:
    from src.ops.application.jobs.prune import execute_prune

    return execute_prune({"intraday_keep_days": 0}, store_ctx(store))
