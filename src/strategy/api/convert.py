"""AI 策略转换 / 自定义策略 HTTP。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from src.shared.api_deps import missing_dependency, ops_store
from src.strategy.api.schemas import StrategyConvertRequest


def build_strategy_convert_router(
    *,
    write_dependency,
    ops_db: str | None = None,
) -> APIRouter:
    router = APIRouter()
    write_guard = Depends(write_dependency)

    def _ops():
        return ops_store(ops_db)

    @router.get("/api/strategies/custom", tags=["strategy"])
    def list_custom_strategies() -> list[dict[str, Any]]:
        """列出已保存的自定义策略文件。"""
        try:
            from src.strategy.application.converter import list_custom_strategies as _list
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        return _list()

    @router.post("/api/strategies/convert", tags=["strategy"])
    def convert_strategy(
        payload: StrategyConvertRequest, _write: None = write_guard
    ) -> dict[str, Any]:
        """把通达信公式或文字描述转成可注册的 Python 策略。

        dry_run=True 时只生成代码不保存，用于预览和人工审核。
        干净的代码才落盘并热加载注册。
        """
        try:
            from src.ai import resolve_config
            from src.strategy.application.converter import (
                _extract_code, _syntax_check, _validate_strategy_code,
                build_convert_prompt, save_and_load,
            )
        except ImportError as exc:
            raise missing_dependency(exc) from exc

        with _ops() as store:
            try:
                provider = resolve_config(
                    store, payload.provider,
                    model=payload.model,
                )
            except Exception as exc:
                raise HTTPException(status_code=422, detail=f"供应商配置错误：{exc}") from exc

        # 构建 prompt 并调用 LLM
        prompt = build_convert_prompt(
            source=payload.source,
            source_type=payload.source_type,
            slug=payload.slug,
            name=payload.name,
            entry_timing=payload.entry_timing,
        )
        try:
            from src.ai import ChatMessage, chat
            messages = [ChatMessage(role="user", content=prompt)]
            response = chat(
                provider,
                messages,
                max_tokens=4096,
                temperature=0.1,
                thinking=payload.thinking,
            )
            raw = response.text
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"LLM 请求失败：{exc}") from exc

        code = _extract_code(raw)

        # 语法检查
        syntax_err = _syntax_check(code)
        if syntax_err:
            return {
                "status": "syntax_error",
                "error": syntax_err,
                "code": code,
                "slug": payload.slug,
            }

        # 完整性检查
        issues = _validate_strategy_code(code, payload.slug)

        # 前视静态审计：entry_timing=open 裸用盘中字段 → fail-closed
        from src.strategy.application.audit import audit_source

        audit = audit_source(
            code,
            entry_timing=str(payload.entry_timing or "next_open"),
            strategy=payload.slug,
        )
        if audit.failed:
            return {
                "status": "lookahead",
                "error": audit.reason(),
                "issues": issues,
                "audit": audit.to_dict(),
                "code": code,
                "slug": payload.slug,
            }

        if payload.dry_run or issues:
            return {
                "status": "preview" if not issues else "issues",
                "issues": issues,
                "code": code,
                "slug": payload.slug,
            }

        # 保存并热加载
        try:
            result = save_and_load(code, payload.slug)
        except RuntimeError as exc:
            return {
                "status": "load_error",
                "error": str(exc),
                "code": code,
                "slug": payload.slug,
            }

        return {
            "status": "ok",
            "issues": [],
            "code": code,
            "slug": payload.slug,
            **result,
        }

    @router.post("/api/strategies/convert/save", tags=["strategy"])
    def save_converted_strategy(
        payload: dict[str, Any], _write: None = write_guard
    ) -> dict[str, Any]:
        """在用户审核后，把已生成的代码保存注册（dry_run 预览后的第二步）。"""
        code = str(payload.get("code", ""))
        slug = str(payload.get("slug", ""))
        if not code or not slug:
            raise HTTPException(status_code=422, detail="code 和 slug 均为必填")
        try:
            from src.strategy.application.converter import (
                _syntax_check, _validate_strategy_code, save_and_load
            )
        except ImportError as exc:
            raise missing_dependency(exc) from exc

        syntax_err = _syntax_check(code)
        if syntax_err:
            raise HTTPException(status_code=422, detail=f"代码有语法错误：{syntax_err}")

        issues = _validate_strategy_code(code, slug)
        if issues:
            raise HTTPException(status_code=422, detail=f"代码有问题：{'; '.join(issues)}")

        from src.strategy.application.audit import audit_source

        entry_timing = str(payload.get("entry_timing") or "next_open")
        audit = audit_source(code, entry_timing=entry_timing, strategy=slug)
        if audit.failed:
            raise HTTPException(status_code=422, detail=audit.reason())

        try:
            result = save_and_load(code, slug)
        except RuntimeError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return result

    @router.delete("/api/strategies/custom/{slug}", tags=["strategy"])
    def delete_custom_strategy(slug: str, _write: None = write_guard) -> dict[str, bool]:
        """删除自定义策略文件并从注册表移除。"""
        try:
            from src.strategy.application.converter import delete_custom_strategy as _delete
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        if not _delete(slug):
            raise HTTPException(status_code=404, detail=f"未找到自定义策略：{slug}")
        return {"removed": True}

    return router
