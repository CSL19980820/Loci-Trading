"""腾讯现价：量字段读不出来时不许用 0 冒充 —— 不打真网。

夹具 ``fixtures/tencent/qt_spot_boards.txt`` 是 2026-08-11 盘中录制的真实
``qt.gtimg.cn`` 报文；这里只把其中一根的**成交量字段**改坏来模拟报文变形，
不伪造价格。
"""
from __future__ import annotations

from pathlib import Path
import unittest

from src.market.infrastructure import tencent

FIXTURE = Path(__file__).parent / "fixtures" / "tencent" / "qt_spot_boards.txt"


def _lines() -> list[str]:
    raw = FIXTURE.read_text(encoding="utf-8")
    return [chunk for chunk in raw.split(";") if "~" in chunk]


def _line_for(symbol: str) -> str:
    for line in _lines():
        if symbol in line.split("~")[0]:
            return line
    raise AssertionError(f"夹具里没有 {symbol}")


def _with_broken_volume(line: str, *, replacement: str = "") -> str:
    fields = line.split("~")
    assert len(fields) > 36, len(fields)
    fields[36] = replacement
    return "~".join(fields)


class TencentSpotMissingVolumeTests(unittest.TestCase):
    def test_baseline_row_parses(self) -> None:
        row = tencent._parse_spot_row(_line_for("sh600519"))
        assert row is not None
        self.assertGreater(row["volume"], 0.0)
        self.assertGreater(row["amount"], 0.0)

    def test_unparseable_volume_drops_the_bar(self) -> None:
        """量缺失却有成交额时，落 0 量的当日 bar 会让量比/换手/放量形态全错。"""
        for bad in ("", "-", "null"):
            broken = _with_broken_volume(_line_for("sh600519"), replacement=bad)
            self.assertIsNone(tencent._parse_spot_row(broken), bad)

    def test_real_zero_volume_still_means_no_trade(self) -> None:
        """源侧确实回 0（停牌 / 竞价未成交）时行为不变：无量无额 → 不落 bar。"""
        fields = _line_for("sh600519").split("~")
        fields[36] = "0"
        fields[35] = "0.00/0/0.00/0/0"
        fields[37] = "0.00"
        self.assertIsNone(tencent._parse_spot_row("~".join(fields)))

    def test_live_row_keeps_the_quote_with_zero_volume(self) -> None:
        """live 只上屏不落库：量读不出来时保住报价行，volume 记 0。"""
        broken = _with_broken_volume(_line_for("sh600519"))
        row = tencent._parse_live_row(broken)
        assert row is not None
        self.assertEqual(row["volume"], 0.0)
        self.assertGreater(row["price"], 0.0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
