from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
from threading import Barrier, Event
import unittest
from unittest.mock import patch

from src.ai.infrastructure.crypto import mask_secret
from src.ops.application.jobs import JobContext, run_job
from src.ops.infrastructure.scheduler import SchedulerError, validate_cron
from src.ops.infrastructure.store import OpsError, OpsStore


class MaskSecretTests(unittest.TestCase):
    def test_mask_only_shows_last_four(self) -> None:
        self.assertEqual(mask_secret("sk-abcdefgh1234"), "****1234")
        self.assertNotIn("abcdefgh", mask_secret("sk-abcdefgh1234"))


class CronValidationTests(unittest.TestCase):
    def test_accepts_standard_expressions(self) -> None:
        for expression in ("35 15 * * 1-5", "0 9 * * *", "*/15 * * * *"):
            with self.subTest(expression=expression):
                self.assertIsNotNone(validate_cron(expression))

    def test_accepts_multiline_and_semicolon_expressions(self) -> None:
        """支持一个定时任务配置多个时间点（多行或分号）。"""
        multi1 = "50 14 * * mon-fri\n30 15 * * mon-fri"
        triggers1 = validate_cron(multi1)
        self.assertIsInstance(triggers1, list)
        self.assertEqual(len(triggers1), 2)

        multi2 = "50 14 * * mon-fri; 30 15 * * mon-fri"
        triggers2 = validate_cron(multi2)
        self.assertIsInstance(triggers2, list)
        self.assertEqual(len(triggers2), 2)

    def test_cron_uses_shanghai_timezone(self) -> None:
        trigger = validate_cron("35 15 * * 1-5")
        self.assertEqual(str(trigger.timezone), "Asia/Shanghai")

    def test_rejects_wrong_field_count(self) -> None:
        """写错的 cron 必须当场报错，不能等到它安静地永不触发。"""
        with self.assertRaises(SchedulerError) as ctx:
            validate_cron("35 15 * *")
        self.assertIn("5 个字段", str(ctx.exception))

    def test_rejects_garbage(self) -> None:
        with self.assertRaises(SchedulerError):
            validate_cron("每天下午三点半")

    def test_rejects_empty(self) -> None:
        with self.assertRaises(SchedulerError):
            validate_cron("   ")
