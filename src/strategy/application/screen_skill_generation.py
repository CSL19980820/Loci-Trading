"""Screen Skill 草稿生成与方言原稿归一。"""
from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any

from src.strategy.api.screen_skill_schemas import ScreenSkillDraftModel, ScreenSkillGenerateRequest
from src.ops import ScreenPackageError

_SIGNAL_PATTERN = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*:(?!=)", re.M)
_FACTOR_PATTERN = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*:=", re.M)
_FORMULA_FIELDS = {
    "OPEN": "open",
    "HIGH": "high",
    "LOW": "low",
    "CLOSE": "close",
    "VOL": "volume",
    "AMOUNT": "amount",
    "HSL": "turnover",
}
_PYTHON_PANEL_FIELD_PATTERN = re.compile(
    r'panels(?:\.get)?\(\s*[\'"]([A-Za-z_][A-Za-z0-9_]*)[\'"]'
    r'|panels\[\s*[\'"]([A-Za-z_][A-Za-z0-9_]*)[\'"]\s*\]'
)


def build_generated_draft(
    payload: ScreenSkillGenerateRequest,
    *,
    ops_db: str | None = None,
) -> ScreenSkillDraftModel:
    if payload.source_type in {"tdx", "ths"}:
        return _build_formula_draft(payload)
    if payload.source_type == "python":
        return _build_python_draft(payload)
    return _generate_description_draft(payload, ops_db=ops_db)


BRIEF_REFERENCE_ID = "brief"

_DRAFT_KEYS = {
    "slug", "name", "description", "version", "enabled", "runtime", "dialect",
    "code", "formula", "entrypoint", "manifest", "ui",
}
_MANIFEST_KEYS = {
    "schema_version", "entry_timing", "min_bars", "params", "output",
    "factors", "logic", "references", "data",
}
_LOGIC_KEYS = {"id", "title", "expression", "explanation", "citations"}
_SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


def _generation_references(
    payload: ScreenSkillGenerateRequest,
) -> tuple[list[dict[str, Any]], bool]:
    """用户给了资料就只用资料；没给时，用户的原话就是逻辑唯一可追溯的来源。"""
    supplied = [item.model_dump(exclude_none=True) for item in payload.references]
    if supplied:
        return supplied, False
    brief = (payload.brief or payload.source).strip()[:4000]
    return [
        {"id": BRIEF_REFERENCE_ID, "title": "需求描述", "kind": "brief", "quote": brief}
    ], True


def _generate_description_draft(
    payload: ScreenSkillGenerateRequest,
    *,
    ops_db: str | None = None,
) -> ScreenSkillDraftModel:
    from src.ai import ChatMessage, chat, resolve_config
    from src.shared.api_deps import ops_store

    references, synthesized = _generation_references(payload)
    with ops_store(ops_db) as store:
        provider = resolve_config(
            store,
            str(payload.provider or ""),
            model=str(payload.model or ""),
        )
    response = chat(
        provider,
        [
            ChatMessage(
                role="user",
                content=_build_generate_prompt(payload, references, synthesized),
            )
        ],
        max_tokens=6000,
        temperature=0.2,
        thinking=str(payload.thinking or ""),
    )
    raw = _extract_json_object(response.text.strip())
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ScreenPackageError(f"AI 草稿不是合法 JSON：{exc}") from exc
    if not isinstance(data, dict):
        raise ScreenPackageError("AI 草稿不是 JSON 对象")
    data = _normalize_generated_draft(data, payload, references, synthesized)
    try:
        return ScreenSkillDraftModel.model_validate(
            data, context={"require_provenance": True}
        )
    except Exception as exc:
        raise ScreenPackageError(f"AI 草稿缺少 provenance：{exc}") from exc


