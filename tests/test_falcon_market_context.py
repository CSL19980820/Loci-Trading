import sqlite3
from types import SimpleNamespace

import pytest

from src.ops.application.falcon_market_context import read_falcon_market_context


def test_environment_aggregates_exclude_future_and_never_return_stocks(tmp_path):
    path = tmp_path / "market.db"
    with sqlite3.connect(path) as db:
        db.executescript("""CREATE TABLE instruments(code TEXT,name TEXT,industry TEXT,instrument_type TEXT);
            CREATE TABLE quotes_daily(trade_date TEXT,code TEXT,close REAL,amount REAL);
            INSERT INTO instruments VALUES('600000','候选甲','银行','STOCK'),('600001','池外乙','银行','STOCK'),('000001','上证','指数','INDEX');
            INSERT INTO quotes_daily VALUES('2026-09-28','600000',10,100),('2026-09-28','600001',10,100),
                ('2026-09-29','600000',11,200),('2026-09-29','600001',9,150),('2026-09-29','000001',3000,500),
                ('2026-09-30','600000',999,999);
        """)
    result = read_falcon_market_context(cutoff="2026-09-29", days=1, path=path)
    day = result["daily_breadth"][0]
    assert day["trade_date"] == "2026-09-29"
    assert day["coverage"] == 2 and day["advancing"] == 1 and day["declining"] == 1
    assert day["amount"] == 350
    assert result["industry_aggregates"][0]["coverage"] == 2
    assert not result["stock_discovery"] and not result["live"]
    for row in [*result["daily_breadth"], *result["industry_aggregates"]]:
        assert "code" not in row and "name" not in row


@pytest.mark.parametrize("days", [0, 21, "5", True])
def test_environment_window_is_validated(days):
    with pytest.raises(ValueError):
        read_falcon_market_context(cutoff="2026-09-29", days=days)


def test_market_emotion_never_exposes_provider_stock_lists(monkeypatch):
    import src.market as market
    from src.ops.application.falcon_market_context import read_falcon_market_emotion
    provenance = market.TapeProvenance(provider_id="test", as_of_date="2026-09-30", fetched_at="2026-09-30T10:00:00+08:00")
    data = market.MarketEmotion(trade_date="2026-09-30", breadth=0.65, limit_up_count=30,
                               payload={"stocks": [{"code": "600999", "name": "池外强股"}]})
    requests = []
    monkeypatch.setattr(market, "fetch_tape", lambda request: requests.append(request) or market.TapeResult(data=data, provenance=provenance))
    result = read_falcon_market_emotion(as_of="2026-09-30T10:01:00+08:00")
    assert result["available"] and result["metrics"]["breadth"] == 0.65
    assert requests[0].lane == "market_emotion" and not requests[0].codes
    assert "payload" not in result and "600999" not in str(result)
    monkeypatch.setattr(market, "fetch_tape", lambda _: SimpleNamespace(data=data,
        provenance=market.TapeProvenance(as_of_date="2026-09-29", stale=True, degraded=True), error="source_unavailable"))
    stale = read_falcon_market_emotion(as_of="2026-09-30T10:01:00+08:00")
    assert not stale["available"] and stale["stale"] and stale["degraded"]
