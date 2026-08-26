"""作业结果瘦身:逐票证据不得进 ops.db。

这条防线是被真实事故逼出来的:`screen` 作业把 `data_snapshot()` 的全库证据
原样写进 `job_runs.result_json`,单条 257 MB,694 行把 ops.db 撑到 5.67 GB,
`GET /api/jobs/runs`(默认 limit=50)一次返回 1.5 GB、耗时 97 秒。

`sync` 当初单独修过一次,但补丁只打在 sync 自己身上——所以这次收口到
`finish_run`。测试要守住的正是「收口」这件事:**任意 kind** 都得被压。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.ops.application.jobs.evidence import (
    RECEIPT_LIMIT,
    SAMPLE_LIMIT,
    compact_job_result,
)
from src.ops.infrastructure.store import OpsStore


def _evidence(n_receipts: int = 1000, n_attempts: int = 2000) -> dict:
    return {
        "receipts": [
            {"code": "%06d" % i, "state": "failed" if i % 100 == 0 else "ok",
              "unresolved": i % 100 == 0}
            for i in range(n_receipts)
        ],
        "attempts": [{"source_id": "tdx", "code": "%06d" % i} for i in range(n_attempts)],
        "observed_codes": ["%06d" % i for i in range(n_receipts)],
        "sources": ["tdx", "tencent"],
    }


class CompactJobResultTests(unittest.TestCase):
    def test_receipts_keep_only_failed_samples(self) -> None:
        """失败样本才有诊断价值;成功回执的权威副本在 market.db。"""
        payload = {"source_evidence": _evidence()}
        self.assertEqual(compact_job_result(payload), 1)
        ev = payload["source_evidence"]
        self.assertLessEqual(len(ev["receipts"]), RECEIPT_LIMIT)
        self.assertTrue(all(r["unresolved"] for r in ev["receipts"]))
        self.assertEqual(ev["receipts_total"], 1000)
        self.assertEqual(ev["receipts_failed"], 10)
        self.assertIn("market.db", ev["receipts_source"])

    def test_attempts_are_also_capped(self) -> None:
        """当初只压 receipts 是漏网:attempts 实测能到 18.8 万条 / 89 MB。"""
        payload = {"source_evidence": _evidence()}
        compact_job_result(payload)
        ev = payload["source_evidence"]
        self.assertEqual(len(ev["attempts"]), SAMPLE_LIMIT)
        self.assertEqual(ev["attempts_total"], 2000)
        self.assertEqual(len(ev["observed_codes"]), SAMPLE_LIMIT)

    def test_nested_evidence_is_found(self) -> None:
        """screen 把证据埋在 data_snapshot 下,不是顶层。"""
        payload = {"data_snapshot": {"source_evidence": _evidence()}}
        self.assertEqual(compact_job_result(payload), 1)
        self.assertEqual(
            payload["data_snapshot"]["source_evidence"]["receipts_total"], 1000
        )

    def test_small_payload_is_untouched(self) -> None:
        """没超阈值就别改——压缩不该把正常结果也改得面目全非。"""
        payload = {"source_evidence": {"sources": ["tdx"], "attempts": [{"a": 1}]}}
        compact_job_result(payload)
        self.assertEqual(payload["source_evidence"]["attempts"], [{"a": 1}])
        self.assertNotIn("attempts_total", payload["source_evidence"])

    def test_non_dict_result_survives(self) -> None:
        for value in (None, 3, "x", [1, 2]):
            self.assertEqual(compact_job_result(value), 0)

    def test_cycle_does_not_hang(self) -> None:
        """深度上限的意义:收尾流程卡死会让运行永远停在 running 占着槽。"""
        node: dict = {}
        node["self"] = node
        self.assertEqual(compact_job_result(node), 0)


class FinishRunCompactionTests(unittest.TestCase):
    def test_any_kind_is_compacted_at_the_write_choke_point(self) -> None:
        """收口的意义:不是只修 screen,是任何 kind 都别想把逐票证据写进来。"""
        for kind in ("screen", "sync", "backtest"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                with OpsStore(str(Path(tmp) / "ops.db")) as store:
                    job_id = store.create_job(
                        name="t-" + kind, kind=kind, cron="0 0 * * *", config={}
                    )
                    run_id = store.start_run(store.get_job(job_id), trigger="manual")
                    result = {"data_snapshot": {"source_evidence": _evidence(5000, 5000)}}
                    raw = len(json.dumps(result, ensure_ascii=False))
                    store.finish_run(
                        run_id, status="success", result=result, duration_ms=1
                    )
                    stored = store.conn.execute(
                        "SELECT LENGTH(result_json) FROM job_runs WHERE id = ?",
                        (run_id,),
                    ).fetchone()[0]
                    self.assertLess(stored, raw / 20)
                    self.assertLess(stored, 100_000)

    def test_run_still_finishes_when_result_is_odd(self) -> None:
        """瘦身失败也必须让运行正常收尾,否则占槽比丢证据严重得多。"""
        with tempfile.TemporaryDirectory() as tmp:
            with OpsStore(str(Path(tmp) / "ops.db")) as store:
                job_id = store.create_job(
                    name="odd", kind="sync", cron="0 0 * * *", config={}
                )
                run_id = store.start_run(store.get_job(job_id), trigger="manual")
                store.finish_run(run_id, status="success", result={"ok": True})
                row = store.get_run(run_id)
                assert row is not None
                self.assertEqual(row["status"], "success")


class IdempotenceTests(unittest.TestCase):
    def test_compacting_twice_keeps_the_real_totals(self) -> None:
        """压第二遍不能把 total 写成上一遍留下的样本数。

        调用方常常拿浅拷贝,同一份 source_evidence 会被同一轮里的多个写入点
        反复传进来(逐条候选各存一份快照就是)。不幂等的话 receipts_total 会从
        133640 变成 50——看起来是对的,所以比不压更危险。
        """
        evidence = _evidence(1000, 2000)
        payload = {"source_evidence": evidence}
        self.assertEqual(compact_job_result(payload), 1)
        for _ in range(3):
            self.assertEqual(compact_job_result(payload), 0)
        self.assertEqual(evidence["receipts_total"], 1000)
        self.assertEqual(evidence["attempts_total"], 2000)

    def test_shallow_copy_aliasing_is_safe(self) -> None:
        """persist 里就是 dict(data_snapshot) 浅拷贝后再压。"""
        shared = {"source_evidence": _evidence(500, 500)}
        for _ in range(5):
            compact_job_result(dict(shared))
        self.assertEqual(shared["source_evidence"]["receipts_total"], 500)


class CandidateEvidenceTests(unittest.TestCase):
    def test_persist_compacts_the_snapshot_it_stores(self) -> None:
        """候选证据里的快照必须先瘦身:227 行曾占掉 palace.db 的 99%。"""
        import inspect

        from src.strategy.application import persist

        src = inspect.getsource(persist)
        # 写入点必须经过压缩,而不是直接 dict(data_snapshot) 塞进去。
        self.assertIn("compact_job_result(snapshot)", src)
        self.assertNotIn('evidence["_data_snapshot"] = dict(data_snapshot)', src)


if __name__ == "__main__":
    unittest.main()
