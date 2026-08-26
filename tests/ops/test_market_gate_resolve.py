"""纸面舱龙空龙闸门解析：TTL 缓存、关段 fail-closed、tape 桥降级。"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.ops.application.jobs import paper_quant_support as support
from src.ops.application.jobs.paper_quant_support import _resolve_market_gate


def test_resolve_market_gate_reuses_short_ttl_cache(monkeypatch) -> None:
    support.clear_market_gate_cache()
    calls = {"n": 0}

    def fake_scan(_call_tool, *, params=None, force_refresh=False, **_kwargs):  # noqa: ANN001
        del force_refresh
        calls["n"] += 1
        return {
            "state": "dragon",
            "entry_allowed": True,
            "reason": "ok",
            "data_status": "ok",
        }

    monkeypatch.setattr(
        "src.ops.application.skill_watch.market_regime.scan_market_gate",
        fake_scan,
    )
    monkeypatch.setattr(
        "src.ops.application.skill_watch.tuning.load_tuning",
        lambda *_a, **_k: {"stages": {"market_gate": True}, "gate": {}},
    )
    monkeypatch.setattr(
        "src.ops.application.skill_watch.tuning.section",
        lambda *_a, **_k: {},
    )
    monkeypatch.setattr(
        "src.ops.application.skill_watch.tuning.stage_enabled",
        lambda *_a, **_k: True,
    )
    monkeypatch.setattr("src.market.legacy_call_tool", lambda *_a, **_k: {})

    first = support._resolve_market_gate("dragon-return", {})
    second = support._resolve_market_gate("dragon-return", {})
    assert first is not None and first["entry_allowed"] is True
    assert second is not None and second.get("from_cache") is True
    assert calls["n"] == 1

    forced = support._resolve_market_gate("dragon-return", {}, force_refresh=True)
    assert forced is not None and forced.get("from_cache") is False
    assert calls["n"] == 2
    support.clear_market_gate_cache()


def test_disabled_market_gate_section_blocks_entry() -> None:
    support.clear_market_gate_cache()
    with (
        patch(
            "src.ops.application.skill_watch.tuning.load_tuning",
            return_value={"stages": {"market_gate": False}, "gate": {}},
        ),
        patch(
            "src.ops.application.skill_watch.tuning.stage_enabled",
            return_value=False,
        ),
        patch(
            "src.ops.application.skill_watch.tuning.section",
            return_value={},
        ),
        patch(
            "src.ops.application.skill_watch.market_regime.scan_market_gate"
        ) as scan,
    ):
        gate = _resolve_market_gate("dragon-return", {"enabled": True}, store=MagicMock())
    assert gate is not None
    assert gate["entry_allowed"] is False
    assert gate["data_status"] == "disabled"
    assert "market_gate_disabled" in gate["quality_warnings"]
    scan.assert_not_called()
    support.clear_market_gate_cache()


def test_resolve_market_gate_calls_scan_via_legacy_call_tool() -> None:
    support.clear_market_gate_cache()
    with (
        patch(
            "src.ops.application.skill_watch.market_regime.scan_market_gate"
        ) as scan,
        patch(
            "src.ops.application.skill_watch.tuning.load_tuning",
            return_value={"stages": {"market_gate": True}, "gate": {}},
        ),
        patch(
            "src.ops.application.skill_watch.tuning.stage_enabled",
            return_value=True,
        ),
        patch(
            "src.ops.application.skill_watch.tuning.section",
            return_value={},
        ),
    ):
        scan.return_value = {
            "entry_allowed": False,
            "data_status": "degraded",
            "provider_id": "local",
        }
        gate = _resolve_market_gate("dragon-return", {"enabled": True}, store=MagicMock())
    assert gate is not None
    assert gate["entry_allowed"] is False
    assert gate["data_status"] == "degraded"
    assert gate["provider_id"] == "local"
    scan.assert_called_once()
    assert callable(scan.call_args.args[0])
    support.clear_market_gate_cache()


def test_resolve_market_gate_applies_to_dragon_suite_slugs() -> None:
    """P1-1：套件三 slug 默认走闸门，非套件仍需显式 market_gate。"""
    support.clear_market_gate_cache()
    with (
        patch(
            "src.ops.application.skill_watch.tuning.load_tuning",
            return_value={"stages": {"market_gate": True}, "gate": {}},
        ),
        patch(
            "src.ops.application.skill_watch.tuning.stage_enabled",
            return_value=True,
        ),
        patch(
            "src.ops.application.skill_watch.tuning.section",
            return_value={},
        ),
        patch(
            "src.ops.application.skill_watch.market_regime.scan_market_gate",
            return_value={"entry_allowed": True, "mode": "龙"},
        ) as scan,
        patch("src.market.legacy_call_tool", return_value={}),
    ):
        for slug in ("dragon-return", "market-leader-map", "theme-leader-rotation"):
            support.clear_market_gate_cache()
            gate = _resolve_market_gate(slug, {}, store=MagicMock())
            assert gate is not None, slug
            assert gate.get("entry_allowed") is True
        assert scan.call_count == 3
        assert _resolve_market_gate("limit-up-momentum", {}, store=MagicMock()) is None
        assert (
            _resolve_market_gate(
                "limit-up-momentum", {"market_gate": True}, store=MagicMock()
            )
            is not None
        )
    support.clear_market_gate_cache()
