from __future__ import annotations

import sys

import pytest

from src.market.domain.tape import TapeAttempt, TapeProvenance, TapeRequest, TapeResult
from src.market.infrastructure.tape.router import (
    clear_provider_cooldown,
    route_tape,
    tape_readiness,
)
from src.market.infrastructure.tape.wudao_provider import WudaoTapeProvider


class _Provider:
    def __init__(
        self,
        provider_id: str,
        result: TapeResult | None = None,
        *,
        error: Exception | None = None,
        available: bool = True,
    ) -> None:
        self.provider_id = provider_id
        self.lanes = ("market_emotion",)
        self.result = result
        self.error = error
        self.available = available
        self.calls = 0

    def is_available(self, _request: TapeRequest) -> bool:
        return self.available

    def fetch(self, _request: TapeRequest) -> TapeResult:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.result or TapeResult(data={"provider": self.provider_id})


@pytest.fixture(autouse=True)
def _clear_tape_circuit() -> None:
    clear_provider_cooldown()
    yield
    clear_provider_cooldown()


def test_tape_dto_keeps_single_provider_provenance() -> None:
    attempt = TapeAttempt(provider_id="wudao", lane="market_emotion", ok=True, status="succeeded")
    provenance = TapeProvenance(
        provider_id="wudao",
        lane="market_emotion",
        requested_date="2026-08-07",
        as_of_date="2026-08-07",
        attempts=(attempt,),
        warnings=("非实时快照",),
    )

    result = TapeResult(data={"temperature": 72}, provenance=provenance)

    assert result.healthy
    assert result.provenance.provider_id == "wudao"
    assert result.provenance.attempts == (attempt,)
    assert result.provenance.requested_trade_date == "2026-08-07"


def test_router_first_healthy_wins() -> None:
    first = _Provider("first")
    second = _Provider("second")

    result = route_tape(
        TapeRequest(lane="market_emotion"),
        providers=[first, second],
        failure_cooldown_seconds=0,
    )

    assert result.data == {"provider": "first"}
    assert result.provenance.provider_id == "first"
    assert second.calls == 0
    assert [attempt.status for attempt in result.provenance.attempts] == ["succeeded"]


def test_router_falls_back_after_provider_failure() -> None:
    first = _Provider("first", error=RuntimeError("offline"))
    second = _Provider("second")

    result = route_tape(
        TapeRequest(lane="market_emotion"),
        providers=[first, second],
        failure_cooldown_seconds=0,
    )

    assert result.data == {"provider": "second"}
    assert result.provenance.provider_id == "second"
    assert [attempt.status for attempt in result.provenance.attempts] == [
        "failed",
        "succeeded",
    ]


def test_router_returns_degraded_when_all_providers_unavailable() -> None:
    first = _Provider("first", available=False)
    second = _Provider("second", available=False)

    result = route_tape(
        TapeRequest(lane="market_emotion", requested_date="2026-08-07"),
        providers=[first, second],
    )

    assert result.data is None
    assert result.provenance.degraded
    assert result.provenance.provider_id is None
    assert "no_provider_available" in result.provenance.warnings
    assert [attempt.status for attempt in result.provenance.attempts] == [
        "unavailable",
        "unavailable",
    ]
    assert first.calls == second.calls == 0


def test_tape_readiness_reports_missing_lanes_without_raising() -> None:
    result = tape_readiness(
        required_lanes=("market_emotion", "theme_board"),
        providers=[_Provider("local")],
        trade_date="2026-08-07",
    )

    assert result["ready"] is False
    assert result["lanes"]["market_emotion"]["available"] is True
    assert result["lanes"]["theme_board"]["available"] is False
    assert result["missing_lanes"] == ["theme_board"]


def test_wudao_provider_missing_is_cleanly_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "src.intel", None)

    result = WudaoTapeProvider().fetch(TapeRequest(lane="market_emotion"))

    assert result.data is None
    assert result.provenance.degraded
    assert result.provenance.provider_id == "wudao"
    assert result.error
