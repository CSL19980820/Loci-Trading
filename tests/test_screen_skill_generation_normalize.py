"""AI 策稿生成：模型输出收口不改写用户选择，且对异常形状稳健。"""
import json

from src.strategy.api.screen_skill_schemas import ScreenSkillDraftModel, ScreenSkillGenerateRequest
from src.strategy.application.screen_skill_generation import (
    BRIEF_REFERENCE_ID,
    _extract_json_object,
    _generation_references,
    _normalize_generated_draft,
)


def _request(**overrides):
    base = {
        "source_type": "description",
        "source": "放量突破 20 日均线",
        "brief": "放量突破 20 日均线",
        "provider": "fixture",
        "entry_timing": "close",
        "runtime": "formula",
        "dialect": "loci",
    }
    base.update(overrides)
    return ScreenSkillGenerateRequest(**base)


def test_brief_becomes_the_only_reference_when_none_supplied():
    references, synthesized = _generation_references(_request())
    assert synthesized is True
    assert references == [
        {"id": BRIEF_REFERENCE_ID, "title": "需求描述", "kind": "brief", "quote": "放量突破 20 日均线"}
    ]


def test_extract_json_ignores_prose_and_fences_around_the_object():
    assert _extract_json_object('{"a": 1}\n说明：已完成') == '{"a": 1}'
    assert _extract_json_object('```json\n{"a": 1}\n```\n以上是草稿') == '{"a": 1}'
    assert _extract_json_object('好的：\n{"a": {"b": 2}}') == '{"a": {"b": 2}}'


def test_normalize_keeps_user_choices_and_survives_odd_shapes():
    payload = _request(name="我的战法")
    references, synthesized = _generation_references(payload)
    raw = json.loads(
        '{"runtime": "python", "dialect": "python", "name": "模型起的名", "slug": "Volume Breakout!",'
        ' "extra": 1, "code": "BASE:=MA(CLOSE,N);\\nPICK: CLOSE>BASE;",'
        ' "manifest": {"entry_timing": "next_open", "min_bars": Infinity, "foo": "bar",'
        ' "params": {"N": {"type": "int", "default": 20, "min": NaN, "max": 120}, "BAD": {"type": "str", "default": "x"}},'
        ' "logic": [{"title": "站上均线", "expression": "CLOSE>BASE", "explanation": "收盘高于均线", "citations": 1},'
        ' {"title": "放量", "expression": "VOL>MA(VOL,5)", "explanation": "量能放大", "citations": "12"}]}}'
    )
    draft = _normalize_generated_draft(raw, payload, references, synthesized)

    assert draft["runtime"] == "formula"
    assert draft["dialect"] == "loci"
    assert draft["name"] == "我的战法"
    assert draft["slug"] == "volume-breakout"
    assert "extra" not in draft
    manifest = draft["manifest"]
    assert manifest["entry_timing"] == "close"
    assert manifest["min_bars"] == 120
    assert "foo" not in manifest
    assert manifest["params"] == {"N": {"type": "int", "default": 20, "max": 120}}
    assert [row["citations"] for row in manifest["logic"]] == [[BRIEF_REFERENCE_ID], [BRIEF_REFERENCE_ID]]

    model = ScreenSkillDraftModel.model_validate(draft, context={"require_provenance": True})
    assert model.manifest.references[0].id == BRIEF_REFERENCE_ID


def test_python_entrypoint_defaults_when_missing_callable():
    payload = _request(runtime="python", dialect="python", entrypoint="strategy.py")
    references, synthesized = _generation_references(payload)
    raw = {
        "code": "def compute(panels, params):\n    return {'signals': panels['close'] > 0}\n",
        "manifest": {
            "logic": [{"title": "t", "expression": "e", "explanation": "x", "citations": []}],
        },
    }
    draft = _normalize_generated_draft(raw, payload, references, synthesized)
    assert draft["runtime"] == "python"
    assert draft["entrypoint"] == "strategy.py:compute"
    assert "formula" not in draft
