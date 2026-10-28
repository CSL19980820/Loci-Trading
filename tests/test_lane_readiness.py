from types import SimpleNamespace

import pytest

from scripts import check_lane_readiness as readiness
from src.market.infrastructure import tdx_daily


def test_tdx_probe_distinguishes_handshake_from_real_bars(monkeypatch):
    class Api:
        def __init__(self, **kwargs):
            assert kwargs == {"raise_exception": True, "auto_retry": False}

        def connect(self, host, port, **kwargs):
            self.host = host
            return self

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get_security_bars(self, category, market, code, start, count):
            assert (category, market, code, start, count) == (9, 1, readiness.SAMPLE, 0, 4)
            if self.host == "broken":
                try:
                    raise ValueError("truncated response")
                except ValueError as exc:
                    raise RuntimeError("SDK error") from exc
            if self.host == "empty":
                return []
            return [{"datetime": "2026-10-26 15:00"}]

    monkeypatch.setattr(tdx_daily, "_api_class", lambda: Api)
    monkeypatch.setattr(tdx_daily, "_servers", lambda: (("good", 7709), ("empty", 7709), ("broken", 7709)))
    good, empty, broken = readiness.probe_tdx_servers()
    assert good["ok"] is True
    assert good["last_date"] == "2026-10-26"
    assert empty["ok"] is False
    assert "返回空数据" in empty["error"]
    assert broken["ok"] is False
    assert broken["error"] == "ValueError: truncated response"


@pytest.mark.parametrize("tdx_alive, lane_alive, expected", [(False, True, 1), (True, False, 1), (True, True, 0)])
def test_readiness_exit_reports_tdx_outage_even_when_fallback_works(
    monkeypatch, tdx_alive, lane_alive, expected
):
    from src.market.infrastructure import adapters

    monkeypatch.setattr("sys.argv", ["check_lane_readiness.py", "--lanes", "hist_daily", "--tdx-servers"])
    monkeypatch.setattr(adapters, "ALL_LANES", ("hist_daily",))
    monkeypatch.setattr(adapters, "adapters_for_lane", lambda lane: [SimpleNamespace(meta=SimpleNamespace(id="sina"))])
    monkeypatch.setattr(readiness, "probe_all", lambda lane: [{"adapter_id": "sina", "ok": lane_alive}])
    monkeypatch.setattr(readiness, "probe_tdx_servers", lambda: [{
        "server": "node:7709", "ok": tdx_alive, "rows": int(tdx_alive),
        "last_date": "2026-10-26", "rtt_ms": 1, "error": "protocol error",
    }])
    assert readiness.main() == expected
