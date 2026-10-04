"""真实引擎的完整盘后样本→竞价候选内遴选与快照失效边界。"""
from __future__ import annotations

from datetime import datetime
import json
import re
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from src.market.application import double_yin_inputs as sources
from src.market.domain.exchange_schedule import scheduled_trading_days
from src.shared.tenancy import tenant_scope
from src.strategy.application.double_yin_low_open import DoubleYinLowOpenV1
from src.strategy.application import double_yin_pool as pools
from src.strategy.application import double_yin_realtime as realtime
from src.strategy.domain.base import StrategyError


FIELDS = ("open", "high", "low", "close", "volume")
MAIN_CODES = ["000001", "000002", "600003", "600004", "600001"]
CODES = [*MAIN_CODES, "300001", "301001"]
INDUSTRIES = {
    "000001": "食品饮料-饮料-白酒",
    "000002": "商贸零售-零售-超市",
    "600003": "电子-半导体-集成电路",
    "600004": "机械设备-通用设备-机床工具",
    "600001": "",  # 低价、板块未知也必须保留在未经次日过滤的完整形态池。
    "300001": "电子-半导体-集成电路",
    "301001": "机械设备-通用设备-机床工具",
}
SHANGHAI = ZoneInfo("Asia/Shanghai")


def forbidden(*_args, **_kwargs):
    raise AssertionError("不应访问此数据源")


class ClosedStore:
    def __init__(self, as_of):
        self.days = scheduled_trading_days("2026-05-01", as_of)[-70:]
        self.panels = {
            field: pd.DataFrame(value, index=self.days, columns=CODES, dtype=float)
            for field, value in {"open": 10, "high": 12, "low": 8, "close": 10, "volume": 100}.items()
        }
        for field, value in {"open": 10, "high": 11.3, "low": 9.9, "close": 11.2, "volume": 100}.items():
            self.panels[field].iloc[-2] = value
        for field, value in {"open": 11.1, "high": 11.2, "low": 10.9, "close": 11.0, "volume": 200}.items():
            self.panels[field].iloc[-1] = value
        for field in FIELDS[:-1]:
            self.panels[field]["600001"] *= 0.5
        self.loads = []

    def trading_days(self, *, end):
        return [day for day in self.days if day <= end]

    def market_revision(self):
        return "closed-market-revision-1"

    def load_panel(self, *, fields, codes, start, end, min_bars, adjust):
        self.loads.append({"fields": fields, "codes": codes, "start": start, "end": end,
                           "min_bars": min_bars, "adjust": adjust})
        return {field: self.panels[field].loc[start:end, codes].copy() for field in fields}

    def data_snapshot(self, **kwargs):
        return {"market_revision": self.market_revision(), "closed_day": kwargs["end"],
                "source_evidence": {"sources": [{"source_id": "closed-store", "rows": len(self.days) * len(kwargs["codes"])}],
                                    "observed_codes": list(kwargs["codes"])}}


class VerifiedOpening(dict):
    """报价已由接口验证；不能将今日盘中影子字段传进历史形态计算。"""
    shadow_fields = {"close", "high", "low", "volume"}

    def __getitem__(self, key):
        if key in self.shadow_fields:
            raise AssertionError(f"读取今日影子字段 {key}")
        return super().__getitem__(key)

    def get(self, key, default=None):
        if key in self.shadow_fields:
            raise AssertionError(f"读取今日影子字段 {key}")
        return super().get(key, default)


