from src.app.screen_skill_models import ScreenSkillPreviewRequest
from src.app.screen_skills import _data_field_diagnostics, preview_screen_skill


class _Engine:
    def required_fields(self) -> tuple[str, ...]:
        return ("close", "volume")


def test_data_field_diagnostics_reports_missing_runtime_fields() -> None:
    diagnostics = _data_field_diagnostics(
        _Engine(),
        {"data": {"fields": ["close"], "adjust": "qfq"}},
    )

    assert diagnostics == [
        {
            "code": "W_DATA_FIELDS_MISSING",
            "severity": "warning",
            "line": None,
            "column": None,
            "message": "data.fields 缺少运行时必需字段：['volume']",
        }
    ]


def test_python_preview_is_disabled_without_run() -> None:
    payload = ScreenSkillPreviewRequest.model_validate(
        {
            "slug": "bad-python",
            "name": "语法错误示例",
            "description": "用于验证 Python 静态预览会拒绝语法错误。",
            "runtime": "python",
            "dialect": "python",
            "entrypoint": "strategy.py:compute",
            "code": "def compute(panels, params)\n    return {}\n",
            "manifest": {
                "schema_version": 2,
                "entry_timing": "next_open",
                "min_bars": 2,
                "params": {},
                "output": {"signal": "PICK"},
                "factors": [],
                "logic": [],
                "references": [],
                "data": {"fields": ["close"], "adjust": "qfq"},
            },
        }
    )

    result = preview_screen_skill(payload)

    assert result["ok"] is False
    assert result["diagnostics"][0]["code"] == "E_PYTHON_PREVIEW_DISABLED"
