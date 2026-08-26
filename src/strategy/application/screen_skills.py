"""Screen Skill 应用编排。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from src.shared.api_deps import market_store, missing_dependency
from src.strategy.application.screen_skill_generation import build_generated_draft
from src.strategy.api.screen_skill_schemas import (
    ScreenSkillDraftModel,
    ScreenSkillGenerateRequest,
    ScreenSkillPreviewRequest,
)
from src.ops import (
    ScreenPackageError,
    ScreenPackageRecord,
    delete_screen_history,
    delete_screen_package,
    get_screen_package,
    list_screen_history,
    list_screen_packages,
    read_screen_archive,
    restore_screen_package,
    save_screen_package,
)
from src.formula import (
    build_formula_explanation,
    build_manifest_explanation,
    screen_skill_catalog,
)
from src.strategy.application.catalog import replace_screen_engines
from src.strategy.application.screen_formula import (
    FormulaScreenEngine,
    ScreenFormulaError,
    build_formula_engine,
)
from src.strategy.application.screen_python import PythonScreenEngine, build_python_engine
from src.strategy.application.screener import ScreenResult, screen
from src.strategy import StrategyEngine, is_builtin_registered

ScreenEngine = FormulaScreenEngine | PythonScreenEngine
MAX_PREVIEW_PICKS = 500


def refresh_screen_strategy_catalog() -> dict[str, Any]:
    engines: list[StrategyEngine] = []
    metadata_by_slug: dict[str, dict[str, Any]] = {}
    rejected: list[dict[str, Any]] = []
    for record in list_screen_packages():
        if not record.enabled:
            continue
        try:
            _ensure_formula_slug_available(record.slug, allow_existing_formula=True)
            engines.append(_compile_record(record))
            metadata_by_slug[record.slug] = {
                "version": record.package_revision,
                "version_history": list_screen_history(
                    record.slug, skill_root_path=Path(record.install_path).parent
                ),
            }
        except ScreenFormulaError as exc:
            rejected.append(
                {"slug": record.slug, "diagnostics": _diagnostics_from_error(exc)}
            )
        except ScreenPackageError as exc:
            rejected.append(
                {
                    "slug": record.slug,
                    "diagnostics": [_package_error_diagnostic(exc)],
                }
            )
    replace_screen_engines(engines, metadata_by_slug=metadata_by_slug)
    return {"count": len(engines), "rejected": rejected}


def get_screen_skill_catalog() -> dict[str, Any]:
    """返回工坊可插入、且当前 compiler/runtime 确实支持的能力目录。"""
    return screen_skill_catalog()


def list_screen_skill_items() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for record in list_screen_packages():
        engine: ScreenEngine | None = None
        try:
            engine = _compile_record(record)
        except ScreenFormulaError:
            pass
        items.append(_record_summary(record, engine))
    return items


def get_screen_skill_item(slug: str) -> dict[str, Any] | None:
    record = get_screen_package(slug)
    if record is None:
        return None
    return _record_detail(record, _compile_record(record))


def preview_screen_skill(
    payload: ScreenSkillPreviewRequest,
    *,
    market_db: str | None = None,
) -> dict[str, Any]:
    package_revision = _package_revision_for_payload(payload)
    manifest = payload.manifest.model_dump(mode="python")
    if payload.runtime == "python":
        # Draft code arrives over HTTP. It must not be imported into the API process.
        return {
            "ok": False,
            "diagnostics": [{
                "code": "E_PYTHON_PREVIEW_DISABLED",
                "severity": "error",
                "line": None,
                "column": None,
                "message": "Python 运行时在线预览已禁用；请使用受限执行器运行已保存战法。",
            }],
            "derived": None,
            "package_revision": package_revision,
            "runtime": payload.runtime,
            "dialect": payload.dialect,
            "code": payload.code or payload.formula or "",
            "logic": manifest.get("logic") or [],
            "references": manifest.get("references") or [],
            "data": _manifest_data(manifest),
            "explanation": None,
        }
    try:
        engine = _build_engine(_payload_dict(payload))
        _validate_engine(engine)
    except ScreenFormulaError as exc:
        return {
            "ok": False,
            "diagnostics": _diagnostics_from_error(exc),
            "derived": None,
            "package_revision": package_revision,
            "runtime": payload.runtime,
            "dialect": payload.dialect,
            "code": payload.code or payload.formula or "",
            "logic": manifest.get("logic") or [],
            "references": manifest.get("references") or [],
            "data": _manifest_data(manifest),
            "explanation": None,
        }

    body: dict[str, Any] = {
        "ok": True,
        "diagnostics": _data_field_diagnostics(engine, manifest),
        "derived": _derived_info(engine, manifest),
        "package_revision": package_revision,
        "strategy_revision": engine.strategy_revision,
        "runtime": payload.runtime,
        "dialect": payload.dialect,
        "code": payload.code or payload.formula or "",
        "logic": manifest.get("logic") or [],
        "references": manifest.get("references") or [],
        "data": _manifest_data(manifest),
        "explanation": _explanation_for(engine, manifest),
    }
    if payload.run is not None:
        run_universe = (
            payload.run.universe.model_dump(exclude_none=True)
            if payload.run.universe
            else getattr(engine, "default_universe", None)
        )
        try:
            from src.market import open_screen_store
        except ImportError as exc:
            raise missing_dependency(exc) from exc

        # 试跑与正式选股一致：默认热库（经 open_screen_store 判定浅/落后后回退
        # 全量）；requires_full_history 直接读全量。
        open_store = (
            market_store
            if bool(getattr(engine, "requires_full_history", False))
            else open_screen_store
        )
        with open_store(market_db) as store:
            result = screen(
                store,
                engine,
                trade_date=payload.run.trade_date,
                params=payload.run.params,
                codes=payload.run.codes,
                universe=run_universe,
                adjust=str(getattr(engine, "adjust", "qfq") or "qfq"),
                health_check=not payload.run.skip_health_check,
            )
        body["run_result"] = _screen_result_dict(result)
    return body


def create_screen_skill(payload: ScreenSkillDraftModel) -> dict[str, Any]:
    if get_screen_package(payload.slug) is not None:
        raise ScreenPackageError("slug_conflict")
    _ensure_formula_slug_available(payload.slug, allow_existing_formula=False)
    engine = _build_engine(_payload_dict(payload))
    _validate_engine(engine)
    record = save_screen_package(
        payload.slug,
        _render_bundle(payload),
        expected_revision=None,
    )
    refresh_screen_strategy_catalog()
    return _record_detail(record, engine)


def update_screen_skill(
    slug: str,
    payload: ScreenSkillDraftModel,
    *,
    expected_revision: str,
) -> dict[str, Any]:
    if payload.slug != slug:
        raise ScreenPackageError("slug_conflict")
    if get_screen_package(slug) is None:
        raise ScreenPackageError("not_found")
    engine = _build_engine(_payload_dict(payload))
    _validate_engine(engine)
    record = save_screen_package(
        slug,
        _render_bundle(payload),
        expected_revision=expected_revision,
    )
    refresh_screen_strategy_catalog()
    return _record_detail(record, engine)


def delete_screen_skill(slug: str, *, expected_revision: str) -> bool:
    if get_screen_package(slug) is None:
        return False
    removed = delete_screen_package(slug, expected_revision=expected_revision)
    refresh_screen_strategy_catalog()
    return removed


def list_screen_skill_history(slug: str) -> list[dict[str, str]]:
    return list_screen_history(slug)


def rollback_screen_skill(
    slug: str, revision: str, *, expected_revision: str | None = None
) -> dict[str, Any]:
    record = restore_screen_package(
        slug, revision, expected_revision=expected_revision
    )
    engine = _compile_record(record)
    _validate_engine(engine)
    refresh_screen_strategy_catalog()
    return _record_detail(record, engine)


def delete_screen_skill_history(slug: str, revision: str) -> bool:
    return delete_screen_history(slug, revision)


def import_screen_skill_archive(archive_path: Path | str) -> dict[str, Any]:
    bundle = read_screen_archive(archive_path)
    if get_screen_package(bundle.record.slug) is not None:
        raise ScreenPackageError("slug_conflict")
    _ensure_formula_slug_available(bundle.record.slug, allow_existing_formula=False)
    engine = _compile_record(bundle.record)
    _validate_engine(engine)
    record = save_screen_package(
        bundle.record.slug,
        bundle.files,
        expected_revision=None,
    )
    refresh_screen_strategy_catalog()
    return _record_detail(record, engine)


def generate_screen_skill_draft(
    payload: ScreenSkillGenerateRequest,
    *,
    ops_db: str | None = None,
) -> dict[str, Any]:
    draft = build_generated_draft(payload, ops_db=ops_db)
    preview = preview_screen_skill(ScreenSkillPreviewRequest(**draft.model_dump()))
    return {
        "ok": bool(preview["ok"]),
        "diagnostics": preview["diagnostics"],
        "draft": draft.model_dump(exclude_none=True),
        "derived": preview.get("derived"),
        "strategy_revision": preview.get("strategy_revision"),
    }


def _render_bundle(payload: ScreenSkillDraftModel) -> dict[str, str]:
    meta = {
        "slug": payload.slug,
        "name": payload.name,
        "version": payload.version,
        "description": payload.description,
        "capability": "screen",
        "enabled": payload.enabled,
        "runtime": payload.runtime,
        "dialect": payload.dialect,
    }
    manifest = payload.manifest.model_dump(mode="python")
    screen_yaml = {"runtime": payload.runtime, "dialect": payload.dialect, **manifest}
    if payload.runtime == "python":
        screen_yaml["entrypoint"] = payload.entrypoint or "strategy.py:compute"
    code_name = "strategy.py" if payload.runtime == "python" else "formula.tdx"
    files = {
        "SKILL.md": (
            "---\n"
            + yaml.safe_dump(meta, allow_unicode=True, sort_keys=False).strip()
            + "\n---\n\n"
            + _skill_body(payload)
            + "\n"
        ),
        "screen.yaml": yaml.safe_dump(
            screen_yaml,
            allow_unicode=True,
            sort_keys=False,
        ),
        code_name: _normalize_code(payload.code or payload.formula or ""),
    }
    if payload.ui is not None:
        files["ui.json"] = json.dumps(payload.ui, ensure_ascii=False, indent=2) + "\n"
    return files


def _record_summary(
    record: ScreenPackageRecord,
    engine: ScreenEngine | None,
) -> dict[str, Any]:
    manifest = _manifest_dict(record)
    return {
        "slug": record.slug,
        "name": record.name,
        "description": record.description,
        "version": record.version,
        "enabled": record.enabled,
        "runtime": record.runtime,
        "dialect": record.dialect,
        "entrypoint": record.entrypoint,
        "entry_timing": manifest["entry_timing"],
        "required_fields": list(engine.required_fields()) if engine else _fallback_fields(manifest),
        "min_bars": engine.min_bars() if engine else int(manifest["min_bars"]),
        "params": {
            name: spec.get("default")
            for name, spec in (manifest.get("params") or {}).items()
            if isinstance(spec, dict)
        },
        "default_universe": _manifest_data(manifest)["universe"],
        "editable": True,
        "source_kind": record.runtime,
        "package_revision": record.package_revision,
        "strategy_revision": engine.strategy_revision if engine else "",
        "updated_at": record.updated_at,
    }


def _record_detail(record: ScreenPackageRecord, engine: ScreenEngine) -> dict[str, Any]:
    manifest = _manifest_dict(record)
    return {
        "slug": record.slug,
        "name": record.name,
        "description": record.description,
        "version": record.version,
        "enabled": record.enabled,
        "runtime": record.runtime,
        "dialect": record.dialect,
        "entrypoint": record.entrypoint,
        "code": record.code,
        "formula": record.formula or record.code,
        "manifest": manifest,
        "logic": manifest.get("logic") or [],
        "references": manifest.get("references") or [],
        "data": _manifest_data(manifest),
        "ui": record.ui,
        "package_revision": record.package_revision,
        "strategy_revision": engine.strategy_revision,
        "updated_at": record.updated_at,
    }


def _compile_record(record: ScreenPackageRecord) -> ScreenEngine:
    payload = _record_payload(record)
    payload["install_path"] = record.install_path
    return _build_engine(payload)


def _record_payload(record: ScreenPackageRecord) -> dict[str, Any]:
    return {
        "slug": record.slug,
        "name": record.name,
        "description": record.description,
        "version": record.version or "0.1.0",
        "enabled": record.enabled,
        "runtime": record.runtime,
        "dialect": record.dialect,
        "code": record.code,
        "formula": record.formula or record.code,
        "entrypoint": record.entrypoint,
        "manifest": _manifest_dict(record),
        "ui": record.ui,
    }


def _payload_dict(payload: ScreenSkillDraftModel) -> dict[str, Any]:
    return payload.model_dump(mode="python", exclude_none=True)


def _manifest_dict(record: ScreenPackageRecord) -> dict[str, Any]:
    manifest = dict(record.screen or {})
    manifest.pop("runtime", None)
    manifest.pop("dialect", None)
    manifest.pop("entrypoint", None)
    output = manifest.get("output")
    if not isinstance(output, dict):
        output = {}
    signal = manifest.pop("signal", None)
    if signal and not output.get("signal"):
        output["signal"] = signal
    output.setdefault("signal", "PICK")
    manifest["output"] = output
    manifest.setdefault("schema_version", 1)
    if manifest.get("params") is None:
        manifest["params"] = {}
    if manifest.get("factors") is None:
        manifest["factors"] = []
    manifest.setdefault("logic", [])
    manifest.setdefault("references", [])
    data = manifest.get("data")
    if not isinstance(data, dict):
        data = {}
    data.setdefault("fields", [])
    data.setdefault("adjust", "qfq")
    data.setdefault("universe", None)
    manifest["data"] = data
    return manifest


def _package_revision_for_payload(payload: ScreenSkillDraftModel) -> str:
    files = _render_bundle(payload)
    text = "".join(f"{name}\0{files[name]}\0" for name in sorted(files))
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _screen_result_dict(result: ScreenResult) -> dict[str, Any]:
    total_picks = len(result.picks)
    total_watch_picks = len(result.watch_picks)
    return {
        "strategy": result.strategy_slug,
        "strategy_revision": result.strategy_revision,
        "trade_date": result.trade_date,
        "entry_timing": result.entry_timing,
        "universe_size": result.universe_size,
        "elapsed_seconds": round(result.elapsed_seconds, 3),
        "params": result.params,
        "effective_params": result.effective_params,
        "picks": result.picks[:MAX_PREVIEW_PICKS],
        "picks_total": total_picks,
        "picks_truncated": total_picks > MAX_PREVIEW_PICKS,
        "watch_picks": result.watch_picks[:MAX_PREVIEW_PICKS],
        "watch_picks_total": total_watch_picks,
        "watch_picks_truncated": total_watch_picks > MAX_PREVIEW_PICKS,
        "health": result.health,
        "universe": result.universe,
        "universe_funnel": result.universe_funnel,
        "data_snapshot": getattr(result, "data_snapshot", None),
    }


def _build_engine(skill: dict[str, Any]) -> ScreenEngine:
    runtime = str(skill.get("runtime") or "").strip().lower() or "formula"
    if runtime == "python":
        return build_python_engine(skill)
    return build_formula_engine(skill)


def _validate_engine(engine: ScreenEngine) -> None:
    if isinstance(engine, PythonScreenEngine):
        engine.validate()
        # 用户源码前视静态审计（热路径 guard 审的是适配器类，不够）
        from src.ops import ScreenPackageError
        from src.strategy.application.audit import audit_source

        code = str(getattr(engine, "code", "") or "")
        timing = str(getattr(engine, "entry_timing", "next_open") or "next_open")
        if code:
            report = audit_source(
                code,
                entry_timing=timing,
                strategy=str(getattr(engine, "slug", "") or ""),
            )
            if report.failed:
                raise ScreenPackageError(f"前视审计未通过：{report.reason()}")


def _ensure_formula_slug_available(slug: str, *, allow_existing_formula: bool) -> None:
    if is_builtin_registered(slug):
        raise ScreenPackageError("builtin_slug_conflict")
    if not allow_existing_formula and get_screen_package(slug) is not None:
        raise ScreenPackageError("slug_conflict")


def _diagnostics_from_error(exc: ScreenFormulaError) -> list[dict[str, Any]]:
    if exc.diagnostics:
        return [item.to_dict() for item in exc.diagnostics]
    return [exc.to_dict()]


def _package_error_diagnostic(exc: ScreenPackageError) -> dict[str, Any]:
    return {
        "code": "E_SCREEN_PACKAGE",
        "severity": "error",
        "line": None,
        "column": None,
        "message": str(exc),
    }


def _derived_info(engine: ScreenEngine, manifest: dict[str, Any]) -> dict[str, Any]:
    output = manifest.get("output") if isinstance(manifest.get("output"), dict) else {}
    return {
        "required_fields": list(engine.required_fields()),
        "min_bars_required": engine.min_bars(),
        "signal": output.get("signal", "PICK"),
        "factors": list(manifest.get("factors") or []),
        "runtime": getattr(engine, "runtime", "formula"),
        "dialect": getattr(engine, "dialect", "loci"),
        "data": _manifest_data(manifest),
    }


def _explanation_for(engine: ScreenEngine, manifest: dict[str, Any]) -> dict[str, Any]:
    if isinstance(engine, FormulaScreenEngine):
        return build_formula_explanation(engine.compiled, manifest)
    return build_manifest_explanation(
        runtime=getattr(engine, "runtime", "python"),
        manifest=manifest,
        required_fields=engine.required_fields(),
        min_bars=engine.min_bars(),
    )


def _data_field_diagnostics(
    engine: ScreenEngine, manifest: dict[str, Any]
) -> list[dict[str, Any]]:
    declared = {str(item) for item in _manifest_data(manifest)["fields"]}
    missing = [field for field in engine.required_fields() if field not in declared]
    if not missing:
        return []
    return [
        {
            "code": "W_DATA_FIELDS_MISSING",
            "severity": "warning",
            "line": None,
            "column": None,
            "message": f"data.fields 缺少运行时必需字段：{missing}",
        }
    ]


def _manifest_data(manifest: dict[str, Any]) -> dict[str, Any]:
    data = manifest.get("data") if isinstance(manifest.get("data"), dict) else {}
    return {
        "fields": list(data.get("fields") or []),
        "adjust": str(data.get("adjust") or "qfq"),
        "universe": data.get("universe"),
    }


def _fallback_fields(manifest: dict[str, Any]) -> list[str]:
    data = _manifest_data(manifest)
    return [str(item) for item in data["fields"]]


def _normalize_code(source: str) -> str:
    return str(source or "").rstrip() + "\n"


def _skill_body(payload: ScreenSkillDraftModel) -> str:
    lines = [payload.description.strip() or payload.name.strip()]
    if payload.manifest.logic:
        lines.append("")
        lines.extend(
            f"- {item.title}: {item.explanation}" for item in payload.manifest.logic
        )
    return "\n".join(lines).strip()