@pytest.fixture
def flow(request, tmp_path, monkeypatch):
    as_of = getattr(request, "param", "2026-09-29")
    monkeypatch.setenv("LOCI_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LOCI_CONFIG_JSON", str(tmp_path / "absent-config.json"))
    monkeypatch.setattr(realtime, "scheduled_trading_days", scheduled_trading_days)
    target = realtime._session(as_of, 1)
    engine = DoubleYinLowOpenV1()
    store = ClosedStore(as_of)
    state = SimpleNamespace(clock=datetime.fromisoformat(as_of + "T15:30:00+08:00"))
    monkeypatch.setattr(realtime, "_now", lambda: state.clock)
    monkeypatch.setattr(realtime, "scheduled_trading_days", scheduled_trading_days)
    monkeypatch.setattr(realtime, "calendar_trading_day", lambda day: bool(scheduled_trading_days(day, day)))

    resolved_universes = []
    def resolve(current, universe, *, codes, as_of):
        assert current is store
        resolved_universes.append(dict(universe))
        chosen = CODES if codes is None else codes
        return SimpleNamespace(codes=list(chosen), meta={code: {"name": "旧名称" + code} for code in chosen})
    monkeypatch.setattr(realtime, "resolve_universe", resolve)
    industry_calls = []

    def industry_http(_url, *, params, **_kwargs):
        wanted = re.findall(r'"(\d{6})"', params["filter"])
        industry_calls.append(wanted)
        rows = [{"SECURITY_CODE": code, "SECURITY_NAME_ABBR": "行业名录" + code,
                 "EM2016": INDUSTRIES[code], "INDUSTRYCSRC1": "制造业"} for code in wanted]
        return SimpleNamespace(raise_for_status=lambda: None,
                               json=lambda: {"success": True, "result": {"pages": 1, "data": rows}})
    monkeypatch.setattr(sources, "market_get", industry_http)
    quote_calls = []
    live_names = {code: "今日名称" + code for code in CODES}
    quotes = {
        code: VerifiedOpening(code=code, name=live_names[code], open=10.44 if code != "600001" else 5.22,
                              price=10.44 if code != "600001" else 5.22,
                              prev_close=11.0 if code != "600001" else 5.5,
                              trade_date=target, trade_time="09:25:01", source="sina",
                              high=9999, low=-9999, close=9999, volume=-9999)
        for code in CODES
    }

    def live_openings(codes, *, trade_date, now, on_progress=None):
        assert trade_date == target and now == state.clock
        quote_calls.append(list(codes))
        selected = {code: quotes[code] for code in codes if code in quotes}
        return selected, {"source": "sina", "trade_date": target, "source_time_min": "09:25:01",
                          "requested": len(codes), "returned": len(selected), "coverage": len(selected) / len(codes),
                          "rejects": {code: "现场报价缺失" for code in codes if code not in quotes}}
    monkeypatch.setattr(sources, "fetch_double_yin_openings", live_openings)
    original_compute = engine.compute
    computed = []

    def real_compute(panels, params=None):
        for field in ("close", "high", "low", "volume"):
            assert panels[field].loc[target].isna().all(), f"今日{field}必须保持不可知"
        computed.append(panels["open"].loc[target].copy())
        return original_compute(panels, params)
    monkeypatch.setattr(engine, "compute", real_compute)
    return SimpleNamespace(as_of=as_of, target=target, engine=engine, store=store, state=state,
                           quotes=quotes, industry_calls=industry_calls, quote_calls=quote_calls,
                           computed=computed, resolved_universes=resolved_universes,
                           path=pools.pool_path(engine.slug, target))


def prepare(flow, **kwargs):
    flow.state.clock = datetime.fromisoformat(flow.as_of + "T15:30:00+08:00")
    return realtime.prepare_double_yin_pool(flow.engine, store=flow.store, as_of=flow.as_of, **kwargs)


def morning(flow, **kwargs):
    flow.state.clock = datetime.fromisoformat(flow.target + "T09:25:02+08:00")
    return realtime.screen_live_double_yin(flow.engine, **kwargs)


