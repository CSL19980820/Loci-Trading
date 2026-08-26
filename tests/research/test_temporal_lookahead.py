"""时点事实与历史成分快照的防前视不变量。

这是 `src/research` 里最不能出错的一层：一旦「今天才知道的事实」被历史某日
的回测看见，整条研究结论就是虚的，而且从收益曲线上看不出来。README 也把
它列为补测第一优先级。

口径要点：可见性由 ``available_at`` 决定，**不是** ``observed_on`` / ``as_of``。
财报属于某季度（observed_on）但要等披露日（available_at）之后才能用；指数成分
在生效日（as_of）之后、公告可见日（available_at）之前同样不能用。
"""
from __future__ import annotations

import pytest

from src.research.domain.temporal import (
    MembershipSnapshot,
    PointInTimeObservation,
    TemporalDataError,
    assert_strict_membership,
    resolve_membership,
    select_point_in_time,
)

DIGEST = "a" * 64


def _fact(
    observation_id: str,
    *,
    observed_on: str,
    available_at: str,
    entity_id: str = "600519",
    revision: str = "r1",
) -> PointInTimeObservation:
    return PointInTimeObservation(
        observation_id=observation_id,
        entity_id=entity_id,
        observed_on=observed_on,
        available_at=available_at,
        revision=revision,
        values={"eps": 1.0},
    )


def _snapshot(
    *,
    as_of: str,
    available_at: str,
    members: tuple[str, ...] = ("600519",),
    universe_id: str = "CSI300",
    revision: str = "s1",
) -> MembershipSnapshot:
    return MembershipSnapshot(
        universe_id=universe_id,
        as_of=as_of,
        members=members,
        available_at=available_at,
        source_id="fixture",
        source_url="https://example.test/csi300",
        snapshot_revision=revision,
        fetched_at="2026-01-01T00:00:00",
        payload_sha256=DIGEST,
        parser_revision="p1",
        pit_membership=True,
    )


class TestPointInTimeFacts:
    def test_fact_not_yet_published_is_invisible(self) -> None:
        """财报期在截止日之前，但披露日在之后——不能被看见。"""
        q1 = _fact("q1", observed_on="2026-03-31", available_at="2026-04-28")
        assert select_point_in_time([q1], as_of="2026-04-27") is None
        assert select_point_in_time([q1], as_of="2026-04-28") is q1

    def test_later_period_published_later_does_not_shadow_visible_one(self) -> None:
        """按可见日选，不是按期间选。"""
        q1 = _fact("q1", observed_on="2026-03-31", available_at="2026-04-28")
        q2 = _fact("q2", observed_on="2026-06-30", available_at="2026-07-30")
        assert select_point_in_time([q1, q2], as_of="2026-07-01") is q1
        assert select_point_in_time([q1, q2], as_of="2026-07-30") is q2

    def test_restatement_wins_only_after_it_becomes_visible(self) -> None:
        original = _fact("q1", observed_on="2026-03-31", available_at="2026-04-28")
        restated = _fact("q1b", observed_on="2026-03-31", available_at="2026-08-15", revision="r2")
        assert select_point_in_time([original, restated], as_of="2026-08-14") is original
        assert select_point_in_time([original, restated], as_of="2026-08-15") is restated

    def test_other_entities_are_not_mixed_in(self) -> None:
        mine = _fact("a", observed_on="2026-03-31", available_at="2026-04-28")
        other = _fact("b", observed_on="2026-03-31", available_at="2026-04-28", entity_id="000001")
        assert select_point_in_time([mine, other], as_of="2026-05-01", entity_id="000001") is other

    def test_payload_digest_must_be_a_real_sha256(self) -> None:
        with pytest.raises(TemporalDataError):
            PointInTimeObservation(
                observation_id="x",
                entity_id="600519",
                observed_on="2026-03-31",
                available_at="2026-04-28",
                payload_sha256="not-a-digest",
            )


class TestMembershipSnapshots:
    def test_snapshot_effective_but_not_yet_announced_is_unusable(self) -> None:
        """成分生效日已过、公告可见日未到时必须降级，不能当成当时的名单用。"""
        pending = _snapshot(as_of="2026-06-01", available_at="2026-06-15")
        resolved = resolve_membership([pending], universe_id="CSI300", as_of="2026-06-10")
        assert resolved.members == ()
        assert resolved.degraded and resolved.survivorship_bias
        assert not resolved.pit_membership

    def test_degraded_snapshot_is_refused_by_the_strict_gate(self) -> None:
        pending = _snapshot(as_of="2026-06-01", available_at="2026-06-15")
        resolved = resolve_membership([pending], universe_id="CSI300", as_of="2026-06-10")
        with pytest.raises(TemporalDataError):
            assert_strict_membership(resolved)

    def test_picks_the_latest_snapshot_visible_at_the_cutoff(self) -> None:
        older = _snapshot(as_of="2026-03-01", available_at="2026-03-05", members=("600519",))
        newer = _snapshot(
            as_of="2026-06-01", available_at="2026-06-05", members=("600519", "000001"), revision="s2"
        )
        assert resolve_membership([older, newer], universe_id="CSI300", as_of="2026-05-31") is older
        assert resolve_membership([older, newer], universe_id="CSI300", as_of="2026-06-05") is newer

    def test_other_universes_are_not_borrowed(self) -> None:
        other = _snapshot(as_of="2026-03-01", available_at="2026-03-05", universe_id="CSI500")
        resolved = resolve_membership([other], universe_id="CSI300", as_of="2026-06-01")
        assert resolved.degraded and resolved.members == ()

    def test_strict_gate_accepts_a_complete_pit_snapshot(self) -> None:
        assert_strict_membership(_snapshot(as_of="2026-03-01", available_at="2026-03-05"))

    @pytest.mark.parametrize(
        "field, value",
        [
            ("available_at", ""),
            ("source_id", ""),
            ("source_url", ""),
            ("snapshot_revision", ""),
            ("payload_sha256", ""),
            ("parser_revision", ""),
        ],
    )
    def test_strict_gate_refuses_incomplete_provenance(self, field: str, value: str) -> None:
        """严格回测要求来源、版本、载荷 hash 齐全，缺一项就拒。"""
        base = _snapshot(as_of="2026-03-01", available_at="2026-03-05").to_dict()
        base[field] = value
        with pytest.raises(TemporalDataError):
            assert_strict_membership(MembershipSnapshot.from_dict(base))

    def test_strict_gate_refuses_an_empty_member_list(self) -> None:
        empty = _snapshot(as_of="2026-03-01", available_at="2026-03-05", members=())
        with pytest.raises(TemporalDataError):
            assert_strict_membership(empty)
