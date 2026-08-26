"""批量水位:签名必须和同步侧的调用对得上。

这组测试守的是一个**静默退化**:`sync_engine._set_watermarks` 一直按
`sources=`(复数、按票给来源)调用,而 store 侧的形参是 `source=`(单数标量),
于是每次批量写都必然 TypeError,被 `except TypeError: pass` 吞掉后落到逐票兜底。
一次全市场同步 = 5547 个独立事务,且日志里一个字都没有。
"""
from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path

from src.market import MarketStore
from src.market.infrastructure.sync_engine import BatchWriter


class SetWatermarksSignatureTests(unittest.TestCase):
    def test_store_accepts_the_kwarg_sync_actually_passes(self) -> None:
        """调用方与实现的契约:这一条挂了就等于批量水位没生效。"""
        params = inspect.signature(MarketStore.set_watermarks).parameters
        self.assertIn("sources", params)
        self.assertIn("source", params)

    def test_sync_engine_no_longer_swallows_typeerror(self) -> None:
        """接口对不上是代码 bug,要炸出来;吞掉它正是这次事故藏了这么久的原因。"""
        import ast
        import textwrap

        tree = ast.parse(textwrap.dedent(inspect.getsource(BatchWriter._set_watermarks)))
        fn = tree.body[0]
        # 摘掉 docstring 再看:正文里不能有,注释里讲清来龙去脉是应该的。
        if (
            fn.body
            and isinstance(fn.body[0], ast.Expr)
            and isinstance(fn.body[0].value, ast.Constant)
        ):
            fn.body = fn.body[1:]
        handlers = [
            h.type.id
            for node in ast.walk(fn)
            if isinstance(node, ast.Try)
            for h in node.handlers
            if isinstance(h.type, ast.Name)
        ]
        self.assertNotIn("TypeError", handlers)


class SetWatermarksBehaviourTests(unittest.TestCase):
    def test_per_code_source_is_preserved(self) -> None:
        """粘性竞速会让同一批里混着 tdx / tencent,标量 source 表达不了。"""
        marks = [("%06d" % i, "2026-08-24") for i in range(6)]
        sources = {c: ("tdx" if i % 2 else "tencent") for i, (c, _d) in enumerate(marks)}
        with tempfile.TemporaryDirectory() as tmp:
            with MarketStore(str(Path(tmp) / "m.db")) as store:
                written = store.set_watermarks(marks, status="ok", sources=sources)
                self.assertEqual(written, 6)
                rows = dict(
                    store.conn.execute("SELECT code, source FROM ingest_watermark").fetchall()
                )
                self.assertEqual(rows, sources)

    def test_scalar_source_still_works(self) -> None:
        """老调用方(只给标量)语义不能变。"""
        with tempfile.TemporaryDirectory() as tmp:
            with MarketStore(str(Path(tmp) / "m.db")) as store:
                store.set_watermarks([("600519", "2026-08-24")], status="ok", source="tdx")
                row = store.conn.execute(
                    "SELECT source FROM ingest_watermark WHERE code = ?", ("600519",)
                ).fetchone()
                self.assertEqual(row[0], "tdx")

    def test_sources_falls_back_to_scalar_for_missing_codes(self) -> None:
        marks = [("600519", "2026-08-24"), ("000001", "2026-08-24")]
        with tempfile.TemporaryDirectory() as tmp:
            with MarketStore(str(Path(tmp) / "m.db")) as store:
                store.set_watermarks(
                    marks, status="ok", source="tdx", sources={"600519": "tencent"}
                )
                rows = dict(
                    store.conn.execute("SELECT code, source FROM ingest_watermark").fetchall()
                )
                self.assertEqual(rows["600519"], "tencent")
                self.assertEqual(rows["000001"], "tdx")

    def test_one_transaction_not_one_per_code(self) -> None:
        """退化成逐票写正是这次要修的问题,用事务条数把它钉住。"""
        marks = [("%06d" % i, "2026-08-24") for i in range(200)]
        with tempfile.TemporaryDirectory() as tmp:
            with MarketStore(str(Path(tmp) / "m.db")) as store:
                begins: list[str] = []
                store.conn.set_trace_callback(
                    lambda sql: begins.append(sql) if sql.strip().upper().startswith("BEGIN") else None
                )
                try:
                    store.set_watermarks(marks, status="ok")
                finally:
                    store.conn.set_trace_callback(None)
                # 200 只票,事务数必须是个位数而不是 200。
                self.assertLessEqual(len(begins), 2, begins[:5])


if __name__ == "__main__":
    unittest.main()