@pytest.mark.parametrize("flow", ["2026-09-29", "2026-09-30"], indirect=True)
def test_complete_eod_pool_then_next_opening_diversifies_adjacent_consumers(flow):
    report = prepare(flow)
    assert report["status"] == "prepared_with_warnings"
    assert report["candidate_count"] == 5 > 2
    assert report["candidate_codes"] == sorted(MAIN_CODES)
    assert report["target_trade_date"] == ("2026-09-30" if flow.as_of == "2026-09-29" else "2026-10-08")
    envelope = json.loads(flow.path.read_text(encoding="utf-8"))
    payload = envelope["payload"]
    assert not payload["data_snapshot"]["pre_ranked"] and not payload["data_snapshot"]["push_wecom"]
    assert all(item["historical_factors"]["score"] is None for item in payload["candidates"])
    assert any(item["code"] == "600001" and not item["industry"] for item in payload["candidates"])
    assert all(len(item["history"]) >= 60 for item in payload["candidates"])
    result = morning(flow)
    assert [pick["code"] for pick in result.picks] == ["000001", "600003"]
    assert all(pick["name"].startswith("今日名称") for pick in result.picks)
    assert flow.quote_calls == [sorted(MAIN_CODES)]
    assert len(flow.store.loads) == 1, "晨间不得重新加载行情仓"
    assert result.data_snapshot["local_market_read"] is False
    assert result.data_snapshot["full_market_live_scan"] is False
    assert result.data_snapshot["live_requested_codes"] == 5
    assert result.data_snapshot["prepared_pool_sha256"] == envelope["sha256"]
    retail = next(row for row in result.data_snapshot["candidate_reviews"] if row["code"] == "000002")
    assert retail["factors"]["同板块排除"] == 1
    assert retail["industry"]["industry_l1"] != result.picks[0]["industry"].split("-")[0]
    assert "family:consumer" in retail["industry"]["groups"]
    assert len(flow.computed) == 2 and flow.computed[0].isna().all()


def test_explicit_legacy_growth_scope_cannot_include_chinext_in_either_stage(flow):
    universe = {"preset": "default_a_share", "boards": ["main", "chi_next"]}
    report = prepare(flow, codes=CODES, universe=universe)
    assert flow.resolved_universes == [{"preset": "default_a_share", "boards": ["main"]}]
    assert set(flow.store.loads[0]["codes"]) == set(CODES), "源仍提供满足形态的300/301反例"
    assert report["candidate_codes"] == sorted(MAIN_CODES)
    payload = json.loads(flow.path.read_text(encoding="utf-8"))["payload"]
    assert payload["universe"]["boards"] == ["main"]
    assert {row["code"] for row in payload["candidates"]} == set(MAIN_CODES)
    result = morning(flow, codes=CODES, universe=universe)
    assert result.universe["boards"] == ["main"]
    assert flow.quote_calls == [sorted(MAIN_CODES)]
    assert {row["code"] for row in result.data_snapshot["candidate_reviews"]}.issubset(MAIN_CODES)
    assert [row["code"] for row in result.picks] == ["000001", "600003"]


def test_current_live_st_name_overrides_prepared_name_and_is_excluded(flow):
    prepare(flow)
    flow.quotes["000001"]["name"] = "*ST今日名称"
    result = morning(flow)
    assert [pick["code"] for pick in result.picks] == ["000002", "600003"]
    assert result.data_snapshot["instrument_names"]["000001"] == "*ST今日名称"
    assert result.data_snapshot["prepared_instrument_names"]["000001"] == "旧名称000001"
    assert all(row["code"] != "000001" for row in result.data_snapshot["candidate_reviews"])


def test_top_n_and_price_floor_can_change_without_preparing_new_shape_pool(flow):
    prepare(flow)
    before = flow.path.read_bytes()
    result = morning(flow, params={"top_n": 3, "price_floor": 7.0})
    assert [pick["code"] for pick in result.picks] == ["000001", "600003", "600004"]
    assert flow.path.read_bytes() == before
    assert result.effective_params["top_n"] == 3


