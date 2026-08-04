"""Screen Skill API 模型。"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, ValidationInfo, model_validator

from src.app.legacy.quant_common import QuantModel, UniverseSpecModel

ScreenRuntime = Literal["formula", "python"]
ScreenDialect = Literal["loci", "tdx", "ths", "python"]


class ScreenSkillParamModel(QuantModel):
    type: Literal["int", "float", "bool"]
    default: int | float | bool
    min: int | float | None = None
    max: int | float | None = None
    label: str = Field(default="", max_length=40)


class ScreenSkillManifestOutputModel(QuantModel):
    signal: str = Field(default="PICK", min_length=1, max_length=64)


class ScreenSkillLogicModel(QuantModel):
    id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=120)
    expression: str = Field(min_length=1, max_length=4000)
    explanation: str = Field(min_length=1, max_length=2000)
    citations: list[str] = Field(default_factory=list)


class ScreenSkillReferenceModel(QuantModel):
    id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=200)
    kind: str = Field(min_length=1, max_length=40)
    url: str | None = Field(default=None, max_length=1000)
    path: str | None = Field(default=None, max_length=1000)
    section: str | None = Field(default=None, max_length=240)
    quote: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def _ensure_locator(self) -> ScreenSkillReferenceModel:
        if not any(
            str(value or "").strip()
            for value in (self.url, self.path, self.section, self.quote)
        ):
            raise ValueError("reference 至少要提供 url/path/section/quote 之一")
        return self


class ScreenSkillDataModel(QuantModel):
    fields: list[str] = Field(default_factory=list)
    adjust: str = Field(default="qfq", max_length=16)
    universe: dict[str, Any] | None = None


class ScreenSkillManifestModel(QuantModel):
    schema_version: Literal[1, 2] = 2
    entry_timing: Literal["open", "close", "next_open", "next_dip"] = "next_open"
    min_bars: int = Field(default=1, ge=1, le=5000)
    params: dict[str, ScreenSkillParamModel] = Field(default_factory=dict, max_length=100)
    output: ScreenSkillManifestOutputModel = Field(
        default_factory=ScreenSkillManifestOutputModel
    )
    factors: list[str] = Field(default_factory=list, max_length=100)
    logic: list[ScreenSkillLogicModel] = Field(default_factory=list, max_length=100)
    references: list[ScreenSkillReferenceModel] = Field(default_factory=list, max_length=100)
    data: ScreenSkillDataModel = Field(default_factory=ScreenSkillDataModel)

    @model_validator(mode="before")
    @classmethod
    def _coerce_legacy_signal(cls, raw: Any) -> Any:
        if not isinstance(raw, dict):
            return raw
        data = dict(raw)
        output = data.get("output")
        if not isinstance(output, dict):
            output = {}
        signal = data.pop("signal", None)
        if signal and not output.get("signal"):
            output["signal"] = signal
        data["output"] = output
        data.setdefault("schema_version", 1)
        data.setdefault("logic", [])
        data.setdefault("references", [])
        data.setdefault("data", {})
        if data.get("params") is None:
            data["params"] = {}
        if data.get("factors") is None:
            data["factors"] = []
        return data

    @model_validator(mode="after")
    def _validate_citations(self) -> ScreenSkillManifestModel:
        known = {item.id for item in self.references}
        for logic in self.logic:
            unknown = [item for item in logic.citations if item not in known]
            if unknown:
                raise ValueError(
                    f"逻辑 {logic.id} 引用了未知 reference：{unknown}"
                )
        return self


class ScreenSkillRunModel(QuantModel):
    trade_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    codes: list[str] | None = Field(default=None, max_length=5000)
    params: dict[str, Any] | None = None
    universe: UniverseSpecModel | None = None
    skip_health_check: bool = False


class ScreenSkillDraftModel(QuantModel):
    slug: str = Field(
        min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$"
    )
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=240)
    version: str = Field(default="0.1.0", max_length=32)
    enabled: bool = True
    runtime: ScreenRuntime = "formula"
    dialect: ScreenDialect = "loci"
    code: str | None = Field(default=None, min_length=1, max_length=200000)
    formula: str | None = Field(default=None, min_length=1, max_length=200000)
    entrypoint: str | None = Field(default=None, max_length=240)
    manifest: ScreenSkillManifestModel
    ui: dict[str, Any] | None = None

    @model_validator(mode="before")
    @classmethod
    def _coerce_legacy_payload(cls, raw: Any) -> Any:
        if not isinstance(raw, dict):
            return raw
        if "skill" not in raw and "screen" not in raw:
            return raw
        skill = raw.get("skill") or {}
        manifest = raw.get("manifest") or raw.get("screen") or {}
        runtime = raw.get("runtime") or manifest.get("runtime") or "formula"
        dialect = raw.get("dialect") or manifest.get("dialect")
        code = raw.get("code")
        formula = raw.get("formula")
        if code is None and formula is not None:
            code = formula
        return {
            "slug": raw.get("slug") or skill.get("slug"),
            "name": raw.get("name") or skill.get("name"),
            "description": raw.get("description") or skill.get("description"),
            "version": raw.get("version") or skill.get("version") or "0.1.0",
            "enabled": raw.get("enabled")
            if "enabled" in raw
            else skill.get("enabled", True),
            "runtime": runtime,
            "dialect": dialect,
            "code": code,
            "formula": formula,
            "entrypoint": raw.get("entrypoint") or manifest.get("entrypoint"),
            "manifest": manifest,
            "ui": raw.get("ui"),
        }

    @model_validator(mode="after")
    def _normalize_runtime_fields(self, info: ValidationInfo) -> ScreenSkillDraftModel:
        raw_code = self.code or self.formula
        if not raw_code:
            raise ValueError("缺少 code/formula")
        self.code = raw_code
        if self.runtime == "python":
            self.dialect = "python"
            self.entrypoint = str(self.entrypoint or "strategy.py:compute").strip()
            if ":" not in self.entrypoint:
                raise ValueError("python runtime 的 entrypoint 必须是 file.py:callable")
        else:
            if self.dialect == "python":
                raise ValueError("formula runtime 的 dialect 不能是 python")
            self.entrypoint = None
            self.formula = self.code
        if info.context and info.context.get("require_provenance"):
            _ensure_manifest_provenance(self.manifest)
        return self


class ScreenSkillPreviewRequest(ScreenSkillDraftModel):
    run: ScreenSkillRunModel | None = None


class ScreenSkillUpdateRequest(ScreenSkillDraftModel):
    expected_revision: str = Field(min_length=8, max_length=64)


class ScreenSkillDeleteRequest(QuantModel):
    expected_revision: str = Field(min_length=8, max_length=64)


class ScreenSkillGenerateRequest(QuantModel):
    source_type: Literal["description", "tdx", "ths", "python"]
    source: str = Field(min_length=1, max_length=20000)
    slug: str | None = Field(
        default=None, max_length=64, pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$"
    )
    name: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=240)
    entry_timing: Literal["open", "close", "next_open", "next_dip"] = "next_open"
    runtime: ScreenRuntime | None = None
    dialect: ScreenDialect | None = None
    entrypoint: str | None = Field(default=None, max_length=240)
    references: list[ScreenSkillReferenceModel] = Field(default_factory=list, max_length=100)
    provider: str | None = Field(default=None, max_length=64)
    model: str | None = Field(default=None, max_length=120)
    thinking: str | None = Field(default=None, max_length=16)

    @model_validator(mode="after")
    def _validate_source(self) -> ScreenSkillGenerateRequest:
        if self.source_type == "description":
            if len(self.source.strip()) < 10:
                raise ValueError("自然语言描述至少 10 个字符")
            if not (self.provider or "").strip():
                raise ValueError("自然语言生成必须指定 provider")
            if not self.references:
                raise ValueError("自然语言生成必须至少提供一条可定位资料来源")
        return self


def _ensure_manifest_provenance(manifest: ScreenSkillManifestModel) -> None:
    if not manifest.logic:
        raise ValueError("AI 生成稿必须提供 manifest.logic")
    if not manifest.references:
        raise ValueError("AI 生成稿必须提供 manifest.references")
    if not manifest.data.fields:
        raise ValueError("AI 生成稿必须提供 manifest.data.fields")
    known = {item.id for item in manifest.references}
    for logic in manifest.logic:
        if not logic.citations:
            raise ValueError(f"逻辑 {logic.id} 缺少 citations")
        unknown = [item for item in logic.citations if item not in known]
        if unknown:
            raise ValueError(f"逻辑 {logic.id} 引用了未知 reference：{unknown}")
