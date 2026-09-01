"""行情库体检:阈值判据与中文告警。

体检是换源之后唯一的日常防线,它自己不能出错——判据写反会让泡坏的库看起来全绿。
"""
from __future__ import annotations

from datetime import datetime
import sqlite3
import unittest

from src.market.application.data_quality import (
    Finding,
    QualityThresholds,
    build_alert,
    inspect_market_data,
)


class _FakeStore:
    """只提供 ``conn``——体检只读 SQL,不该碰 store 的其它面。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn


def _build_db(rows: list[tuple], *, instruments: list[tuple] | None = None,
            watermarks: list[tuple] | None = None) -> _FakeStore:
    conn = sqlite3.connect(":memory:")
    # high/low 默认取不相等:合成成交额判据要跳过「整日单一价格」日
    # (那天 amount = close*volume 是算术恒等,不是造假)。既有用例断言的
    # 都是「该被判为合成」,所以默认必须落在 high <> low 一侧。
    conn.execute(
        "CREATE TABLE quotes_daily (code TEXT, trade_date TEXT, close REAL,"
        " volume REAL, amount REAL, source TEXT, receipt_id TEXT,"
        " high REAL DEFAULT 2.0, low REAL DEFAULT 1.0)"
    )
    conn.executemany(
        "INSERT INTO quotes_daily(code, trade_date, close, volume, amount,"
        " source, receipt_id) VALUES (?,?,?,?,?,?,?)",
        rows,
    )
    conn.execute("CREATE TABLE trading_calendar (trade_date TEXT)")
    days = sorted({r[1] for r in rows})
    conn.executemany("INSERT INTO trading_calendar VALUES (?)", [(d,) for d in days])
    # 真实库的 instruments 带 instrument_type；覆盖率判据按它数股票只数。
    # 夹具跟着真实列走，否则新的比率分支永远走不到，等于没测。
    conn.execute(
        "CREATE TABLE instruments (code TEXT, status TEXT,"
        " instrument_type TEXT DEFAULT 'STOCK')"
    )
    conn.executemany(
  "INSERT INTO instruments(code, status) VALUES (?,?)", instruments or []
    )
    conn.execute(
        "CREATE TABLE ingest_watermark (code TEXT, source TEXT, status TEXT,"
        " last_trade_date TEXT)"
    )
    conn.executemany(
        "INSERT INTO ingest_watermark VALUES (?,?,?,?)", watermarks or []
    )
    return _FakeStore(conn)


def _healthy_rows(count: int = 20) -> list[tuple]:
    """tdx 源 + 真实成交额(amount != close*volume)+ 有回执。"""
    return [
        ("%06d" % i, "2026-08-24", 10.0, 1000.0, 12345.0, "tdx", "r%d" % i)
        for i in range(count)
    ]


# 覆盖率判据按 `instruments` 里的股票数算；这些用例的夹具不建 instruments，
# 于是走「证券列表为空」分支，只比绝对地板 —— 设成 1 行即恒过。
LOOSE = QualityThresholds(min_last_day_rows_floor=1, min_authoritative_ratio=0.95)


class AuthoritativeRatioTests(unittest.TestCase):
    def test_all_tdx_is_ok(self) -> None:
        store = _build_db(_healthy_rows())
        report = inspect_market_data(store, thresholds=LOOSE)
        self.assertFalse(report["blocked"])
        self.assertEqual(report["alert"], "")

    def test_fallback_majority_blocks(self) -> None:
        """主源长期失联 = 库在靠回退源续命,必须阻断,不能只是提醒。"""
        rows = _healthy_rows(5) + [
            ("9%05d" % i, "2026-08-24", 10.0, 1000.0, 12345.0, "tencent", "r")
            for i in range(95)
        ]
        report = inspect_market_data(_build_db(rows), thresholds=LOOSE)
        self.assertTrue(report["blocked"])
        finding = next(f for f in report["findings"] if f["key"] == "authoritative_ratio")
        self.assertEqual(finding["level"], "block")
        self.assertIn("通达信", finding["message"])
        self.assertIn("resync_market_authoritative", finding["remediation"])


class FabricatedAmountTests(unittest.TestCase):
    def test_synth_amount_on_tdx_is_not_flagged(self) -> None:
        """关键判据:通达信给的是真实成交额,即使数值恰好相等也不算合成。"""
        rows = [
            ("%06d" % i, "2026-08-24", 10.0, 1000.0, 10000.0, "tdx", "r")
            for i in range(50)
        ]
        report = inspect_market_data(_build_db(rows), thresholds=LOOSE)
        finding = next(f for f in report["findings"] if f["key"] == "fabricated_amount")
        self.assertEqual(finding["level"], "ok")
        self.assertEqual(finding["observed"]["rows"], 0)

    def test_synth_amount_on_tencent_is_flagged(self) -> None:
        rows = _healthy_rows(90) + [
            ("9%05d" % i, "2026-08-24", 10.0, 1000.0, 10000.0, "tencent", "r")
            for i in range(5)
        ]
        limits = QualityThresholds(min_last_day_rows_floor=1, max_fabricated_rows=2)
        report = inspect_market_data(_build_db(rows), thresholds=limits)
        finding = next(f for f in report["findings"] if f["key"] == "fabricated_amount")
        self.assertEqual(finding["level"], "warn")
        self.assertEqual(finding["observed"]["rows"], 5)
        self.assertIn("close×volume", finding["message"])


class SinglePriceDayTests(unittest.TestCase):
    """整日单一价格(high == low)时 amount = close*volume 是算术恒等。

    生产库曾报「合成成交额 8128 行」,实测 7721 行(95%)当日 high == low:
    1990 年代涨跌停加薄成交、北交所/新三板低流动性个股,整日一价是常态。
    把它们报成假值,等于让一条天天响、照着做又没用的告警训练人忽略体检表。
    """

    def _fab(self, report: dict) -> dict:
        return next(f for f in report["findings"] if f["key"] == "fabricated_amount")

    def test_single_price_day_is_not_fabricated(self) -> None:
        """同一批数字,high == low 就不该被算进合成行。"""
        store = _build_db(_healthy_rows(90))
        conn = store.conn
        conn.executemany(
            "INSERT INTO quotes_daily(code, trade_date, close, volume, amount,"
            " source, receipt_id, high, low) VALUES (?,?,?,?,?,?,?,?,?)",
            [
                ("9%05d" % i, "2026-08-24", 10.0, 1000.0, 10000.0, "tencent", "r", 10.0, 10.0)
                for i in range(50)
            ],
        )
        report = inspect_market_data(
            store, thresholds=QualityThresholds(max_fabricated_rows=2,
                            min_last_day_rows_floor=1)
        )
        found = self._fab(report)
        self.assertEqual(found["level"], "ok", found["message"])
        self.assertEqual(found["observed"]["rows"], 0)

    def test_intraday_range_with_synth_amount_still_flagged(self) -> None:
        """放宽不等于放弃:当日有价差却恰好等于 close*volume,仍是真嫌疑。"""
        store = _build_db(_healthy_rows(90))
        store.conn.executemany(
            "INSERT INTO quotes_daily(code, trade_date, close, volume, amount,"
            " source, receipt_id, high, low) VALUES (?,?,?,?,?,?,?,?,?)",
            [
                ("9%05d" % i, "2026-08-24", 10.0, 1000.0, 10000.0, "tencent", "r", 10.5, 9.5)
                for i in range(50)
            ],
        )
        report = inspect_market_data(
            store, thresholds=QualityThresholds(max_fabricated_rows=2,
                            min_last_day_rows_floor=1)
        )
        found = self._fab(report)
        self.assertEqual(found["level"], "warn")
        self.assertEqual(found["observed"]["rows"], 50)


class IndexSanityTests(unittest.TestCase):
    def test_index_串成个股_blocks(self) -> None:
        """中证 500 该 7717,串成同号个股会返回 8.54——这是真出过的事故。"""
        rows = _healthy_rows(10) + [
            ("000905", "2026-08-24", 8.54, 1000.0, 12345.0, "tdx", "r"),
        ]
        report = inspect_market_data(_build_db(rows), thresholds=LOOSE)
        self.assertTrue(report["blocked"])
        finding = next(f for f in report["findings"] if f["key"] == "index_sanity")
        self.assertEqual(finding["level"], "block")
        self.assertIn("get_index_bars", finding["message"])

    def test_real_index_level_is_ok(self) -> None:
        rows = _healthy_rows(10) + [
            ("000905", "2026-08-24", 7717.0, 1000.0, 12345.0, "tdx", "r"),
        ]
        report = inspect_market_data(_build_db(rows), thresholds=LOOSE)
        finding = next(f for f in report["findings"] if f["key"] == "index_sanity")
        self.assertEqual(finding["level"], "ok")


class WatermarkTests(unittest.TestCase):
    def test_delisted_non_tdx_watermark_is_explained(self) -> None:
        """退市票通达信取不到是正常的,不该天天报警。"""
        store = _build_db(
            _healthy_rows(10),
            instruments=[("920305", "delisted")],
            watermarks=[("920305", "sina", "ok", "2026-07-29")],
        )
        report = inspect_market_data(store, thresholds=LOOSE)
        finding = next(f for f in report["findings"] if f["key"] == "watermark_source")
        self.assertEqual(finding["level"], "ok")

    def test_active_non_tdx_watermark_warns(self) -> None:
        store = _build_db(
            _healthy_rows(10),
            instruments=[("600519", "listed")],
            watermarks=[("600519", "tencent", "ok", "2026-07-29")],
        )
        report = inspect_market_data(store, thresholds=LOOSE)
        finding = next(f for f in report["findings"] if f["key"] == "watermark_source")
        self.assertEqual(finding["level"], "warn")


class LastDayCoverageTests(unittest.TestCase):
    """覆盖率判据。这一组是为一次真实误报写的回归护栏:

    生产库当日覆盖 4935 行、证券列表 4932 只(**100.1%**,已经全了),却因为
    旧判据写死 `min_last_day_rows = 5000` 而天天报警。绝对阈值扛不住退市与
    扩容带来的漂移;判据一旦永远为真,人就会开始忽略整张体检表。
    """

    def _finding(self, report: dict) -> dict:
        return next(f for f in report["findings"] if f["key"] == "last_day_rows")

    def test_full_coverage_is_ok_even_below_the_old_absolute_floor(self) -> None:
        """4935 / 4932 = 100.1%:判绿。旧的「≥5000 行」在这里会误报。"""
        rows = _healthy_rows(40)
        store = _build_db(rows, instruments=[(r[0], "listed") for r in rows])
        report = inspect_market_data(
            store, thresholds=QualityThresholds(min_authoritative_ratio=0.95)
        )
        found = self._finding(report)
        self.assertEqual(found["level"], "ok", found["message"])
        self.assertEqual(found["observed"]["universe"], 40)
        self.assertGreaterEqual(found["observed"]["coverage"], 1.0)

    def test_half_the_market_missing_still_warns(self) -> None:
        """放宽判据不等于放弃判据:真缺一半仍要报。"""
        rows = _healthy_rows(10)
        listed = [("%06d" % i, "listed") for i in range(40)]
        store = _build_db(rows, instruments=listed)
        report = inspect_market_data(
            store, thresholds=QualityThresholds(min_authoritative_ratio=0.95)
        )
        found = self._finding(report)
        self.assertEqual(found["level"], "warn")
        self.assertIn("25.0%", found["message"])

    def test_missing_instruments_table_degrades_instead_of_crashing(self) -> None:
        """体检是最后一道防线:辅助表读不到该退化,不该抛栈把任务刷红。"""
        store = _build_db(_healthy_rows(20))
        # 表在、但没有 instrument_type 列:旧库或精简夹具的真实形态。
        store.conn.execute("DROP TABLE instruments")
        store.conn.execute("CREATE TABLE instruments (code TEXT, status TEXT)")
        report = inspect_market_data(store, thresholds=LOOSE)
        found = self._finding(report)
        self.assertEqual(found["level"], "ok", found["message"])
        self.assertIn("证券列表为空", found["message"])

    def test_empty_db_is_not_silently_passed(self) -> None:
        """证券列表为空时退回绝对地板——空库不能因为「比率算不出来」而蒙混过关。"""
        store = _build_db(_healthy_rows(3))
        # 表在、但没有 instrument_type 列:旧库或精简夹具的真实形态。
        store.conn.execute("DROP TABLE instruments")
        store.conn.execute("CREATE TABLE instruments (code TEXT, status TEXT)")
        report = inspect_market_data(
            store, thresholds=QualityThresholds(min_last_day_rows_floor=500)
        )
        found = self._finding(report)
        self.assertEqual(found["level"], "warn")
        self.assertIn("地板", found["message"])


def _codes(count: int, start: int = 600000) -> list[str]:
    r"""从 600000 起编号。**不能用 ``"%06d" % i``**:那会造出 000300 / 000852 /
    000905 三个基准指数伪代码,收盘价 10.0 会被 `index_sanity` 判成「指数串成同号
    个股」而阻断——那是另一条判据的事故,不该混进本组结论。"""
    return ["%06d" % (start + i) for i in range(count)]


class LastDayAuthoritativeTests(unittest.TestCase):
    r"""最后一个交易日的权威源占比——全库口径的结构性盲区。

    `authoritative_ratio` 的分母是**全部历史**。生产库只读实测(2026-08-26):
    全库 16,966,403 行里 tdx 占 16,376,434 行 = **96.5%**,稳稳压在 95% 线之上
    判绿;而同一时刻最后一个交易日 2026-08-25 的 5542 行里 tdx **0 行**——
    主源当天一行都没写进来,全库判据却一声不吭。

    这不是「迟几天会报」,而是**几乎永远不报**:要把 96.5% 压到 95% 以下,还得再
    灌 271,948 行非权威数据,按每天 5542 行算是 **49 个交易日**。真库从
    2026-07-28 起当日权威源占比就从 ~98% 掉到 ~20.7%、08-25 归零,20 个交易日
    过去,全库口径依然是绿的。

    夹具按**比例**复刻而不是按绝对行数:1600 万行插进 :memory: 要几分钟,而判据
    只看比例。12 万行历史 tdx : 5000 行当日 tencent = 96.0% 全库占比,同样能把
    旧判据喂绿——盲区靠的是「历史体量压过当日体量」,与绝对量级无关。
    """

    _LAST_DAY = "2026-08-25"
    _UNIVERSE = 5000

    def _finding(self, report: dict) -> dict:
        keys = [f["key"] for f in report["findings"]]
        self.assertIn(
            "last_day_authoritative",
            keys,
            "体检表里没有「最后一个交易日权威源占比」这条判据;当前只有 %s" % keys,
        )
        return next(
            f for f in report["findings"] if f["key"] == "last_day_authoritative"
        )

    def _store(self, last_day_rows: list[tuple]) -> _FakeStore:
        """12 万行全 tdx 历史 + 调用方给定的最后一个交易日。

        历史落在 2026-06 整月(30 天 x 4000 只),既让全库 tdx 占比停在 96.0%
        (旧判据判绿),又都带回执、都落在 `missing_receipts` 的近 90 日窗口内,
        不会有别的判据抢先变红把结论搅浑。
        """
        history = [
            (code, "2026-06-%02d" % (day + 1), 10.0, 1000.0, 12345.0, "tdx", "r")
            for day in range(30)
            for code in _codes(4000)
        ]
        return _build_db(
            history + last_day_rows,
            instruments=[(code, "listed") for code in _codes(self._UNIVERSE)],
        )

    def _last_day(self, source: str, count: int = 5000) -> list[tuple]:
        return [
            (code, self._LAST_DAY, 10.0, 1000.0, 12345.0, source, "r")
            for code in _codes(count)
        ]

    def test_last_day_all_tencent_is_caught_while_library_stays_green(self) -> None:
        """本组的核心用例:全库判绿的同时,当天主源 0 行必须被报出来。"""
        report = inspect_market_data(self._store(self._last_day("tencent")))

        # 盲区本身:全库判据看不见。这两条断言修复前后都成立。
        whole = next(
            f for f in report["findings"] if f["key"] == "authoritative_ratio"
        )
        self.assertEqual(whole["level"], "ok", whole["message"])
        self.assertGreaterEqual(whole["observed"]["ratio"], 0.95)

        found = self._finding(report)
        self.assertEqual(found["level"], "warn", found["message"])
        self.assertEqual(found["observed"]["trade_date"], self._LAST_DAY)
        self.assertEqual(found["observed"]["authoritative_rows"], 0)
        self.assertEqual(found["observed"]["settled_rows"], 5000)
        self.assertIn(self._LAST_DAY, found["message"])
        # 告警文案必须真的出得来——它是企微推送唯一读的字段。
        self.assertIn(self._LAST_DAY, report["alert"])

    def test_healthy_last_day_is_ok(self) -> None:
        """放宽不等于放弃:当天 tdx 写满就判绿,少量 spot 残留不影响结论。"""
        rows = self._last_day("tdx", 4900) + [
            (code, self._LAST_DAY, 10.0, 1000.0, 12345.0, "tencent_spot", "r")
            for code in _codes(100, start=604900)
        ]
        found = self._finding(inspect_market_data(self._store(rows)))
        self.assertEqual(found["level"], "ok", found["message"])
        self.assertEqual(found["observed"]["ratio"], 1.0)
        self.assertEqual(found["observed"]["provisional_rows"], 100)

    def test_tdx_spot_rows_are_provisional_not_authoritative(self) -> None:
        """`tdx_spot` 是当天的临时行,不能拿它冒充「主源已经写进来了」。

        否则只要盘中 spot 走了通达信,占比就被洗绿,而日终真正该落的正式日 K
        根本没来——那恰恰是本判据要抓的形态。
        """
        rows = self._last_day("tencent", 3000) + [
            (code, self._LAST_DAY, 10.0, 1000.0, 12345.0, "tdx_spot", "r")
            for code in _codes(2000, start=603000)
        ]
        found = self._finding(inspect_market_data(self._store(rows)))
        self.assertEqual(found["level"], "warn", found["message"])
        self.assertEqual(found["observed"]["authoritative_rows"], 0)
        self.assertEqual(found["observed"]["provisional_rows"], 2000)
        self.assertEqual(found["observed"]["settled_rows"], 3000)

    def test_intraday_all_spot_day_does_not_false_alarm(self) -> None:
        """盘中手动跑体检:当天本来就全是 spot 临时行,判红等于天天误报。"""
        rows = [
            (code, "2026-08-26", 10.0, 1000.0, 12345.0, "tencent_spot", "r")
            for code in _codes(self._UNIVERSE)
        ]
        report = inspect_market_data(
            self._store(rows), now=datetime(2026, 8, 26, 11, 0)
        )
        found = self._finding(report)
        self.assertEqual(found["level"], "ok", found["message"])
        self.assertIn("尚未定稿", found["message"])

    def test_all_spot_day_after_settle_deadline_warns(self) -> None:
        """同一批 spot 行,过了日终定稿窗口还没被正式日 K 改写,就是真问题。

        「盘中全是 spot」这个豁免必须带时限,否则日终同步整个失败的那天会被
        当成「还没定稿」白白放过——那恰恰是最该当天知道的一天。
        """
        rows = [
            (code, "2026-08-26", 10.0, 1000.0, 12345.0, "tencent_spot", "r")
            for code in _codes(self._UNIVERSE)
        ]
        report = inspect_market_data(
            self._store(rows), now=datetime(2026, 8, 26, 16, 30)
        )
        found = self._finding(report)
        self.assertEqual(found["level"], "warn", found["message"])
        self.assertIn("定稿", found["message"])

    def test_fallback_spot_warning_names_the_fabricated_amount(self) -> None:
        """回退源的临时行:必须明说成交额是合成假值、战法会算错。"""
        rows = [
            (code, "2026-08-26", 10.0, 1000.0, 12345.0, "tencent_spot", "r")
            for code in _codes(self._UNIVERSE)
        ]
        found = self._finding(
            inspect_market_data(self._store(rows), now=datetime(2026, 8, 26, 16, 30))
        )
        self.assertEqual(found["level"], "warn", found["message"])
        self.assertIn("close×volume", found["message"])
        self.assertIn("会算错", found["message"])
        self.assertEqual(found["observed"]["provisional_fallback_rows"], self._UNIVERSE)
        self.assertEqual(found["observed"]["provisional_authoritative_rows"], 0)

    def test_authoritative_spot_warning_does_not_claim_the_numbers_are_wrong(self) -> None:
        """``tdx_spot`` 满屏:仍然 warn(日终定稿没跑),但**不许**说数值不可用。

        ``TdxAdapter.fetch_spot`` 取的就是通达信日线的最后一根,成交额是真值、回执
        与换手齐全。生产实测(2026-08-26,4935 行全 ``tdx_spot``):合成成交额 4 行、
        缺回执 0 行、换手为空 0 行,``amount/(close*volume)`` 在 0.97~0.998 之间——
        不是 1.0000,也就是说 amount 是真的成交额而不是乘出来的。

        所以旧文案那句「临时行没有正式日 K 的成交额与复权口径」在这一档是**假话**。
        假话会让人整体不信这张表,那正是本模块最想避免的失效模式。
        """
        rows = [
            (code, "2026-08-26", 10.0, 1000.0, 12345.0, "tdx_spot", "r")
            for code in _codes(self._UNIVERSE)
        ]
        found = self._finding(
            inspect_market_data(self._store(rows), now=datetime(2026, 8, 26, 16, 30))
        )
        # 还是 warn:定稿这一步确实没跑,严格 PIT 会把这天认成未定稿。
        self.assertEqual(found["level"], "warn", found["message"])
        self.assertIn("读到的数字是对的", found["message"])
        # 但不许把合成假值的罪名扣到权威源内容上。
        self.assertNotIn("close×volume", found["message"])
        self.assertEqual(
            found["observed"]["provisional_authoritative_rows"], self._UNIVERSE
        )
        self.assertEqual(found["observed"]["provisional_fallback_rows"], 0)

    def test_threshold_is_tunable(self) -> None:
        """阈值是旋钮:放到 0 之后同一份库判绿,证明判据真的读了配置。"""
        limits = QualityThresholds(min_last_day_authoritative_ratio=0.0)
        found = self._finding(
            inspect_market_data(
                self._store(self._last_day("tencent")), thresholds=limits
            )
        )
        self.assertEqual(found["level"], "ok", found["message"])


class AlertTests(unittest.TestCase):
    def test_all_green_is_silent(self) -> None:
        """没事就别打扰人——全绿必须是空串,否则告警会被当噪音忽略。"""
        self.assertEqual(build_alert([Finding("a", "ok", "fine")]), "")

    def test_alert_carries_level_and_remediation(self) -> None:
        text = build_alert([
            Finding("a", "block", "主源没了", remediation="去看连通性"),
            Finding("b", "warn", "有点脏"),
            Finding("c", "ok", "没事"),
        ])
        self.assertIn("【阻断】主源没了", text)
        self.assertIn("处理：去看连通性", text)
        self.assertIn("【提醒】有点脏", text)
        self.assertNotIn("没事", text)


if __name__ == "__main__":
    unittest.main()