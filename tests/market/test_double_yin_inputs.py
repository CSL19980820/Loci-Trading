"""外部竞价报价和板块分类契约；所有网络与时间均为隔离替身。"""
from datetime import datetime, timezone
import sqlite3
import threading
import time

import pytest

from src.market.application import double_yin_inputs as inputs

DAY = "2026-10-08"
NOW = datetime.fromisoformat(DAY + "T09:25:01+08:00")


def quote(code="300750", **changes):
    return {"code": code, "name": "宁德时代", "open": 10.6, "prev_close": 11,
            "price": 10.7, "volume": 12500, "trade_date": DAY, "trade_time": "09:25:00",
            **changes}


@pytest.fixture(autouse=True)
def isolated_sources(monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("外部边界不能读取真实数据库或发送未替换网络请求")
    monkeypatch.setattr(sqlite3, "connect", unexpected)
    monkeypatch.setattr(inputs, "market_get", unexpected)
    monkeypatch.setattr(inputs.SinaAdapter, "fetch_live_quotes", unexpected)
    monkeypatch.setattr(inputs, "OPENING_RETRY_SECONDS", 0.02)
    monkeypatch.setattr(inputs, "OPENING_RETRY_INTERVAL", 0.02)


def test_valid_opening_uses_only_requested_candidate_and_preserves_share_units(monkeypatch):
    calls = []
    def fetch(self, codes):
        calls.append(codes)
        return [quote(), quote("600519", name="额外股票")]
    monkeypatch.setattr(inputs.SinaAdapter, "fetch_live_quotes", fetch)
    quotes, snapshot = inputs.fetch_double_yin_openings(["300750", "300750"], trade_date=DAY, now=NOW)
    assert calls == [["300750"]]
    assert set(quotes) == {"300750"}
    assert quotes["300750"]["open"] == 10.6
    assert quotes["300750"]["volume"] == 12500
    assert snapshot["volume_unit"] == "share"
    assert snapshot["source_date"] == DAY
    assert snapshot["source_time_min"] == snapshot["source_time_max"] == "09:25:00"
    assert (snapshot["requested"], snapshot["returned"], snapshot["rejected"], snapshot["coverage"]) == (1, 1, 0, 1)
    assert "quotes" not in snapshot


@pytest.mark.parametrize(("changes", "reason"), [
    ({"name": ""}, "证券名称缺失"),
    ({"name": None}, "证券名称缺失"),
    ({"name": "   "}, "证券名称缺失"),
    ({"trade_date": "2026-09-30"}, "日期"),
    ({"trade_date": ""}, "日期"),
    ({"trade_time": ""}, "时间缺失"),
    ({"trade_time": "09:24:59"}, "尚未定盘"),
    ({"trade_time": "09:30:00"}, "连续竞价"),
    ({"trade_time": "09:26:00"}, "晚于"),
    ({"open": 0, "price": 10.6}, "不用现价回填"),
    ({"open": float("nan")}, "开盘价"),
    ({"open": True}, "开盘价"),
    ({"volume": 0}, "成交量"),
    ({"volume": None}, "成交量"),
    ({"volume": float("inf")}, "成交量"),
    ({"prev_close": None}, "前收盘价"),
    ({"prev_close": float("nan")}, "前收盘价"),
])
def test_ineligible_quotes_are_explicitly_rejected(monkeypatch, changes, reason):
    monkeypatch.setattr(inputs.SinaAdapter, "fetch_live_quotes", lambda self, codes: [quote(**changes)])
    quotes, snapshot = inputs.fetch_double_yin_openings(["300750"], trade_date=DAY, now=NOW)
    assert quotes == {}
    assert snapshot["failed_codes"] == ["300750"]
    assert reason in snapshot["rejects"]["300750"]
    assert snapshot["coverage"] == 0
    assert snapshot["source_dates_seen"] == [changes.get("trade_date", DAY)]


def test_delayed_opening_retries_only_missing_codes(monkeypatch):
    calls = []
    monkeypatch.setattr(inputs, "OPENING_RETRY_SECONDS", 0.1)
    monkeypatch.setattr(inputs, "OPENING_RETRY_INTERVAL", 0)
    def fetch(self, codes):
        calls.append(codes)
        return [quote()] if len(calls) == 1 else [quote("600519", name="贵州茅台")]
    monkeypatch.setattr(inputs.SinaAdapter, "fetch_live_quotes", fetch)
    quotes, snapshot = inputs.fetch_double_yin_openings(["300750", "600519"], trade_date=DAY, now=NOW)
    assert calls == [["300750", "600519"], ["600519"]]
    assert set(quotes) == {"300750", "600519"}
    assert snapshot["attempts"] == 2


def test_repeated_calls_never_reuse_previous_opening(monkeypatch):
    calls = []
    def fetch(self, codes):
        calls.append(codes)
        return [quote(open=10 + len(calls))]
    monkeypatch.setattr(inputs.SinaAdapter, "fetch_live_quotes", fetch)
    first, _ = inputs.fetch_double_yin_openings(["300750"], trade_date=DAY, now=NOW)
    second, _ = inputs.fetch_double_yin_openings(["300750"], trade_date=DAY, now=NOW)
    assert first["300750"]["open"] == 11
    assert second["300750"]["open"] == 12
    assert len(calls) == 2


def test_wrong_request_date_cannot_query_live_quote():
    with pytest.raises(inputs.RealtimeInputError, match="上海时间的当日"):
        inputs.fetch_double_yin_openings(["300750"], trade_date="2026-09-30", now=NOW)


def test_datetime_is_converted_to_shanghai(monkeypatch):
    monkeypatch.setattr(inputs.SinaAdapter, "fetch_live_quotes", lambda self, codes: [quote()])
    quotes, _ = inputs.fetch_double_yin_openings(["300750"], trade_date=DAY,
                                               now=datetime(2026, 10, 8, 1, 25, 1, tzinfo=timezone.utc))
    assert "300750" in quotes


def test_continuous_trading_time_cannot_pass_future_clock_tolerance(monkeypatch):
    monkeypatch.setattr(inputs.SinaAdapter, "fetch_live_quotes",
                        lambda self, codes: [quote(trade_time="09:30:02")])
    quotes, snapshot = inputs.fetch_double_yin_openings(
        ["300750"], trade_date=DAY, now=datetime.fromisoformat(DAY + "T09:29:59+08:00"),
    )
    assert quotes == {}
    assert "连续竞价" in snapshot["rejects"]["300750"]


def test_realtime_security_name_is_preserved_for_identity_revalidation(monkeypatch):
    monkeypatch.setattr(inputs.SinaAdapter, "fetch_live_quotes",
                        lambda self, codes: [quote(name="*ST 时代")])
    quotes, _ = inputs.fetch_double_yin_openings(["300750"], trade_date=DAY, now=NOW)
    assert quotes["300750"]["name"] == "*ST 时代"


def test_source_error_remains_rejected_and_does_not_fallback(monkeypatch):
    def failed(self, codes):
        raise OSError("offline")
    monkeypatch.setattr(inputs.SinaAdapter, "fetch_live_quotes", failed)
    quotes, snapshot = inputs.fetch_double_yin_openings(["300750"], trade_date=DAY, now=NOW)
    assert quotes == {}
    assert snapshot["rejects"] == {"300750": "现场报价缺失"}
    assert snapshot["errors"] == ["新浪现场报价失败：OSError"]


def test_unresponsive_provider_respects_retry_budget(monkeypatch):
    finished = threading.Event()
    def slow(self, codes):
        finished.wait(0.25)
        return [quote()]
    monkeypatch.setattr(inputs.SinaAdapter, "fetch_live_quotes", slow)
    started = time.monotonic()
    try:
        quotes, snapshot = inputs.fetch_double_yin_openings(["300750"], trade_date=DAY, now=NOW)
        assert time.monotonic() - started < 0.2
        assert quotes == {}
        assert "时间预算" in snapshot["errors"][0]
    finally:
        finished.set()


class Response:
    def __init__(self, rows, pages=1, success=True):
        self.payload = {"success": success, "result": {"pages": pages, "data": rows}}

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


def test_industry_hierarchy_and_adjacent_consumption_group(monkeypatch):
    rows = [
        {"SECURITY_CODE": "600519", "EM2016": "食品饮料-饮料-白酒"},
        {"SECURITY_CODE": "600887", "EM2016": "食品饮料-食品-乳制品"},
        {"SECURITY_CODE": "000333", "EM2016": "家电-白色家电-白色家电"},
        {"SECURITY_CODE": "601116", "EM2016": "商贸零售-零售-超市"},
        {"SECURITY_CODE": "300750", "EM2016": "电气设备-电源设备-储能设备"},
    ]
    calls = []
    def get(url, **kwargs):
        calls.append((url, kwargs))
        return Response(rows)
    monkeypatch.setattr(inputs, "market_get", get)
    codes = [row["SECURITY_CODE"] for row in rows]
    metadata, snapshot = inputs.fetch_double_yin_industries(codes)
    assert metadata["600519"]["industry_l1"] == "食品饮料"
    assert metadata["600519"]["industry_l2"] == "饮料"
    assert metadata["600519"]["industry_l3"] == "白酒"
    assert metadata["600519"]["industry_path"] == "食品饮料-饮料-白酒"
    assert metadata["600887"]["groups"] == metadata["600519"]["groups"]
    for code in ["600519", "600887", "000333", "601116"]:
        assert "family:consumer" in metadata[code]["groups"]
    assert metadata["300750"]["groups"] == ["industry:电气设备"]
    assert snapshot["coverage"] == 1
    assert calls[0][0] == inputs.INDUSTRY_URL
    assert calls[0][1]["params"]["pageSize"] == 100
    assert calls[0][1]["retries"] == 0


@pytest.mark.parametrize("path", ["", "制造业", "食品饮料-", "未知-未知-未知"])
def test_incomplete_industry_never_guesses_from_stock_name(monkeypatch, path):
    monkeypatch.setattr(inputs, "market_get", lambda *a, **kw: Response([
        {"SECURITY_CODE": "600519", "SECURITY_NAME_ABBR": "贵州茅台", "EM2016": path},
    ]))
    metadata, snapshot = inputs.fetch_double_yin_industries(["600519"])
    assert metadata == {}
    assert snapshot["failed_codes"] == ["600519"]
    assert "层级缺失" in snapshot["rejects"]["600519"]


def test_industry_batches_are_fresh_and_missing_codes_explicit(monkeypatch):
    calls = []
    def get(url, **kwargs):
        calls.append(kwargs["params"])
        return Response([])
    monkeypatch.setattr(inputs, "market_get", get)
    codes = [f"{i:06d}" for i in range(101)]
    metadata, snapshot = inputs.fetch_double_yin_industries(codes)
    inputs.fetch_double_yin_industries([codes[0]])
    assert metadata == {}
    assert snapshot["requested"] == snapshot["rejected"] == 101
    assert len(calls) == 3
    assert calls[0]["filter"].count('"') == 200
    assert calls[1]["filter"].count('"') == 2


@pytest.mark.parametrize("pages,success", [(2, True), (1, False)])
def test_industry_provider_failure_cannot_claim_full_classification(monkeypatch, pages, success):
    monkeypatch.setattr(inputs, "market_get", lambda *a, **kw: Response([], pages=pages, success=success))
    metadata, snapshot = inputs.fetch_double_yin_industries(["300750"])
    assert metadata == {}
    assert snapshot["coverage"] == 0
    assert "请求失败" in snapshot["rejects"]["300750"]


def test_empty_candidate_list_sends_no_external_request():
    assert inputs.fetch_double_yin_openings([], trade_date=DAY, now=NOW)[0] == {}
    assert inputs.fetch_double_yin_industries([])[0] == {}


@pytest.mark.parametrize("code", ["300750);secret", "30075", "sh600519"])
def test_code_validation_rejects_query_injection(code):
    with pytest.raises(inputs.RealtimeInputError, match="六位数字"):
        inputs.fetch_double_yin_industries([code])
