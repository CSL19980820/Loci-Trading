"""上架清单单测：回测门槛、成本非零、entry_timing、文案与引流拦截。"""

from __future__ import annotations

import pytest

from src.community.domain.models import PublishRuleError
from src.community.domain.publish_rules import (
    ENTRY_TIMINGS,
    MIN_BACKTEST_DAYS,
    MIN_TRADES,
    check_publish_ready,
    checklist,
    ensure_publishable,
)
from tests.community.conftest import valid_backtest, valid_payload


def codes(payload: dict) -> set[str]:
    return {item.code for item in check_publish_ready(payload)}


def test_entry_timings_mirror_strategy() -> None:
    """``publish_rules.ENTRY_TIMINGS`` 是 strategy 域的镜像，禁止漂移。

    社区 domain 不许 import 兄弟上下文，所以常量是复制的；这条测试就是那份复制品的
    保鲜期检查——strategy 加了新时点而这里没跟上，测试立刻红。
    """
    from src.strategy import ENTRY_TIMINGS as CANONICAL

    assert ENTRY_TIMINGS == tuple(CANONICAL)


def test_valid_payload_passes() -> None:
    assert check_publish_ready(valid_payload()) == []


def test_backtest_is_mandatory() -> None:
    assert "backtest_required" in codes(valid_payload(backtest=None))
    assert "backtest_required" in codes(valid_payload(backtest={}))


def test_trade_count_threshold() -> None:
    too_few = valid_payload(backtest=valid_backtest(trades=MIN_TRADES - 1))
    assert "trades_too_few" in codes(too_few)
    enough = valid_payload(backtest=valid_backtest(trades=MIN_TRADES))
    assert "trades_too_few" not in codes(enough)


def test_backtest_window_must_span_a_year() -> None:
    short = valid_payload(backtest=valid_backtest(start="2024-01-01", end="2024-06-30"))
    assert "backtest_window_too_short" in codes(short)
    missing = valid_payload(backtest=valid_backtest(start="", end=""))
    assert "backtest_window_missing" in codes(missing)
    exact = valid_payload(backtest=valid_backtest(start="2023-01-01", end="2024-01-01"))
    assert "backtest_window_too_short" not in codes(exact)
    assert MIN_BACKTEST_DAYS == 365


def test_entry_timing_must_be_declared_and_known() -> None:
    assert "entry_timing_required" in codes(valid_payload(entry_timing=""))
    assert "entry_timing_invalid" in codes(valid_payload(entry_timing="盘中随便买"))
    for timing in ENTRY_TIMINGS:
        assert "entry_timing_invalid" not in codes(valid_payload(entry_timing=timing))


@pytest.mark.parametrize("field", ["commission_bps", "stamp_duty_bps", "slippage_bps"])
def test_costs_must_not_be_zero(field: str) -> None:
    """零成本回测是最常见的注水手法，直接拦。"""
    zeroed = valid_payload(backtest=valid_backtest(**{field: 0}))
    assert f"cost_zero_{field}" in codes(zeroed)
    missing = valid_backtest()
    missing.pop(field)
    assert f"cost_missing_{field}" in codes(valid_payload(backtest=missing))


def test_costs_may_live_in_a_nested_config() -> None:
    """成本平铺或放在 costs / config 子对象里都认。"""
    nested = {
        "trades": 40,
        "start": "2023-01-01",
        "end": "2024-06-30",
        "costs": {"commission_bps": 3, "stamp_duty_bps": 10, "slippage_bps": 5},
    }
    assert check_publish_ready(valid_payload(backtest=nested)) == []


def test_title_and_summary_required() -> None:
    assert "title_required" in codes(valid_payload(title="  "))
    assert "summary_required" in codes(valid_payload(summary=""))
    assert "title_too_long" in codes(valid_payload(title="龙" * 81))
    assert "source_required" in codes(valid_payload(source_text=" "))


@pytest.mark.parametrize(
    "text",
    [
        "加微信 quant_master_88 看实盘",
        "有问题 QQ: 123456789",
        "电话 13800138000 随时联系",
        "邮箱 me@example.com 交流",
        "扫码进群，一对一指导",
        "详情看 https://my-shop.example.cn/vip",
    ],
)
def test_contact_information_is_blocked(text: str) -> None:
    """广场不是引流场：联系方式与站外链接一律拦。"""
    found = codes(valid_payload(summary=text))
    assert found, f"未拦下引流文案：{text}"
    assert any(code.startswith("contact_") or code == "external_link" for code in found)


def test_repo_links_are_allowed() -> None:
    """白名单里的源码仓库链接不算引流。"""
    ok = valid_payload(summary="源码见 https://github.com/someone/repo，欢迎提 issue。")
    assert check_publish_ready(ok) == []


def test_tags_are_scanned_too() -> None:
    assert codes(valid_payload(tags=["加V看单"]))
    assert "tags_too_many" in codes(valid_payload(tags=[f"t{i}" for i in range(9)]))


def test_all_violations_are_reported_at_once() -> None:
    """一次性返回全部问题，别让作者改一条提交一次。"""
    broken = valid_payload(title="", summary="", entry_timing="", backtest=None)
    found = codes(broken)
    assert {
        "title_required",
        "summary_required",
        "entry_timing_required",
        "backtest_required",
    } <= found


def test_ensure_publishable_raises_with_violations() -> None:
    with pytest.raises(PublishRuleError) as excinfo:
        ensure_publishable(valid_payload(backtest=None))
    assert excinfo.value.http_status == 422
    assert excinfo.value.violations
    assert excinfo.value.violations[0]["code"] == "backtest_required"
    assert excinfo.value.violations[0]["field"] == "backtest"


def test_ensure_publishable_accepts_valid_payload() -> None:
    ensure_publishable(valid_payload())


def test_checklist_codes_are_real_rules() -> None:
    """前端展示的清单条目必须真的能被触发，不能是装饰性文案。"""
    broken = {
        "title": "",
        "summary": "加微信 abcd1234",
        "entry_timing": "",
        "source_text": "",
        "tags": [],
        "backtest": {
            "trades": 1,
            "start": "2024-01-01",
            "end": "2024-02-01",
            "commission_bps": 0,
            "stamp_duty_bps": 0,
            "slippage_bps": 0,
        },
    }
    triggered = (
        codes(broken)
        | codes(valid_payload(backtest=None))
        | codes(valid_payload(summary="details at https://my-shop.example.cn/vip"))
    )
    for item in checklist():
        assert item["code"] in triggered, item