def test_changed_position_window_requires_new_preparation_before_quote_fetch(flow):
    prepare(flow)
    with pytest.raises(StrategyError, match="参数|版本"):
        morning(flow, params={"position_lookback": 20})
    assert not flow.quote_calls
    prepare(flow, params={"position_lookback": 20})
    assert morning(flow, params={"position_lookback": 20}).picks


@pytest.mark.parametrize("wanted", [None, CODES])
def test_expanding_explicit_prepared_stock_scope_is_rejected_before_quotes(flow, wanted):
    prepare(flow, codes=CODES[:3])
    with pytest.raises(StrategyError, match="范围超出"):
        morning(flow, codes=wanted)
    assert not flow.quote_calls


def test_requested_subset_of_prepared_stock_scope_only_requests_that_subset(flow):
    prepare(flow, codes=CODES[:4])
    result = morning(flow, codes=["000002", "600003"])
    assert flow.quote_calls == [["000002", "600003"]]
    assert [row["code"] for row in result.picks] == ["000002", "600003"]


@pytest.mark.parametrize("fault", ["stale", "hash", "missing"])
def test_bad_or_missing_pool_does_not_fetch_quotes_or_fall_back_to_store(flow, fault):
    prepare(flow)
    if fault == "missing":
        flow.path.unlink()
    elif fault == "hash":
        envelope = json.loads(flow.path.read_text(encoding="utf-8"))
        envelope["sha256"] = "0" * 64
        flow.path.write_text(json.dumps(envelope, ensure_ascii=False), encoding="utf-8")
    else:
        envelope = json.loads(flow.path.read_text(encoding="utf-8"))
        envelope["payload"]["as_of"] = "2026-09-28"
        pools.save_prepared_pool(envelope["payload"])
    with pytest.raises(StrategyError, match="尚未准备|不可用"):
        morning(flow)
    assert not flow.quote_calls and len(flow.store.loads) == 1


def test_failed_atomic_replacement_keeps_prior_complete_pool_and_cleans_staging(flow, monkeypatch):
    prepare(flow)
    before = flow.path.read_bytes()
    with monkeypatch.context() as isolated:
        isolated.setattr(pools.os, "replace", lambda *_args: (_ for _ in ()).throw(OSError("原子替换失败")))
        with pytest.raises(OSError, match="原子替换失败"):
            prepare(flow)
    assert flow.path.read_bytes() == before
    assert not list(flow.path.parent.glob("*.tmp"))
    assert morning(flow).picks


def test_failed_industry_request_keeps_prior_complete_pool(flow, monkeypatch):
    prepare(flow)
    before = flow.path.read_bytes()
    def failure(_codes):
        raise sources.RealtimeInputError("行业接口失败")
    monkeypatch.setattr(sources, "fetch_double_yin_industries", failure)
    with pytest.raises(StrategyError, match="原样本保持不变"):
        prepare(flow)
    assert flow.path.read_bytes() == before


def test_complete_empty_shape_pool_does_not_request_opening_quotes(flow, monkeypatch):
    flow.store.panels["volume"].iloc[-1] = 100
    monkeypatch.setattr(sources, "fetch_double_yin_openings", forbidden)
    report = prepare(flow)
    assert report["status"] == "prepared_empty" and report["candidate_count"] == 0
    assert not flow.industry_calls
    result = morning(flow)
    assert result.picks == [] and result.data_snapshot["status"] == "completed_empty"
    assert result.data_snapshot["live_requested_codes"] == 0


def test_explicit_empty_universe_is_a_complete_empty_pool_without_source_fetch(flow, monkeypatch):
    monkeypatch.setattr(realtime, "resolve_universe", lambda *_args, **_kwargs: SimpleNamespace(codes=[], meta={}))
    monkeypatch.setattr(sources, "fetch_double_yin_industries", forbidden)
    monkeypatch.setattr(sources, "fetch_double_yin_openings", forbidden)
    report = prepare(flow)
    assert report["status"] == "prepared_empty" and report["candidate_count"] == 0
    assert report["universe_size"] == 0
    assert morning(flow).picks == []


