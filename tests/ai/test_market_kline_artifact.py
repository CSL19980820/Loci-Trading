"""UI artifact contract; fake market store, no account or market database reads."""
from types import MethodType, SimpleNamespace

import pytest

from src.ai.application.system_toolbus import SystemToolBus
from src.ai.application.system_toolbus_market import market_kline


class Frame:
    def __init__(self, rows):
        self.rows = rows

    def tail(self, limit):
        return Frame(self.rows[-limit:])

    def to_dict(self, orient):
        assert orient == "records"
        return self.rows


@pytest.fixture
def setup_tool(monkeypatch, tmp_path):
    events = []
    calls = []
    failure = {"stage": None}
    rows = [
        {"trade_date": "2026-01-01", "open": 2.0, "high": 3.0, "low": 1.0, "close": 2.5},
        {"trade_date": "2026-01-02", "open": 2.5, "high": 3.5, "low": 2.0, "close": 3.0},
    ]

    class Store:
        def __init__(self, path):
            assert path == tmp_path / "unused.db"

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def instruments_meta(self, codes):
            calls.append(("meta", codes))
            return {codes[0]: {"name": "模拟标的"}}

        def history(self, code, **kwargs):
            calls.append(("history", code, kwargs))
            if failure["stage"] == "history":
                raise RuntimeError("fixture-error")
            return Frame(rows)

    monkeypatch.setattr("src.market.MarketStore", Store)
    owner = SimpleNamespace(on_event=events.append, market_db=tmp_path / "unused.db")
    owner._artifact = MethodType(SystemToolBus._artifact, owner)
    return owner, events, calls, failure, tmp_path


def test_loading_and_ready_have_one_stable_id(setup_tool):
    owner, events, calls, _failure, path = setup_tool
    market_kline(owner, {"code": "000980", "limit": 1})
    assert [event["status"] for event in events] == ["loading", "ready"]
    assert events[0]["id"] == events[1]["id"]
    assert events[1]["data"]["code"] == "000980"
    assert events[1]["data"]["name"] == "模拟标的"
    assert events[1]["data"]["price_unit"] == "元"
    assert events[1]["data"]["adjust"] == "qfq"
    assert len(events[1]["data"]["bars"]) == 1
    assert events[0]["data"]["name"] == ""  # emitted snapshots are not mutated
    assert calls[0] == ("meta", ["000980"])
    assert not (path / "unused.db").exists()


def test_separate_calls_never_share_artifact_ids(setup_tool):
    owner, events, *_ = setup_tool
    market_kline(owner, {"code": "000980"})
    market_kline(owner, {"code": "000980"})
    assert events[0]["id"] != events[2]["id"]
    assert events[2]["id"] == events[3]["id"]


def test_failure_settles_loading_and_preserves_original_exception(setup_tool):
    owner, events, _calls, failure, _path = setup_tool
    failure["stage"] = "history"
    with pytest.raises(RuntimeError, match="fixture-error"):
        market_kline(owner, {"code": "000980"})
    assert [event["status"] for event in events] == ["loading", "error"]
    assert events[0]["id"] == events[1]["id"]
    assert events[1]["data"]["error"] == "K线数据读取失败"


def test_other_artifact_callers_remain_compatible(setup_tool):
    owner, events, *_ = setup_tool
    owner._artifact("table", "模拟表格", {"rows": []})
    assert events == [{"type": "artifact", "kind": "table", "title": "模拟表格", "data": {"rows": []}, "status": "ready"}]