class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = OpsStore(Path(self.temp.name) / "ops.db")

    def tearDown(self) -> None:
        self.store.close()
        self.temp.cleanup()

    def test_job_crud(self) -> None:
        job_id = self.store.create_job(
            name="盘后同步", kind="sync", cron="35 15 * * 1-5", config={"workers": 6}
        )
        job = self.store.get_job(job_id)
        self.assertEqual(job["name"], "盘后同步")
        self.assertEqual(job["config"]["workers"], 6)
        self.assertTrue(job["enabled"])

        self.store.update_job(job_id, cron="40 15 * * 1-5", enabled=False)
        self.assertEqual(self.store.get_job(job_id)["cron"], "40 15 * * 1-5")
        self.assertFalse(self.store.get_job(job_id)["enabled"])
        self.assertEqual(self.store.list_jobs(enabled_only=True), [])
        self.assertTrue(self.store.delete_job(job_id))

    def test_duplicate_job_name_is_rejected(self) -> None:
        self.store.create_job(name="dup", kind="sync")
        with self.assertRaises(OpsError):
            self.store.create_job(name="dup", kind="sync")

    def test_ensure_job_is_atomic_across_connections(self) -> None:
        """并发启动时，同一个托管任务只能被创建一次而非让一方报重名。"""
        barrier = Barrier(2)

        def ensure() -> str:
            with OpsStore(self.store.db_path) as concurrent_store:
                barrier.wait()
                return concurrent_store.ensure_job(
                    name="concurrent-managed",
                    kind="sync",
                    cron="0 9 * * 1-5",
                    config={"workers": 2},
                )

        with ThreadPoolExecutor(max_workers=2) as executor:
            job_ids = list(executor.map(lambda _: ensure(), range(2)))

        self.assertEqual(job_ids[0], job_ids[1])
        jobs = [job for job in self.store.list_jobs() if job["name"] == "concurrent-managed"]
        self.assertEqual(len(jobs), 1)

    def test_ensure_job_preserves_existing_config_when_not_replaced(self) -> None:
        job_id = self.store.create_job(
            name="managed", kind="sync", cron="0 9 * * 1-5", config={"workers": 4}
        )

        ensured_id = self.store.ensure_job(
            name="managed", kind="screen", cron="30 15 * * 1-5", config=None, enabled=False
        )

        job = self.store.get_job(job_id)
        self.assertEqual(ensured_id, job_id)
        self.assertEqual(job["kind"], "sync")
        self.assertEqual(job["cron"], "30 15 * * 1-5")
        self.assertEqual(job["config"], {"workers": 4})
        self.assertFalse(job["enabled"])

    def test_unknown_job_kind_is_rejected(self) -> None:
        with self.assertRaises(OpsError):
            self.store.create_job(name="x", kind="mystery")

    def test_unknown_update_field_is_rejected(self) -> None:
        job_id = self.store.create_job(name="x", kind="sync")
        with self.assertRaises(OpsError):
            self.store.update_job(job_id, kind="screen")

    def test_conditional_job_mutations_do_not_touch_changed_target(self) -> None:
        job_id = self.store.create_job(name="assistant-owned", kind="sync")

        self.assertFalse(
            self.store.update_job(
                job_id,
                enabled=False,
                expected_name="assistant-owned",
                allowed_kinds={"skill"},
            )
        )
        self.assertTrue(self.store.get_job(job_id)["enabled"])
        self.assertFalse(
            self.store.delete_job(
                job_id,
                expected_name="renamed",
                allowed_kinds={"sync"},
            )
        )
        self.assertIsNotNone(self.store.get_job(job_id))
        self.assertTrue(
            self.store.update_job(
                job_id,
                enabled=False,
                expected_name="assistant-owned",
                allowed_kinds={"sync"},
            )
        )
        self.assertFalse(self.store.get_job(job_id)["enabled"])

    def test_run_history_updates_job_status(self) -> None:
        job_id = self.store.create_job(name="x", kind="sync")
        job = self.store.get_job(job_id)
        run_id = self.store.start_run(job, trigger="schedule")
        self.store.finish_run(run_id, status="success", result={"rows": 10}, duration_ms=1234)

        runs = self.store.list_runs(job_id=job_id)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["status"], "success")
        self.assertEqual(runs[0]["result"]["rows"], 10)
        self.assertEqual(runs[0]["trigger"], "schedule")
        self.assertEqual(self.store.get_job(job_id)["last_status"], "success")

    def test_claim_run_recovers_a_stale_running_record(self) -> None:
        job_id = self.store.create_job(name="x", kind="sync")
        job = self.store.get_job(job_id)
        stale_id = self.store.start_run(job)
        with self.store._transaction() as cursor:
            cursor.execute(
                "UPDATE job_runs SET started_at = '2000-01-01 00:00:00' WHERE id = ?",
                (stale_id,),
            )

        run_id, claimed = self.store.claim_run(job)

        self.assertTrue(claimed)
        self.assertNotEqual(run_id, stale_id)
        runs = {run["id"]: run for run in self.store.list_runs(job_id=job_id, limit=10)}
        self.assertEqual(runs[stale_id]["status"], "failed")
        self.assertTrue(
            any(
                token in runs[stale_id]["error_text"]
                for token in ("已按中断回收", "PID 复用", "占槽已回收")
            )
        )

    def test_claim_run_recovers_stale_sync_after_time_window(self) -> None:
        job_id = self.store.create_job(name="sync-stale", kind="sync")
        job = self.store.get_job(job_id)
        stale_id = self.store.start_run(job)
        # 1 小时前：超过 sync 的 45 分钟回收窗
        with self.store._transaction() as cursor:
            cursor.execute(
                "UPDATE job_runs SET started_at = datetime('now', '-60 minutes') WHERE id = ?",
                (stale_id,),
            )

        run_id, claimed = self.store.claim_run(job)

        self.assertTrue(claimed)
        self.assertNotEqual(run_id, stale_id)
        runs = {run["id"]: run for run in self.store.list_runs(job_id=job_id, limit=10)}
        self.assertEqual(runs[stale_id]["status"], "failed")
        self.assertTrue(
            any(
                token in runs[stale_id]["error_text"]
                for token in ("sync", "PID 复用", "占槽已回收", "已按中断回收")
            )
        )

    def test_claim_run_recovers_dead_owner_pid_immediately(self) -> None:
        job_id = self.store.create_job(name="dead-pid", kind="screen")
        job = self.store.get_job(job_id)
        stale_id = self.store.start_run(job)
        with self.store._transaction() as cursor:
            # 用不存在的 PID；即使刚启动也必须立刻腾槽
            cursor.execute(
                "UPDATE job_runs SET owner_pid = 99999999 WHERE id = ?",
                (stale_id,),
            )

        run_id, claimed = self.store.claim_run(job)

        self.assertTrue(claimed)
        self.assertNotEqual(run_id, stale_id)
        runs = {run["id"]: run for run in self.store.list_runs(job_id=job_id, limit=10)}
        self.assertEqual(runs[stale_id]["status"], "failed")
        self.assertIn("进程已退出", runs[stale_id]["error_text"])

    def test_reclaim_same_pid_from_previous_process(self) -> None:
        """容器 Recreate 后 uvicorn 仍是 PID 1，旧 running 必须立刻腾槽。

        2026-09-01 线上硬重启后三条 run 的 owner_pid 全是 1，自动收尸以为
        「进程还活着」，盘中增量 / 选股槽被假占用到时间窗到期。
        """
        from datetime import timedelta

        from src.ops.infrastructure import store_runs as runs_mod

        job_id = self.store.create_job(name="pid-reuse", kind="sync")
        job = self.store.get_job(job_id)
        stale_id = self.store.start_run(job)
        prior = (runs_mod.PROCESS_STARTED_AT - timedelta(minutes=5)).isoformat()
        with self.store._transaction() as cursor:
            cursor.execute(
                "UPDATE job_runs SET started_at = ?, heartbeat_at = ? WHERE id = ?",
                (prior, prior, stale_id),
            )

        n = self.store.reclaim_stale_runs()
        self.assertGreaterEqual(n, 1)
        row = self.store.list_runs(job_id=job_id, limit=1)[0]
        self.assertEqual(row["status"], "failed")
        self.assertIn("重启", row["error_text"])

    def test_reclaim_stale_runs_clears_other_jobs(self) -> None:
        sync_id = self.store.create_job(name="sync-a", kind="sync")
        screen_id = self.store.create_job(name="screen-a", kind="screen")
        sync_run = self.store.start_run(self.store.get_job(sync_id))
        screen_run = self.store.start_run(self.store.get_job(screen_id))
        with self.store._transaction() as cursor:
            cursor.execute(
                "UPDATE job_runs SET started_at = datetime('now', '-3 hours') "
                "WHERE id IN (?, ?)",
                (sync_run, screen_run),
            )
        n = self.store.reclaim_stale_runs()
        self.assertGreaterEqual(n, 2)
        self.assertEqual(
            self.store.list_runs(run_id=sync_run)[0]["status"], "failed"
        )
        self.assertEqual(
            self.store.list_runs(run_id=screen_run)[0]["status"], "failed"
        )

    def test_failed_run_keeps_the_full_error_text(self) -> None:
        """只留状态码不留报错，等于失败了也查不出为什么。"""
        job_id = self.store.create_job(name="x", kind="sync")
        run_id = self.store.start_run(self.store.get_job(job_id))
        self.store.finish_run(run_id, status="failed", error="ConnectionError: 东财超时")
        self.assertIn("东财超时", self.store.list_runs(job_id=job_id)[0]["error_text"])

    def test_prune_keeps_recent_runs_per_job(self) -> None:
        """定时任务每天跑，不清理这张表会无限膨胀。"""
        job_id = self.store.create_job(name="x", kind="sync")
        job = self.store.get_job(job_id)
        for _ in range(12):
            run_id = self.store.start_run(job)
            self.store.finish_run(run_id, status="success")
        self.store.prune_runs(keep_per_job=5)
        self.assertEqual(len(self.store.list_runs(job_id=job_id, limit=100)), 5)

    def test_delete_runs_removes_selected_ids(self) -> None:
        job_id = self.store.create_job(name="x", kind="sync")
        job = self.store.get_job(job_id)
        ids = []
        for _ in range(3):
            run_id = self.store.start_run(job)
            self.store.finish_run(run_id, status="success")
            ids.append(run_id)
        removed = self.store.delete_runs(ids[:2])
        self.assertEqual(removed, 2)
        left = self.store.list_runs(job_id=job_id, limit=10)
        self.assertEqual(len(left), 1)
        self.assertEqual(left[0]["id"], ids[2])
        self.assertEqual(self.store.delete_runs([]), 0)

    def test_running_run_cannot_be_deleted_or_release_the_execution_claim(self) -> None:
        job_id = self.store.create_job(name="exclusive", kind="sync")
        job = self.store.get_job(job_id)
        assert job is not None
        run_id = self.store.start_run(job)

        with self.assertRaisesRegex(OpsError, "运行中的任务记录不可删除"):
            self.store.delete_runs([run_id])
        claimed_id, claimed = self.store.claim_run(job)
        self.assertFalse(claimed)
        self.assertEqual(claimed_id, run_id)

        self.store.finish_run(run_id, status="success")
        self.assertEqual(self.store.delete_runs([run_id]), 1)
        with self.assertRaisesRegex(OpsError, "不存在或已被删除"):
            self.store.finish_run(run_id, status="success")

    def test_provider_never_exposes_the_secret_by_default(self) -> None:
        self.store.upsert_provider(
            {
                "name": "openrouter", "protocol": "openai_compatible",
                "base_url": "https://openrouter.ai/api/v1",
                "encrypted_key": b"cipher-bytes", "key_last4": "****abcd",
                "default_model": "anthropic/claude-3.5-sonnet",
            }
        )
        listed = self.store.list_providers()[0]
        self.assertNotIn("encrypted_key", listed)
        self.assertTrue(listed["has_key"])
        self.assertEqual(listed["key_last4"], "****abcd")

        with_secret = self.store.get_provider("openrouter", include_secret=True)
        self.assertEqual(with_secret["encrypted_key"], b"cipher-bytes")

    def test_save_provider_rejects_unknown_protocol_before_database_write(self) -> None:
        from src.ai.infrastructure.providers import save_provider

        with self.assertRaisesRegex(OpsError, "未知协议"):
            save_provider(
                self.store,
                name="invalid-protocol",
                protocol="not-a-protocol",
                base_url="https://example.test",
                api_key="sk-test",
                model="demo",
                validate=False,
                discover_models=False,
            )
        self.assertIsNone(self.store.get_provider("invalid-protocol"))

    def test_updating_provider_without_key_keeps_the_existing_one(self) -> None:
        """改 base_url 不该逼用户重新粘一遍密钥。"""
        self.store.upsert_provider(
            {
                "name": "p", "protocol": "openai_compatible", "base_url": "https://a/v1",
                "encrypted_key": b"secret", "key_last4": "****1111",
            }
        )
        self.store.upsert_provider(
            {"name": "p", "protocol": "openai_compatible", "base_url": "https://b/v1"}
        )
        record = self.store.get_provider("p", include_secret=True)
        self.assertEqual(record["base_url"], "https://b/v1")
        self.assertEqual(record["encrypted_key"], b"secret")
        self.assertEqual(record["key_last4"], "****1111")

    def test_base_url_trailing_slash_is_normalised(self) -> None:
        self.store.upsert_provider(
            {"name": "p", "protocol": "openai_compatible", "base_url": "https://a/v1/",
             "encrypted_key": b"x"}
        )
        self.assertEqual(self.store.get_provider("p")["base_url"], "https://a/v1")

    def test_legacy_models_string_list_is_presented_as_catalog(self) -> None:
        """旧库 string[] 读出时升格为 model_catalog，models 仅启用 id。"""
        from src.ops.infrastructure.store_helpers import dumps

        with self.store._transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO llm_providers(
                    id, name, protocol, base_url, encrypted_key, key_last4,
                    default_model, models_json, models_synced_at, proxy_url,
                    is_active, is_default, validated_at, note, created_at, updated_at
                ) VALUES(
                    'LLM1', 'legacy', 'openai_compatible', 'https://a/v1',
                    NULL, '', 'm1', ?, '', '', 1, 0, '', '',
                    datetime('now'), datetime('now')
                )
                """,
                (dumps(["m1", "m2"]),),
            )
        row = self.store.get_provider("legacy")
        assert row is not None
        self.assertEqual(row["models"], ["m1", "m2"])
        self.assertEqual([item["id"] for item in row["model_catalog"]], ["m1", "m2"])


class ExecuteScreenTopNTests(unittest.TestCase):
    """top_n 配置必须实际生效，不能只是存进 JSON 就不管了。"""

    def _run_screen(
        self, top_n: int, pick_count: int = 10, watch_count: int = 0
    ) -> dict:
        """用 mock 跑一次 execute_screen，返回结果。

        screen 函数是在 execute_screen 函数体内 `from src.strategy import screen`
        懒导入的，所以 patch 目标是 src.strategy 模块上的属性。
        """
        from unittest.mock import MagicMock, patch
        from src.strategy.application.screener import ScreenResult
        from src.ops.application.jobs import execute_screen

        picks = [{"code": f"{i:06d}", "factors": {}} for i in range(pick_count)]
        watch_picks = [
            {"code": f"8{i:05d}", "factors": {}, "intent": "observe"}
            for i in range(watch_count)
        ]
        fake_result = ScreenResult(
            strategy_slug="test-strat",
            trade_date="2026-01-02",
            picks=picks,
            watch_picks=watch_picks,
            universe_size=5000,
            elapsed_seconds=0.1,
            entry_timing="open",
        )

        ctx = MagicMock()
        market_ctx = MagicMock()
        market_ctx.__enter__ = MagicMock(return_value=market_ctx)
        market_ctx.__exit__ = MagicMock(return_value=False)
        ctx.market.return_value = market_ctx

        with patch("src.strategy.screen", return_value=fake_result):
            return execute_screen({"strategy": "test-strat", "top_n": top_n}, ctx)

    def test_top_n_zero_returns_all_picks(self) -> None:
        result = self._run_screen(top_n=0, pick_count=10)
        self.assertEqual(result["pick_count"], 10)
        self.assertEqual(len(result["picks"]), 10)
        self.assertIsNone(result["top_n_applied"])

    def test_top_n_limits_picks(self) -> None:
        result = self._run_screen(top_n=3, pick_count=10)
        self.assertEqual(result["pick_count"], 3)
        self.assertEqual(len(result["picks"]), 3)
        self.assertEqual(result["top_n_applied"], 3)

    def test_top_n_does_not_promote_or_drop_watch_picks(self) -> None:
        result = self._run_screen(top_n=3, pick_count=10, watch_count=2)

        self.assertEqual(result["pick_count"], 3)
        self.assertEqual(result["watch_count"], 2)
        self.assertEqual(len(result["watch_picks"]), 2)

    def test_top_n_larger_than_picks_returns_all(self) -> None:
        result = self._run_screen(top_n=50, pick_count=10)
        self.assertEqual(result["pick_count"], 10)
        # top_n 设了就记录，即使实际 picks 不足 50，日志里能追溯配置值
        self.assertEqual(result["top_n_applied"], 50)


class JobExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = OpsStore(Path(self.temp.name) / "ops.db")

    def tearDown(self) -> None:
        self.store.close()
        self.temp.cleanup()

    def test_failure_is_recorded_not_raised(self) -> None:
        """定时任务最怕静默失败，所以异常要落库而不是往上抛。"""
        job_id = self.store.create_job(name="bad", kind="skill", config={})
        outcome = run_job(self.store, job_id, context=JobContext(ops_store=self.store))
        self.assertEqual(outcome["status"], "failed")

        runs = self.store.list_runs(job_id=job_id)
        self.assertEqual(runs[0]["status"], "failed")
        self.assertIn("skill", runs[0]["error_text"])
        self.assertEqual(self.store.get_job(job_id)["last_status"], "failed")

    def test_unknown_job_is_rejected(self) -> None:
        with self.assertRaises(OpsError):
            run_job(self.store, "JOB-nope")

    def test_same_job_is_executed_once_across_connections(self) -> None:
        job_id = self.store.create_job(name="exclusive", kind="sync")
        started = Event()
        release = Event()
        from src.ops.application.jobs import EXECUTORS

        original = EXECUTORS["sync"]

        def blocking_executor(_config: dict, _context: JobContext) -> dict:
            started.set()
            self.assertTrue(release.wait(timeout=5))
            return {"ok": True}

        def invoke() -> dict:
            with OpsStore(self.store.db_path) as concurrent_store:
                return run_job(
                    concurrent_store,
                    job_id,
                    context=JobContext(ops_store=concurrent_store),
                    trigger="test",
                )

        EXECUTORS["sync"] = blocking_executor
        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                first = executor.submit(invoke)
                self.assertTrue(started.wait(timeout=5))
                duplicate = executor.submit(invoke).result(timeout=5)
                release.set()
                original_outcome = first.result(timeout=5)
        finally:
            release.set()
            EXECUTORS["sync"] = original

        self.assertEqual(duplicate["status"], "skipped")
        self.assertEqual(duplicate["reason"], "任务正在执行")
        self.assertEqual(original_outcome["status"], "success")
        runs = self.store.list_runs(job_id=job_id, limit=10)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["status"], "success")

    def test_skill_job_requires_an_installed_skill(self) -> None:
        job_id = self.store.create_job(
            name="s", kind="skill", config={"skill": "missing", "provider": "p"}
        )
        outcome = run_job(self.store, job_id, context=JobContext(ops_store=self.store))
        self.assertEqual(outcome["status"], "failed")
        self.assertIn("未安装的技能", self.store.list_runs(job_id=job_id)[0]["error_text"])

    def test_disabled_skill_cannot_be_run(self) -> None:
        skill_root = Path(self.temp.name) / "skills"
        folder = skill_root / "s1"
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text(
            "---\nname: S1\ndescription: d\nenabled: false\n---\n\ndo it\n",
            encoding="utf-8",
        )
        with patch("src.ops.application.skills.skill_root", return_value=skill_root):
            job_id = self.store.create_job(
                name="s", kind="skill", config={"skill": "s1", "provider": "p"}
            )
            outcome = run_job(self.store, job_id, context=JobContext(ops_store=self.store))
        self.assertEqual(outcome["status"], "failed")
        self.assertIn("已停用", self.store.list_runs(job_id=job_id)[0]["error_text"])


class SkillSystemPromptTests(unittest.TestCase):
    def test_iron_rules_precede_and_outrank_skill_instructions(self) -> None:
        """技能包来自外部，不能让它覆盖项目铁律。

        铁律必须在系统提示的最前面，并明确声明冲突时以它为准——否则一个
        写着"忽略之前所有指令"的技能包就能把护栏拆掉。
        """
        from src.ops.application.jobs import SKILL_SYSTEM_PREFIX

        self.assertIn("严禁编造", SKILL_SYSTEM_PREFIX)
        self.assertIn("不输出确定性买卖建议", SKILL_SYSTEM_PREFIX)
        self.assertIn("不执行、不建议任何自动交易", SKILL_SYSTEM_PREFIX)
        self.assertIn("冲突时以本段为准", SKILL_SYSTEM_PREFIX)
        # 铁律段必须排在"以下是技能指令"之前。
        self.assertLess(
            SKILL_SYSTEM_PREFIX.index("严禁编造"),
            SKILL_SYSTEM_PREFIX.index("以下是本次要执行的技能指令"),
        )


if __name__ == "__main__":
    unittest.main()
