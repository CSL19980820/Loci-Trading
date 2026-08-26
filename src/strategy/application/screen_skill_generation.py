"""Screen Skill 草稿生成与方言原稿归一。"""
from __future__ import annotations

import json
import re

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


def _generate_description_draft(
    payload: ScreenSkillGenerateRequest,
    *,
    ops_db: str | None = None,
) -> ScreenSkillDraftModel:
    from src.ai import ChatMessage, chat, resolve_config
    from src.shared.api_deps import ops_store

    with ops_store(ops_db) as store:
        provider = resolve_config(
            store,
            str(payload.provider or ""),
            model=str(payload.model or ""),
        )
    response = chat(
        provider,
        [ChatMessage(role="user", content=_build_generate_prompt(payload))],
        max_tokens=4000,
        temperature=0.2,
        thinking=str(payload.thinking or ""),
    )
    raw = _strip_code_fence(response.text.strip())
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ScreenPackageError(f"AI 草稿不是合法 JSON：{exc}") from exc
    manifest = data.get("manifest") if isinstance(data, dict) else None
    if isinstance(manifest, dict):
        # 引用内容以用户提交的资料为准，避免模型改写摘录或补造来源。
        manifest["references"] = [
            item.model_dump(exclude_none=True) for item in payload.references
        ]
    try:
        return ScreenSkillDraftModel.model_validate(
            data, context={"require_provenance": True}
        )
    except Exception as exc:
        raise ScreenPackageError(f"AI 草稿缺少 provenance：{exc}") from exc


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


def _build_generate_prompt(payload: ScreenSkillGenerateRequest) -> str:
    supplied = [item.model_dump(exclude_none=True) for item in payload.references]
    desired_runtime = payload.runtime or "formula"
    desired_dialect = payload.dialect or ("python" if desired_runtime == "python" else "loci")
    return (
        "你是 A 股 Screen Skill 生成助手。只输出一个 JSON 对象，不要 markdown 代码块。\n"
        "字段必须只有 slug、name、description、version、enabled、runtime、dialect、"
        "code、formula、entrypoint、manifest、ui。\n"
        "runtime 只能是 formula 或 python；dialect 只能是 loci/tdx/ths/python。\n"
        "manifest 必须包含 schema_version=2、entry_timing、min_bars、params、"
        "output.signal、factors、logic、references、data。\n"
        "logic 每项必须有 id/title/expression/explanation/citations；每个 citation 必须"
        "引用 references 中存在的 id。references 必须有可定位的 url/path/section/quote。\n"
        "data.fields 列出行情字段，adjust 为 qfq/hfq/none，universe 给股票池对象。\n"
        "不得虚构资料。优先原样使用用户提供的 references，并在逻辑中准确引用。\n"
        f"目标 runtime={desired_runtime}，dialect={desired_dialect}，"
        f"entrypoint={payload.entrypoint or 'strategy.py:compute'}。\n"
        f"给定 entry_timing={payload.entry_timing}。\n"
        f"如提供 slug={payload.slug or ''}、name={payload.name or ''}，请优先沿用。\n"
        f"用户提供的 references={json.dumps(supplied, ensure_ascii=False)}\n\n"
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
