"""盘中留存带：加密落盘、读回、过期删除的安全闸门。

背景见 `docs/adr/ADR-014-encrypted-intraday-tape-retention.md`。这批数据的特点是
**上游没有历史**（AkShare 侧 21 个接口只有当天快照），因此本模块的每个失败模式都
是「永久丢一天」，测试要比普通缓存更严。

全程离线：采集源由测试注入，不碰网络。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

import pandas as pd

from src.market.application.intraday import CaptureSpec, capture_snapshots, intraday_status
from src.market.infrastructure.intraday_archive import (
    IntradayArchiveError,
    day_dir,
    list_days,
    read_manifest,
    read_snapshot,
    validate_dataset,
    validate_trade_date,
    write_snapshot,
)
from src.market.infrastructure.intraday_keyring import load_or_create_key
from src.market.infrastructure.intraday_prune import (
    IntradayPruneError,
    prune_intraday,
)


def _frame(rows: int = 50) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "代码": [f"{i:06d}" for i in range(rows)],
            "名称": [f"股票{i}" for i in range(rows)],
            "最新价": [10.0 + i * 0.01 for i in range(rows)],
            "涨跌幅": [(i % 21) - 10.0 for i in range(rows)],
        }
    )


class ArchiveRoundTripTest(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.data = Path(self._dir.name)
        self.key = load_or_create_key(self.data / "intraday")

    def tearDown(self):
        self._dir.cleanup()

    def test_write_then_read_preserves_rows_and_columns(self):
        frame = _frame(120)
        record = write_snapshot(
            self.data,
            trade_date="2026-08-25",
            dataset="spot_close",
            frame=frame,
            source="test",
            key=self.key,
        )
        self.assertEqual(record.rows, 120)
        self.assertEqual(record.columns, list(frame.columns))
        back = read_snapshot(
            self.data, trade_date="2026-08-25", dataset="spot_close", key=self.key
        )
        self.assertEqual(len(back), 120)
        self.assertEqual(list(back.columns), list(frame.columns))

    def test_column_projection_reads_only_requested_columns(self):
        write_snapshot(
            self.data,
            trade_date="2026-08-25",
            dataset="spot_close",
            frame=_frame(30),
            source="test",
            key=self.key,
        )
        back = read_snapshot(
            self.data,
            trade_date="2026-08-25",
            dataset="spot_close",
            key=self.key,
            columns=["代码", "最新价"],
        )
        self.assertEqual(list(back.columns), ["代码", "最新价"])

    def test_empty_frame_is_refused(self):
        """空表必须报错：上游返空和「今天真的没有」在下游是同一个形状。"""
        with self.assertRaises(IntradayArchiveError):
            write_snapshot(
                self.data,
                trade_date="2026-08-25",
                dataset="limit_up_pool",
                frame=pd.DataFrame(),
                source="test",
                key=self.key,
            )

    def test_manifest_records_columns_as_drift_baseline(self):
        write_snapshot(
            self.data,
            trade_date="2026-08-25",
            dataset="spot_close",
            frame=_frame(10),
            source="akshare:stock_zh_a_spot_em",
            key=self.key,
        )
        body = read_manifest(self.data, "2026-08-25")
        self.assertEqual(body["contract_version"], "loci-intraday-manifest-v1")
        entry = body["files"][0]
        self.assertEqual(entry["dataset"], "spot_close")
        self.assertEqual(entry["columns"], ["代码", "名称", "最新价", "涨跌幅"])
        self.assertEqual(entry["source"], "akshare:stock_zh_a_spot_em")
        self.assertIn("akshare_version", body)

    def test_second_dataset_same_day_does_not_clobber_manifest(self):
        for name in ("spot_close", "limit_up_pool"):
            write_snapshot(
                self.data,
                trade_date="2026-08-25",
                dataset=name,
                frame=_frame(5),
                source="test",
                key=self.key,
            )
        body = read_manifest(self.data, "2026-08-25")
        self.assertEqual([f["dataset"] for f in body["files"]], ["limit_up_pool", "spot_close"])

    def test_manifest_is_plaintext_and_holds_no_quote_values(self):
        write_snapshot(
            self.data,
            trade_date="2026-08-25",
            dataset="spot_close",
            frame=_frame(5),
            source="test",
            key=self.key,
        )
        raw = (day_dir(self.data, "2026-08-25") / "manifest.json").read_text(encoding="utf-8")
        json.loads(raw)
        self.assertNotIn("10.01", raw)


class EncryptionTest(unittest.TestCase):
    """没有密钥必须硬失败，不能静默返回空表。"""

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.data = Path(self._dir.name)
        self.key = load_or_create_key(self.data / "intraday")

    def tearDown(self):
        self._dir.cleanup()

    def test_encrypted_file_is_unreadable_without_the_key(self):
        if not self.key.encrypted:
            self.skipTest("本机无 DPAPI，跳过加密断言")
        write_snapshot(
            self.data,
            trade_date="2026-08-25",
            dataset="spot_close",
            frame=_frame(20),
            source="test",
            key=self.key,
        )
        path = day_dir(self.data, "2026-08-25") / "spot_close.parquet.enc"
        self.assertTrue(path.exists())
        import duckdb

        con = duckdb.connect()
        with self.assertRaises(Exception):
            con.execute(f"SELECT * FROM read_parquet('{path.as_posix()}')").fetchall()
        con.close()

    def test_ciphertext_does_not_leak_stock_names(self):
        if not self.key.encrypted:
            self.skipTest("本机无 DPAPI，跳过加密断言")
        write_snapshot(
            self.data,
            trade_date="2026-08-25",
            dataset="spot_close",
            frame=_frame(20),
            source="test",
            key=self.key,
        )
        blob = (day_dir(self.data, "2026-08-25") / "spot_close.parquet.enc").read_bytes()
        self.assertNotIn("股票7".encode("utf-8"), blob)


class PruneGateTest(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.data = Path(self._dir.name)
        self.key = load_or_create_key(self.data / "intraday")

    def tearDown(self):
        self._dir.cleanup()

    def _seed(self, days):
        for day in days:
            write_snapshot(
                self.data,
                trade_date=day,
                dataset="spot_close",
                frame=_frame(5),
                source="test",
                key=self.key,
            )

    def test_deletes_only_days_older_than_cutoff(self):
        self._seed(["2026-01-01", "2026-06-01", "2026-08-20"])
        report = prune_intraday(
            self.data, retention_days=60, today=date(2026, 8, 25), max_delete=30
        )
        self.assertEqual(report.deleted, ["2026-01-01", "2026-06-01"])
        self.assertEqual(list_days(self.data), ["2026-08-20"])

    def test_dry_run_touches_nothing(self):
        self._seed(["2026-01-01", "2026-08-20"])
        report = prune_intraday(
            self.data, retention_days=60, today=date(2026, 8, 25), dry_run=True
        )
        self.assertEqual(report.deleted, ["2026-01-01"])
        self.assertEqual(list_days(self.data), ["2026-01-01", "2026-08-20"])

    def test_refuses_when_batch_exceeds_max_delete(self):
        self._seed([f"2026-01-{i:02d}" for i in range(1, 8)])
        with self.assertRaises(IntradayPruneError):
            prune_intraday(
                self.data, retention_days=60, today=date(2026, 8, 25), max_delete=3
            )
        self.assertEqual(len(list_days(self.data)), 7)

    def test_never_touches_non_date_entries(self):
        """闸门 2：.dek 和任何非日期目录都不许被扫进删除清单。"""
        self._seed(["2026-01-01"])
        root = self.data / "intraday"
        (root / "logs").mkdir()
        (root / "logs" / "keep.txt").write_text("keep me", encoding="utf-8")
        dek = root / ".dek"
        prune_intraday(self.data, retention_days=1, today=date(2026, 8, 25), max_delete=30)
        self.assertTrue((root / "logs" / "keep.txt").exists())
        self.assertEqual(dek.exists(), self.key.encrypted)

    def test_rejects_bad_retention(self):
        with self.assertRaises(IntradayPruneError):
            prune_intraday(self.data, retention_days=0)

    def test_missing_root_is_a_no_op(self):
        fresh = Path(self._dir.name) / "empty"
        fresh.mkdir()
        report = prune_intraday(fresh, retention_days=60)
        self.assertEqual(report.deleted, [])


class ValidationTest(unittest.TestCase):
    def test_dataset_name_blocks_path_traversal(self):
        for bad in ("../etc", "a/b", "UPPER", "", "x" * 80):
            with self.assertRaises(IntradayArchiveError):
                validate_dataset(bad)

    def test_trade_date_must_be_iso_day(self):
        for bad in ("2026-8-1", "20260825", "..", "2026-08-25/x"):
            with self.assertRaises(IntradayArchiveError):
                validate_trade_date(bad)
        self.assertEqual(validate_trade_date(" 2026-08-25 "), "2026-08-25")


class CaptureTest(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.data = Path(self._dir.name)

    def tearDown(self):
        self._dir.cleanup()

    def test_one_bad_source_does_not_sink_the_batch(self):
        def boom():
            raise RuntimeError("上游 502")

        specs = [
            CaptureSpec(dataset="good_one", source="t", fetch=lambda: _frame(9)),
            CaptureSpec(dataset="bad_one", source="t", fetch=boom),
            CaptureSpec(dataset="good_two", source="t", fetch=lambda: _frame(3)),
        ]
        report = capture_snapshots(self.data, specs, trade_date="2026-08-25")
        self.assertEqual([c["dataset"] for c in report.captured], ["good_one", "good_two"])
        self.assertEqual(len(report.failures), 1)
        self.assertEqual(report.failures[0]["stage"], "fetch")
        self.assertFalse(report.ok)

    def test_empty_upstream_lands_in_failures_not_as_a_silent_empty_day(self):
        specs = [CaptureSpec(dataset="limit_up_pool", source="t", fetch=pd.DataFrame)]
        report = capture_snapshots(self.data, specs, trade_date="2026-08-25")
        self.assertEqual(report.captured, [])
        self.assertEqual(report.failures[0]["stage"], "write")

    def test_status_reports_coverage(self):
        specs = [CaptureSpec(dataset="spot_close", source="t", fetch=lambda: _frame(4))]
        capture_snapshots(self.data, specs, trade_date="2026-08-24")
        capture_snapshots(self.data, specs, trade_date="2026-08-25")
        body = intraday_status(self.data)
        self.assertEqual(body["days"], 2)
        self.assertEqual(body["first_day"], "2026-08-24")
        self.assertEqual(body["datasets"]["spot_close"], 2)


if __name__ == "__main__":
    unittest.main()
