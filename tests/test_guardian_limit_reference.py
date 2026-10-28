"""Live quote references supplement price evidence without order book simulation."""
from datetime import datetime
import time
from types import SimpleNamespace

import pytest
import requests

from src.ops.application import guardian_tools as market
from src.ops.application.guardian_quotes import executable_quote


NOW = datetime.fromisoformat("2026-10-13T13:05:00+08:00")
CODE = "000823"


def minute_payload(code=CODE, price=22.32, **reference):
    return {"structured": {"success": True, "data": {
        "stock": {"code": code, "name": "超声电子", **reference},
        "points": [{"time": "2026-10-13 13:05", "price": price}],
    }}}


def sina_quote(code=CODE, **changes):
    return {"code": code, "name": "超声电子", "price": 22.32, "prev_close": 20.29,
            "source": "sina", "trade_date": "2026-10-13", "trade_time": "13:05:00", **changes}


def sources(monkeypatch, primary=None, direct=None, *, enabled=True):
    import src.intel
    import src.market
    import src.market.application.live_cache

    calls = []
    monkeypatch.setattr(market, "data_source", lambda: {"wudao": True, "server": "test"})
    monkeypatch.setattr(src.intel, "call_mcp_tool", primary or (lambda *_a, **_k: minute_payload()))
    monkeypatch.setattr(src.market, "lane_provider_enabled", lambda *_a: enabled)

    def fetch(codes):
        calls.append(list(codes))
        return direct(codes) if direct else [sina_quote(code) for code in codes]

    monkeypatch.setattr(src.market, "get_adapter", lambda *_a: SimpleNamespace(fetch_live_quotes=fetch))
    monkeypatch.setattr(src.market.application.live_cache, "build_monitor_snapshot",
                        lambda *_a, **_k: pytest.fail("successful primary prices need no system fallback"))
    return calls


def test_limit_reference_blocks_reported_limit_up_without_changing_primary_price(monkeypatch):
    calls = sources(monkeypatch)
    quote = market.snapshot([CODE], now=NOW).quotes[CODE]
    assert calls == [[CODE]]
    assert quote["source"] == "wudao" and quote["price"] == 22.32
    assert quote["trade_time"] == "13:05:00" and "order_book" not in quote
    assert quote["limit_reference"] == {key: sina_quote()[key] for key in
                                       ("code", "name", "prev_close", "source", "trade_date", "trade_time")}
    with pytest.raises(ValueError, match="涨停"):
        executable_quote(CODE, "buy", 1200, quote, NOW, paper=True)
    quote["price"] = 22.31
    execution = executable_quote(CODE, "buy", 1200, quote, NOW, paper=True)
    assert execution["execution_evidence"]["limit_up_check"]["limit_up"] == 22.32


def test_reference_codes_are_batched_and_native_reference_is_not_refetched(monkeypatch):
    def primary(_name, arguments, **_kwargs):
        code = arguments["code"]
        return minute_payload(code, **({"prev_close": 20.29} if code == "600000" else {}))

    calls = sources(monkeypatch, primary=primary)
    result = market.snapshot([CODE, "600000", "600001", CODE], now=NOW)
    assert calls == [[CODE, "600001"]]
    assert result.quotes["600000"]["prev_close"] == 20.29
    assert "limit_reference" not in result.quotes["600000"]
    assert all("error" not in quote for quote in result.quotes.values())


@pytest.mark.parametrize("changes", [{"trade_date": "2026-10-12"}, {"source": ""},
    {"source": "other"}, {"code": "600000"}, {"prev_close": None},
    {"prev_close": float("nan")}, {"prev_close": True}])
def test_invalid_reference_is_not_attached_and_primary_remains_usable(monkeypatch, changes):
    sources(monkeypatch, direct=lambda _: [sina_quote(**changes)])
    quote = market.snapshot([CODE], now=NOW).quotes[CODE]
    assert quote["price"] == 22.32 and quote["source"] == "wudao" and "error" not in quote
    assert "limit_reference" not in quote and quote["limit_reference_error"]


def test_disabled_reference_provider_is_not_bypassed(monkeypatch):
    calls = sources(monkeypatch, enabled=False)
    quote = market.snapshot([CODE], now=NOW).quotes[CODE]
    assert not calls and "error" not in quote
    assert "停用" in quote["limit_reference_error"]


def test_reference_timeout_retains_successful_primary(monkeypatch):
    def slow(_codes):
        time.sleep(0.15)
        return [sina_quote()]

    sources(monkeypatch, direct=slow)
    monkeypatch.setattr(market, "_DIRECT_QUOTE_SECONDS", 0.02)
    quote = market.snapshot([CODE], now=NOW).quotes[CODE]
    assert quote["price"] == 22.32 and "error" not in quote and "limit_reference" not in quote
    assert "TimeoutError" in quote["limit_reference_error"]


def test_reference_cancellation_is_propagated(monkeypatch):
    from src.ops.application.jobs.context import JobCancelled

    def cancelled(_codes):
        raise JobCancelled("reference query cancelled")

    sources(monkeypatch, direct=cancelled)
    with pytest.raises(JobCancelled, match="reference query cancelled"):
        market.snapshot([CODE], now=NOW)


def hq_line(previous):
    fields = ["0"] * 32
    fields[:6] = ["超声电子", "21.14", str(previous), "22.32", "22.32", "21.14"]
    fields[30:] = ["2026-10-13", "13:05:00"]
    return 'var hq_str_sz000823="' + ",".join(fields) + '";'


@pytest.mark.parametrize("previous", [0, -1, float("nan"), float("inf")])
def test_sina_missing_previous_close_is_never_replaced_by_open_or_current(previous):
    from src.market.infrastructure.sina import _parse_hq_line

    quote = _parse_hq_line(hq_line(previous))
    assert quote["price"] == 22.32
    assert quote["prev_close"] is None and quote["change"] is None and quote["pct"] is None


def test_sina_preserves_real_previous_close_and_decodes_stock_name(monkeypatch):
    from src.market.infrastructure import http_client, sina

    response = requests.Response()
    response.status_code = 200
    response.encoding = "utf-8"
    response._content = hq_line(20.29).encode("gb18030")
    monkeypatch.setattr(http_client, "market_get", lambda *_a, **_k: response)
    quote = sina._parse_hq_line(sina._get(sina.SPOT_URL.format("sz000823")))
    assert quote["name"] == "超声电子" and quote["prev_close"] == 20.29
    assert quote["change"] == 2.03 and quote["pct"] == 10.0