def _normalize_generated_draft(
    data: dict[str, Any],
    payload: ScreenSkillGenerateRequest,
    references: list[dict[str, Any]],
    synthesized: bool,
) -> dict[str, Any]:
    """把模型输出收进草稿契约：丢掉多余键、补齐标识、引用以用户资料为准。

    只做形状层面的收口，不改写公式与逻辑内容；公式能不能编译仍由试跑诊断说话。
    """
    draft = {key: value for key, value in data.items() if key in _DRAFT_KEYS}
    # 请求里写明的运行时 / 方言 / 入场时点 / 名称是用户的选择，模型只能填空，不能改写。
    runtime = payload.runtime or draft.get("runtime")
    if runtime not in ("formula", "python"):
        runtime = "formula"
    draft["runtime"] = runtime
    if runtime == "python":
        draft["dialect"] = "python"
        entrypoint = str(payload.entrypoint or draft.get("entrypoint") or "").strip()
        draft["entrypoint"] = entrypoint if ":" in entrypoint else "strategy.py:compute"
    else:
        dialect = payload.dialect if payload.dialect in ("loci", "tdx", "ths") else draft.get("dialect")
        draft["dialect"] = dialect if dialect in ("loci", "tdx", "ths") else "loci"
        draft.pop("entrypoint", None)

    code = str(draft.get("code") or draft.get("formula") or "").strip()
    if code:
        draft["code"] = code + "\n"
        draft["formula"] = code + "\n" if runtime == "formula" else None
    if runtime == "python":
        draft.pop("formula", None)

    draft["slug"] = _generated_slug(draft.get("slug"), payload)
    name = str(payload.name or draft.get("name") or "").strip()[:80] or "AI 草稿战法"
    draft["name"] = name
    draft["description"] = (
        str(draft.get("description") or payload.description or name).strip()[:240] or name
    )
    draft["version"] = str(draft.get("version") or "0.1.0")[:32]
    draft["enabled"] = draft.get("enabled") is not False
    if not isinstance(draft.get("ui"), dict):
        draft.pop("ui", None)

    raw_manifest = draft.get("manifest")
    manifest = {
        key: value
        for key, value in (raw_manifest.items() if isinstance(raw_manifest, dict) else [])
        if key in _MANIFEST_KEYS
    }
    manifest["schema_version"] = 2
    manifest["entry_timing"] = payload.entry_timing
    min_bars = manifest.get("min_bars")
    manifest["min_bars"] = (
        max(1, min(5000, int(min_bars))) if _is_finite_number(min_bars) else 120
    )
    manifest["params"] = _normalized_params(manifest.get("params"))
    output = manifest.get("output")
    signal = str(output.get("signal") or "") if isinstance(output, dict) else ""
    manifest["output"] = {"signal": (signal or _detect_signal_name(code))[:64]}
    factors = manifest.get("factors")
    manifest["factors"] = (
        [str(item)[:64] for item in factors if str(item).strip()][:100]
        if isinstance(factors, list)
        else _detect_factor_names(code)
    )
    manifest["references"] = references
    manifest["logic"] = _normalized_logic(manifest.get("logic"), references, synthesized)
    data_block = manifest.get("data")
    data_block = dict(data_block) if isinstance(data_block, dict) else {}
    fields = data_block.get("fields")
    if not isinstance(fields, list) or not fields:
        fields = _detect_python_fields(code) if runtime == "python" else _detect_formula_fields(code)
    adjust = str(data_block.get("adjust") or "qfq")
    universe = data_block.get("universe")
    manifest["data"] = {
        "fields": [str(item) for item in fields if str(item).strip()],
        "adjust": adjust if adjust in ("qfq", "hfq", "none") else "qfq",
        "universe": universe if isinstance(universe, dict) else {"preset": "default_a_share"},
    }
    draft["manifest"] = manifest
    return draft


def _generated_slug(raw: Any, payload: ScreenSkillGenerateRequest) -> str:
    if payload.slug:
        return payload.slug
    text = re.sub(r"[^a-z0-9._-]+", "-", str(raw or "").strip().lower()).strip("-._")[:64]
    if _SLUG_PATTERN.match(text):
        return text
    digest = hashlib.sha1((payload.brief or payload.source).encode("utf-8")).hexdigest()[:8]
    return f"ai-{digest}"


