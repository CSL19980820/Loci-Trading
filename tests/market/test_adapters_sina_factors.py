"""新浪后复权因子：取数失败不得伪装成「这只票没有除权事件」 —— 不打真网。

夹具 ``fixtures/sina/hfq_*.js`` 是 2026-08-11 从 ``finance.sina.com.cn`` 录制的
真实报文（含尾部 JS 注释块），用来锁住解析口径。
"""
from __future__ import annotations

from pathlib import Path
import unittest
from unittest import mock

import pandas as pd

from src.market.infrastructure import sina
from src.market.infrastructure.adapters.base import AdapterError
from src.market.infrastructure.adapters.sina_adapter import SinaAdapter
from src.market.infrastructure.sources import SinaSource, SourceError

FIXTURES = Path(__file__).parent / "fixtures" / "sina"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class SinaHfqFactorParseTests(unittest.TestCase):
    def test_parses_recorded_payload_ascending(self) -> None:
        with mock.patch.object(sina, "_get", return_value=_fixture("hfq_sh688981.js")):
            frame = sina.fetch_hfq_factors("sh688981")
        self.assertEqual(list(frame.columns), ["date", "hfq_factor"])
        self.assertEqual(len(frame), 2)
        self.assertEqual(str(frame.iloc[0]["date"]), "1900-01-01")
        self.assertEqual(str(frame.iloc[-1]["date"]), "2020-07-16")

    def test_parses_a_long_dividend_history(self) -> None:
        with mock.patch.object(sina, "_get", return_value=_fixture("hfq_sh600519.js")):
            frame = sina.fetch_hfq_factors("sh600519")
        self.assertGreater(len(frame), 20)
        dates = list(frame["date"])
        self.assertEqual(dates, sorted(dates))
        self.assertTrue((frame["hfq_factor"] > 0).all())

    def test_network_failure_raises_instead_of_returning_empty(self) -> None:
        """404 / 超时被吞成空表时，调用方会当成「无需复权」按不复权价画图。"""
        with mock.patch.object(
            sina, "_get", side_effect=sina.SinaFetchError("返回 404")
        ):
            with self.assertRaises(sina.SinaFetchError):
                sina.fetch_hfq_factors("sh999999")

    def test_payload_without_json_raises(self) -> None:
        with mock.patch.object(sina, "_get", return_value="<html>502</html>"):
            with self.assertRaises(sina.SinaFetchError):
                sina.fetch_hfq_factors("sh600519")

    def test_broken_json_raises(self) -> None:
        with mock.patch.object(sina, "_get", return_value='var x={"data":[{'):
            with self.assertRaises(sina.SinaFetchError):
                sina.fetch_hfq_factors("sh600519")

    def test_unparseable_rows_raise_rather_than_look_empty(self) -> None:
        payload = 'var x={"total":2,"data":[{"d":"x","f":"y"},{"d":"z","f":"w"}]}'
        with mock.patch.object(sina, "_get", return_value=payload):
            with self.assertRaises(sina.SinaFetchError):
                sina.fetch_hfq_factors("sh600519")

    def test_no_dividend_event_is_still_an_empty_table(self) -> None:
        """票存在但没有除权除息：这才是合法的空表。"""
        for body in ('var x={"total":0,"data":null}', 'var x={"total":0,"data":[]}'):
            with mock.patch.object(sina, "_get", return_value=body):
                frame = sina.fetch_hfq_factors("sz301618")
            self.assertTrue(frame.empty)
            self.assertEqual(list(frame.columns), ["date", "hfq_factor"])


class SinaFactorFailurePropagationTests(unittest.TestCase):
    """失败要一路向上冒到线路层，错误文案说清是「取不到」不是「没有」。"""

    def test_source_wraps_failure_as_source_error(self) -> None:
        with mock.patch.object(
            sina, "fetch_hfq_factors", side_effect=sina.SinaFetchError("返回 404")
        ):
            with self.assertRaises(SourceError) as ctx:
                SinaSource().fetch_adjust_factors("600519")
        self.assertIn("复权因子失败", str(ctx.exception))

    def test_adapter_wraps_failure_as_adapter_error(self) -> None:
        with mock.patch.object(
            sina, "fetch_hfq_factors", side_effect=sina.SinaFetchError("Timeout")
        ):
            with self.assertRaises(AdapterError):
                SinaAdapter().fetch_adjust_factors("600519")

    def test_empty_table_still_flows_through_untouched(self) -> None:
        empty = pd.DataFrame(columns=["date", "hfq_factor"])
        with mock.patch.object(sina, "fetch_hfq_factors", return_value=empty):
            frame = SinaSource().fetch_adjust_factors("600519")
        self.assertTrue(frame.empty)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
