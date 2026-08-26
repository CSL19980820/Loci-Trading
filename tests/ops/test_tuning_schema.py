"""调参字段表：后端是唯一真相，界面不能漏掉任何一个阈值。"""
from __future__ import annotations

from src.ops.application.skill_watch.tuning import (
    DEFAULT_STAGES,
    FIELD_META,
    default_tuning,
    normalize_tuning,
    tuning_schema,
)


def test_schema_covers_every_stage_and_threshold() -> None:
    """新增阈值忘了登记 FIELD_META，这条会红——避免「能调但界面看不到」。"""
    schema = tuning_schema()
    defaults = default_tuning()

    assert {stage["key"] for stage in schema["stages"]} == set(DEFAULT_STAGES)

    for section in schema["sections"]:
        described = {field["key"] for field in section["fields"]}
        assert described == set(defaults[section["name"]]), section["name"]
        for field in section["fields"]:
            assert field["key"] in FIELD_META, f"{field['key']} 未登记中文名与步长"
            assert field["label"] != field["key"]
            assert field["step"] > 0


def test_schema_carries_the_same_ranges_used_for_clamping() -> None:
    schema = tuning_schema()
    gate = next(s for s in schema["sections"] if s["name"] == "gate")
    promotion = next(f for f in gate["fields"] if f["key"] == "promotion_attack")

    assert (promotion["min"], promotion["max"]) == (0.0, 1.0)
    # 界面允许填的上界之外，后端仍会钳回来
    clamped = normalize_tuning({"gate": {"promotion_attack": 9.9}})
    assert clamped["gate"]["promotion_attack"] == 1.0
