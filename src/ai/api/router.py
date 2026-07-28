"""LLM 供应商 / AI 判定 HTTP。"""
from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from src.app.legacy.quant_common import (
    AiJudgmentCreate,
    ProviderCreate,
    missing_dependency,
    ops_store,
    palace_store,
)


def build_ai_router(
    *,
    write_dependency,
    ops_db: str | None = None,
    palace_db: str | None = None,
) -> APIRouter:
    router = APIRouter()
    write_guard = Depends(write_dependency)

    def _ops():
        return ops_store(ops_db)

    def _palace():
        return palace_store(palace_db)

    @router.get("/api/providers", tags=["llm"])
    def list_providers() -> list[dict[str, Any]]:
        """只返回末四位，永不回显明文或密文。"""
        with _ops() as store:
            return store.list_providers()

    @router.post("/api/providers", tags=["llm"], status_code=201)
    def save_provider_api(payload: ProviderCreate, _write: None = write_guard) -> dict[str, Any]:
        try:
            from src.ai.infrastructure.crypto import CryptoError
            from src.ai.infrastructure.providers import save_provider
            from src.ops import OpsError
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        with _ops() as store:
            try:
                return save_provider(
                    store,
                    name=payload.name, protocol=payload.protocol,
                    base_url=payload.base_url, api_key=payload.api_key,
                    model=payload.model, proxy_url=payload.proxy_url,
                    note=payload.note, validate=payload.validate_key,
                    discover_models=payload.discover_models,
                    is_default=payload.is_default,
                )
            except (OpsError, CryptoError) as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/api/providers/{name}/default", tags=["llm"])
    def set_default_provider_api(name: str, _write: None = write_guard) -> dict[str, Any]:
        with _ops() as store:
            if not store.set_default_provider(name):
                raise HTTPException(status_code=404, detail=f"未配置的供应商：{name}")
            record = store.get_provider(name)
        return record or {"name": name, "is_default": True}

    @router.post("/api/providers/{name}/models", tags=["llm"])
    def refresh_provider_models(name: str, _write: None = write_guard) -> dict[str, Any]:
        try:
            from src.ai.infrastructure.crypto import CryptoError
            from src.ai.infrastructure.providers import refresh_models
            from src.ops import OpsError
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        with _ops() as store:
            try:
                models = refresh_models(store, name)
            except (OpsError, CryptoError) as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"models": models, "count": len(models)}

    @router.post("/api/providers/{name}/test", tags=["llm"])
    def test_provider_api(name: str, _write: None = write_guard) -> dict[str, Any]:
        """发一次最小请求验证供应商可用性，不回写配置。"""
        try:
            from src.ai import resolve_config
            from src.ai.infrastructure.client import LLMError, validate
            from src.ai.infrastructure.crypto import CryptoError
            from src.ops import OpsError
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        with _ops() as store:
            try:
                provider = resolve_config(store, name)
            except OpsError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            except CryptoError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        started = time.monotonic()
        try:
            response = validate(provider)
        except LLMError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"测试请求失败：{exc}") from exc
        latency_ms = int((time.monotonic() - started) * 1000)
        preview = (response.text or "").strip()[:200]
        return {
            "ok": True,
            "provider": provider.name,
            "model": response.model or provider.model,
            "latency_ms": latency_ms,
            "preview": preview,
        }

    @router.delete("/api/providers/{name}", tags=["llm"])
    def delete_provider(name: str, _write: None = write_guard) -> dict[str, bool]:
        with _ops() as store:
            if not store.delete_provider(name):
                raise HTTPException(status_code=404, detail=f"未配置的供应商：{name}")
        return {"removed": True}

    @router.post("/api/ai/judgments", tags=["ai"], status_code=201)
    def create_ai_judgment(payload: AiJudgmentCreate, _write: None = write_guard) -> dict[str, str]:
        with _palace() as palace:
            jid = palace.record_ai_judgment(**payload.model_dump())
        return {"id": jid}

    @router.get("/api/ai/judgments/{strategy_tag}", tags=["ai"])
    def list_ai_judgments(strategy_tag: str, limit: int = Query(default=100, ge=1, le=500)) -> list[dict[str, Any]]:
        with _palace() as palace:
            return palace.ai_judgment_payload(strategy_tag, limit=limit)

    return router