@pytest.mark.parametrize("missing", [1, len(MAIN_CODES)])
def test_partial_or_missing_live_quotes_fail_the_whole_ranking_and_keep_pool(flow, missing):
    prepare(flow)
    before = flow.path.read_bytes()
    for code in MAIN_CODES[:missing]:
        flow.quotes.pop(code)
    with pytest.raises(StrategyError, match="样本不完整"):
        morning(flow)
    assert flow.path.read_bytes() == before
    assert len(flow.computed) == 1, "报价不完整不能继续计算剩余股票排名"


def test_all_live_previous_closes_disagreeing_with_history_fail_instead_of_zero_picks(flow):
    prepare(flow)
    for quote in flow.quotes.values():
        quote["prev_close"] = 999.0
    with pytest.raises(StrategyError, match="所有样本.*不一致"):
        morning(flow)
    assert len(flow.computed) == 1


@pytest.mark.parametrize("clock", ["09:24:59", "09:30:00", "15:30:00"])
def test_outside_auction_window_never_fetches_market_data(flow, clock):
    flow.state.clock = datetime.fromisoformat(flow.target + "T" + clock + "+08:00")
    with pytest.raises(StrategyError, match="09:25至09:30"):
        realtime.screen_live_double_yin(flow.engine)
    assert not flow.quote_calls and not flow.industry_calls and not flow.store.loads


def test_holiday_is_explicit_skip_without_any_source_or_pool_reads(flow, monkeypatch):
    flow.state.clock = datetime.fromisoformat("2026-10-01T09:25:02+08:00")
    monkeypatch.setattr(realtime, "load_prepared_pool", forbidden)
    result = realtime.screen_live_double_yin(flow.engine)
    assert result.picks == [] and result.data_snapshot["status"] == "skipped_non_trading_day"
    assert not flow.quote_calls and not flow.industry_calls and not flow.store.loads


def test_missing_latest_closed_day_never_overwrites_prior_good_pool(flow, monkeypatch):
    prepare(flow)
    before = flow.path.read_bytes()
    monkeypatch.setattr(flow.store, "trading_days", lambda **_kwargs: flow.store.days[:-1])
    with pytest.raises(StrategyError, match="完整日K尚未就绪"):
        prepare(flow)
    assert flow.path.read_bytes() == before and len(flow.store.loads) == 1


def test_market_revision_change_during_preparation_keeps_prior_good_pool(flow, monkeypatch):
    prepare(flow)
    before = flow.path.read_bytes()
    revisions = iter(["old", "new", "new"])
    monkeypatch.setattr(flow.store, "market_revision", lambda: next(revisions))
    with pytest.raises(StrategyError, match="行情.*变化"):
        prepare(flow)
    assert flow.path.read_bytes() == before


def test_current_price_and_shadow_fields_do_not_change_opening_scores_or_winners(flow):
    prepare(flow)
    first = morning(flow)
    for quote in flow.quotes.values():
        quote["price"] = 9999.0
    second = morning(flow)
    assert [row["code"] for row in first.picks] == [row["code"] for row in second.picks]
    assert [row["factors"] for row in first.picks] == [row["factors"] for row in second.picks]
    assert second.picks[0]["close"] == 9999.0  # 仅供当前价展示，不影响条件、评分、排名。


def test_prepared_pool_paths_and_contents_are_isolated_between_tenants(flow):
    paths = []
    for tenant in ("pool-owner-a", "pool-owner-b"):
        with tenant_scope(tenant):
            report = prepare(flow)
            paths.append(report["pool"]["path"])
            assert morning(flow).picks
    assert paths[0] != paths[1]
    assert "pool-owner-a" in paths[0] and "pool-owner-b" in paths[1]
    with tenant_scope("pool-owner-c"):
        with pytest.raises(StrategyError, match="尚未准备"):
            morning(flow)
