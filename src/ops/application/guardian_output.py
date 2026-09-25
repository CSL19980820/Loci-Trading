"""Strict complete JSON output, with harmless Markdown wrappers and diagnostics."""
import hashlib
import json
import re

JSON_OUTPUT_RULES = '最终仅输出一个符合所附契约的完整JSON对象，不添加前导说明、Markdown或代码围栏。字段中的判断与完整行动条件不能为格式或简洁要求而删改。'


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'JSON对象存在重复字段{key!r}；请依据原始意图明确唯一值，不能默认取首个或最后一个值')
        result[key] = value
    return result


def load_json_response(text: str):
    value = text.strip()
    wrapper = re.fullmatch(r'```(?:json)?[ \t]*\r?\n([\s\S]*?)\r?\n?```', value, re.IGNORECASE)
    if wrapper:
        value = wrapper[1]
    # The hook also checks nested orders and execution terms before schema validation.
    result = json.loads(value, object_pairs_hook=_unique_object)
    if not isinstance(result, dict):
        raise ValueError('最终JSON必须是一个完整对象')
    return result


def failed_response(diagnostic: dict, text: str) -> None:
    # Stored with tenant-scoped usage evidence, never appended to public report prose.
    diagnostic.update(raw_response=text, response_sha256=hashlib.sha256(text.encode()).hexdigest())