def _is_finite_number(value: Any) -> bool:
    """JSON 能解析出 Infinity / NaN；它们既不能进 int()，也不该落进 manifest。"""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _normalized_params(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    params: dict[str, Any] = {}
    for name, spec in list(raw.items())[:100]:
        if not isinstance(spec, dict):
            continue
        kind = spec.get("type")
        default = spec.get("default")
        if kind == "bool" and isinstance(default, bool):
            value: int | float | bool = default
        elif kind in ("int", "float") and _is_finite_number(default):
            value = int(default) if kind == "int" else float(default)
        else:
            continue
        row: dict[str, Any] = {"type": kind, "default": value}
        for bound in ("min", "max"):
            limit = spec.get(bound)
            if _is_finite_number(limit):
                row[bound] = limit
        label = str(spec.get("label") or "").strip()[:40]
        if label:
            row["label"] = label
        params[str(name)[:64]] = row
    return params


def _normalized_logic(
    raw: Any,
    references: list[dict[str, Any]],
    synthesized: bool,
) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    known = {str(item.get("id")) for item in references}
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(raw[:100]):
        if not isinstance(item, dict):
            continue
        row = {key: value for key, value in item.items() if key in _LOGIC_KEYS}
        title = str(row.get("title") or "").strip()[:120]
        expression = str(row.get("expression") or "").strip()[:4000]
        explanation = str(row.get("explanation") or "").strip()[:2000]
        if not (title and expression and explanation):
            continue
        raw_citations = row.get("citations")
        citations = (
            [str(c) for c in raw_citations if isinstance(c, (str, int)) and str(c) in known]
            if isinstance(raw_citations, list)
            else []
        )
        if not citations and synthesized:
            citations = [BRIEF_REFERENCE_ID]
        rows.append(
            {
                "id": str(row.get("id") or f"rule-{index + 1}")[:64],
                "title": title,
                "expression": expression,
                "explanation": explanation,
                "citations": citations,
            }
        )
    return rows


def _extract_json_object(text: str) -> str:
    """取回复里第一个 `{` 到最后一个 `}`：前后的说明文字与代码围栏都丢掉。"""
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return text[start : end + 1]
    return _strip_code_fence(text).strip()


def _build_formula_draft(payload: ScreenSkillGenerateRequest) -> ScreenSkillDraftModel:
    formula = _normalize_code(payload.source)
    signal = _detect_signal_name(formula)
    factors = _detect_factor_names(formula)
    draft = {
        "slug": payload.slug or f"{payload.source_type}-draft",
        "name": payload.name or f"{payload.source_type.upper()} 草稿战法",
        "description": payload.description
        or f"由 {payload.source_type.upper()} 原稿归一得到，需继续校对参数与因子。",
        "version": "0.1.0",
        "enabled": True,
        "runtime": "formula",
        "dialect": payload.source_type,
        "code": formula,
        "formula": formula,
        "manifest": {
            "schema_version": 2,
            "entry_timing": payload.entry_timing,
            "min_bars": 120,
            "params": {},
            "output": {"signal": signal},
            "factors": factors,
            "logic": [],
            "references": [item.model_dump(exclude_none=True) for item in payload.references],
            "data": {
                "fields": _detect_formula_fields(formula),
                "adjust": "qfq",
                "universe": {"preset": "default_a_share"},
            },
        },
    }
    return ScreenSkillDraftModel.model_validate(draft)


def _build_python_draft(payload: ScreenSkillGenerateRequest) -> ScreenSkillDraftModel:
    source = _normalize_code(payload.source)
    from src.strategy.application.audit import audit_source

    audit = audit_source(
        source,
        entry_timing=str(payload.entry_timing or "next_open"),
        strategy=str(payload.slug or "python-draft"),
    )
    if audit.failed:
        raise ScreenPackageError(f"前视审计未通过：{audit.reason()}")
    draft = {
        "slug": payload.slug or "python-draft",
        "name": payload.name or "Python 草稿战法",
        "description": payload.description or "由 Python 原稿导入，需补齐参数和说明。",
        "version": "0.1.0",
        "enabled": True,
        "runtime": "python",
        "dialect": "python",
        "code": source,
        "entrypoint": payload.entrypoint or "strategy.py:compute",
        "manifest": {
            "schema_version": 2,
            "entry_timing": payload.entry_timing,
            "min_bars": 120,
            "params": {},
            "output": {"signal": "PICK"},
            "factors": [],
            "logic": [],
            "references": [item.model_dump(exclude_none=True) for item in payload.references],
            "data": {
                "fields": _detect_python_fields(source),
                "adjust": "qfq",
                "universe": {"preset": "default_a_share"},
            },
        },
    }
    return ScreenSkillDraftModel.model_validate(draft)


def _formula_syntax_guide() -> str:
    from src.formula import formula_functions_catalog

    signatures = "、".join(
        f"{row['signature']}={row['summary']}" for row in formula_functions_catalog()
    )
    return (
        "Loci 公式语法：每条语句以分号结尾；`名称:=表达式;` 定义中间因子，"
        "`PICK: 布尔表达式;` 输出唯一主信号（output.signal 与它同名）。\n"
        "行情字段：OPEN HIGH LOW CLOSE VOL AMOUNT HSL（换手率，百分比口径）。\n"
        "运算：+ - * /，比较 > >= < <= = <>，逻辑 AND OR NOT；注释写在 {} 里。\n"
        "manifest.params 里定义的参数名可直接当常量使用（如 N）。\n"
        f"只允许使用这些函数：{signatures}。\n"
        "示例：\nBASE:=MA(CLOSE,N);\nVOLR:=VOL/MA(VOL,5);\nPICK: CLOSE>BASE AND VOLR>=1.5;\n"
    )


def _build_generate_prompt(
    payload: ScreenSkillGenerateRequest,
    references: list[dict[str, Any]] | None = None,
    synthesized: bool = False,
) -> str:
    supplied = (
        references
        if references is not None
        else [item.model_dump(exclude_none=True) for item in payload.references]
    )
    desired_runtime = payload.runtime or "formula"
    desired_dialect = payload.dialect or ("python" if desired_runtime == "python" else "loci")
    citation_rule = (
        f"没有外部资料：每条 logic 的 citations 只写 [\"{BRIEF_REFERENCE_ID}\"]（即用户需求原话），"
        "不得编造论文、网址或书目。\n"
        if synthesized
        else "不得虚构资料。优先原样使用用户提供的 references，并在逻辑中准确引用。\n"
    )
    syntax = _formula_syntax_guide() if desired_runtime == "formula" else (
        "Python 策略：entrypoint 指向 strategy.py:compute(panels, params)，"
        "panels 是字段名到 DataFrame（日期 × 代码）的映射；返回 {'signals': 布尔 DataFrame, "
        "'factors': {名称: DataFrame}}。只能使用当日及以前的数据，禁止前视。\n"
    )
    return (
        "你是 A 股 Screen Skill 生成助手。只输出一个 JSON 对象，不要 markdown 代码块。\n"
        "字段必须只有 slug、name、description、version、enabled、runtime、dialect、"
        "code、formula、entrypoint、manifest、ui。\n"
        "slug 只用小写字母、数字与连字符；name 为简洁中文战法名（不超过 16 字）；"
        "description 一句话概括选股逻辑（不超过 80 字）。\n"
        "runtime 只能是 formula 或 python；dialect 只能是 loci/tdx/ths/python。\n"
        "manifest 必须包含 schema_version=2、entry_timing、min_bars、params、"
        "output.signal、factors、logic、references、data。\n"
        "params 每项形如 {\"type\":\"int|float|bool\",\"default\":值,\"min\":下限,\"max\":上限,\"label\":\"中文名\"}。\n"
        "logic 每项必须有 id/title/expression/explanation/citations；每个 citation 必须"
        "引用 references 中存在的 id；title 与 explanation 用中文。\n"
        "data.fields 列出行情字段（open/high/low/close/volume/amount/turnover），"
        "adjust 为 qfq/hfq/none，universe 给股票池对象。\n"
        + citation_rule
        + syntax
        + f"目标 runtime={desired_runtime}，dialect={desired_dialect}，"
        f"entrypoint={payload.entrypoint or 'strategy.py:compute'}。\n"
        f"给定 entry_timing={payload.entry_timing}。\n"
        f"如提供 slug={payload.slug or ''}、name={payload.name or ''}，请优先沿用。\n"
        f"references={json.dumps(supplied, ensure_ascii=False)}\n\n"
        f"需求：{payload.source.strip()}"
    )


def _strip_code_fence(text: str) -> str:
    if not text.startswith("```"):
        return text
    stripped = text.strip("`")
    return stripped.split("\n", 1)[1] if "\n" in stripped else stripped


def _normalize_code(source: str) -> str:
    return str(source or "").rstrip() + "\n"


def _detect_signal_name(formula: str) -> str:
    hit = _SIGNAL_PATTERN.search(formula)
    return str(hit.group(1)).upper() if hit else "PICK"


def _detect_factor_names(formula: str) -> list[str]:
    signal = _detect_signal_name(formula)
    found: list[str] = []
    for match in _FACTOR_PATTERN.finditer(formula):
        name = str(match.group(1)).upper()
        if name != signal and name not in found:
            found.append(name)
    return found


def _detect_formula_fields(formula: str) -> list[str]:
    found: list[str] = []
    upper = formula.upper()
    for token, field in _FORMULA_FIELDS.items():
        if token in upper and field not in found:
            found.append(field)
    return found or ["close"]


def _detect_python_fields(source: str) -> list[str]:
    found: list[str] = []
    for match in _PYTHON_PANEL_FIELD_PATTERN.finditer(source):
        raw = match.group(1) or match.group(2)
        if not raw:
            continue
        field = _FORMULA_FIELDS.get(raw.upper()) or raw.strip().lower()
        if field not in found:
            found.append(field)
    return found or ["close"]
